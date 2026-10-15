"""Tests lifecycle services. All SQL lives in repository; callers own no commits."""
import time
import hashlib
import hmac
import secrets

from . import repository as repo
from .errors import TestsError
from .grading import grade_answer, summarize
from .serializers import iso_utc, attempt_summary_dto, attempt_dto, result_dto, admin_attempt_dto
from .statistics import best_attempt
from .validation import ValidationError, digest, validate_draft, validate_publication, validate_answer


def now_ms():
    return time.time_ns() // 1_000_000


def fail(code, status, message, **details):
    raise TestsError(code, status, message, details)


def _user(db, actor_id, *, admin=False):
    user = repo.get_user(db, actor_id) if type(actor_id) is int and 0 < actor_id <= 2**63 - 1 else None
    if user is None:
        fail("AUTH_REQUIRED", 401, "Требуется вход.")
    if admin and user["is_admin"] != 1:
        fail("ADMIN_REQUIRED", 403, "Требуются права администратора.")
    return user


def _test(db, test_id):
    _integer(test_id, "test_id")
    parent = repo.get_test(db, test_id)
    if parent is None:
        fail("NOT_FOUND", 404, "Тест не найден.")
    return parent


def _integer(value, field, *, minimum=1):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise ValidationError({field: "Ожидается представимое целое число."})
    return value


def _body(body, allowed):
    if not isinstance(body, dict):
        fail("BAD_JSON", 400, "Ожидается JSON-объект.")
    if set(body) - set(allowed):
        raise ValidationError({"request": "Неизвестные поля не допускаются."})


def _identity(body, payload=None):
    key = body.get("request_key")
    if not isinstance(key, str) or not key:
        raise ValidationError({"request_key": "Требуется ключ запроса."})
    try:
        key.encode("utf-8")
        hashed = digest(payload if payload is not None else {k: v for k, v in body.items() if k != "request_key"})
    except (ValueError, TypeError, UnicodeError):
        raise ValidationError({"request": "Некорректные данные запроса."}) from None
    return key, hashed


def _receipt(db, actor, scope, key, hashed):
    previous = repo.get_operation(db, actor, scope, key)
    if previous is not None and previous["request_hash"] != hashed:
        fail("IDEMPOTENCY_KEY_REUSED", 409, "Ключ уже использован для другого запроса.")
    return previous


def _record(db, actor, scope, key, hashed, resource, now):
    repo.record_operation_in_transaction(db, actor, scope, key, hashed, resource, now)


def _revision(actual, expected):
    _integer(expected, "expected_revision")
    if actual != expected:
        fail("REVISION_CONFLICT", 409, "Данные уже изменены. Обновите страницу.", revision=actual)


def _representable(document, now):
    for field in ("attempt_limit", "time_limit_seconds"):
        if document[field] is not None:
            _integer(document[field], field)
    if document["time_limit_seconds"] is not None:
        deadline = now + document["time_limit_seconds"] * 1000
        _integer(deadline, "time_limit_seconds")
        try:
            iso_utc(deadline)
        except (OverflowError, ValueError):
            raise ValidationError({"time_limit_seconds": "Срок выходит за представимый диапазон даты."}) from None


def _media_check(db, test_id, document):
    for question in document["questions"]:
        ident = question.get("media_id")
        if ident is None:
            continue
        _integer(ident, "media_id")
        media = repo.get_media(db, ident)
        if media is None or media["state"] != "ready" or not repo.media_belongs_to_test(db, test_id, ident):
            raise ValidationError({"media_id": "Изображение недоступно для этого теста."})


def _draft_dto(db, test_id):
    parent = _test(db, test_id)
    draft = repo.get_draft(db, test_id)
    materials = []
    for ident in dict.fromkeys(q.get("media_id") for q in draft["document"]["questions"] if q.get("media_id") is not None):
        media = repo.get_media(db, ident)
        if media is not None and repo.media_belongs_to_test(db, test_id, ident):
            materials.append({"id": ident, "url": f"/api/admin/tests/{test_id}/media/{ident}",
                              "alt_text": media["alt_text"], "width": media["width"], "height": media["height"]})
    return {"id": test_id, "test_id": test_id, "revision": draft["revision"], "test_revision": parent["revision"],
            "publication_state": parent["publication_state"], "current_version_id": parent["current_version_id"],
            "document": draft["document"], "media": materials}


def _publication_dto(db, test_id, version_id=None):
    parent = _test(db, test_id)
    return {"test_id": test_id, "version_id": version_id or parent["current_version_id"],
            "revision": parent["revision"], "draft_revision": repo.get_draft(db, test_id)["revision"],
            "publication_state": parent["publication_state"]}


