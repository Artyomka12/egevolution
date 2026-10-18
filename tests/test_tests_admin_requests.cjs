'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Evaluate the actual request function without bootstrapping its page DOM.
// No request implementation is copied or substituted by this harness.
function requester(name, fetch, runTimeout = false) {
  const filename = path.join(__dirname, '../static/js/admin/tests', name + '.js');
  const source = fs.readFileSync(filename, 'utf8');
  const begin = source.indexOf('  async function api(');
  const end = source.indexOf('\n  function ', begin + 1);
  assert.ok(begin >= 0 && end > begin, 'actual api() boundaries must exist: ' + name);
  let sequence = 0;
  const sandbox = {fetch, AbortController, FormData, console, crypto: {randomUUID: () => 'synthetic-' + (++sequence)},
    setTimeout: (callback, delay) => delay >= 5000 && !runTimeout ? 0 : setTimeout(callback, 0), clearTimeout};
  const api = vm.runInNewContext(`(() => {
    let csrf = 'synthetic-csrf';
    const root = {dataset: {userId: '1'}};
    const meta = {content: csrf};
    const document = {querySelector: () => meta};
    const requestKeys = new Map();
    const pendingKeys = new Map();
    const key = () => crypto.randomUUID();
    ${source.slice(begin, end)}
    return api;
  })()`, sandbox, {filename});
  return {call: () => name === 'review' || name === 'user-stats'
    ? api('/synthetic-mutation', {request_key: 'stable-key', score: 1})
    : api('/synthetic-mutation', 'POST', {document: {title: 'synthetic'}}), api};
}
const success = () => ({ok: true, status: 200, json: async () => ({ok: true})});

for (const name of ['review', 'user-stats']) {
  test(name + ': semantically incomplete mutation response remains unconfirmed', async () => {
    const client = requester(name, async () => success());
    await assert.rejects(client.api('/synthetic', {request_key: 'stable'}, () => false));
  });
}

for (const name of ['review', 'user-stats', 'manage', 'editor']) {
  test(name + ': malformed successful JSON remains an unknown failed outcome', async () => {
    let requests = 0;
    const client = requester(name, async () => {
      requests++;
      return {ok: true, status: 200, json: async () => { throw new SyntaxError('truncated JSON'); }};
    });
    await assert.rejects(client.call());
    assert.ok(requests >= 1 && requests <= 3, 'bounded retries');
  });

  test(name + ': retry after lost connection sends the same request and key', async () => {
    const requests = [];
    const client = requester(name, async (url, options) => {
      requests.push({url, body: options.body, headers: {...options.headers}});
      if (requests.length === 1) throw new TypeError('connection reset after commit');
      return success();
    });
    await client.call();
    assert.equal(requests.length, 2);
    assert.deepEqual(requests[0], requests[1]);
    assert.equal(requests[0].headers['X-CSRFToken'], 'synthetic-csrf');
  });

  test(name + ': timeout while reading response body rejects with bounded same-key retries', async () => {
    const requests = [];
    const client = requester(name, async (url, options) => {
      requests.push(options.body);
      return {ok: true, status: 200, json: () => new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), {name: 'AbortError'})), {once: true});
      })};
    }, true);
    await assert.rejects(client.call());
    assert.equal(requests.length, 3);
    assert.equal(new Set(requests).size, 1);
  });
}

test('editor and manage reject incomplete successful mutation DTOs', async () => {
  for (const [name, url] of [['editor', '/api/admin/tests'], ['editor', '/api/admin/tests/1/publish'],
                            ['editor', '/api/admin/tests/1/draft'], ['manage', '/api/admin/tests/1/copy'],
                            ['manage', '/api/admin/tests/order'], ['manage', '/api/admin/tests/1/visibility']]) {
    const client = requester(name, async () => ({ok: true, status: 200, json: async () => ({})}));
    await assert.rejects(client.api(url, 'POST', {request_key: 'same-key'}));
  }
});

test('editor upload keeps exact FormData and request key after unknown success', async () => {
  const requests = [];
  let failing = true;
  const client = requester('editor', async (url, options) => {
    requests.push(options);
    return {ok: true, status: 200, json: async () => {
      if (failing) throw new SyntaxError('truncated upload response');
      return {media_id: 5, url: '/api/admin/tests/1/media/5', alt_text: 'Synthetic', width: 2, height: 3};
    }};
  });
  const form = new FormData();
  form.append('request_key', 'same-upload'); form.append('alt_text', 'Synthetic');
  form.append('file', new Blob(['synthetic-media-bytes'], {type: 'image/png'}), 'fixture.png');
  await assert.rejects(client.api('/api/admin/tests/1/media', 'POST', form));
  failing = false;
  const result = await client.api('/api/admin/tests/1/media', 'POST', form);
  assert.equal(result.media_id, 5);
  assert.equal(requests.length, 4);
  for (const request of requests) {
    assert.equal(request.body, form);
    assert.equal(request.body.get('request_key'), 'same-upload');
    assert.equal(request.headers['Content-Type'], undefined, 'browser must own multipart boundary');
  }
});

