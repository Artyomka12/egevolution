"""Pure allowlisted DTOs; callers authorize owner/latest within their transaction.

No serializer grants access. Student callers must pass the authorized latest
attempt and its immutable version/answers. Admin DTOs are separate entry points
and must never be used in student HTML, JSON or embedded page data.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from .errors import TestsError
from .grading import summarize


def iso_utc(milliseconds):
    if milliseconds is None:
        return None
    return (datetime(1970, 1, 1, tzinfo=timezone.utc)
            + timedelta(milliseconds=milliseconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timing_dto(attempt, now):
    """Freeze completed remaining time at submission, including timeout=0."""
    active = attempt["state"] == "active"
    end = now if active else attempt["submitted_at"]
    duration = attempt["time_limit_seconds_snapshot"] * 1000
    elapsed = min(max(end - attempt["started_at"], 0), duration)
    remaining_ms = max(0, attempt["deadline_at"] - end)
    remaining = (remaining_ms + 999) // 1000
    if not active and attempt.get("finish_reason") == "timeout":
        remaining = 0
    return {
        "server_now": iso_utc(now), "started_at": iso_utc(attempt["started_at"]),
        "deadline_at": iso_utc(attempt["deadline_at"]),
        "submitted_at": iso_utc(attempt.get("submitted_at")),
        "finalized_at": iso_utc(attempt.get("finalized_at")),
        "remaining_seconds": remaining, "elapsed_seconds": elapsed // 1000,
        "time_limit_seconds": attempt["time_limit_seconds_snapshot"],
    }


def attempt_summary_dto(attempt, *, now):
    result = {"attempt_id": attempt["id"], "test_id": attempt["test_id"],
              "attempt_no": attempt["attempt_no"], "state": attempt["state"],
              "generation": attempt["active_generation"],
              "finish_reason": attempt.get("finish_reason")}
    result.update(timing_dto(attempt, now))
    return result


def _media(question, attempt, media_by_id, *, admin=False):
    ident = question.get("media_id")
    if ident is None:
        return None
    metadata = (media_by_id or {}).get(ident, {})
    url = (f"/api/admin/tests/{attempt['test_id']}/media/{ident}" if admin else
           f"/tests/attempts/{attempt['id']}/media/{ident}")
    return {"id": ident, "url": url, "alt_text": metadata.get("alt_text", ""),
            "width": metadata.get("width"), "height": metadata.get("height")}


def question_dto(question, answer, attempt, *, media_by_id=None, admin=False):
    result = {key: deepcopy(question.get(key)) for key in (
        "id", "position", "title", "question_type", "prompt_text", "code_text",
        "free_input_mode", "grading_mode")}
    result["options"] = [{key: deepcopy(option[key]) for key in ("id", "position", "text")}
                         for option in question.get("options", [])]
    result["media"] = _media(question, attempt, media_by_id, admin=admin)
    result["answer"] = deepcopy(answer["answer"])
    result["revision"] = answer["revision"]
    result["saved_at"] = iso_utc(answer.get("saved_at"))
    return result


def _reference(question):
    if question["question_type"] in ("single_choice", "multiple_choice"):
        return {"option_ids": [option["id"] for option in question["options"] if option["is_correct"]]}
    accepted = question.get("accepted_answers", [])
    return {"accepted_answers": deepcopy(accepted)} if accepted else None


def _rows(version, answers):
    rows = list(answers)
    by_id = {row["question_id"]: row for row in rows}
    ids = {question["id"] for question in version["questions"]}
    if len(by_id) != len(rows) or ids != set(by_id) or len(ids) != version["question_count"]:
        raise ValueError("Answer rows do not match the immutable version")
    return rows, by_id


def attempt_dto(attempt, version, answers, *, now, media_by_id=None):
    """Safe attempt payload, even when given rows with internal grading fields."""
    _, by_id = _rows(version, answers)
    result = attempt_summary_dto(attempt, now=now)
    result.update(title=version["title"], description=version.get("description", ""),
                  question_count=version["question_count"],
                  questions=[question_dto(question, by_id[question["id"]], attempt,
                                          media_by_id=media_by_id)
                             for question in version["questions"]])
    return result


def result_dto(attempt, version, answers, *, now, media_by_id=None):
    if attempt["state"] == "active":
        raise TestsError("ATTEMPT_ACTIVE", 409, "Попытка ещё не завершена.",
                         {"attempt_url": f"/tests/attempts/{attempt['id']}"})
    rows, by_id = _rows(version, answers)
    result = attempt_dto(attempt, version, rows, now=now, media_by_id=media_by_id)
    summary = summarize(rows, version["question_count"])
    fully_graded = attempt["state"] == "graded" and summary["pending_count"] == 0
    if not fully_graded:
        summary.update(final_score=None, percentage=None, is_final=False)
    result.update(summary=summary, result_revision=attempt["result_revision"])
    show = fully_graded and bool(attempt["show_correct_answers_snapshot"])
    for raw, public in zip(version["questions"], result["questions"]):
        row = by_id[raw["id"]]
        public.update(score=row["score"], was_unanswered=bool(row["was_unanswered"]),
                      grade_revision=row["grade_revision"],
                      status=("pending" if row["score"] is None else
                              "skipped" if row["was_unanswered"] else
                              "correct" if row["score"] == 1 else "incorrect"))
        reference = _reference(raw)
        if show and reference is not None:
            public["reference"] = reference
        elif (attempt["state"] == "pending_review" and
              attempt["show_correct_answers_snapshot"] and reference is not None):
            public["reference_pending"] = True
    return result


def admin_attempt_dto(attempt, version, answers, *, now, media_by_id=None):
    """Administrative entry point: full history, existing references and audit fields."""
    rows, by_id = _rows(version, answers)
    result = attempt_dto(attempt, version, rows, now=now, media_by_id=media_by_id)
    result.update(user_id=attempt["user_id"], version_id=attempt["version_id"],
                  result_revision=attempt["result_revision"],
                  can_grade=attempt["state"] in ("pending_review", "graded"))
    result["summary"] = summarize(rows, version["question_count"]) if result["can_grade"] else None
    for raw, public in zip(version["questions"], result["questions"]):
        row = by_id[raw["id"]]
        public["media"] = _media(raw, attempt, media_by_id, admin=True)
        public.update({key: deepcopy(row.get(key)) for key in (
            "score", "auto_score", "was_unanswered", "grading_source", "grade_revision", "graded_by")})
        public["graded_at"] = iso_utc(row.get("graded_at"))
        public["status"] = ("active" if not result["can_grade"] else
                            "pending" if row["score"] is None else
                            "skipped" if row["was_unanswered"] else
                            "correct" if row["score"] == 1 else "incorrect")
        reference = _reference(raw)
        if reference is not None:
            public["reference"] = reference
    return result
