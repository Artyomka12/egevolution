"""Low-level thematic persistence; callers own authorization and lifecycle."""
from core.content_store import store_for, transaction
import json
from pathlib import Path
import sqlite3
from .validation import canonical_json, digest, validate_sources, validate_snapshot, validate_draft
from .grading import GRADER_VERSION


def connect(database):
    """Explicit existing path only; never falls back to either working database."""
    db = sqlite3.connect(Path(database).resolve(strict=True).as_uri() + "?mode=rw",
                         uri=True, isolation_level=None, timeout=5)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA recursive_triggers=ON")
    return db


def content(db):
    return store_for(db, 'thematic')


def row(db, table, ident):
    return content(db).get('thematic_' + table, ident)


def rows(db, table):
    return content(db).rows('thematic_' + table)


def insert(db, table, values):
    return content(db).insert('thematic_' + table, values)


def update(db, table, ident, **values):
    return content(db).update('thematic_' + table, ident, **values)


def bump_catalog(db):
    current = row(db, 'catalog_state', 1)
    update(db, 'catalog_state', 1, revision=current['revision'] + 1)


def media_for_version(db, version_id, media_id, *, finished=True):
    links = [link for link in rows(db, 'item_media') if link['version_id'] == version_id
             and link['media_id'] == media_id and (finished or link['role'] in {'condition', 'attachment'})]
    material = row(db, 'media', media_id)
    return dict(material, role=links[0]['role']) if material and links else None


class Conflict(ValueError):
    pass


def save_draft(db, variant_id, document, *, expected_revision, actor_id, now):
    validate_draft(document)
    with transaction(db):
        parent = row(db, 'variants', variant_id)
        if parent is None or parent['state'] in {"deleting", "deleted"}:
            raise Conflict("Variant unavailable")
        current = row(db, 'drafts', variant_id)
        if current is None:
            if expected_revision != 0:
                raise Conflict("Draft revision mismatch")
            insert(db, 'drafts', dict(variant_id=variant_id, document_json=canonical_json(document), revision=1,
                                    updated_by=actor_id, updated_at=now, based_on_version_id=None))
            return 1
        if current['revision'] != expected_revision:
            raise Conflict("Draft revision mismatch")
        update(db, 'drafts', variant_id, document_json=canonical_json(document), revision=expected_revision + 1,
               updated_by=actor_id, updated_at=now)
        return expected_revision + 1


def store_version(db, variant_id, title, description, snapshots, *, actor_id, now):
    with transaction(db):
        return store_version_in_transaction(db, variant_id, title, description, snapshots,
                                            actor_id=actor_id, now=now)


def store_version_in_transaction(db, variant_id, title, description, snapshots, *, actor_id, now):
    """Store/seal within the caller's publication transaction, without committing."""
    if not isinstance(title, str) or not title.strip() or not isinstance(description, str):
        raise ValueError("Invalid version title/description")
    validate_sources(snapshots)
    for snapshot in snapshots:
        validate_snapshot(snapshot)
    if not db.in_transaction:
        raise ValueError("Publication requires an owned transaction")
    parent = row(db, 'variants', variant_id)
    if parent is None or parent['state'] in {"deleting", "deleted"}:
        raise Conflict("Variant unavailable")
    number = max((v['version_no'] for v in rows(db, 'versions') if v['variant_id'] == variant_id), default=0) + 1
    version_id = insert(db, 'versions', dict(variant_id=variant_id, version_no=number, title=title,
        description=description, question_count=len(snapshots), snapshot_schema_version=1,
        grader_version=GRADER_VERSION, content_hash=digest({'title': title, 'description': description, 'items': snapshots}),
        published_by=actor_id, published_at=now, sealed=0))
    for position, snapshot in enumerate(snapshots, 1):
        item_id = insert(db, 'version_items', dict(version_id=version_id, position=position,
            source_task_num=snapshot['source_task_num'], source_task_id=snapshot['source_task_id'],
            task_type=snapshot['task_type'], snapshot_json=canonical_json(snapshot), snapshot_hash=digest(snapshot)))
        for material in snapshot["materials"]:
            stored = row(db, 'media', material['media_id'])
            if stored is None or stored['sha256'] != material["sha256"]:
                raise ValueError("Missing or changed immutable material")
            insert(db, 'item_media', dict(item_id=item_id, version_id=version_id, media_id=material['media_id'],
                role=material['role'], position=material['position'], alt_text=material['alt_text'],
                display_metadata_json=canonical_json(material['display_metadata'])))
    update(db, 'versions', version_id, sealed=1)
    return version_id


def get_version(db, version_id):
    version = row(db, 'versions', version_id)
    if version is None or version['sealed'] != 1:
        return None
    result = dict(version)
    result['items'] = sorted((dict(item) for item in rows(db, 'version_items') if item['version_id'] == version_id), key=lambda item: item['position'])
    for item in result["items"]:
        item["snapshot"] = json.loads(item.pop("snapshot_json"))
    return result


def list_attempts(db, user_id, variant_id):
    return [dict(row) for row in db.execute(
        "SELECT * FROM thematic_attempts WHERE user_id=? AND variant_id=? ORDER BY attempt_no",
        (user_id, variant_id))]
