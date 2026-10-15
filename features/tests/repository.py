"""Tests persistence. Services own authorization and transaction boundaries.

Every mutation requires a caller-owned transaction. No helper commits. Published
content is read from JSON, while SQL stores identities and learner operations.
The content transaction coordinates JSON publication with SQLite commit markers.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from core.content_store import store_for, transaction as content_transaction

def _store(db):
    return store_for(db, 'tests')

def _rows(db, table, **filters):
    return [r for r in _store(db).rows(table) if all(r.get(k) == v for k, v in filters.items())]


class Conflict(ValueError):
    """A revision or an operation receipt no longer matches."""


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def connect(database):
    """Require an explicit existing database; never select a working DB."""
    db = sqlite3.connect(Path(database).resolve(strict=True).as_uri() + "?mode=rw",
                         uri=True, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA recursive_triggers=ON")
    db.execute("PRAGMA busy_timeout=5000")
    return db


@contextmanager
def transaction(db):
    if db.in_transaction:
        raise ValueError("Transaction ownership must be explicit")
    with content_transaction(db):
        yield db


def _require_transaction(db):
    if not db.in_transaction:
        raise ValueError("Caller-owned transaction required")


def _one(db, sql, values=()):
    row = db.execute(sql, values).fetchone()
    return dict(row) if row is not None else None


def _all(db, sql, values=()):
    return [dict(row) for row in db.execute(sql, values)]


def get_test(db, test_id):
    return _store(db).get("tests", test_id)


def get_user(db, user_id):
    return _one(db, "SELECT id,is_admin FROM users WHERE id=?", (user_id,))


def student_identity(db, user_id):
    return _one(db, "SELECT id,name,username FROM users WHERE id=?", (user_id,))


def pending_attempts_page(db, *, offset, limit):
    rows = _all(db, """SELECT a.id AS attempt_id,a.user_id,a.submitted_at,a.version_id,u.name AS student_name,u.username,
               (SELECT COUNT(*) FROM test_attempt_answers x WHERE x.attempt_id=a.id AND x.score IS NULL) AS pending_count
        FROM test_attempts a JOIN users u ON u.id=a.user_id
        WHERE a.state='pending_review' ORDER BY a.submitted_at,a.id LIMIT ? OFFSET ?""", (limit, offset))
    for row in rows:
        row["title"] = get_version(db, row.pop("version_id"))["title"]
    count = db.execute("SELECT COUNT(*) FROM test_attempts WHERE state='pending_review'").fetchone()[0]
    return rows, count


def user_attempts_page(db, user_id, test_id, *, offset, limit):
    rows = _all(db, """SELECT * FROM test_attempts WHERE user_id=? AND test_id=?
        ORDER BY attempt_no DESC,id DESC LIMIT ? OFFSET ?""", (user_id, test_id, limit, offset))
    count = db.execute("SELECT COUNT(*) FROM test_attempts WHERE user_id=? AND test_id=?", (user_id, test_id)).fetchone()[0]
    return rows, count


def get_grade_event_by_key(db, actor_id, request_key):
    return _one(db, "SELECT * FROM test_grade_events WHERE actor_user_id=? AND request_key=?", (actor_id, request_key))


def get_grant_by_key(db, actor_id, request_key):
    return _one(db, "SELECT * FROM test_attempt_grants WHERE granted_by=? AND request_key=?", (actor_id, request_key))


def get_grant(db, grant_id):
    return _one(db, "SELECT * FROM test_attempt_grants WHERE id=?", (grant_id,))


def user_has_test_references(db, user_id):
    """Read-only integrity guard for account deletion through legacy FK-off code."""
    for table, column in (("test_attempts", "user_id"), ("test_attempt_grants", "user_id"),
                          ("test_operation_keys", "actor_user_id"),
                          ("test_media", "created_by"), ("test_attempt_answers", "graded_by"),
                          ("test_grade_events", "actor_user_id"), ("test_attempt_grants", "granted_by")):
        if db.execute(f"SELECT 1 FROM {table} WHERE {column}=? LIMIT 1", (user_id,)).fetchone():
            return True
    return False


def list_tests(db, *, published_only=False):
    return sorted((r for r in _store(db).rows("tests") if not published_only or r["publication_state"] == "published"), key=lambda r: (r["sort_order"], r["id"]))


def catalog_revision(db):
    return _store(db).get("test_catalog_state", 1)["revision"]


def _bump_catalog(db):
    _store(db).update("test_catalog_state", 1, revision=catalog_revision(db) + 1)


def get_draft(db, test_id):
    row = _store(db).get("test_drafts", test_id)
    if row is not None:
        row["document"] = json.loads(row["document_json"])
    return row


def create_test_in_transaction(db, document, *, actor_id, now):
    _require_transaction(db)
    from .validation import validate_draft
    document = validate_draft(document)
    store = _store(db)
    order = max((r["sort_order"] for r in store.rows("tests")), default=0) + 1
    test_id = store.insert("tests", dict(sort_order=order, created_at=now, updated_at=now,
        publication_state="draft", current_version_id=None, revision=1))
    store.insert("test_drafts", dict(test_id=test_id, document_json=canonical_json(document),
        revision=1, updated_at=now, based_on_version_id=None))
    _bump_catalog(db)
    return test_id


def save_draft_in_transaction(db, test_id, document, *, expected_revision, actor_id, now):
    _require_transaction(db)
    from .validation import validate_draft
    document = validate_draft(document)
    draft = get_draft(db, test_id)
    if draft is None or draft["revision"] != expected_revision:
        raise Conflict("Draft revision mismatch")
    _store(db).update("test_drafts", test_id, document_json=canonical_json(document),
        revision=expected_revision + 1, updated_at=now)
    parent = get_test(db, test_id)
    _store(db).update("tests", test_id, revision=parent["revision"] + 1, updated_at=now)
    return expected_revision + 1


def store_version_in_transaction(db, test_id, document, *, actor_id, now):
    _require_transaction(db)
    from .validation import validate_publication
    document = validate_publication(document)
    if get_test(db, test_id) is None:
        raise Conflict("Test unavailable")
    store = _store(db)
    number = max((r["version_no"] for r in _rows(db, "test_versions", test_id=test_id)), default=0) + 1
    version_id = store.insert("test_versions", dict(test_id=test_id, version_no=number,
        title=document["title"], description=document["description"], time_limit_seconds=document["time_limit_seconds"],
        attempt_limit=document["attempt_limit"], show_correct_answers=int(document["show_correct_answers"]),
        question_count=len(document["questions"]), schema_version=1, content_hash=digest(document),
        published_at=now, sealed=0))
    for position, question in enumerate(document["questions"], 1):
        media_id = question.get("media_id")
        if media_id is not None and (not media_belongs_to_test(db, test_id, media_id) or get_media(db, media_id)["state"] != "ready"):
            raise sqlite3.IntegrityError("Question media unavailable")
        question_id = store.insert("test_version_questions", dict(version_id=version_id, position=position,
            title=question["title"], prompt_text=question["prompt_text"], code_text=question.get("code_text"),
            question_type=question["question_type"], free_input_mode=question.get("free_input_mode"),
            grading_mode=question["grading_mode"], media_id=media_id))
        for i, option in enumerate(question.get("options", []), 1):
            store.insert("test_question_options", dict(question_id=question_id, position=i, text=option["text"], is_correct=int(option["is_correct"])))
        for i, value in enumerate(question.get("accepted_answers", []), 1):
            store.insert("test_accepted_answers", dict(question_id=question_id, position=i, value=value))
    store.update("test_versions", version_id, sealed=1)
    return version_id


def get_version(db, version_id):
    version = _store(db).get("test_versions", version_id)
    if version is None or version["sealed"] != 1:
        return None
    questions = sorted(_rows(db, "test_version_questions", version_id=version_id), key=lambda r: r["position"])
    for question in questions:
        question["options"] = sorted(_rows(db, "test_question_options", question_id=question["id"]), key=lambda r: r["position"])
        question["accepted_answers"] = [r["value"] for r in sorted(_rows(db, "test_accepted_answers", question_id=question["id"]), key=lambda r: r["position"])]
        question["media"] = get_media(db, question["media_id"]) if question["media_id"] is not None else None
    version["questions"] = questions
    return version


def publish_version_in_transaction(db, test_id, version_id, *, expected_revision, now):
    _require_transaction(db)
    parent, version = get_test(db, test_id), get_version(db, version_id)
    if parent is None or parent["revision"] != expected_revision:
        raise Conflict("Test revision mismatch")
    if version is None or version["test_id"] != test_id:
        raise sqlite3.IntegrityError("Version does not belong to test")
    _store(db).update("tests", test_id, current_version_id=version_id, publication_state="published", revision=expected_revision + 1, updated_at=now)
    draft = get_draft(db, test_id)
    _store(db).update("test_drafts", test_id, based_on_version_id=version_id, revision=draft["revision"] + 1, updated_at=now)


def set_publication_state_in_transaction(db, test_id, state, *, expected_revision, now):
    _require_transaction(db)
    if state not in ("published", "hidden"):
        raise ValueError("Invalid publication state")
    parent = get_test(db, test_id)
    if parent is None or parent["revision"] != expected_revision or parent["current_version_id"] is None:
        raise Conflict("Test revision mismatch or no published version")
    _store(db).update("tests", test_id, publication_state=state, revision=expected_revision + 1, updated_at=now)


def reorder_tests_in_transaction(db, test_ids, *, expected_revision):
    _require_transaction(db)
    existing = {r["id"] for r in _store(db).rows("tests")}
    if len(test_ids) != len(existing) or set(test_ids) != existing:
        raise ValueError("Order must contain every test exactly once")
    if catalog_revision(db) != expected_revision:
        raise Conflict("Catalog revision mismatch")
    _bump_catalog(db)
    for i, test_id in enumerate(test_ids, 1):
        _store(db).update("tests", test_id, sort_order=i)
    return expected_revision + 1


def delete_test_in_transaction(db, test_id, *, expected_revision):
    """Delete content and result identities in one coordinated transaction."""
    _require_transaction(db)
    parent = get_test(db, test_id)
    if parent is None or parent["revision"] != expected_revision:
        raise Conflict("Test revision mismatch")
    media_ids = [r["media_id"] for r in _rows(db, "test_media_links", test_id=test_id)]
    _store(db).delete("tests", test_id)
    db.execute("DELETE FROM tests WHERE id=?", (test_id,))
    _bump_catalog(db)
    return media_ids


def get_media(db, media_id):
    return _store(db).get("test_media", media_id)


def media_belongs_to_test(db, test_id, media_id):
    return bool(_rows(db, "test_media_links", test_id=test_id, media_id=media_id))


def create_media_in_transaction(db, *, storage_key, mime_type, size_bytes, sha256, width, height, alt_text, actor_id, now, state="ready"):
    _require_transaction(db)
    return _store(db).insert("test_media", dict(storage_key=storage_key, mime_type=mime_type, size_bytes=size_bytes,
        sha256=sha256, width=width, height=height, alt_text=alt_text, created_by=actor_id, created_at=now, state=state))


def link_media_in_transaction(db, test_id, media_id):
    _require_transaction(db)
    if not media_belongs_to_test(db, test_id, media_id):
        _store(db).insert("test_media_links", dict(test_id=test_id, media_id=media_id))


def delete_unreferenced_media_in_transaction(db, media_id):
    _require_transaction(db)
    if get_media(db, media_id) is None or _rows(db, "test_media_links", media_id=media_id) or _rows(db, "test_version_questions", media_id=media_id):
        return False
    _store(db).delete("test_media", media_id)
    db.execute("DELETE FROM test_media WHERE id=?", (media_id,))
    return True


def get_operation(db, actor_id, scope, key):
    return _one(db, "SELECT * FROM test_operation_keys WHERE actor_user_id=? AND operation_scope=? AND request_key=?",
                (actor_id, scope, key))


def record_operation_in_transaction(db, actor_id, scope, key, request_hash, resource_id, now):
    _require_transaction(db)
    previous = get_operation(db, actor_id, scope, key)
    if previous is not None:
        if previous["request_hash"] != request_hash or previous["resource_id"] != resource_id:
            raise Conflict("Idempotency key already used")
        return previous
    db.execute("""INSERT INTO test_operation_keys(actor_user_id,operation_scope,request_key,request_hash,resource_id,created_at)
                  VALUES(?,?,?,?,?,?)""", (actor_id, scope, key, request_hash, resource_id, now))
    return get_operation(db, actor_id, scope, key)


def get_attempt(db, attempt_id):
    return _one(db, "SELECT * FROM test_attempts WHERE id=?", (attempt_id,))


def latest_attempt(db, user_id, test_id):
    return _one(db, "SELECT * FROM test_attempts WHERE user_id=? AND test_id=? ORDER BY attempt_no DESC LIMIT 1", (user_id, test_id))


def active_attempt(db, user_id, test_id):
    return _one(db, "SELECT * FROM test_attempts WHERE user_id=? AND test_id=? AND state='active'", (user_id, test_id))


def list_attempts(db, *, user_id=None, test_id=None, state=None):
    clauses, values = [], []
    for field, value in (("user_id", user_id), ("test_id", test_id), ("state", state)):
        if value is not None:
            clauses.append(field + "=?")
            values.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return _all(db, "SELECT * FROM test_attempts" + where + " ORDER BY id", values)


def expired_attempt_ids(db, now, *, limit=100):
    return [row[0] for row in db.execute("SELECT id FROM test_attempts WHERE state='active' AND deadline_at<=? ORDER BY deadline_at,id LIMIT ?", (now, limit))]


def quota_usage(db, user_id, test_id):
    used = db.execute("SELECT COUNT(*) FROM test_attempts WHERE user_id=? AND test_id=?", (user_id, test_id)).fetchone()[0]
    grants = db.execute("SELECT COALESCE(SUM(amount),0) FROM test_attempt_grants WHERE user_id=? AND test_id=?", (user_id, test_id)).fetchone()[0]
    return {"used": used, "grants": grants}


def create_attempt_in_transaction(db, user_id, test_id, version_id, *, request_key, now):
    _require_transaction(db)
    version = get_version(db, version_id)
    if version is None or version["test_id"] != test_id:
        raise Conflict("Version unavailable")
    _store(db).register()  # Seal identity fingerprints before an attempt references a new version.
    number = db.execute("SELECT COALESCE(MAX(attempt_no),0)+1 FROM test_attempts WHERE user_id=? AND test_id=?", (user_id, test_id)).fetchone()[0]
    attempt_id = db.execute("""INSERT INTO test_attempts
        (user_id,test_id,version_id,attempt_no,started_at,deadline_at,time_limit_seconds_snapshot,show_correct_answers_snapshot,start_request_key)
        VALUES(?,?,?,?,?,?,?,?,?)""", (user_id, test_id, version_id, number, now,
        now + 1000 * version["time_limit_seconds"], version["time_limit_seconds"], version["show_correct_answers"], request_key)).lastrowid
    db.execute("""INSERT INTO test_attempt_answers(attempt_id,question_id,version_id)
                  SELECT ?,id,version_id FROM test_version_questions WHERE version_id=?""", (attempt_id, version_id))
    return attempt_id


def _decode_answer(row):
    if row is not None:
        row["answer"] = json.loads(row["answer_json"]) if row["answer_json"] is not None else None
    return row


def get_answers(db, attempt_id):
    rows = [_decode_answer(r) for r in _all(db, "SELECT * FROM test_attempt_answers WHERE attempt_id=?", (attempt_id,))]
    positions = {r["id"]: r["position"] for r in _store(db).rows("test_version_questions")}
    return sorted(rows, key=lambda r: positions[r["question_id"]])


def get_answer(db, attempt_id, question_id):
    return _decode_answer(_one(db, "SELECT * FROM test_attempt_answers WHERE attempt_id=? AND question_id=?", (attempt_id, question_id)))


def save_answer_in_transaction(db, attempt_id, question_id, answer, *, expected_revision, now):
    _require_transaction(db)
    changed = db.execute("""UPDATE test_attempt_answers SET answer_json=?,revision=revision+1,saved_at=?
        WHERE attempt_id=? AND question_id=? AND revision=?
        AND EXISTS(SELECT 1 FROM test_attempts WHERE id=? AND state='active' AND deadline_at>?)""",
        (canonical_json(answer), now, attempt_id, question_id, expected_revision, attempt_id, now)).rowcount
    if changed != 1:
        raise Conflict("Answer revision mismatch or attempt unavailable")
    return get_answer(db, attempt_id, question_id)


def claim_attempt_in_transaction(db, attempt_id, *, expected_generation, writer_token_hash, writer_client_id, now):
    _require_transaction(db)
    changed = db.execute("""UPDATE test_attempts SET active_generation=active_generation+1,writer_token_hash=?,writer_client_id=?,lease_acquired_at=?,last_seen_at=?
        WHERE id=? AND active_generation=? AND state='active' AND deadline_at>?""",
        (writer_token_hash, writer_client_id, now, now, attempt_id, expected_generation, now)).rowcount
    if changed != 1:
        raise Conflict("Writer generation mismatch or attempt unavailable")
    return get_attempt(db, attempt_id)


def update_attempt_in_transaction(db, attempt_id, **values):
    _require_transaction(db)
    allowed = {"state", "submitted_at", "finalized_at", "finish_reason", "active_generation", "writer_token_hash",
               "writer_client_id", "lease_acquired_at", "last_seen_at", "result_revision"}
    if not values or not set(values) <= allowed:
        raise ValueError("Unsupported attempt fields")
    changed = db.execute("UPDATE test_attempts SET " + ",".join(field + "=?" for field in values) + " WHERE id=?",
                         list(values.values()) + [attempt_id]).rowcount
    if changed != 1:
        raise Conflict("Attempt unavailable")


def set_answer_grade_in_transaction(db, attempt_id, question_id, *, expected_grade_revision=None, **values):
    _require_transaction(db)
    allowed = {"was_unanswered", "auto_score", "score", "grading_source", "graded_by", "graded_at", "grade_revision"}
    if not values or not set(values) <= allowed:
        raise ValueError("Unsupported grade fields")
    for field in ("score", "auto_score"):
        if field in values and values[field] is not None and (type(values[field]) is not int or values[field] not in (0, 1)):
            raise ValueError("A score must be integer 0 or 1")
    where, parameters = " WHERE attempt_id=? AND question_id=?", [attempt_id, question_id]
    if expected_grade_revision is not None:
        where += " AND grade_revision=?"
        parameters.append(expected_grade_revision)
    changed = db.execute("UPDATE test_attempt_answers SET " + ",".join(field + "=?" for field in values) + where,
                         list(values.values()) + parameters).rowcount
    if changed != 1:
        raise Conflict("Grade revision mismatch")
    return get_answer(db, attempt_id, question_id)


def add_grade_event_in_transaction(db, attempt_id, question_id, *, old_score, new_score, old_source, new_source,
                                   actor_id, actor_kind, now, request_key, result_revision):
    _require_transaction(db)
    return db.execute("""INSERT INTO test_grade_events(attempt_id,question_id,old_score,new_score,old_source,new_source,
        actor_user_id,actor_kind,occurred_at,request_key,result_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (attempt_id, question_id, old_score, new_score, old_source, new_source, actor_id, actor_kind, now, request_key, result_revision)).lastrowid


def add_grant_in_transaction(db, user_id, test_id, amount, *, actor_id, now, request_key):
    _require_transaction(db)
    if type(amount) is not int or amount <= 0:
        raise ValueError("Grant must be a positive integer")
    return db.execute("INSERT INTO test_attempt_grants(user_id,test_id,amount,granted_by,granted_at,request_key) VALUES(?,?,?,?,?,?)",
                      (user_id, test_id, amount, actor_id, now, request_key)).lastrowid