def finalize_in_transaction(db, attempt, *, now, reason="timeout"):
    """Shared finalizer; caller holds the write lock and commits before HTTP errors."""
    if attempt["state"] != "active":
        return attempt
    if reason not in ("manual", "timeout"):
        raise ValueError("Unsupported finalization reason")
    version = repo.get_version(db, attempt["version_id"])
    answers = {row["question_id"]: row for row in repo.get_answers(db, attempt["id"])}
    pending = False
    for question in version["questions"]:
        answer = answers[question["id"]]
        values = grade_answer(question, answer["answer"])
        pending = pending or values["score"] is None
        repo.set_answer_grade_in_transaction(db, attempt["id"], question["id"],
                                            **values, graded_at=now if values["score"] is not None else None,
                                            grade_revision=1 if values["score"] is not None else 0)
    repo.update_attempt_in_transaction(db, attempt["id"], state="pending_review" if pending else "graded",
                                      submitted_at=attempt["deadline_at"] if reason == "timeout" else now,
                                      finalized_at=now, finish_reason=reason,
                                      result_revision=attempt["result_revision"] + 1)
    return repo.get_attempt(db, attempt["id"])


def _expire_in_transaction(db, now):
    for attempt in repo.list_attempts(db, state="active"):
        if attempt["deadline_at"] <= now:
            finalize_in_transaction(db, attempt, now=now)


def create_test(db, body, actor_id):
    _body(body, {"request_key"})
    key, hashed = _identity(body)
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        now = now_ms()
        old = _receipt(db, actor_id, "create", key, hashed)
        if old:
            return _draft_dto(db, old["resource_id"])
        ident = repo.create_test_in_transaction(db, {}, actor_id=actor_id, now=now)
        _record(db, actor_id, "create", key, hashed, ident, now)
        return _draft_dto(db, ident)


def admin_catalog(db, actor_id):
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _expire_in_transaction(db, now_ms())
        items = []
        for parent in repo.list_tests(db):
            draft = repo.get_draft(db, parent["id"])
            document = (repo.get_version(db, parent["current_version_id"])
                        if parent["current_version_id"] is not None else draft["document"])
            attempts = repo.list_attempts(db, test_id=parent["id"])
            item = {key: parent[key] for key in ("id", "publication_state", "revision", "current_version_id", "sort_order")}
            item.update({key: document[key] for key in ("title", "description", "time_limit_seconds", "attempt_limit", "show_correct_answers")})
            item.update(draft_revision=draft["revision"], question_count=len(document["questions"]),
                        submitted_count=sum(a["state"] != "active" for a in attempts),
                        active_count=sum(a["state"] == "active" for a in attempts),
                        pending_count=sum(a["state"] == "pending_review" for a in attempts))
            items.append(item)
        return {"tests": items, "revision": repo.catalog_revision(db)}


def get_draft(db, test_id, actor_id):
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        return _draft_dto(db, test_id)


def save_draft(db, test_id, body, actor_id):
    _body(body, {"request_key", "expected_revision", "document"})
    document = validate_draft(body.get("document"))
    key, hashed = _identity(body, {"document": document, "expected_revision": body.get("expected_revision")})
    scope = f"draft:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _test(db, test_id)
        now = now_ms()
        if _receipt(db, actor_id, scope, key, hashed):
            return _draft_dto(db, test_id)
        _revision(repo.get_draft(db, test_id)["revision"], body.get("expected_revision"))
        _representable(document, now)
        _media_check(db, test_id, document)
        repo.save_draft_in_transaction(db, test_id, document, expected_revision=body["expected_revision"], actor_id=actor_id, now=now)
        _record(db, actor_id, scope, key, hashed, test_id, now)
        return _draft_dto(db, test_id)


def publish_test(db, test_id, body, actor_id):
    _body(body, {"request_key", "expected_revision"})
    key, hashed = _identity(body)
    scope = f"publish:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        parent = _test(db, test_id)
        now = now_ms()
        old = _receipt(db, actor_id, scope, key, hashed)
        if old:
            if repo.get_version(db, old["resource_id"]) is None:
                fail("NOT_FOUND", 404, "Версия не найдена.")
            return _publication_dto(db, test_id, old["resource_id"])
        draft = repo.get_draft(db, test_id)
        _revision(draft["revision"], body.get("expected_revision"))
        document = validate_publication(draft["document"])
        _representable(document, now)
        _media_check(db, test_id, document)
        version_id = repo.store_version_in_transaction(db, test_id, document, actor_id=actor_id, now=now)
        repo.publish_version_in_transaction(db, test_id, version_id, expected_revision=parent["revision"], now=now)
        _record(db, actor_id, scope, key, hashed, version_id, now)
        return _publication_dto(db, test_id, version_id)


