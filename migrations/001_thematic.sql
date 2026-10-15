-- SQLite >= 3.26.0. No JSON1, generated columns, STRICT or RETURNING.
-- schema_migrations is owned by the migration runner, not by this file.
CREATE TABLE thematic_catalog_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    revision INTEGER NOT NULL CHECK (revision >= 1)
);
INSERT INTO thematic_catalog_state VALUES (1, 1);

CREATE TABLE thematic_variants (
    id INTEGER PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','published','hidden','deleting','deleted')),
    current_version_id INTEGER,
    sort_order INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    deleted_at INTEGER,
    FOREIGN KEY (current_version_id,id) REFERENCES thematic_versions(id,variant_id) ON DELETE RESTRICT,
    CHECK (state NOT IN ('published','hidden') OR current_version_id IS NOT NULL),
    CHECK ((state = 'deleted' AND deleted_at IS NOT NULL AND current_version_id IS NULL)
        OR (state <> 'deleted' AND deleted_at IS NULL))
);

CREATE TABLE thematic_versions (
    id INTEGER PRIMARY KEY,
    variant_id INTEGER NOT NULL REFERENCES thematic_variants(id) ON DELETE RESTRICT,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description TEXT NOT NULL,
    question_count INTEGER NOT NULL CHECK (question_count > 0),
    snapshot_schema_version INTEGER NOT NULL CHECK (snapshot_schema_version > 0),
    grader_version TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    published_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    published_at INTEGER NOT NULL,
    sealed INTEGER NOT NULL DEFAULT 0 CHECK (sealed IN (0,1)),
    UNIQUE (variant_id,version_no), UNIQUE (id,variant_id)
);

CREATE TABLE thematic_drafts (
    variant_id INTEGER PRIMARY KEY REFERENCES thematic_variants(id) ON DELETE RESTRICT,
    document_json TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    based_on_version_id INTEGER,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (based_on_version_id,variant_id) REFERENCES thematic_versions(id,variant_id) ON DELETE RESTRICT
);

CREATE TABLE thematic_version_items (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES thematic_versions(id) ON DELETE RESTRICT,
    position INTEGER NOT NULL CHECK (position > 0),
    source_task_num INTEGER NOT NULL CHECK (source_task_num BETWEEN 1 AND 27),
    source_task_id INTEGER NOT NULL CHECK (source_task_id > 0),
    task_type TEXT NOT NULL CHECK (task_type IN ('scalar','pair','grid')),
    snapshot_json TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
    UNIQUE (version_id,position), UNIQUE (version_id,source_task_num,source_task_id), UNIQUE (id,version_id)
);

