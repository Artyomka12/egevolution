'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const TestsSaveQueue = require('../static/js/tests/attempt.js');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function keys() { let n = 0; return () => `synthetic-key-${++n}`; }

test('one in-flight request per question preserves newer typing after old response', async () => {
  const requests = [], pending = [];
  const queue = new TestsSaveQueue((id, body) => {
    requests.push({id, body: structuredClone(body)});
    const request = deferred(); pending.push(request); return request.promise;
  }, keys());
  queue.seed(10, '', 0); queue.edit(10, 'old');
  const flight = queue.save(10);
  assert.equal(queue.save(10), flight);
  queue.edit(10, 'new');
  assert.equal(requests.length, 1);
  pending[0].resolve({revision: 1}); await tick();
  assert.equal(requests.length, 2);
  assert.equal(requests[1].body.answer, 'new');
  assert.equal(requests[1].body.expected_revision, 1);
  assert.notEqual(requests[1].body.mutation_id, requests[0].body.mutation_id);
  assert.equal(queue.snapshot()[0].answer, 'new');
  pending[1].resolve({revision: 2}); await flight;
  assert.equal(queue.dirty(10), false);
  assert.deepEqual(queue.snapshot(), [{question_id: 10, answer: 'new', expected_revision: 2}]);
});

test('unknown network outcome retries exact mutation and then saves newly typed value', async () => {
  const requests = [];
  const queue = new TestsSaveQueue(async (id, body) => {
    requests.push(structuredClone(body));
    if (requests.length === 1) throw Object.assign(new Error('offline'), {status: 0});
    return {revision: requests.length - 1};
  }, keys());
  queue.seed(1, 'acknowledged', 0); queue.edit(1, 'sent');
  await assert.rejects(queue.save(1), /offline/);
  queue.edit(1, 'new unsent');
  assert.equal(queue.dirty(1), true);
  await queue.save(1);
  assert.deepEqual(requests[1], requests[0]);
  assert.equal(requests[2].answer, 'new unsent');
  assert.equal(requests[2].expected_revision, 1);
  assert.equal(queue.dirty(1), false);
});

test('503 retains pending mutation key across explicit retry', async () => {
  const requests = [];
  const queue = new TestsSaveQueue(async (id, body) => {
    requests.push(structuredClone(body));
    if (requests.length === 1) throw Object.assign(new Error('busy'), {status: 503, code: 'DB_BUSY'});
    return {revision: 8};
  }, keys());
  queue.seed(1, '', 7); queue.edit(1, 'retry');
  await assert.rejects(queue.flush(), /busy/);
  await queue.flush();
  assert.deepEqual(requests[0], requests[1]);
  assert.equal(queue.snapshot()[0].expected_revision, 8);
});

test('malformed successful save responses preserve value, revision and exact pending mutation', async () => {
  for (const response of [null, {}, [], {revision: null}, {revision: true}, {revision: '8'},
                           {revision: 7}, {revision: -1}, {revision: 8.5},
                           {revision: Number.MAX_SAFE_INTEGER + 1}]) {
    const requests = [];
    const queue = new TestsSaveQueue(async (id, body) => {
      requests.push(structuredClone(body));
      return requests.length === 1 ? response : {revision: 8};
    }, keys());
    queue.seed(1, 'acknowledged', 7); queue.edit(1, 'pending text');
    await assert.rejects(queue.save(1), error => error.code === 'BAD_RESPONSE');
    assert.equal(queue.dirty(1), true);
    assert.deepEqual(queue.snapshot(), [{question_id: 1, answer: 'pending text', expected_revision: 7}]);
    await queue.save(1);
    assert.deepEqual(requests[1], requests[0]);
    assert.equal(queue.dirty(1), false);
    assert.equal(queue.snapshot()[0].expected_revision, 8);
  }
});