def set_visibility(db, test_id, body, actor_id):
    _body(body, {"request_key", "expected_revision", "published"})
    if type(body.get("published")) is not bool:
        raise ValidationError({"published": "Ожидается логическое значение."})
    key, hashed = _identity(body)
    scope = f"visibility:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        parent = _test(db, test_id)
        now = now_ms()
        if _receipt(db, actor_id, scope, key, hashed):
            return _publication_dto(db, test_id)
        _revision(parent["revision"], body.get("expected_revision"))
        if parent["current_version_id"] is None:
            raise ValidationError({"published": "Сначала опубликуйте корректную версию."})
        repo.set_publication_state_in_transaction(db, test_id, "published" if body["published"] else "hidden",
                                                 expected_revision=parent["revision"], now=now)
        _record(db, actor_id, scope, key, hashed, test_id, now)
        return _publication_dto(db, test_id)


def copy_test(db, test_id, body, actor_id):
    _body(body, {"request_key"})
    key, hashed = _identity(body)
    scope = f"copy:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _test(db, test_id)
        now = now_ms()
        old = _receipt(db, actor_id, scope, key, hashed)
        if old:
            return _draft_dto(db, old["resource_id"])
        document = repo.get_draft(db, test_id)["document"]
        _media_check(db, test_id, document)
        ident = repo.create_test_in_transaction(db, document, actor_id=actor_id, now=now)
        for question in document["questions"]:
            if question.get("media_id") is not None:
                repo.link_media_in_transaction(db, ident, question["media_id"])
        _record(db, actor_id, scope, key, hashed, ident, now)
        return _draft_dto(db, ident)


def reorder_tests(db, body, actor_id):
    _body(body, {"request_key", "expected_revision", "test_ids"})
    ids = body.get("test_ids")
    if not isinstance(ids, list) or any(type(ident) is not int or ident <= 0 for ident in ids) or len(set(ids)) != len(ids):
        raise ValidationError({"test_ids": "Ожидается список уникальных ID тестов."})
    key, hashed = _identity(body)
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        now = now_ms()
        if _receipt(db, actor_id, "order", key, hashed):
            return {"revision": repo.catalog_revision(db), "test_ids": [row["id"] for row in repo.list_tests(db)]}
        _revision(repo.catalog_revision(db), body.get("expected_revision"))
        if set(ids) != {row["id"] for row in repo.list_tests(db)}:
            raise ValidationError({"test_ids": "Список должен содержать все тесты ровно один раз."})
        revision = repo.reorder_tests_in_transaction(db, ids, expected_revision=body["expected_revision"])
        _record(db, actor_id, "order", key, hashed, 1, now)
        return {"revision": revision, "test_ids": ids}


def delete_test(db, test_id, body, actor_id):
    _body(body, {"request_key", "expected_revision", "confirmed"})
    if body.get("confirmed") is not True:
        raise ValidationError({"confirmed": "Подтвердите удаление теста и всех результатов."})
    key, hashed = _identity(body)
    scope = f"delete:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        now = now_ms()
        if _receipt(db, actor_id, scope, key, hashed):
            return {"test_id": test_id, "deleted": True}
        parent = _test(db, test_id)
        _revision(parent["revision"], body.get("expected_revision"))
        repo.delete_test_in_transaction(db, test_id, expected_revision=parent["revision"])
        _record(db, actor_id, scope, key, hashed, test_id, now)
        return {"test_id": test_id, "deleted": True}


def add_media(db, test_id, descriptor, body, actor_id):
    """Descriptor is trusted output of staged upload validation, never JSON input."""
    _body(body, {"request_key"})
    fields = ("mime_type", "size_bytes", "sha256", "width", "height", "alt_text")
    key, hashed = _identity(body, {name: descriptor[name] for name in fields})
    scope = f"media:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _test(db, test_id)
        now = now_ms()
        old = _receipt(db, actor_id, scope, key, hashed)
        if old:
            media = repo.get_media(db, old["resource_id"])
            if media is None or not repo.media_belongs_to_test(db, test_id, media["id"]):
                fail("NOT_FOUND", 404, "Изображение не найдено.")
            return media
        ident = repo.create_media_in_transaction(db, **{name: descriptor[name] for name in (*fields, "storage_key")},
                                                actor_id=actor_id, now=now)
        repo.link_media_in_transaction(db, test_id, ident)
        _record(db, actor_id, scope, key, hashed, ident, now)
        return repo.get_media(db, ident)


def get_admin_media(db, test_id, media_id, actor_id):
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _test(db, test_id)
        _integer(media_id, "media_id")
        media = repo.get_media(db, media_id)
        if media is None or media["state"] != "ready" or not repo.media_belongs_to_test(db, test_id, media_id):
            fail("NOT_FOUND", 404, "Изображение не найдено.")
        return media


