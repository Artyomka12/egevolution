'use strict';

// Per-question serialization. A pending mutation survives an unknown network outcome.
class TestsSaveQueue {
  static badResponse() { return Object.assign(new Error('Сервер вернул неполный ответ. Повторите запрос.'), {code: 'BAD_RESPONSE', status: 0}); }
  static validateAttemptDTO(value, attemptId, {questions = false, writer = false, completed = false} = {}) {
    if (!value || value.attempt_id !== attemptId || !['active', 'pending_review', 'graded'].includes(value.state)
        || !Number.isSafeInteger(value.generation) || value.generation < 1
        || !Number.isSafeInteger(value.remaining_seconds) || value.remaining_seconds < 0
        || !Number.isFinite(Date.parse(value.server_now)) || !Number.isFinite(Date.parse(value.deadline_at))
        || (completed && value.state === 'active')
        || (writer && (value.state !== 'active' || typeof value.writer_token !== 'string' || !value.writer_token))
        || (questions && (!Array.isArray(value.questions) || !value.questions.length
          || value.questions.some(q => !q || !Number.isSafeInteger(q.id) || !Number.isSafeInteger(q.revision) || q.revision < 0)))) throw TestsSaveQueue.badResponse();
    return value;
  }
  static validateSubmitDTO(value, attemptId) {
    if (!value || value.attempt_id !== attemptId || !['pending_review', 'graded'].includes(value.state)
        || value.result_url !== `/tests/attempts/${attemptId}/result`) throw TestsSaveQueue.badResponse();
    return value;
  }
  constructor(send, key = () => crypto.randomUUID()) { this.send = send; this.key = key; this.items = new Map(); }
  seed(id, answer, revision) { this.items.set(id, {value: structuredClone(answer), acknowledged: structuredClone(answer), revision, generation: 0, saved: 0, pending: null, flight: null, conflict: null}); }
  edit(id, answer) { const s = this.items.get(id); s.value = structuredClone(answer); s.generation++; }
  dirty(id) { const s = this.items.get(id); return !!s.pending || s.saved !== s.generation || !!s.conflict; }
  save(id) {
    const s = this.items.get(id);
    if (s.flight) return s.flight;
    s.flight = this._save(id, s).finally(() => { s.flight = null; });
    return s.flight;
  }
  async _save(id, s) {
    while (this.dirty(id)) {
      if (s.conflict) throw Object.assign(new Error('Ответ изменён. Требуется сверка.'), {code: 'ANSWER_CONFLICT', status: 409, question_id: id, ...s.conflict});
      if (!s.pending) s.pending = {body: {answer: structuredClone(s.value), expected_revision: s.revision, mutation_id: this.key()}, generation: s.generation};
      const pending = s.pending;
      let result;
      try { result = await this.send(id, pending.body); }
      catch (e) { if (e.code === 'ANSWER_CONFLICT') s.conflict = {answer: structuredClone(e.answer), revision: e.revision}; if (e.status === 422) s.pending = null; throw e; }
      if (!result || !Number.isSafeInteger(result.revision) || result.revision < pending.body.expected_revision + 1) throw TestsSaveQueue.badResponse();
      s.revision = result.revision; s.acknowledged = structuredClone(pending.body.answer); s.saved = pending.generation; s.pending = null;
    }
  }
  async flush() { for (const id of this.items.keys()) await this.save(id); }
  resolve(id, answer, revision, keepLocal = false) {
    const s = this.items.get(id);
    if (s.flight) throw new Error('Дождитесь завершения запроса.');
    const value = structuredClone(s.value);
    this.seed(id, answer, revision);
    if (keepLocal) this.edit(id, value);
  }
  snapshot() { return [...this.items].map(([question_id, s]) => ({question_id, answer: structuredClone(s.value), expected_revision: s.revision})); }
}
if (typeof module !== 'undefined' && module.exports) module.exports = TestsSaveQueue;

