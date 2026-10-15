-- Additive tests schema. SQLite 3.26; transaction belongs to the migrator.
CREATE TABLE tests (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 publication_state TEXT NOT NULL DEFAULT 'draft' CHECK(publication_state IN ('draft','published','hidden')),
 current_version_id INTEGER,
 sort_order INTEGER NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1 CHECK(revision>=1),
 created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
 FOREIGN KEY(current_version_id,id) REFERENCES test_versions(id,test_id) ON DELETE RESTRICT
);
CREATE TABLE test_catalog_state (
 singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1), revision INTEGER NOT NULL CHECK(revision>=1)
);
INSERT INTO test_catalog_state VALUES(1,1);
CREATE TABLE test_drafts (
 test_id INTEGER PRIMARY KEY REFERENCES tests(id) ON DELETE CASCADE,
 document_json TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=1),
 based_on_version_id INTEGER,
 updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL, updated_at INTEGER NOT NULL,
 FOREIGN KEY(based_on_version_id,test_id) REFERENCES test_versions(id,test_id) ON DELETE RESTRICT
);
CREATE TABLE test_versions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
 version_no INTEGER NOT NULL CHECK(version_no>=1), title TEXT NOT NULL, description TEXT NOT NULL,
 time_limit_seconds INTEGER NOT NULL CHECK(typeof(time_limit_seconds)='integer' AND time_limit_seconds>0),
 attempt_limit INTEGER CHECK(attempt_limit IS NULL OR (typeof(attempt_limit)='integer' AND attempt_limit>0)),
 show_correct_answers INTEGER NOT NULL CHECK(show_correct_answers IN (0,1)),
 question_count INTEGER NOT NULL CHECK(question_count>0), schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version=1),
 content_hash TEXT NOT NULL CHECK(length(content_hash)=64),
 published_by INTEGER REFERENCES users(id) ON DELETE SET NULL, published_at INTEGER NOT NULL,
 sealed INTEGER NOT NULL DEFAULT 0 CHECK(sealed IN (0,1)),
 UNIQUE(test_id,version_no), UNIQUE(id,test_id)
);
CREATE TABLE test_media (
 id INTEGER PRIMARY KEY AUTOINCREMENT, storage_key TEXT NOT NULL UNIQUE,
 mime_type TEXT NOT NULL CHECK(mime_type IN ('image/png','image/jpeg','image/gif')),
 size_bytes INTEGER NOT NULL CHECK(size_bytes>0 AND size_bytes<=5242880),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64), width INTEGER NOT NULL CHECK(width>0), height INTEGER NOT NULL CHECK(height>0),
 alt_text TEXT NOT NULL DEFAULT '', created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
 created_at INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('staged','ready'))
);
CREATE TABLE test_media_links (
 test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
 media_id INTEGER NOT NULL REFERENCES test_media(id) ON DELETE RESTRICT,
 PRIMARY KEY(test_id,media_id)
);
CREATE TABLE test_version_questions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, version_id INTEGER NOT NULL REFERENCES test_versions(id) ON DELETE CASCADE,
 position INTEGER NOT NULL CHECK(position>=1), title TEXT NOT NULL, prompt_text TEXT NOT NULL, code_text TEXT,
 question_type TEXT NOT NULL CHECK(question_type IN ('single_choice','multiple_choice','free_text')),
 free_input_mode TEXT CHECK(free_input_mode IN ('singleline','multiline')),
 grading_mode TEXT NOT NULL CHECK(grading_mode IN ('auto','manual')),
 media_id INTEGER REFERENCES test_media(id) ON DELETE RESTRICT,
 max_points INTEGER NOT NULL DEFAULT 1 CHECK(max_points=1),
 CHECK((question_type='free_text' AND free_input_mode IS NOT NULL) OR
       (question_type IN ('single_choice','multiple_choice') AND free_input_mode IS NULL AND grading_mode='auto')),
 UNIQUE(version_id,position), UNIQUE(id,version_id)
);
CREATE TABLE test_question_options (
 id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL REFERENCES test_version_questions(id) ON DELETE CASCADE,
 position INTEGER NOT NULL CHECK(position>=1), text TEXT NOT NULL, is_correct INTEGER NOT NULL CHECK(is_correct IN (0,1)),
 UNIQUE(question_id,position), UNIQUE(id,question_id)
);
CREATE TABLE test_accepted_answers (
 id INTEGER PRIMARY KEY AUTOINCREMENT, question_id INTEGER NOT NULL REFERENCES test_version_questions(id) ON DELETE CASCADE,
 position INTEGER NOT NULL CHECK(position>=1), value TEXT COLLATE BINARY NOT NULL CHECK(length(value)>0),
 UNIQUE(question_id,position)
);
CREATE TABLE test_attempts (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE, version_id INTEGER NOT NULL,
 attempt_no INTEGER NOT NULL CHECK(attempt_no>=1), state TEXT NOT NULL DEFAULT 'active' CHECK(state IN ('active','pending_review','graded')),
 started_at INTEGER NOT NULL, deadline_at INTEGER NOT NULL, submitted_at INTEGER, finalized_at INTEGER,
 finish_reason TEXT CHECK(finish_reason IN ('manual','timeout')),
 time_limit_seconds_snapshot INTEGER NOT NULL CHECK(time_limit_seconds_snapshot>0),
 show_correct_answers_snapshot INTEGER NOT NULL CHECK(show_correct_answers_snapshot IN (0,1)),
 active_generation INTEGER NOT NULL DEFAULT 1 CHECK(active_generation>=1),
 writer_token_hash TEXT CHECK(writer_token_hash IS NULL OR length(writer_token_hash)=64), writer_client_id TEXT,
 lease_acquired_at INTEGER, last_seen_at INTEGER,
 result_revision INTEGER NOT NULL DEFAULT 0 CHECK(result_revision>=0), start_request_key TEXT NOT NULL,
 FOREIGN KEY(version_id,test_id) REFERENCES test_versions(id,test_id) ON DELETE CASCADE,
 CHECK(deadline_at=started_at+1000*time_limit_seconds_snapshot),
 CHECK((state='active' AND submitted_at IS NULL AND finalized_at IS NULL AND finish_reason IS NULL) OR
       (state<>'active' AND submitted_at IS NOT NULL AND finalized_at IS NOT NULL AND finish_reason IS NOT NULL)),
 UNIQUE(user_id,start_request_key), UNIQUE(user_id,test_id,attempt_no), UNIQUE(id,version_id)
);
CREATE TABLE test_attempt_answers (
 attempt_id INTEGER NOT NULL, question_id INTEGER NOT NULL, version_id INTEGER NOT NULL,
 answer_json TEXT, revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), saved_at INTEGER,
 was_unanswered INTEGER NOT NULL DEFAULT 1 CHECK(was_unanswered IN (0,1)),
 auto_score INTEGER CHECK(auto_score IN (0,1)), score INTEGER CHECK(score IN (0,1)),
 grading_source TEXT CHECK(grading_source IN ('automatic','manual','override')),
 graded_by INTEGER REFERENCES users(id) ON DELETE SET NULL, graded_at INTEGER,
 grade_revision INTEGER NOT NULL DEFAULT 0 CHECK(grade_revision>=0),
 PRIMARY KEY(attempt_id,question_id),
 FOREIGN KEY(attempt_id,version_id) REFERENCES test_attempts(id,version_id) ON DELETE CASCADE,
 FOREIGN KEY(question_id,version_id) REFERENCES test_version_questions(id,version_id) ON DELETE CASCADE,
 CHECK(was_unanswered=0 OR score IS NULL OR score=0)
);
CREATE TABLE test_grade_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL, question_id INTEGER NOT NULL,
 old_score INTEGER CHECK(old_score IN (0,1)), new_score INTEGER CHECK(new_score IN (0,1)),
 old_source TEXT CHECK(old_source IN ('automatic','manual','override')),
 new_source TEXT CHECK(new_source IN ('automatic','manual','override')),
 actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
 actor_kind TEXT NOT NULL CHECK(actor_kind IN ('system','admin')), occurred_at INTEGER NOT NULL,
 request_key TEXT NOT NULL, result_revision INTEGER NOT NULL CHECK(result_revision>=0),
 FOREIGN KEY(attempt_id,question_id) REFERENCES test_attempt_answers(attempt_id,question_id) ON DELETE CASCADE,
 UNIQUE(actor_user_id,request_key)
);
CREATE TABLE test_attempt_grants (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE, amount INTEGER NOT NULL CHECK(typeof(amount)='integer' AND amount>0),
 granted_by INTEGER REFERENCES users(id) ON DELETE SET NULL, granted_at INTEGER NOT NULL, request_key TEXT NOT NULL,
 UNIQUE(granted_by,request_key)
);
CREATE TABLE test_operation_keys (
 actor_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 operation_scope TEXT NOT NULL, request_key TEXT NOT NULL, request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
 resource_id INTEGER NOT NULL, created_at INTEGER NOT NULL,
 PRIMARY KEY(actor_user_id,operation_scope,request_key)
);
CREATE UNIQUE INDEX test_one_active ON test_attempts(user_id,test_id) WHERE state='active';
CREATE INDEX test_expired_attempts ON test_attempts(state,deadline_at);
CREATE INDEX test_user_history ON test_attempts(user_id,test_id,state,submitted_at);
CREATE INDEX test_attempt_state ON test_attempts(test_id,state);
CREATE INDEX test_pending_answers ON test_attempt_answers(attempt_id,score);
CREATE INDEX test_catalog_order ON tests(publication_state,sort_order,id);
CREATE INDEX test_user_grants ON test_attempt_grants(user_id,test_id);
CREATE INDEX test_event_history ON test_grade_events(attempt_id,occurred_at);
CREATE INDEX test_media_references ON test_version_questions(media_id);
CREATE INDEX test_media_owners ON test_media_links(media_id,test_id);