def _owned_latest(db, attempt_id, actor_id):
    _integer(attempt_id, "attempt_id")
    attempt = repo.get_attempt(db, attempt_id)
    if attempt is None or attempt["user_id"] != actor_id:
        fail("NOT_FOUND", 404, "Попытка не найдена.")
    latest = repo.latest_attempt(db, actor_id, attempt["test_id"])
    if latest["id"] != attempt_id:
        fail("RESULT_NOT_LATEST", 403, "Доступна только последняя попытка.",
             latest_attempt_id=latest["id"], attempt_url=f"/tests/attempts/{latest['id']}")
    return attempt


def _urls(attempt):
    return {"attempt_url": f"/tests/attempts/{attempt['id']}",
            "result_url": f"/tests/attempts/{attempt['id']}/result"}


def _summary(attempt, now):
    result = attempt_summary_dto(attempt, now=now)
    result.update(_urls(attempt))
    return result


def _expired(db, attempt, now):
    if attempt["state"] == "active" and now >= attempt["deadline_at"]:
        return finalize_in_transaction(db, attempt, now=now), True
    return attempt, False


def _writer(attempt, body, token):
    generation = body.get("generation")
    valid = type(generation) is int and generation == attempt["active_generation"]
    valid = valid and isinstance(token, str) and bool(token) and bool(attempt["writer_token_hash"])
    if valid:
        try:
            valid = hmac.compare_digest(hashlib.sha256(token.encode("utf-8")).hexdigest(), attempt["writer_token_hash"])
        except UnicodeError:
            valid = False
    if not valid:
        fail("SESSION_REPLACED", 409, "Продолжение передано другому окну. Активируйте это окно явно.",
             generation=attempt["active_generation"])


def _mutate_attempt(db, attempt_id, body, actor_id, token, action, *, needs_writer=True):
    # An expiry must commit even when the HTTP mutation returns DEADLINE_REACHED.
    expired_error = None
    with repo.transaction(db):
        _user(db, actor_id)
        attempt = _owned_latest(db, attempt_id, actor_id)
        now = now_ms()
        if needs_writer:
            _writer(attempt, body, token)
        attempt, expired = _expired(db, attempt, now)
        if expired:
            expired_error = TestsError("DEADLINE_REACHED", 409, "Время истекло. Сохранённые ответы отправлены.", _summary(attempt, now))
        else:
            result = action(attempt, now)
    if expired_error:
        raise expired_error
    return result


def _remaining(db, actor_id, test_id, version):
    quota = repo.quota_usage(db, actor_id, test_id)
    return quota, (None if version["attempt_limit"] is None else max(0, version["attempt_limit"] + quota["grants"] - quota["used"]))


def start_attempt(db, test_id, body, actor_id, *, starts_enabled=False):
    _body(body, {"request_key"})
    key, hashed = _identity(body)
    deferred = None
    scope = f"start:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id)
        parent = _test(db, test_id)
        now = now_ms()
        old = _receipt(db, actor_id, scope, key, hashed)
        if old:
            attempt = _owned_latest(db, old["resource_id"], actor_id)
            attempt, _ = _expired(db, attempt, now)
            return {**_summary(attempt, now), "_created": False}
        attempt = repo.active_attempt(db, actor_id, test_id)
        if attempt is not None:
            attempt, expired = _expired(db, attempt, now)
            if expired:
                attempt = None
        if attempt is not None:
            _record(db, actor_id, scope, key, hashed, attempt["id"], now)
            return {**_summary(attempt, now), "_created": False}
        # Delay new-start errors so a preceding timeout stays committed.
        if parent["publication_state"] != "published":
            deferred = TestsError("TEST_HIDDEN", 403, "Тест недоступен для нового прохождения.")
        elif not starts_enabled:
            deferred = TestsError("TEMPORARILY_UNAVAILABLE", 503, "Начало новых попыток временно недоступно.")
        else:
            version = repo.get_version(db, parent["current_version_id"])
            quota, remaining = _remaining(db, actor_id, test_id, version)
            if remaining is not None and remaining <= 0:
                deferred = TestsError("LIMIT_REACHED", 409, "Доступные попытки закончились.")
            else:
                _representable(version, now)
                ident = repo.create_attempt_in_transaction(db, actor_id, test_id, version["id"], request_key=f"{test_id}:{key}", now=now)
                _record(db, actor_id, scope, key, hashed, ident, now)
                result = {**_summary(repo.get_attempt(db, ident), now), "_created": True}
    if deferred:
        raise deferred
    return result


