const test = require('node:test');
const assert = require('node:assert/strict');
const Queue = require('../static/js/thematic/save-queue.js');

test('input entered while request is in flight is saved before finish', async () => {
  let resolve, calls = [], key = 0;
  const q = new Queue(async (id, body) => { calls.push(structuredClone(body)); if (calls.length === 1) await new Promise(r => resolve = r); return {revision: body.expected_revision + 1}; }, () => 'key-' + ++key);
  q.seed(1, '', 0); q.edit(1, 'first');
  const saving = q.flush(); await new Promise(r => setImmediate(r));
  q.edit(1, 'last answer'); resolve(); await saving;
  assert.equal(calls.length, 2); assert.equal(calls[1].answer, 'last answer');
  assert.equal(calls[1].expected_revision, 1); assert.equal(q.dirty(1), false);
});
test('lost response retries exactly the same key and payload then saves newer input', async () => {
  const calls = []; let key = 0;
  const q = new Queue(async (id, body) => { calls.push(structuredClone(body)); if (calls.length === 1) throw new Error('network'); return {revision: body.expected_revision + 1}; }, () => 'key-' + ++key);
  q.seed(1, '', 0); q.edit(1, 'old'); await assert.rejects(q.flush());
  q.edit(1, 'new'); await q.flush();
  assert.deepEqual(calls[0], calls[1]); assert.equal(calls[2].answer, 'new'); assert.equal(q.items.get(1).revision, 2);
});
test('conflict keeps local input and prevents automatic overwriting', async () => {
  let calls = 0;
  const q = new Queue(async () => { calls++; throw Object.assign(new Error('conflict'), {status: 409}); }, () => 'key');
  q.seed(1, '', 0); q.edit(1, 'local'); await assert.rejects(q.flush()); await assert.rejects(q.flush());
  assert.equal(calls, 1); assert.equal(q.items.get(1).value, 'local'); assert.equal(q.items.get(1).conflict, true);
});
test('submit waits for every queued answer including clearing an input', async () => {
  const calls = [];
  const q = new Queue(async (id, body) => { calls.push([id, body.answer]); return {revision: body.expected_revision + 1}; }, () => 'key');
  q.seed(1, 'previous', 1); q.seed(2, '', 0); q.edit(1, null); q.edit(2, 'last');
  await q.flush(); calls.push('submit');
  assert.deepEqual(calls, [[1, null], [2, 'last'], 'submit']);
});
test('replayed older revision cannot overwrite later changes from another device', async () => {
  const q = new Queue(async () => ({revision: 1, current_revision: 2, replayed: true}), () => 'key');
  q.seed(1, '', 0); q.edit(1, 'local'); await assert.rejects(q.flush());
  assert.equal(q.items.get(1).conflict, true); assert.equal(q.items.get(1).value, 'local');
});