-- Versions are assembled and sealed in one publication transaction.
CREATE TRIGGER test_version_insert BEFORE INSERT ON test_versions WHEN NEW.sealed<>0
BEGIN SELECT RAISE(ABORT,'version must be assembled before sealing'); END;
CREATE TRIGGER test_version_immutable BEFORE UPDATE ON test_versions
WHEN OLD.id IS NOT NEW.id OR OLD.test_id IS NOT NEW.test_id OR OLD.version_no IS NOT NEW.version_no
 OR OLD.title IS NOT NEW.title OR OLD.description IS NOT NEW.description
 OR OLD.time_limit_seconds IS NOT NEW.time_limit_seconds OR OLD.attempt_limit IS NOT NEW.attempt_limit
 OR OLD.show_correct_answers IS NOT NEW.show_correct_answers OR OLD.question_count IS NOT NEW.question_count
 OR OLD.schema_version IS NOT NEW.schema_version OR OLD.content_hash IS NOT NEW.content_hash
 OR OLD.published_at IS NOT NEW.published_at OR NEW.sealed<OLD.sealed
 OR (OLD.published_by IS NOT NEW.published_by AND NEW.published_by IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'immutable test version'); END;
CREATE TRIGGER test_version_seal BEFORE UPDATE OF sealed ON test_versions WHEN OLD.sealed=0 AND NEW.sealed=1
BEGIN
 SELECT CASE WHEN (SELECT COUNT(*) FROM test_version_questions WHERE version_id=OLD.id)<>NEW.question_count
  OR (SELECT MIN(position) FROM test_version_questions WHERE version_id=OLD.id)<>1
  OR (SELECT MAX(position) FROM test_version_questions WHERE version_id=OLD.id)<>NEW.question_count
  THEN RAISE(ABORT,'incomplete test version') END;
 SELECT CASE WHEN EXISTS (SELECT 1 FROM test_version_questions q WHERE q.version_id=OLD.id AND (
  (q.question_type='single_choice' AND (SELECT COUNT(*) FROM test_question_options o WHERE o.question_id=q.id AND o.is_correct=1)<>1)
  OR (q.question_type='multiple_choice' AND NOT EXISTS(SELECT 1 FROM test_question_options o WHERE o.question_id=q.id AND o.is_correct=1))
  OR (q.question_type='free_text' AND EXISTS(SELECT 1 FROM test_question_options o WHERE o.question_id=q.id))
  OR (q.question_type<>'free_text' AND EXISTS(SELECT 1 FROM test_accepted_answers a WHERE a.question_id=q.id))
  OR (q.question_type='free_text' AND q.grading_mode='auto' AND NOT EXISTS(SELECT 1 FROM test_accepted_answers a WHERE a.question_id=q.id))
  OR EXISTS(SELECT 1 FROM test_question_options o WHERE o.question_id=q.id GROUP BY o.question_id HAVING MIN(position)<>1 OR MAX(position)<>COUNT(*))
  OR EXISTS(SELECT 1 FROM test_accepted_answers a WHERE a.question_id=q.id GROUP BY a.question_id HAVING MIN(position)<>1 OR MAX(position)<>COUNT(*))
 )) THEN RAISE(ABORT,'invalid question references') END;
