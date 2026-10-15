"""Pure binary grading for immutable test versions.

Answers are validated before entering this module. Text comparisons deliberately
preserve every character; transport newline conversion belongs at the input
boundary, never in the grader.
"""


def grade_answer(question, answer):
    """Grade a single ID, list of IDs, or literal text against its version.

    None clears any answer. Empty multiple-choice lists and empty free-text
    strings are skips. Whitespace-only text is an answer, including for manual
    questions. A skip is always zero and does not require manual review.
    """
    kind = question["question_type"]
    if kind not in ("single_choice", "multiple_choice", "free_text"):
        raise ValueError("Unsupported question type")
    unanswered = (answer is None
                  or (kind == "multiple_choice" and answer == [])
                  or (kind == "free_text" and answer == ""))
    if unanswered:
        return {"was_unanswered": True, "auto_score": 0, "score": 0,
                "grading_source": "automatic"}

    if kind == "free_text" and question["grading_mode"] == "manual":
        return {"was_unanswered": False, "auto_score": None, "score": None,
                "grading_source": None}

    if kind == "free_text":
        correct = answer in question["accepted_answers"]
    else:
        expected = {option["id"] for option in question["options"]
                    if option["is_correct"]}
        correct = ({answer} == expected if kind == "single_choice"
                   else set(answer) == expected)
    score = int(correct)
    return {"was_unanswered": False, "auto_score": score, "score": score,
            "grading_source": "automatic"}


def summarize(answers, total_count):
    """Summarize all persisted answer rows using the version's denominator.

    Reject an incomplete row set instead of treating missing rows as checked
    skips. This prevents a malformed caller from publishing a final percentage.
    """
    if type(total_count) is not int or total_count < 1:
        raise ValueError("The version must contain at least one question")
    rows = list(answers)
    if len(rows) != total_count:
        raise ValueError("Answer count does not match the immutable version")
    earned = checked = 0
    for row in rows:
        score = row["score"]
        if score is None:
            continue
        if type(score) is not int or score not in (0, 1):
            raise ValueError("A question score must be 0, 1, or None")
        earned += score
        checked += 1
    pending = total_count - checked
    return {"earned": earned, "total": total_count, "checked_count": checked,
            "pending_count": pending, "is_final": pending == 0,
            "final_score": earned if pending == 0 else None,
            "percentage": 100 * earned / total_count if pending == 0 else None}


aggregate = summarize