def claim_attempt(db, attempt_id, body, actor_id):
    _body(body, {"expected_generation", "writer_client_id"})
    expected = _integer(body.get("expected_generation"), "expected_generation")
    client = body.get("writer_client_id")
    if not isinstance(client, str) or not client:
        raise ValidationError({"writer_client_id": "Требуется идентификатор нового окна."})
    try:
        client.encode("utf-8")
    except UnicodeError:
        raise ValidationError({"writer_client_id": "Некорректный идентификатор окна."}) from None
    def action(attempt, now):
        if attempt["state"] != "active":
            fail("ATTEMPT_CLOSED", 409, "Попытка завершена.", **_summary(attempt, now))
        if attempt["active_generation"] != expected:
            fail("SESSION_REPLACED", 409, "Другой клиент уже активирован.", generation=attempt["active_generation"])
        token = secrets.token_urlsafe(32)
        updated = repo.claim_attempt_in_transaction(db, attempt_id, expected_generation=expected,
                    writer_token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(), writer_client_id=client, now=now)
        return {**_summary(updated, now), "writer_token": token}
    return _mutate_attempt(db, attempt_id, body, actor_id, None, action, needs_writer=False)


def heartbeat(db, attempt_id, body, actor_id, writer_token):
    _body(body, {"generation"})
    def action(attempt, now):
        if attempt["state"] == "active":
            repo.update_attempt_in_transaction(db, attempt_id, last_seen_at=now)
        return _summary(attempt, now)
    return _mutate_attempt(db, attempt_id, body, actor_id, writer_token, action)


def _answer_value(db, attempt, question_id, value, expected):
    _integer(question_id, "question_id")
    _integer(expected, "expected_revision", minimum=0)
    current = repo.get_answer(db, attempt["id"], question_id)
    if current is None:
        raise ValidationError({"question_id": "Вопрос не принадлежит этой попытке."})
    version = repo.get_version(db, attempt["version_id"])
    question = next(q for q in version["questions"] if q["id"] == question_id)
    answer = validate_answer(question, value)
    if current["revision"] != expected:
        fail("ANSWER_CONFLICT", 409, "Ответ уже изменён. Сверьте сохранённое значение.",
             question_id=question_id, answer=current["answer"], revision=current["revision"])
    return answer


def save_answer(db, attempt_id, question_id, body, actor_id, writer_token):
    _body(body, {"answer", "expected_revision", "generation", "mutation_id"})
    if "answer" not in body:
        raise ValidationError({"answer": "Передайте ответ или очистку ответа."})
    identity = {**body, "request_key": body.get("mutation_id")}
    key, hashed = _identity(identity)
    scope = f"save:{attempt_id}:{question_id}"
    def action(attempt, now):
        if attempt["state"] != "active":
            fail("ATTEMPT_CLOSED", 409, "Попытка завершена.", **_summary(attempt, now))
        if _receipt(db, actor_id, scope, key, hashed):
            saved = repo.get_answer(db, attempt_id, question_id)
        else:
            answer = _answer_value(db, attempt, question_id, body["answer"], body.get("expected_revision"))
            saved = repo.save_answer_in_transaction(db, attempt_id, question_id, answer, expected_revision=body["expected_revision"], now=now)
            _record(db, actor_id, scope, key, hashed, attempt_id, now)
        return {"revision": saved["revision"], "saved_at": iso_utc(saved["saved_at"]),
                "server_now": iso_utc(now), "deadline_at": iso_utc(attempt["deadline_at"]), "state": attempt["state"]}
    return _mutate_attempt(db, attempt_id, body, actor_id, writer_token, action)


def submit_attempt(db, attempt_id, body, actor_id, writer_token):
    _body(body, {"request_key", "generation", "answers"})
    key, hashed = _identity(body)
    scope = f"submit:{attempt_id}"
    def action(attempt, now):
        old = _receipt(db, actor_id, scope, key, hashed)
        if old or attempt["state"] != "active":
            if old is None:
                _record(db, actor_id, scope, key, hashed, attempt_id, now)
            return {"attempt_id": attempt_id, "state": attempt["state"], "result_url": _urls(attempt)["result_url"]}
        batch = body.get("answers", [])
        if not isinstance(batch, list):
            raise ValidationError({"answers": "Ожидается массив ответов."})
        updates, seen = [], set()
        for item in batch:
            _body(item, {"question_id", "answer", "expected_revision"})
            ident = _integer(item.get("question_id"), "question_id")
            if ident in seen or "answer" not in item:
                raise ValidationError({"answers": "Вопросы не должны повторяться; передайте ответ."})
            seen.add(ident)
            answer = _answer_value(db, attempt, ident, item["answer"], item.get("expected_revision"))
            updates.append((ident, answer, item["expected_revision"]))
        for ident, answer, expected in updates:
            repo.save_answer_in_transaction(db, attempt_id, ident, answer, expected_revision=expected, now=now)
        attempt = finalize_in_transaction(db, attempt, now=now, reason="manual")
        _record(db, actor_id, scope, key, hashed, attempt_id, now)
        return {"attempt_id": attempt_id, "state": attempt["state"], "result_url": _urls(attempt)["result_url"]}
    return _mutate_attempt(db, attempt_id, body, actor_id, writer_token, action)


