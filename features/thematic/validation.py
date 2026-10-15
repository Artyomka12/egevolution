"""Validation and detached snapshots; no filesystem or bank mutations."""
from copy import deepcopy
import hashlib
import json
import re
from .grading import answer_spec, GRADER_VERSION, InvalidTask

SNAPSHOT_SCHEMA_VERSION = 1


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_sources(items, *, allow_empty=False):
    if not isinstance(items, list) or (not items and not allow_empty):
        raise ValueError("A nonempty ordered task list is required")
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid source")
        num, source_id = item.get("source_task_num"), item.get("source_task_id")
        if type(num) is not int or not 1 <= num <= 27 or type(source_id) is not int or source_id < 1:
            raise ValueError("Invalid source identity")
        pair = (num, source_id)
        if pair in seen:
            raise ValueError("Duplicate source task")
        seen.add(pair)


def validate_draft(document):
    if not isinstance(document, dict):
        raise ValueError("Draft must be an object")
    for key in ("title", "description"):
        if not isinstance(document.get(key, ""), str):
            raise ValueError("Draft text must be strings")
    validate_sources(document.get("items", []), allow_empty=True)
    canonical_json(document)


def make_snapshot(source_task_num, task, materials=()):
    """Caller supplies already copied, verified immutable material descriptors.

    Each descriptor: role, position, source_path, media_id, sha256, alt_text,
    display_metadata. Images/files never retain a live bank URL in the snapshot.
    Actual file staging and publication transactions belong to stage 1.3.
    """
    validate_sources([{"source_task_num": source_task_num, "source_task_id": task.get("id")}])
    kind, _ = answer_spec(task)
    description = task.get("description")
    if not isinstance(description, list) or not description or not all(isinstance(p, str) for p in description):
        raise InvalidTask("Task description must be a nonempty list of paragraphs")
    if not any(p.strip() for p in description):
        raise InvalidTask("Empty condition")
    expected = []
    for i, image in enumerate(task.get("images") or [], 1):
        expected.append(("condition", i, image))
    files = task.get("files") or ([task["file"]] if task.get("file") else [])
    for i, attachment in enumerate(files, 1):
        expected.append(("attachment", i, attachment))
    if len(materials) != len(expected):
        raise ValueError("Every original material must have an immutable copy")
    copied = []
    for (role, position, original), material in zip(expected, materials):
        if (not isinstance(original, dict) or not isinstance(material, dict)
                or material.get("source_path") != original.get("path")
                or material.get("role") != role or material.get("position") != position
                or type(material.get("media_id")) is not int or material["media_id"] < 1
                or not re.fullmatch(r"[0-9a-f]{64}", material.get("sha256", ""))):
            raise ValueError("Invalid material mapping")
        # Presentation belongs to this version, rather than the mutable bank/file.
        copied.append({"role": role, "position": position,
                       "media_id": material["media_id"], "sha256": material["sha256"],
                       "alt_text": original.get("alt", ""),
                       "display_metadata": {k: deepcopy(v) for k, v in original.items() if k not in {"path", "alt"}}})
    grading = {k: deepcopy(task[k]) for k in ("correct_answer", "answers", "answer_grid") if k in task}
    return {"snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION, "grader_version": GRADER_VERSION,
            "source_task_num": source_task_num, "source_task_id": task["id"], "task_type": kind,
            "title": task.get("title", ""), "description": deepcopy(description),
            "grading": grading, "materials": copied}


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        raise ValueError("Snapshot must be an object")
    if snapshot.get("snapshot_schema_version") != SNAPSHOT_SCHEMA_VERSION or snapshot.get("grader_version") != GRADER_VERSION:
        raise ValueError("Unsupported snapshot version")
    validate_sources([snapshot])
    kind, _ = answer_spec(snapshot.get("grading"))
    if snapshot.get("task_type") != kind:
        raise ValueError("Snapshot type mismatch")
    if not isinstance(snapshot.get("title"), str) or not isinstance(snapshot.get("description"), list) or not snapshot["description"] or not all(isinstance(p, str) for p in snapshot["description"]) or not any(p.strip() for p in snapshot["description"]):
        raise ValueError("Invalid snapshot condition")
    if not isinstance(snapshot.get("materials"), list):
        raise ValueError("Snapshot material list is required")
    seen = set()
    for material in snapshot["materials"]:
        if not isinstance(material, dict):
            raise ValueError("Material must be an object")
        key = (material.get("role"), material.get("position"))
        if key[0] not in {"condition", "reference", "attachment"} or type(key[1]) is not int or key[1] < 1 or key in seen:
            raise ValueError("Invalid material order")
        seen.add(key)
        if type(material.get("media_id")) is not int or material["media_id"] < 1 or not re.fullmatch(r"[0-9a-f]{64}", material.get("sha256", "")):
            raise ValueError("Invalid material identity")
        if not isinstance(material.get("alt_text"), str) or not isinstance(material.get("display_metadata"), dict):
            raise ValueError("Invalid material presentation")
    canonical_json(snapshot)