test('editor: an explicit retry after unreadable success retains original mutation key', async () => {
  const requests = [];
  let failing = true;
  const client = requester('editor', async (url, options) => {
    requests.push(JSON.parse(options.body));
    return failing ? {ok: true, status: 200, json: async () => { throw new SyntaxError('lost body'); }} : success();
  });
  await assert.rejects(client.call());
  failing = false;
  await client.call();
  assert.equal(new Set(requests.map(body => body.request_key)).size, 1);
});

const csrfFailure = () => ({ok: false, status: 400, json: async () => ({
  error: {code: 'CSRF_FAILED', message: 'Synthetic expired token'}, csrf_reason: 'expired'
})});
const freshCSRF = (user = 1) => ({ok: true, status: 200,
  json: async () => ({csrf_token: 'fresh-synthetic-csrf', user_id: user})});

test('editor renews CSRF without changing 25 questions, request body or idempotency key', async () => {
  const requests = [], refreshes = [];
  const client = requester('editor', async (url, options) => {
    if (url === '/api/admin/tests/csrf') { refreshes.push(options); return freshCSRF(); }
    requests.push({body: options.body, headers: {...options.headers}});
    return requests.length === 1 ? csrfFailure() : success();
  });
  const payload = {document: {title: 'Synthetic 25', questions: Array.from({length: 25}, (_, i) => ({
    title: String(i), code_text: 'print("exact")\n', accepted_answers: ['  Exact\nanswer']
  }))}};
  const original = JSON.stringify(payload);
  await client.api('/synthetic-mutation', 'PUT', payload);
  assert.equal(JSON.stringify(payload), original);
  assert.equal(requests.length, 2); assert.equal(refreshes.length, 1);
  assert.equal(requests[0].body, requests[1].body);
  assert.equal(requests[0].headers['X-CSRFToken'], 'synthetic-csrf');
  assert.equal(requests[1].headers['X-CSRFToken'], 'fresh-synthetic-csrf');
  assert.equal(refreshes[0].method, 'GET');
  assert.equal(refreshes[0].credentials, 'same-origin');
  assert.equal(refreshes[0].cache, 'no-store');
  assert.equal(refreshes[0].headers['X-CSRF-Refresh'], '1');
});

test('editor keeps the original key through unknown commit, CSRF renewal and replay', async () => {
  const bodies = [];
  const client = requester('editor', async (url, options) => {
    if (url === '/api/admin/tests/csrf') return freshCSRF();
    bodies.push(options.body);
    if (bodies.length === 1) throw new Error('lost response after commit');
    return bodies.length === 2 ? csrfFailure() : success();
  });
  await client.call();
  assert.equal(bodies.length, 3);
  assert.equal(new Set(bodies).size, 1);
});

test('editor stops after one CSRF renewal if rejection persists', async () => {
  let writes = 0, renewals = 0;
  const client = requester('editor', async url => {
    if (url === '/api/admin/tests/csrf') { renewals++; return freshCSRF(); }
    writes++; return csrfFailure();
  });
  await assert.rejects(client.call(), error => error.code === 'CSRF_FAILED');
  assert.equal(writes, 2); assert.equal(renewals, 1);
});

test('editor does not retry a draft under a different administrator account', async () => {
  let writes = 0;
  const client = requester('editor', async url => {
    if (url === '/api/admin/tests/csrf') return freshCSRF(7);
    writes++; return csrfFailure();
  });
  await assert.rejects(client.call());
  assert.equal(writes, 1);
});

test('editor keeps unsaved operation key when session renewal requires login', async () => {
  let loggedIn = false;
  const bodies = [];
  const client = requester('editor', async (url, options) => {
    if (url === '/api/admin/tests/csrf') return {ok: false, status: 401,
      json: async () => ({error: {code: 'AUTH_REQUIRED', message: 'Login required'}})};
    bodies.push(options.body); return loggedIn ? success() : csrfFailure();
  });
  await assert.rejects(client.call(), error => error.code === 'AUTH_REQUIRED');
  loggedIn = true; await client.call();
  assert.equal(bodies.length, 2); assert.equal(bodies[0], bodies[1]);
});

test('editor renewal rejects malformed fresh-token responses without replaying mutation', async () => {
  let writes = 0, renewals = 0;
  const client = requester('editor', async url => {
    if (url === '/api/admin/tests/csrf') { renewals++; return success(); }
    writes++; return csrfFailure();
  });
  await assert.rejects(client.call());
  assert.equal(writes, 1); assert.equal(renewals, 3);
});

test('editor upload preserves FormData across CSRF renewal', async () => {
  const bodies = [];
  const client = requester('editor', async (url, options) => {
    if (url === '/api/admin/tests/csrf') return freshCSRF();
    bodies.push(options.body);
    return bodies.length === 1 ? csrfFailure() : {ok: true, status: 201,
      json: async () => ({media_id: 5, url: '/synthetic-media', alt_text: '', width: 2, height: 2})};
  });
  const form = new FormData(); form.append('request_key', 'same-upload');
  form.append('file', new Blob(['synthetic']), 'fixture.png');
  await client.api('/api/admin/tests/1/media', 'POST', form);
  assert.equal(bodies.length, 2); assert.equal(bodies[0], form); assert.equal(bodies[1], form);
});
