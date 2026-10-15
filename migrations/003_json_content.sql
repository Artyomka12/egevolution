-- Target identity schema for a NEW database built by json_content_migration.py.
-- Never apply this file directly to an existing database. No source DROP is used.
CREATE TABLE thematic_variants (id INTEGER PRIMARY KEY);
CREATE TABLE thematic_versions (
 id INTEGER PRIMARY KEY, variant_id INTEGER NOT NULL REFERENCES thematic_variants(id) ON DELETE RESTRICT,
 json_hash TEXT CHECK(json_hash IS NULL OR length(json_hash)=64), UNIQUE(id,variant_id)
);
CREATE TABLE thematic_version_items (
 id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES thematic_versions(id) ON DELETE RESTRICT, UNIQUE(id,version_id)
);
CREATE TABLE thematic_media (id INTEGER PRIMARY KEY);
CREATE TABLE tests (id INTEGER PRIMARY KEY AUTOINCREMENT);
CREATE TABLE test_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
 json_hash TEXT CHECK(json_hash IS NULL OR length(json_hash)=64), UNIQUE(id,test_id)
);
CREATE TABLE test_version_questions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL REFERENCES test_versions(id) ON DELETE CASCADE, UNIQUE(id,version_id)
);
CREATE TABLE test_question_options (
 id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL REFERENCES test_version_questions(id) ON DELETE CASCADE, UNIQUE(id,question_id)
);
CREATE TABLE test_media (
 id INTEGER PRIMARY KEY AUTOINCREMENT, created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE content_commits (id TEXT PRIMARY KEY NOT NULL);
CREATE TRIGGER thematic_attempt_insert BEFORE INSERT ON thematic_attempts
WHEN NEW.state <> 'active' OR NOT EXISTS (SELECT 1 FROM thematic_versions v
 WHERE v.id=NEW.version_id AND v.variant_id=NEW.variant_id AND v.json_hash IS NOT NULL)
 OR NEW.total_count <> (SELECT COUNT(*) FROM thematic_version_items WHERE version_id=NEW.version_id)
BEGIN SELECT RAISE(ABORT,'attempt requires complete original version'); END;
CREATE TRIGGER test_attempt_insert BEFORE INSERT ON test_attempts
WHEN NEW.state <> 'active' OR NOT EXISTS (SELECT 1 FROM test_versions v
 WHERE v.id=NEW.version_id AND v.test_id=NEW.test_id AND v.json_hash IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'attempt requires sealed original version'); END;
CREATE TRIGGER test_attempt_finish BEFORE UPDATE OF state ON test_attempts WHEN NEW.state<>'active'
BEGIN
 SELECT CASE WHEN (SELECT COUNT(*) FROM test_attempt_answers WHERE attempt_id=OLD.id)<>(SELECT COUNT(*) FROM test_version_questions WHERE version_id=OLD.version_id)
 OR (NEW.state='graded' AND EXISTS(SELECT 1 FROM test_attempt_answers WHERE attempt_id=OLD.id AND score IS NULL))
 OR (NEW.state='pending_review' AND NOT EXISTS(SELECT 1 FROM test_attempt_answers WHERE attempt_id=OLD.id AND score IS NULL))
 THEN RAISE(ABORT,'incomplete final answers') END;
END;