END;
CREATE TRIGGER test_version_delete BEFORE DELETE ON test_versions
WHEN OLD.sealed=1 AND EXISTS(SELECT 1 FROM tests WHERE id=OLD.test_id)
BEGIN SELECT RAISE(ABORT,'delete the whole test'); END;
CREATE TRIGGER test_question_insert BEFORE INSERT ON test_version_questions
WHEN (SELECT sealed FROM test_versions WHERE id=NEW.version_id)=1
 OR (NEW.media_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM test_media m JOIN test_media_links l ON l.media_id=m.id
 JOIN test_versions v ON v.test_id=l.test_id WHERE v.id=NEW.version_id AND m.id=NEW.media_id AND m.state='ready'))
BEGIN SELECT RAISE(ABORT,'sealed version or unavailable media'); END;
CREATE TRIGGER test_question_update BEFORE UPDATE ON test_version_questions
BEGIN SELECT RAISE(ABORT,'immutable question'); END;
CREATE TRIGGER test_question_delete BEFORE DELETE ON test_version_questions
WHEN EXISTS(SELECT 1 FROM test_versions v JOIN tests t ON t.id=v.test_id WHERE v.id=OLD.version_id AND v.sealed=1)
BEGIN SELECT RAISE(ABORT,'delete the whole test'); END;
CREATE TRIGGER test_option_insert BEFORE INSERT ON test_question_options
WHEN EXISTS(SELECT 1 FROM test_version_questions q JOIN test_versions v ON v.id=q.version_id WHERE q.id=NEW.question_id AND v.sealed=1)
BEGIN SELECT RAISE(ABORT,'sealed options'); END;
CREATE TRIGGER test_option_update BEFORE UPDATE ON test_question_options
BEGIN SELECT RAISE(ABORT,'immutable option'); END;
CREATE TRIGGER test_option_delete BEFORE DELETE ON test_question_options
WHEN EXISTS(SELECT 1 FROM test_version_questions q JOIN test_versions v ON v.id=q.version_id JOIN tests t ON t.id=v.test_id WHERE q.id=OLD.question_id AND v.sealed=1)
BEGIN SELECT RAISE(ABORT,'delete the whole test'); END;
CREATE TRIGGER test_reference_insert BEFORE INSERT ON test_accepted_answers
WHEN EXISTS(SELECT 1 FROM test_version_questions q JOIN test_versions v ON v.id=q.version_id WHERE q.id=NEW.question_id AND v.sealed=1)
BEGIN SELECT RAISE(ABORT,'sealed references'); END;
CREATE TRIGGER test_reference_update BEFORE UPDATE ON test_accepted_answers
BEGIN SELECT RAISE(ABORT,'immutable reference'); END;
CREATE TRIGGER test_reference_delete BEFORE DELETE ON test_accepted_answers
WHEN EXISTS(SELECT 1 FROM test_version_questions q JOIN test_versions v ON v.id=q.version_id JOIN tests t ON t.id=v.test_id WHERE q.id=OLD.question_id AND v.sealed=1)
BEGIN SELECT RAISE(ABORT,'delete the whole test'); END;
CREATE TRIGGER test_media_update BEFORE UPDATE ON test_media WHEN OLD.state='ready' AND (
 OLD.id IS NOT NEW.id OR OLD.storage_key IS NOT NEW.storage_key OR OLD.mime_type IS NOT NEW.mime_type
 OR OLD.size_bytes IS NOT NEW.size_bytes OR OLD.sha256 IS NOT NEW.sha256 OR OLD.width IS NOT NEW.width OR OLD.height IS NOT NEW.height
 OR OLD.alt_text IS NOT NEW.alt_text OR OLD.created_at IS NOT NEW.created_at OR OLD.state IS NOT NEW.state
 OR (OLD.created_by IS NOT NEW.created_by AND NEW.created_by IS NOT NULL))