CREATE TABLE thematic_media (
    id INTEGER PRIMARY KEY,
    storage_key TEXT NOT NULL UNIQUE CHECK (length(storage_key) > 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    width INTEGER CHECK (width > 0), height INTEGER CHECK (height > 0),
    original_name TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE thematic_item_media (
    item_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    media_id INTEGER NOT NULL REFERENCES thematic_media(id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('condition','reference','attachment')),
    position INTEGER NOT NULL CHECK (position > 0),
    alt_text TEXT NOT NULL,
    display_metadata_json TEXT NOT NULL,
    PRIMARY KEY (item_id,role,position),
    FOREIGN KEY (item_id,version_id) REFERENCES thematic_version_items(id,version_id) ON DELETE RESTRICT
);

CREATE TABLE thematic_visibility_intervals (
    id INTEGER PRIMARY KEY,
    variant_id INTEGER NOT NULL REFERENCES thematic_variants(id) ON DELETE RESTRICT,
    hidden_at INTEGER NOT NULL,
    visible_at INTEGER CHECK (visible_at >= hidden_at),
    hidden_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    visible_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE thematic_attempts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    variant_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    attempt_no INTEGER NOT NULL CHECK (attempt_no > 0),
    state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','finished')),
    started_at INTEGER NOT NULL,
    submitted_at INTEGER CHECK (submitted_at >= started_at),
    finish_reason TEXT CHECK (finish_reason IN ('user','variant_deleted')),
    elapsed_ms INTEGER CHECK (elapsed_ms >= 0),
    correct_count INTEGER CHECK (correct_count >= 0 AND correct_count <= total_count),
    total_count INTEGER NOT NULL CHECK (total_count > 0),
    result_revision INTEGER NOT NULL DEFAULT 0 CHECK (result_revision >= 0),
    start_request_key TEXT NOT NULL,
    UNIQUE (user_id,start_request_key), UNIQUE (user_id,variant_id,attempt_no), UNIQUE (id,version_id),
    FOREIGN KEY (version_id,variant_id) REFERENCES thematic_versions(id,variant_id) ON DELETE RESTRICT,
    CHECK ((state = 'active' AND submitted_at IS NULL AND finish_reason IS NULL AND elapsed_ms IS NULL AND correct_count IS NULL)
        OR (state = 'finished' AND submitted_at IS NOT NULL AND finish_reason IS NOT NULL AND elapsed_ms IS NOT NULL AND correct_count IS NOT NULL))
);

CREATE TABLE thematic_answers (
    attempt_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    answer_json TEXT,
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    saved_at INTEGER,
    checked_revision INTEGER CHECK (checked_revision >= 0 AND checked_revision <= revision),
    is_correct INTEGER CHECK (is_correct IN (0,1)),
    checked_at INTEGER,
    final_status TEXT CHECK (final_status IN ('correct','incorrect','skipped')),
    PRIMARY KEY (attempt_id,item_id),
    FOREIGN KEY (attempt_id,version_id) REFERENCES thematic_attempts(id,version_id) ON DELETE RESTRICT,
    FOREIGN KEY (item_id,version_id) REFERENCES thematic_version_items(id,version_id) ON DELETE RESTRICT,
    CHECK (final_status IS NULL OR (final_status = 'correct' AND is_correct IS NOT NULL AND is_correct = 1)
        OR (final_status IN ('incorrect','skipped') AND is_correct IS NOT NULL AND is_correct = 0))
);

CREATE TABLE thematic_operation_keys (
    actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    operation_scope TEXT NOT NULL,
    request_key TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
    resource_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (actor_user_id,operation_scope,request_key)
);

CREATE UNIQUE INDEX thematic_one_active ON thematic_attempts(user_id,variant_id) WHERE state='active';
CREATE UNIQUE INDEX thematic_one_hidden_interval ON thematic_visibility_intervals(variant_id) WHERE visible_at IS NULL;
CREATE INDEX thematic_history ON thematic_attempts(user_id,submitted_at,id);
CREATE INDEX thematic_attempt_state ON thematic_attempts(variant_id,state);
CREATE INDEX thematic_best ON thematic_attempts(user_id,variant_id,state,correct_count);
CREATE INDEX thematic_catalog_order ON thematic_variants(state,sort_order,id);
CREATE INDEX thematic_visibility_time ON thematic_visibility_intervals(variant_id,hidden_at,visible_at);
CREATE INDEX thematic_media_hash ON thematic_media(sha256);
CREATE INDEX thematic_media_references ON thematic_item_media(media_id);

-- sealed is a one-way assembly latch. All inserts and sealing happen in ONE
-- repository transaction. It is not another visible publication/draft state.
CREATE TRIGGER thematic_version_insert BEFORE INSERT ON thematic_versions
WHEN NEW.sealed <> 0 OR EXISTS (SELECT 1 FROM thematic_variants WHERE id=NEW.variant_id AND state IN ('deleting','deleted'))
BEGIN SELECT RAISE(ABORT,'invalid version assembly'); END;

CREATE TRIGGER thematic_version_immutable BEFORE UPDATE ON thematic_versions
WHEN OLD.id IS NOT NEW.id OR OLD.variant_id IS NOT NEW.variant_id OR OLD.version_no IS NOT NEW.version_no
 OR OLD.title IS NOT NEW.title OR OLD.description IS NOT NEW.description OR OLD.question_count IS NOT NEW.question_count
 OR OLD.snapshot_schema_version IS NOT NEW.snapshot_schema_version OR OLD.grader_version IS NOT NEW.grader_version
 OR OLD.content_hash IS NOT NEW.content_hash OR OLD.published_at IS NOT NEW.published_at
 OR (OLD.published_by IS NOT NEW.published_by AND NEW.published_by IS NOT NULL)
 OR NEW.sealed < OLD.sealed
BEGIN SELECT RAISE(ABORT,'immutable thematic version'); END;

CREATE TRIGGER thematic_version_seal BEFORE UPDATE OF sealed ON thematic_versions
WHEN NEW.sealed=1 AND OLD.sealed=0
BEGIN
 SELECT CASE WHEN (SELECT COUNT(*) FROM thematic_version_items WHERE version_id=OLD.id) <> NEW.question_count
  OR (SELECT MIN(position) FROM thematic_version_items WHERE version_id=OLD.id) <> 1
  OR (SELECT MAX(position) FROM thematic_version_items WHERE version_id=OLD.id) <> NEW.question_count
 THEN RAISE(ABORT,'incomplete thematic version') END;
END;

CREATE TRIGGER thematic_version_delete BEFORE DELETE ON thematic_versions WHEN OLD.sealed=1
BEGIN SELECT RAISE(ABORT,'historical version must be retained'); END;
CREATE TRIGGER thematic_item_insert BEFORE INSERT ON thematic_version_items
WHEN (SELECT sealed FROM thematic_versions WHERE id=NEW.version_id)=1
BEGIN SELECT RAISE(ABORT,'sealed version'); END;
CREATE TRIGGER thematic_item_update BEFORE UPDATE ON thematic_version_items
BEGIN SELECT RAISE(ABORT,'immutable snapshot'); END;
CREATE TRIGGER thematic_item_delete BEFORE DELETE ON thematic_version_items
WHEN (SELECT sealed FROM thematic_versions WHERE id=OLD.version_id)=1
BEGIN SELECT RAISE(ABORT,'historical snapshot must be retained'); END;
CREATE TRIGGER thematic_link_insert BEFORE INSERT ON thematic_item_media
WHEN (SELECT sealed FROM thematic_versions WHERE id=NEW.version_id)=1
BEGIN SELECT RAISE(ABORT,'sealed version media'); END;
CREATE TRIGGER thematic_link_update BEFORE UPDATE ON thematic_item_media
BEGIN SELECT RAISE(ABORT,'immutable media presentation'); END;
CREATE TRIGGER thematic_link_delete BEFORE DELETE ON thematic_item_media
WHEN (SELECT sealed FROM thematic_versions WHERE id=OLD.version_id)=1
BEGIN SELECT RAISE(ABORT,'historical media link must be retained'); END;
CREATE TRIGGER thematic_media_update BEFORE UPDATE ON thematic_media
BEGIN SELECT RAISE(ABORT,'immutable media'); END;

CREATE TRIGGER thematic_current_version BEFORE UPDATE OF current_version_id ON thematic_variants
WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM thematic_versions WHERE id=NEW.current_version_id AND variant_id=NEW.id AND sealed=1)
BEGIN SELECT RAISE(ABORT,'current version must be complete'); END;
CREATE TRIGGER thematic_current_version_insert BEFORE INSERT ON thematic_variants
WHEN NEW.current_version_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'create variant before version'); END;
CREATE TRIGGER thematic_tombstone BEFORE UPDATE ON thematic_variants WHEN OLD.state='deleted'
 AND (NEW.state <> 'deleted' OR NEW.current_version_id IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'deleted variant cannot be restored'); END;