test('unknown successful save keeps newer typing and retries original mutation before it', async () => {
  const requests = [];
  const queue = new TestsSaveQueue(async (id, body) => {
    requests.push(structuredClone(body));
    return requests.length === 1 ? {} : {revision: requests.length + 6};
  }, keys());
  queue.seed(1, '', 7); queue.edit(1, 'first text');
  await assert.rejects(queue.save(1), error => error.code === 'BAD_RESPONSE');
  queue.edit(1, 'new text');
  await queue.save(1);
  assert.deepEqual(requests[1], requests[0]);
  assert.equal(requests[2].answer, 'new text');
  assert.equal(requests[2].expected_revision, 8);
  assert.notEqual(requests[2].mutation_id, requests[0].mutation_id);
  assert.deepEqual(queue.snapshot(), [{question_id: 1, answer: 'new text', expected_revision: 9}]);
});

test('CAS conflict stops blind writes; accept-server explicitly clears local dirty state', async () => {
  let sends = 0;
  const queue = new TestsSaveQueue(async () => {
    sends++;
    throw Object.assign(new Error('conflict'), {status: 409, code: 'ANSWER_CONFLICT', answer: 'server', revision: 4});
  }, keys());
  queue.seed(1, 'old', 1); queue.edit(1, 'local');
  await assert.rejects(queue.save(1), /conflict/);
  await assert.rejects(queue.save(1), error => error.code === 'ANSWER_CONFLICT');
  assert.equal(sends, 1);
  assert.equal(queue.snapshot()[0].answer, 'local');
  queue.resolve(1, 'server', 4);
  assert.equal(queue.dirty(1), false);
  assert.deepEqual(queue.snapshot()[0], {question_id: 1, answer: 'server', expected_revision: 4});
});

test('keep-local conflict resolution sends local text against fresh server revision', async () => {
  const requests = [];
  const queue = new TestsSaveQueue(async (id, body) => {
    requests.push(structuredClone(body));
    if (requests.length === 1) throw Object.assign(new Error('conflict'), {code: 'ANSWER_CONFLICT', answer: 'remote', revision: 9});
    return {revision: 10};
  }, keys());
  queue.seed(1, '', 2); queue.edit(1, '  Local\ntext  ');
  await assert.rejects(queue.save(1));
  queue.resolve(1, 'remote', 9, true);
  await queue.save(1);
  assert.equal(requests[1].answer, '  Local\ntext  ');
  assert.equal(requests[1].expected_revision, 9);
  assert.notEqual(requests[1].mutation_id, requests[0].mutation_id);
});

test('different questions tolerate reversed responses without mixing revisions', async () => {
  const waiting = new Map();
  const queue = new TestsSaveQueue((id) => { const request = deferred(); waiting.set(id, request); return request.promise; }, keys());
  queue.seed(1, '', 0); queue.seed(2, [], 3);
  queue.edit(1, '0'); queue.edit(2, [8, 9]);
  const first = queue.save(1), second = queue.save(2);
  waiting.get(2).resolve({revision: 4}); await second;
  waiting.get(1).resolve({revision: 1}); await first;
  assert.deepEqual(queue.snapshot(), [{question_id: 1, answer: '0', expected_revision: 1},
                                     {question_id: 2, answer: [8, 9], expected_revision: 4}]);
});

test('clearing answers is a persisted mutation and snapshots are detached copies', async () => {
  const requests = [];
  const queue = new TestsSaveQueue(async (id, body) => { requests.push({id, body}); return {revision: 2}; }, keys());
  const source = [3, 4];
  queue.seed(1, source, 1); source.push(5);
  queue.seed(2, 'text', 1); queue.seed(3, 7, 1);
  queue.edit(1, []); queue.edit(2, ''); queue.edit(3, null);
  const detached = queue.snapshot(); detached[0].answer.push(99);
  await queue.flush();
  assert.deepEqual(requests.map(request => request.body.answer), [[], '', null]);
  assert.equal(queue.dirty(1), false);
  assert.deepEqual(queue.snapshot()[0].answer, []);
});

test('cannot resolve a conflict while a request is still in flight', async () => {
  const pending = deferred();
  const queue = new TestsSaveQueue(() => pending.promise, keys());
  queue.seed(1, '', 0); queue.edit(1, 'value');
  const flight = queue.save(1);
  assert.throws(() => queue.resolve(1, 'remote', 1));
  pending.resolve({revision: 1}); await flight;
});

