"""Account-owned rows only; caller owns authorization and BEGIN IMMEDIATE.

Publication/media attribution uses the schema's ON DELETE SET NULL. Never delete
catalog entries, snapshots, media or another user's results. No filesystem IO.
"""


def delete_user_data_in_transaction(db, user_id):
    if not db.in_transaction or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise ValueError("Account deletion requires a transaction with foreign keys enabled")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "test_attempts" in tables:
        # Explicit child-first order; do not rely on a user->test cascade.
        db.execute("""DELETE FROM test_grade_events WHERE attempt_id IN
                      (SELECT id FROM test_attempts WHERE user_id=?)""", (user_id,))
        db.execute("""DELETE FROM test_attempt_answers WHERE attempt_id IN
                      (SELECT id FROM test_attempts WHERE user_id=?)""", (user_id,))
        db.execute("DELETE FROM test_attempts WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM test_attempt_grants WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM test_operation_keys WHERE actor_user_id=?", (user_id,))
    if "thematic_attempts" in tables:
        db.execute("""DELETE FROM thematic_answers WHERE attempt_id IN
                      (SELECT id FROM thematic_attempts WHERE user_id=?)""", (user_id,))
        db.execute("DELETE FROM thematic_attempts WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM thematic_operation_keys WHERE actor_user_id=?", (user_id,))
    for table in ("user_task_answers", "user_results", "user_variant_progress",
                  "user_lesson_progress", "user_theory_progress",
                  "user_lesson_last_answer", "user_theory_last_answer",
                  "user_lesson_access", "user_theory_access"):
        db.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
    # Remaining references are nullable creator/reviewer attribution. The known
    # FK actions preserve those records and published versions, including media.
    # Any unexpected RESTRICT reference fails closed and rolls back the caller.
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