def _version_media(version):
    return {q["media_id"]: q["media"] for q in version["questions"] if q.get("media") is not None}


def _read_attempt(db, attempt_id, actor_id, *, result=False):
    with repo.transaction(db):
        _user(db, actor_id)
        attempt = _owned_latest(db, attempt_id, actor_id)
        now = now_ms()
        attempt, _ = _expired(db, attempt, now)
        version = repo.get_version(db, attempt["version_id"])
        serializer = result_dto if result else attempt_dto
        data = serializer(attempt, version, repo.get_answers(db, attempt_id), now=now, media_by_id=_version_media(version))
        data.update(_urls(attempt))
        return data


def get_attempt(db, attempt_id, actor_id):
    return _read_attempt(db, attempt_id, actor_id)


def get_result(db, attempt_id, actor_id):
    return _read_attempt(db, attempt_id, actor_id, result=True)


def _card(db, parent, actor_id, now, starts_enabled):
    version = repo.get_version(db, parent["current_version_id"]) if parent["current_version_id"] else None
    if version is None:
        return None
    attempts = repo.list_attempts(db, user_id=actor_id, test_id=parent["id"])
    attempts = [_expired(db, attempt, now)[0] for attempt in attempts]
    latest = max(attempts, key=lambda a: a["attempt_no"]) if attempts else None
    if parent["publication_state"] != "published" and latest is None:
        return None
    graded = []
    for attempt in attempts:
        if attempt["state"] == "graded":
            snapshot = repo.get_version(db, attempt["version_id"])
            graded.append({**attempt, "summary": summarize(repo.get_answers(db, attempt["id"]), snapshot["question_count"])})
    best = best_attempt(graded)
    quota, remaining = _remaining(db, actor_id, parent["id"], version)
    active = latest is not None and latest["state"] == "active"
    status = "active" if active else "pending_review" if latest and latest["state"] == "pending_review" else "completed" if best else "not_started"
    card = {"id": parent["id"], "publication_state": parent["publication_state"],
            **{key: version[key] for key in ("title", "description", "question_count", "time_limit_seconds", "attempt_limit")},
            "remaining_attempts": remaining, "used_attempts": quota["used"], "status": status,
            "last_attempt_id": latest["id"] if latest else None, "last_attempt_state": latest["state"] if latest else None,
            "attempt_url": _urls(latest)["attempt_url"] if active else None,
            "result_url": _urls(latest)["result_url"] if latest and not active else None,
            "best": {key: best["summary"][key] for key in ("earned", "total", "percentage")} if best else None,
            "can_start": bool(starts_enabled and not active and parent["publication_state"] == "published" and (remaining is None or remaining > 0)),
            "can_resume": active}
    return card


def catalog(db, actor_id, *, starts_enabled=False):
    with repo.transaction(db):
        _user(db, actor_id)
        now = now_ms()
        cards = [_card(db, parent, actor_id, now, starts_enabled) for parent in repo.list_tests(db)]
        return {"tests": [card for card in cards if card is not None], "server_now": iso_utc(now)}


def test_detail(db, test_id, actor_id, *, starts_enabled=False):
    with repo.transaction(db):
        _user(db, actor_id)
        now = now_ms()
        card = _card(db, _test(db, test_id), actor_id, now, starts_enabled)
        if card is None:
            fail("NOT_FOUND", 404, "Тест не найден.")
        return {**card, "server_now": iso_utc(now)}


def get_student_media(db, attempt_id, media_id, actor_id):
    with repo.transaction(db):
        _user(db, actor_id)
        attempt = _owned_latest(db, attempt_id, actor_id)
        attempt, _ = _expired(db, attempt, now_ms())
        _integer(media_id, "media_id")
        version = repo.get_version(db, attempt["version_id"])
        if not any(q["media_id"] == media_id for q in version["questions"]):
            fail("NOT_FOUND", 404, "Изображение не найдено.")
        media = repo.get_media(db, media_id)
        if media is None or media["state"] != "ready":
            fail("NOT_FOUND", 404, "Изображение не найдено.")
        return media