test('claim and sync validators reject malformed identities, state and writer metadata', () => {
  const valid = {attempt_id: 12, state: 'active', generation: 2, remaining_seconds: 59,
    server_now: '2026-10-14T12:00:01Z', deadline_at: '2026-10-14T12:01:00Z',
    writer_token: 'synthetic-writer', questions: [{id: 3, revision: 0}]};
  const options = {writer: true, questions: true};
  assert.equal(TestsSaveQueue.validateAttemptDTO(valid, 12, options), valid);
  for (const response of [null, {}, {...valid, attempt_id: 13}, {...valid, state: 'graded'},
                           {...valid, generation: 0}, {...valid, generation: true},
                           {...valid, remaining_seconds: -1}, {...valid, server_now: 'invalid'},
                           {...valid, deadline_at: null}, {...valid, writer_token: ''},
                           {...valid, questions: []}, {...valid, questions: [{id: 3, revision: -1}]}]) {
    assert.throws(() => TestsSaveQueue.validateAttemptDTO(response, 12, options),
      error => error.code === 'BAD_RESPONSE' && error.status === 0);
  }
  assert.throws(() => TestsSaveQueue.validateAttemptDTO(valid, 12, {completed: true}),
    error => error.code === 'BAD_RESPONSE');
  assert.equal(TestsSaveQueue.validateAttemptDTO({...valid, state: 'pending_review'}, 12,
    {completed: true}).state, 'pending_review');
});

test('submit validates a terminal own-attempt response before navigation', () => {
  const valid = {attempt_id: 12, state: 'pending_review', result_url: '/tests/attempts/12/result'};
  assert.equal(TestsSaveQueue.validateSubmitDTO(valid, 12), valid);
  for (const response of [null, {}, {...valid, attempt_id: 13}, {...valid, state: 'active'},
                           {...valid, result_url: '/tests/attempts/13/result'},
                           {...valid, result_url: 'https://example.invalid/result'},
                           {...valid, result_url: 'javascript:alert(1)'}]) {
    assert.throws(() => TestsSaveQueue.validateSubmitDTO(response, 12),
      error => error.code === 'BAD_RESPONSE' && error.status === 0);
  }
});

test('actual shared student API timeout covers a stalled response body and preserves retry body', async () => {
  const filename = require.resolve('../static/js/tests/attempt.js');
  const source = fs.readFileSync(filename, 'utf8');
  const begin = source.indexOf('    async function api(');
  const end = source.indexOf('\n    const empty', begin);
  assert.ok(begin > 0 && end > begin);
  const requests = [];
  const api = vm.runInNewContext(`(() => { ${source.slice(begin, end)}; return api; })()`, {
    TestsSaveQueue, AbortController,
    document: {querySelector: () => ({content: 'synthetic-csrf'})},
    setTimeout: callback => setTimeout(callback, 0), clearTimeout,
    fetch: async (url, options) => {
      requests.push(options);
      return {ok: true, status: 200, json: () => requests.length > 1 ? Promise.resolve({revision: 1})
        : new Promise((resolve, reject) => options.signal.addEventListener('abort',
          () => reject(Object.assign(new Error('aborted body'), {name: 'AbortError'})), {once: true}))};
    },
  }, {filename});
  const body = {answer: 'local text', expected_revision: 0, mutation_id: 'stable-mutation', generation: 1};
  let watchdog;
  try {
    await assert.rejects(Promise.race([api('/api/tests/attempts/12/answers/3', 'PUT', body, 'token'),
      new Promise((resolve, reject) => { watchdog = setTimeout(() => reject(new Error('QA_TIMEOUT_API_DID_NOT_ABORT')), 1000); })]),
    error => error.message !== 'QA_TIMEOUT_API_DID_NOT_ABORT');
  } finally { clearTimeout(watchdog); }
  assert.equal(requests[0].signal.aborted, true);
  await api('/api/tests/attempts/12/answers/3', 'PUT', body, 'token');
  assert.equal(requests[0].body, requests[1].body);
  assert.equal(requests[1].headers['X-CSRFToken'], 'synthetic-csrf');
  assert.equal(requests[1].headers['X-Test-Writer-Token'], 'token');
});
