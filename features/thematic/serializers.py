"""Allowlisted data; full grading references must not leak into active DTOs."""
from copy import deepcopy
from .validation import validate_snapshot


def task_dto(snapshot, *, finished=False):
    validate_snapshot(snapshot)
    result = {k: deepcopy(snapshot[k]) for k in ("source_task_num", "source_task_id", "title", "description", "task_type")}
    result["materials"] = [deepcopy(m) for m in snapshot["materials"] if finished or m["role"] != "reference"]
    if snapshot["task_type"] == "grid":
        result["answer_shape"] = {k: snapshot["grading"]["answer_grid"][k] for k in ("rows", "cols")}
    if finished:
        result["reference"] = deepcopy(snapshot["grading"])
    return result