BEGIN SELECT RAISE(ABORT,'immutable ready media'); END;
CREATE TRIGGER test_current_version BEFORE UPDATE OF current_version_id ON tests
WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM test_versions WHERE id=NEW.current_version_id AND test_id=NEW.id AND sealed=1)
BEGIN SELECT RAISE(ABORT,'current version must be sealed'); END;
CREATE TRIGGER test_current_version_insert BEFORE INSERT ON tests WHEN NEW.current_version_id IS NOT NULL
BEGIN SELECT RAISE(ABORT,'create test before version'); END;
CREATE TRIGGER test_attempt_insert BEFORE INSERT ON test_attempts
WHEN NEW.state<>'active' OR NOT EXISTS(SELECT 1 FROM test_versions v WHERE v.id=NEW.version_id AND v.test_id=NEW.test_id AND v.sealed=1
 AND v.time_limit_seconds=NEW.time_limit_seconds_snapshot AND v.show_correct_answers=NEW.show_correct_answers_snapshot)
BEGIN SELECT RAISE(ABORT,'attempt requires sealed original version'); END;
CREATE TRIGGER test_attempt_identity BEFORE UPDATE ON test_attempts
WHEN OLD.id IS NOT NEW.id OR OLD.user_id IS NOT NEW.user_id OR OLD.test_id IS NOT NEW.test_id OR OLD.version_id IS NOT NEW.version_id
 OR OLD.attempt_no IS NOT NEW.attempt_no OR OLD.started_at IS NOT NEW.started_at OR OLD.deadline_at IS NOT NEW.deadline_at
 OR OLD.time_limit_seconds_snapshot IS NOT NEW.time_limit_seconds_snapshot OR OLD.show_correct_answers_snapshot IS NOT NEW.show_correct_answers_snapshot
 OR OLD.start_request_key IS NOT NEW.start_request_key OR NEW.active_generation<OLD.active_generation OR NEW.result_revision<OLD.result_revision
 OR (OLD.state<>'active' AND (NEW.state='active' OR OLD.submitted_at IS NOT NEW.submitted_at OR OLD.finalized_at IS NOT NEW.finalized_at OR OLD.finish_reason IS NOT NEW.finish_reason))
 OR (OLD.state='graded' AND NEW.state<>'graded')