if (typeof document !== 'undefined') {
  window.TestsSaveQueue = TestsSaveQueue;
  window.TestsUI = (() => {
    const $ = id => document.getElementById(id);
    const node = (tag, cls = '', text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
    async function api(url, method = 'GET', body, token) {
      const headers = {'Accept': 'application/json'};
      if (body !== undefined) { headers['Content-Type'] = 'application/json'; headers['X-CSRFToken'] = document.querySelector('meta[name="csrf-token"]')?.content || ''; }
      if (token) headers['X-Test-Writer-Token'] = token;
      let response;
      const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 15000);
      try {
        try { response = await fetch(url, {method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: 'same-origin', cache: 'no-store', signal: controller.signal}); }
        catch { throw Object.assign(new Error('Нет связи с сервером. Ваш ввод остаётся на этой странице. Повторите запрос.'), {status: 0}); }
        let data;
        try { data = await response.json(); } catch { throw Object.assign(new Error('Не удалось получить ответ сервера. Повторите запрос.'), {status: response.ok ? 0 : response.status, code: response.status === 401 ? 'AUTH_REQUIRED' : 'BAD_RESPONSE'}); }
        if (!data || typeof data !== 'object' || Array.isArray(data)) throw Object.assign(TestsSaveQueue.badResponse(), {status: response.ok ? 0 : response.status});
        if (!response.ok) throw Object.assign(new Error(data.error?.message || 'Не удалось выполнить запрос.'), data, {status: response.status, code: data.error?.code});
        return data;
      } finally { clearTimeout(timeout); }
    }
    const empty = value => value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length);
    const time = seconds => { seconds = Math.max(0, Math.floor(seconds || 0)); return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; };
    const percent = value => Number(value).toLocaleString('ru-RU', {maximumFractionDigits: 1}) + '%';
    function answerText(q, answer) {
      if (empty(answer)) return 'Ответ не дан';
      if (q.question_type === 'free_text') return String(answer);
      const ids = Array.isArray(answer) ? answer : [answer];
      return ids.map(id => q.options.find(o => o.id === id)?.text ?? '—').join('; ');
    }
    function dialogs() {
      document.querySelectorAll('.tests-surface dialog').forEach(d => {
        d.querySelector('.modal-close')?.addEventListener('click', () => d.close());
        let outsideStart = false;
        const outside = e => { const r = d.getBoundingClientRect(); return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom; };
        d.addEventListener('pointerdown', e => { outsideStart = e.target === d && outside(e); });
        d.addEventListener('click', e => { if (outsideStart && e.target === d && outside(e)) d.close(); });
      });
    }
    return {$, node, api, empty, time, percent, answerText, dialogs};
  })();
}