CREATE TRIGGER thematic_interval_insert BEFORE INSERT ON thematic_visibility_intervals
WHEN EXISTS (SELECT 1 FROM thematic_visibility_intervals i WHERE i.variant_id=NEW.variant_id
 AND (NEW.visible_at IS NULL OR i.hidden_at < NEW.visible_at)
 AND (i.visible_at IS NULL OR NEW.hidden_at < i.visible_at))
BEGIN SELECT RAISE(ABORT,'overlapping hidden intervals'); END;
CREATE TRIGGER thematic_interval_update BEFORE UPDATE ON thematic_visibility_intervals
WHEN OLD.variant_id IS NOT NEW.variant_id OR OLD.hidden_at IS NOT NEW.hidden_at
 OR (OLD.visible_at IS NOT NULL AND OLD.visible_at IS NOT NEW.visible_at)
 OR EXISTS (SELECT 1 FROM thematic_visibility_intervals i WHERE i.id<>OLD.id AND i.variant_id=NEW.variant_id
 AND (NEW.visible_at IS NULL OR i.hidden_at < NEW.visible_at)
 AND (i.visible_at IS NULL OR NEW.hidden_at < i.visible_at))
BEGIN SELECT RAISE(ABORT,'invalid hidden interval change'); END;

CREATE TRIGGER thematic_attempt_insert BEFORE INSERT ON thematic_attempts
WHEN NEW.state <> 'active' OR NOT EXISTS (SELECT 1 FROM thematic_versions v
 WHERE v.id=NEW.version_id AND v.variant_id=NEW.variant_id AND v.sealed=1 AND v.question_count=NEW.total_count)