BEGIN SELECT RAISE(ABORT,'immutable attempt identity'); END;
CREATE TRIGGER test_attempt_finish BEFORE UPDATE OF state ON test_attempts WHEN NEW.state<>'active'
BEGIN
 SELECT CASE WHEN (SELECT COUNT(*) FROM test_attempt_answers WHERE attempt_id=OLD.id)<>(SELECT question_count FROM test_versions WHERE id=OLD.version_id)
 OR (NEW.state='graded' AND EXISTS(SELECT 1 FROM test_attempt_answers WHERE attempt_id=OLD.id AND score IS NULL))
 OR (NEW.state='pending_review' AND NOT EXISTS(SELECT 1 FROM test_attempt_answers WHERE attempt_id=OLD.id AND score IS NULL))
 THEN RAISE(ABORT,'incomplete final answers') END;
END;
CREATE TRIGGER test_answer_insert BEFORE INSERT ON test_attempt_answers
WHEN (SELECT state FROM test_attempts WHERE id=NEW.attempt_id)<>'active'
BEGIN SELECT RAISE(ABORT,'submitted answers cannot be added'); END;
CREATE TRIGGER test_answer_update BEFORE UPDATE ON test_attempt_answers
WHEN OLD.attempt_id IS NOT NEW.attempt_id OR OLD.question_id IS NOT NEW.question_id OR OLD.version_id IS NOT NEW.version_id
 OR ((SELECT state FROM test_attempts WHERE id=OLD.attempt_id)<>'active' AND (
 OLD.answer_json IS NOT NEW.answer_json OR OLD.revision IS NOT NEW.revision OR OLD.saved_at IS NOT NEW.saved_at
 OR OLD.was_unanswered IS NOT NEW.was_unanswered OR OLD.auto_score IS NOT NEW.auto_score))
BEGIN SELECT RAISE(ABORT,'submitted answer is immutable'); END;