if (typeof document !== 'undefined' && document.getElementById('tests-attempt')) (async () => {
  const {$, node, api, empty, time, answerText, dialogs} = TestsUI;
  const id = Number($('tests-attempt').dataset.attemptId), url = `/api/tests/attempts/${id}`;
  let data = JSON.parse($('tests-bootstrap').textContent);
  $('tests-bootstrap').remove();
  let token = null, current = 0, finishing = false, closed = false, denied = false, syncing = false, claiming = false, retryWork = null, submitBody = null, conflictId = null;
  const clientId = crypto.randomUUID(), timers = new Map();
  let remaining = data.remaining_seconds, syncedAt = performance.now(), lastServerTime = 0, deadlineSyncAt = -Infinity, queue;
  const types = {single_choice: 'Один вариант ответа', multiple_choice: 'Несколько вариантов ответа'};
  const status = message => { $('page-status').textContent = message; };
  const allowed = () => !!token && !closed && !denied;
  queue = new TestsSaveQueue(async (questionId, body) => {
    if (!allowed()) throw Object.assign(new Error('Продолжите тест на этом устройстве.'), {code: 'WRITER_REQUIRED'});
    const result = await api(`${url}/answers/${questionId}`, 'PUT', {...body, generation: data.generation}, token);
    if (result.server_now && result.deadline_at) setClock(result);
    return result;
  });
  data.questions.forEach(q => queue.seed(q.id, q.answer, q.revision));
  function setClock(fresh) {
    const serverTime = Date.parse(fresh.server_now);
    if (!Number.isFinite(serverTime) || !Number.isFinite(Date.parse(fresh.deadline_at)) || serverTime < lastServerTime) return;
    lastServerTime = serverTime;
    remaining = fresh.remaining_seconds ?? Math.max(0, Math.ceil((Date.parse(fresh.deadline_at) - Date.parse(fresh.server_now)) / 1000));
    syncedAt = performance.now();
    $('timer').textContent = time(remaining);
  }
  function stopWriter() { token = null; timers.forEach(clearTimeout); timers.clear(); $('writer-notice').hidden = closed || denied; update(); renderQuestion(); }
  function complete(fresh) {
    if (closed) return;
    TestsSaveQueue.validateAttemptDTO(fresh, id, {completed: true});
    closed = true; data = {...data, ...fresh}; token = null; timers.forEach(clearTimeout); setClock(data);
    document.querySelectorAll('.tests-surface dialog[open]').forEach(d => d.close());
    $('timer').textContent = time(data.remaining_seconds); $('writer-notice').hidden = true; $('attempt-layout').hidden = true; $('global-save').hidden = true; $('retry').hidden = true;
    $('finish').hidden = true; $('header-progress').textContent = 'Попытка завершена';
    $('completion-reason').textContent = data.finish_reason === 'timeout' ? 'Время истекло. Попытка завершена автоматически.' : 'Ответы отправлены на проверку.';
    $('completion-result').href = data.result_url || `/tests/attempts/${id}/result`; $('completion').hidden = false; $('completion-title').focus(); status('');
  }
  function fail(e, work) {
    status(e.message); retryWork = work; $('retry').hidden = !work;
    if ([401, 403, 404].includes(e.status)) {
      denied = true; stopWriter(); $('attempt-layout').hidden = true; $('finish').hidden = true; $('global-save').hidden = true; $('writer-notice').hidden = true; $('retry').hidden = true;
      // Revoked pages must stop displaying formerly authorized content.
      $('answer-area').replaceChildren(); data.questions = []; queue.items.clear(); return;
    }
    if (e.code === 'SESSION_REPLACED') { if (e.generation) data.generation = e.generation; submitBody = null; stopWriter(); $('retry').hidden = true; }
    if (['DEADLINE_REACHED', 'ATTEMPT_CLOSED'].includes(e.code)) { stopWriter(); sync().catch(error => fail(error, sync)); }
    if (e.code === 'ANSWER_CONFLICT') {
      const s = queue.items.get(e.question_id);
      if (s) { s.conflict = {answer: e.answer, revision: e.revision}; showConflict(e.question_id); }
    }
    update();
  }
  function update() {
    if (denied) return;
    const entries = [...queue.items];
    const dirty = entries.filter(([questionId]) => queue.dirty(questionId)).length;
    $('global-save').textContent = dirty ? `Изменения ещё не сохранены: ${dirty}` : 'Все ответы сохранены';
    $('answered-count').textContent = `Отвечено: ${entries.filter(([, s]) => !empty(s.acknowledged)).length} из ${entries.length}`;
    [...$('number-grid').children].forEach((button, i) => {
      const q = data.questions[i], s = queue.items.get(q.id), answered = !empty(s.acknowledged);
      button.classList.toggle('answered', answered); button.classList.toggle('unsaved', queue.dirty(q.id));
      if (i === current) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
      button.setAttribute('aria-label', `Вопрос ${i + 1}: ${answered ? 'отвечен' : 'без ответа'}${queue.dirty(q.id) ? ', есть несохранённые изменения' : ''}`);
    });
    const q = data.questions[current];
    if (q) { const s = queue.items.get(q.id); $('question-save').textContent = s.conflict ? 'Ответ изменён: требуется сверка.' : queue.dirty(q.id) ? 'Изменения ещё не сохранены' : 'Сохранено'; }
    $('finish').disabled = !allowed() || finishing || !!submitBody;
  }
  function edit(q, value) {
    if (!allowed() || finishing || submitBody) return;
    queue.edit(q.id, typeof value === 'string' ? value.replace(/\r\n?/g, '\n') : value); update();
    clearTimeout(timers.get(q.id)); timers.set(q.id, setTimeout(() => save(q.id), 600));
  }
  async function save(questionId) { try { await queue.save(questionId); update(); } catch (e) { fail(e, () => queue.flush().then(update)); } }
  function renderQuestion(focus = false) {
    if (closed || denied || !data.questions.length) return;
    const focused = document.activeElement, restoreText = focused?.id === 'text-answer', selection = restoreText ? [focused.selectionStart, focused.selectionEnd] : null;
    const restoreChoice = focused?.matches('#answer-area input') ? focused.value : null;
    const q = data.questions[current], s = queue.items.get(q.id);
    $('header-progress').textContent = `Вопрос ${current + 1} из ${data.questions.length}`; $('question-number').textContent = `Вопрос ${current + 1}`;
    $('question-type').textContent = types[q.question_type] || (q.free_input_mode === 'multiline' ? 'Развёрнутый ответ' : 'Короткий ответ');
    $('question-title').textContent = q.title || `Вопрос ${current + 1}`; $('question-text').textContent = q.prompt_text;
    $('question-code').hidden = !q.code_text; $('question-code').textContent = q.code_text || '';
    $('question-figure').hidden = !q.media;
    if (q.media) { $('question-image').src = q.media.url; $('question-image').alt = q.media.alt_text || ''; } else $('question-image').removeAttribute('src');
    const area = $('answer-area'); area.replaceChildren();
    if (q.question_type !== 'free_text') {
      const fieldset = node('fieldset'), legend = node('legend', '', q.question_type === 'single_choice' ? 'Выберите один ответ' : 'Выберите все подходящие ответы'); fieldset.disabled = !allowed() || finishing || !!submitBody;
      const choices = node('div', 'choices');
      q.options.forEach(option => {
        const label = node('label', 'choice'), input = node('input'); input.type = q.question_type === 'single_choice' ? 'radio' : 'checkbox'; input.name = `question-${q.id}`; input.value = String(option.id);
        input.checked = q.question_type === 'single_choice' ? s.value === option.id : (s.value || []).includes(option.id);
        input.onchange = () => edit(q, q.question_type === 'single_choice' ? option.id : [...choices.querySelectorAll('input:checked')].map(e => Number(e.value)));
        label.append(input, node('span', '', option.text)); choices.append(label);
      });
      fieldset.append(legend, choices); area.append(fieldset);
    } else {
      const label = node('label', 'answer-label', 'Ваш ответ'); label.htmlFor = 'text-answer';
      const input = node(q.free_input_mode === 'multiline' ? 'textarea' : 'input', 'form-input'); if (input.tagName === 'INPUT') input.type = 'text';
      input.id = 'text-answer'; input.value = s.value ?? ''; input.disabled = !allowed() || finishing || !!submitBody; input.setAttribute('aria-describedby', 'answer-hint');
      input.oninput = () => edit(q, input.value); const hint = node('p', 'answer-hint', q.grading_mode === 'manual' ? 'Этот ответ проверит преподаватель.' : 'Введите ответ точно, сохраняя пробелы и регистр.'); hint.id = 'answer-hint'; area.append(label, input, hint);
    }
    const clear = node('button', 'btn btn-secondary clear-answer', 'Очистить ответ'); clear.type = 'button'; clear.disabled = !allowed() || finishing || !!submitBody; clear.onclick = () => { edit(q, q.question_type === 'free_text' ? '' : q.question_type === 'multiple_choice' ? [] : null); renderQuestion(); }; area.append(clear);
    if (s.conflict) { const resolve = node('button', 'btn btn-secondary clear-answer', 'Сверить ответ'); resolve.type = 'button'; resolve.onclick = () => showConflict(q.id); area.append(resolve); }
    $('previous').disabled = current === 0 || finishing || !!submitBody; $('next').disabled = finishing || !!submitBody; $('next').textContent = current === data.questions.length - 1 ? 'Завершить тест' : 'Далее →'; update();
    if (focus) $('question-title').focus({preventScroll: true});
    else if (restoreText && $('text-answer') && !$('text-answer').disabled) { $('text-answer').focus({preventScroll: true}); $('text-answer').setSelectionRange(...selection); }
    else if (restoreChoice !== null) area.querySelector(`input[value="${Number(restoreChoice)}"]`)?.focus({preventScroll: true});
  }
  function showConflict(questionId) {
    const q = data.questions.find(x => x.id === questionId), s = queue.items.get(questionId); if (!q || !s.conflict) return;
    conflictId = questionId; $('local-answer').textContent = answerText(q, s.value); $('server-answer').textContent = answerText(q, s.conflict.answer);
    $('use-local').disabled = !allowed(); if (!$('conflict-dialog').open) $('conflict-dialog').showModal();
  }
  async function resolveConflict(keepLocal) {
    const s = queue.items.get(conflictId); if (!s?.conflict) return;
    if (s.flight) { try { await s.flight; } catch {} }
    queue.resolve(conflictId, s.conflict.answer, s.conflict.revision, keepLocal); $('conflict-dialog').close(); submitBody = null; renderQuestion(); if (keepLocal) await save(conflictId);
  }
  function reconcile(fresh, afterClaim = false) {
    fresh.questions.forEach(q => {
      const s = queue.items.get(q.id); if (!s || s.flight) return;
      if (queue.dirty(q.id)) {
        if (q.revision !== s.revision) s.conflict = {answer: q.answer, revision: q.revision};
        else if (afterClaim) queue.resolve(q.id, q.answer, q.revision, true);
      } else queue.seed(q.id, q.answer, q.revision);
    });
    data = fresh; setClock(fresh); renderQuestion();
  }
  async function sync() {
    if (syncing || denied || closed || claiming) return;
    syncing = true;
    try {
      const fresh = TestsSaveQueue.validateAttemptDTO(await api(url), id, {questions: true});
      if (claiming) return;
      if (fresh.state !== 'active') { complete(fresh); return; }
      if (token && fresh.generation !== data.generation) { status('Продолжение передано другому окну.'); stopWriter(); }
      reconcile(fresh);
      if (token) { const heartbeat = TestsSaveQueue.validateAttemptDTO(await api(`${url}/heartbeat`, 'POST', {generation: data.generation}, token), id); if (heartbeat.state !== 'active') { await syncCompletion(); } else setClock(heartbeat); }
    } finally { syncing = false; }
  }
  async function syncCompletion() { const fresh = TestsSaveQueue.validateAttemptDTO(await api(url), id, {completed: true}); complete(fresh); }
  $('claim').onclick = async () => {
    if (finishing || denied || closed) return;
    $('claim').disabled = true; claiming = true;
    try {
      await Promise.allSettled([...queue.items.values()].map(s => s.flight).filter(Boolean));
      const fresh = TestsSaveQueue.validateAttemptDTO(await api(url), id, {questions: true}); if (fresh.state !== 'active') { complete(fresh); return; }
      const claimed = TestsSaveQueue.validateAttemptDTO(await api(`${url}/claim`, 'POST', {expected_generation: fresh.generation, writer_client_id: clientId}), id, {writer: true});
      token = claimed.writer_token; data.generation = claimed.generation;
      const snapshot = TestsSaveQueue.validateAttemptDTO(await api(url), id, {questions: true});
      if (snapshot.state !== 'active') { complete(snapshot); return; }
      if (snapshot.generation !== claimed.generation) throw Object.assign(new Error('Другой клиент уже активирован.'), {code: 'SESSION_REPLACED', generation: snapshot.generation});
      reconcile(snapshot, true); $('writer-notice').hidden = true; status('Можно продолжать тест.'); $('retry').hidden = true;
    } catch (e) { stopWriter(); fail(e); } finally { claiming = false; $('claim').disabled = false; }
  };
  function showFinish() {
    if (!allowed() || finishing || submitBody) return;
    const skipped = [...queue.items.values()].filter(s => empty(s.value)).length;
    $('skipped-warning').textContent = skipped ? `Без ответа: ${skipped} из ${data.questions.length}. Можно вернуться к вопросам или завершить тест с пропусками.` : 'Вы ответили на все вопросы. Можно завершить тест.';
    $('skipped-warning').classList.toggle('is-complete', !skipped); $('finish-dialog').showModal();
  }
  async function submit() {
    if (!allowed() || finishing) return;
    finishing = true; timers.forEach(clearTimeout); $('confirm-finish').disabled = true; renderQuestion();
    try {
      if (!submitBody) {
        await queue.flush();
        const answers = queue.snapshot().map(row => {
          const q = data.questions.find(item => item.id === row.question_id);
          if (row.answer === null && q.question_type !== 'single_choice') row.answer = q.question_type === 'free_text' ? '' : [];
          return row;
        });
        submitBody = {request_key: crypto.randomUUID(), generation: data.generation, answers};
      }
      TestsSaveQueue.validateSubmitDTO(await api(`${url}/submit`, 'POST', submitBody, token), id); await syncCompletion();
    } catch (e) {
      if (e.status && e.status < 500 && e.code !== 'BAD_RESPONSE') submitBody = null;
      fail(e, submit);
    } finally {
      finishing = false; $('confirm-finish').disabled = false; $('finish-dialog').close();
      // Unknown submit outcome stays locked until the identical request is retried.
      if (submitBody && !closed) { finishing = true; renderQuestion(); finishing = false; $('finish').disabled = true; }
      else renderQuestion();
    }
  }
  data.questions.forEach((q, i) => { const button = node('button', 'question-number', i + 1); button.type = 'button'; button.onclick = () => { if (!finishing && !submitBody) { current = i; renderQuestion(true); } }; $('number-grid').append(button); });
  $('previous').onclick = () => { if (current > 0) { current--; renderQuestion(true); } };
  $('next').onclick = () => { if (current === data.questions.length - 1) showFinish(); else { current++; renderQuestion(true); } };
  $('finish').onclick = showFinish; $('confirm-finish').onclick = submit; $('keep-working').onclick = () => $('finish-dialog').close();
  $('use-server').onclick = () => resolveConflict(false); $('use-local').onclick = () => resolveConflict(true);
  $('retry').onclick = async () => { const work = retryWork; if (!work) return; $('retry').disabled = true; try { await work(); if (!submitBody) { status(''); $('retry').hidden = true; } } catch (e) { fail(e, work); } finally { $('retry').disabled = false; } };
  dialogs(); renderQuestion(); setClock(data);
  setInterval(() => {
    if (closed || denied) return;
    const seconds = Math.max(0, Math.ceil(remaining - (performance.now() - syncedAt) / 1000)); $('timer').textContent = time(seconds); $('timer-box').classList.toggle('timer-warning', seconds <= 60);
    if (!seconds && !syncing && performance.now() - deadlineSyncAt >= 15000) { deadlineSyncAt = performance.now(); sync().catch(e => fail(e, sync)); }
  }, 1000);
  setInterval(() => { if (!document.hidden && !finishing && !submitBody) sync().catch(e => fail(e, sync)); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !submitBody) sync().catch(e => fail(e, sync)); });
  window.addEventListener('offline', () => status('Нет связи с сервером. Несохранённый ввод остаётся на этой странице.'));
  window.addEventListener('online', () => { if (!submitBody) sync().catch(e => fail(e, sync)); });
  window.addEventListener('beforeunload', e => { if (!closed && ([...queue.items.keys()].some(q => queue.dirty(q)) || submitBody)) { e.preventDefault(); e.returnValue = ''; } });
  await sync().catch(e => fail(e, sync));
})();