BEGIN SELECT RAISE(ABORT,'attempt requires complete original version'); END;
CREATE TRIGGER thematic_attempt_identity BEFORE UPDATE ON thematic_attempts
WHEN OLD.state='finished' OR OLD.id IS NOT NEW.id OR OLD.user_id IS NOT NEW.user_id
 OR OLD.variant_id IS NOT NEW.variant_id OR OLD.version_id IS NOT NEW.version_id
 OR OLD.attempt_no IS NOT NEW.attempt_no OR OLD.started_at IS NOT NEW.started_at
 OR OLD.total_count IS NOT NEW.total_count OR OLD.start_request_key IS NOT NEW.start_request_key
BEGIN SELECT RAISE(ABORT,'immutable attempt identity or result'); END;
CREATE TRIGGER thematic_attempt_finish BEFORE UPDATE OF state ON thematic_attempts WHEN NEW.state='finished'
BEGIN
 SELECT CASE WHEN (SELECT COUNT(*) FROM thematic_answers WHERE attempt_id=OLD.id) <> NEW.total_count
 OR EXISTS (SELECT 1 FROM thematic_answers WHERE attempt_id=OLD.id AND
  (final_status IS NULL OR is_correct IS NULL OR checked_revision IS NULL OR checked_revision <> revision))
 OR (SELECT SUM(is_correct) FROM thematic_answers WHERE attempt_id=OLD.id) <> NEW.correct_count
 THEN RAISE(ABORT,'incomplete final answers') END;
END;
CREATE TRIGGER thematic_answer_insert BEFORE INSERT ON thematic_answers
WHEN (SELECT state FROM thematic_attempts WHERE id=NEW.attempt_id)='finished'
BEGIN SELECT RAISE(ABORT,'finished answers are immutable'); END;
CREATE TRIGGER thematic_answer_update BEFORE UPDATE ON thematic_answers
WHEN OLD.attempt_id IS NOT NEW.attempt_id OR OLD.item_id IS NOT NEW.item_id OR OLD.version_id IS NOT NEW.version_id
 OR (SELECT state FROM thematic_attempts WHERE id=OLD.attempt_id)='finished'
BEGIN SELECT RAISE(ABORT,'finished answers or identity are immutable'); END;
