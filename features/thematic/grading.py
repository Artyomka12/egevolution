"""Binary grading v1, matching the existing ordinary-mode normalization."""
from dataclasses import dataclass

GRADER_VERSION = "ordinary-binary-v1"


class InvalidTask(ValueError):
    pass


def _text(value):
    if not isinstance(value, str):
        raise InvalidTask("Reference answers must be strings")
    return value.strip().lower()


def answer_spec(task):
    """Validate the reference shape; never infer EGE number from item position."""
    if not isinstance(task, dict):
        raise InvalidTask("Task must be an object")
    if sum(key in task for key in ("correct_answer", "answers", "answer_grid")) != 1:
        raise InvalidTask("Exactly one answer format is required")
    if "correct_answer" in task:
        reference = _text(task["correct_answer"])
        if not reference:
            raise InvalidTask("Empty reference")
        return "scalar", reference
    if "answers" in task:
        values = task["answers"]
        if not isinstance(values, list) or len(values) != 2:
            raise InvalidTask("A pair must have exactly two answers")
        reference = [_text(v) for v in values]
        if not all(reference):
            raise InvalidTask("Empty pair reference")
        return "pair", reference
    grid = task["answer_grid"]
    if not isinstance(grid, dict):
        raise InvalidTask("Grid must be an object")
    rows, cols = grid.get("rows"), grid.get("cols")
    values = grid.get("answers")
    if type(rows) is not int or type(cols) is not int or min(rows, cols) < 1:
        raise InvalidTask("Invalid grid dimensions")
    if not isinstance(values, list) or len(values) != rows or any(
        not isinstance(row, list) or len(row) != cols for row in values
    ):
        raise InvalidTask("Reference grid shape mismatch")
    reference = [[_text(v) for v in row] for row in values]
    if not any(v for row in reference for v in row):
        raise InvalidTask("Entire reference grid is empty")
    return "grid", reference


def _unanswered(answer):
    if answer is None:
        return True
    if isinstance(answer, str):
        return not answer.strip()
    if isinstance(answer, list):
        return all(_unanswered(value) for value in answer)
    return False


@dataclass(frozen=True)
class Grade:
    score: int
    status: str


def grade(task, answer, *, grader_version=GRADER_VERSION):
    if grader_version != GRADER_VERSION:
        raise InvalidTask("Unsupported grader version")
    kind, expected = answer_spec(task)
    if _unanswered(answer):
        return Grade(0, "skipped")
    correct = False
    if kind == "scalar":
        correct = isinstance(answer, str) and _text(answer) == expected
    elif kind == "pair":
        correct = (isinstance(answer, list) and len(answer) == 2
                   and all(isinstance(v, str) for v in answer)
                   and [_text(v) for v in answer] == expected)
    elif isinstance(answer, list) and len(answer) == len(expected):
        correct = all(
            isinstance(row, list) and len(row) == len(ref)
            and all(isinstance(v, str) for v in row)
            and [_text(v) for v in row] == ref
            for row, ref in zip(answer, expected)
        )
    return Grade(int(correct), "correct" if correct else "incorrect")