def expire_attempts(db, *, batch_size=100):
    _integer(batch_size, "batch_size")
    candidates = repo.expired_attempt_ids(db, now_ms(), limit=batch_size)
    count = 0
    for ident in candidates:
        with repo.transaction(db):
            attempt = repo.get_attempt(db, ident)
            now = now_ms()
            if attempt is not None:
                _, expired = _expired(db, attempt, now)
                count += int(expired)
    return count


def _admin_attempt(db, attempt_id):
    _integer(attempt_id, "attempt_id")
    attempt = repo.get_attempt(db, attempt_id)
    if attempt is None:
        fail("NOT_FOUND", 404, "Попытка не найдена.")
    return attempt


def _student_identity(db, user_id):
    _integer(user_id, "user_id")
    identity = repo.student_identity(db, user_id)
    if identity is None:
        fail("NOT_FOUND", 404, "Ученик не найден.")
    return identity


def admin_attempt(db, attempt_id, actor_id):
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        attempt = _admin_attempt(db, attempt_id)
        now = now_ms()
        attempt, _ = _expired(db, attempt, now)
        version = repo.get_version(db, attempt["version_id"])
        data = admin_attempt_dto(attempt, version, repo.get_answers(db, attempt_id),
                                 now=now, media_by_id=_version_media(version))
        data.update(student=_student_identity(db, attempt["user_id"]), version_no=version["version_no"])
        return data


def review_queue(db, actor_id, offset=0, limit=50):
    _integer(offset, "offset", minimum=0)
    _integer(limit, "limit")
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _expire_in_transaction(db, now_ms())
        rows, total = repo.pending_attempts_page(db, offset=offset, limit=limit)
        for row in rows:
            row["submitted_at"] = iso_utc(row["submitted_at"])
            row["student_name"] = row["student_name"] or row["username"]
        next_offset = offset + len(rows)
        return {"items": rows, "next_offset": next_offset if next_offset < total else None}


def _grade_response(db, attempt_id, question_id):
    attempt = repo.get_attempt(db, attempt_id)
    answer = repo.get_answer(db, attempt_id, question_id)
    version = repo.get_version(db, attempt["version_id"])
    summary = summarize(repo.get_answers(db, attempt_id), version["question_count"])
    return {"attempt_id": attempt_id, "question_id": question_id, "score": answer["score"],
            "grading_source": answer["grading_source"], "grade_revision": answer["grade_revision"],
            "result_revision": attempt["result_revision"], "pending_count": summary["pending_count"],
            "summary": summary, "state": attempt["state"]}


def _grade_in_transaction(db, attempt, question_id, body, actor_id, now, key, hashed):
    attempt_id = attempt["id"]
    scope = f"grade:{attempt_id}:{question_id}"
    answer = repo.get_answer(db, attempt_id, question_id)
    if answer is None:
        fail("NOT_FOUND", 404, "Вопрос попытки не найден.")
    if attempt["state"] == "active":
        fail("ATTEMPT_ACTIVE", 409, "Проверка доступна после отправки попытки.")
    old = _receipt(db, actor_id, scope, key, hashed)
    if old is not None:
        return _grade_response(db, attempt_id, question_id)
    if repo.get_grade_event_by_key(db, actor_id, key) is not None:
        fail("IDEMPOTENCY_KEY_REUSED", 409, "Ключ уже использован для другой оценки.")
    if answer["grade_revision"] != body["expected_grade_revision"]:
        fail("REVISION_CONFLICT", 409, "Оценка уже изменена другим проверяющим.",
             grade_revision=answer["grade_revision"], score=answer["score"])
    if answer["was_unanswered"] and body["score"] != 0:
        raise ValidationError({"score": "Пропущенный вопрос всегда получает 0 баллов."})
    version = repo.get_version(db, attempt["version_id"])
    question = next(q for q in version["questions"] if q["id"] == question_id)
    source = "manual" if question["grading_mode"] == "manual" else "override"
    result_revision = attempt["result_revision"] + 1
    repo.set_answer_grade_in_transaction(db, attempt_id, question_id,
                expected_grade_revision=body["expected_grade_revision"], score=body["score"],
                grading_source=source, graded_by=actor_id, graded_at=now,
                grade_revision=answer["grade_revision"] + 1)
    summary = summarize(repo.get_answers(db, attempt_id), version["question_count"])
    repo.update_attempt_in_transaction(db, attempt_id, result_revision=result_revision,
                state="graded" if summary["pending_count"] == 0 else "pending_review")
    repo.add_grade_event_in_transaction(db, attempt_id, question_id,
                old_score=answer["score"], new_score=body["score"], old_source=answer["grading_source"],
                new_source=source, actor_id=actor_id, actor_kind="admin", now=now,
                request_key=key, result_revision=result_revision)
    _record(db, actor_id, scope, key, hashed, attempt_id, now)
    return _grade_response(db, attempt_id, question_id)


def grade_attempt_answer(db, attempt_id, question_id, body, actor_id):
    _body(body, {"score", "expected_grade_revision", "request_key"})
    if type(body.get("score")) is not int or body["score"] not in (0, 1):
        raise ValidationError({"score": "Оценка должна быть целым числом 0 или 1."})
    _integer(body.get("expected_grade_revision"), "expected_grade_revision", minimum=0)
    _integer(question_id, "question_id")
    key, hashed = _identity(body, {"attempt_id": attempt_id, "question_id": question_id,
                                  "score": body["score"], "expected_grade_revision": body["expected_grade_revision"]})
    deferred = None
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        attempt = _admin_attempt(db, attempt_id)
        now = now_ms()
        attempt, expired = _expired(db, attempt, now)
        try:
            result = _grade_in_transaction(db, attempt, question_id, body, actor_id, now, key, hashed)
        except (TestsError, ValidationError) as error:
            if not expired:
                raise
            deferred = error
    if deferred:
        raise deferred
    return result


def user_tests(db, user_id, actor_id):
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _student_identity(db, user_id)
        now = now_ms()
        tests = []
        for parent in repo.list_tests(db):
            if parent["current_version_id"] is None:
                continue
            card = _card(db, parent, user_id, now, True)
            # Admin history includes hidden tests even before this pupil starts.
            if card is None:
                version = repo.get_version(db, parent["current_version_id"])
                quota, remaining = _remaining(db, user_id, parent["id"], version)
                card = {"id": parent["id"], "title": version["title"], "publication_state": parent["publication_state"],
                        "used_attempts": quota["used"], "remaining_attempts": remaining, "best": None}
            attempts = repo.list_attempts(db, user_id=user_id, test_id=parent["id"])
            tests.append({**{key: card[key] for key in ("id", "title", "publication_state", "used_attempts", "remaining_attempts", "best")},
                          "active_count": sum(a["state"] == "active" for a in attempts),
                          "submitted_count": sum(a["state"] != "active" for a in attempts)})
        return {"user_id": user_id, "tests": tests}


def user_test_attempts(db, user_id, test_id, actor_id, offset=0, limit=50):
    _integer(offset, "offset", minimum=0)
    _integer(limit, "limit")
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _student_identity(db, user_id)
        _test(db, test_id)
        now = now_ms()
        for attempt in repo.list_attempts(db, user_id=user_id, test_id=test_id, state="active"):
            _expired(db, attempt, now)
        rows, total = repo.user_attempts_page(db, user_id, test_id, offset=offset, limit=limit)
        items = []
        for attempt in rows:
            version = repo.get_version(db, attempt["version_id"])
            dto = attempt_summary_dto(attempt, now=now)
            dto.update(version_id=version["id"], version_no=version["version_no"],
                       summary=summarize(repo.get_answers(db, attempt["id"]), version["question_count"])
                               if attempt["state"] != "active" else None)
            items.append(dto)
        next_offset = offset + len(items)
        return {"items": items, "next_offset": next_offset if next_offset < total else None}


def grant_attempts(db, user_id, test_id, body, actor_id):
    _body(body, {"amount", "request_key"})
    amount = _integer(body.get("amount"), "amount")
    key, hashed = _identity(body, {"user_id": user_id, "test_id": test_id, "amount": amount})
    scope = f"grant:{user_id}:{test_id}"
    with repo.transaction(db):
        _user(db, actor_id, admin=True)
        _student_identity(db, user_id)
        parent = _test(db, test_id)
        now = now_ms()
        old = _receipt(db, actor_id, scope, key, hashed)
        if old:
            grant = repo.get_grant(db, old["resource_id"])
            if grant is None:
                fail("NOT_FOUND", 404, "Выдача попыток не найдена.")
            ident = grant["id"]
        else:
            if repo.get_grant_by_key(db, actor_id, key) is not None:
                fail("IDEMPOTENCY_KEY_REUSED", 409, "Ключ уже использован для другой выдачи.")
            quota = repo.quota_usage(db, user_id, test_id)
            _integer(quota["grants"] + amount, "amount")
            ident = repo.add_grant_in_transaction(db, user_id, test_id, amount, actor_id=actor_id, now=now, request_key=key)
            _record(db, actor_id, scope, key, hashed, ident, now)
        version = repo.get_version(db, parent["current_version_id"]) if parent["current_version_id"] else None
        remaining = _remaining(db, user_id, test_id, version)[1] if version else 0
        return {"grant_id": ident, "remaining_attempts": remaining}
