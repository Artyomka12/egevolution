'use strict';
(() => {
  const {api, node, empty, time, condition} = ThematicStudent, $ = id => document.getElementById(id);
  const variant = Number($('thematic-root').dataset.variantId);
  const storageKey = `thematic-start:${variant}`;
  let startKey;
  try { startKey = sessionStorage.getItem(storageKey); } catch {}
  if (!startKey) startKey = crypto.randomUUID();
  try { sessionStorage.setItem(storageKey, startKey); } catch {}
  let attempt, questions = [], queue, blocked = false, finishing = false, timer, retryWork, submitBody;
  let baseElapsed = 0, syncedAt = performance.now(), heartbeatBusy = false;
  const elements = new Map();
  function status(text) { $('page-status').textContent = text; }
  function resultLocation(id) { location.assign(`/thematic-attempts/${id}/result`); }
  function error(e, work) {
    status(e.message);
    retryWork = work; $('retry').hidden = !work;
    if ([423, 410].includes(e.status)) {
      blocked = true; $('workspace').hidden = true; $('blocked').hidden = true;
      if (e.status === 423) $('blocked').hidden = false;
      else if (attempt) resultLocation(attempt.id);
    }
    if (e.status === 409 && e.item_id && elements.has(e.item_id)) {
      queue.items.get(e.item_id).conflict = true;
      elements.get(e.item_id).resolve.hidden = false;
    }
    updateProgress();
  }
  function updateProgress() {
    if (!queue) return;
    const entries = [...queue.items.entries()];
    const dirty = entries.filter(([id]) => queue.dirty(id) || queue.items.get(id).conflict).length;
    $('global-save').textContent = dirty ? `Не сохранено ответов: ${dirty}` : 'Все изменения сохранены';
    $('progress').textContent = `Ответов: ${entries.filter(([, s]) => !empty(s.value)).length} из ${entries.length}`;
    entries.forEach(([id, s]) => { const el = elements.get(id); if (el) { el.number.classList.toggle('answered', !empty(s.value)); el.save.textContent = s.conflict ? 'Конфликт: требуется сверка' : queue.dirty(id) ? 'Изменения ещё не сохранены' : 'Сохранено'; } });
  }
  async function flush() {
    if (blocked) throw Object.assign(new Error('Вариант скрыт. Несохранённый ввод остаётся на этой странице.'), {status: 423});
    await queue.flush(); updateProgress();
  }
  function controls(q, value) {
    const box = node('div', undefined, 'thematic-answer'), inputs = [];
    let rows = 1, cols = 1;
    if (q.task_type === 'pair') cols = 2;
    if (q.task_type === 'grid') ({rows, cols} = q.answer_shape);
    for (let r = 0; r < rows; r++) {
      const row = node('div', undefined, 'thematic-answer-row');
      for (let c = 0; c < cols; c++) {
        const input = node('input', undefined, 'form-input'); input.type = 'text'; input.maxLength = 10000;
        input.setAttribute('aria-label', `Задача ${q.position}, ответ ${r + 1}.${c + 1}`);
        input.value = q.task_type === 'scalar' ? value ?? '' : q.task_type === 'pair' ? value?.[c] ?? '' : value?.[r]?.[c] ?? '';
        inputs.push(input); row.append(input);
      }
      box.append(row);
    }
    const get = () => q.task_type === 'scalar' ? inputs[0].value : q.task_type === 'pair' ? inputs.map(i => i.value) : Array.from({length: rows}, (_, r) => inputs.slice(r * cols, (r + 1) * cols).map(i => i.value));
    inputs.forEach(input => input.oninput = () => {
      queue.edit(q.item_id, get()); q.is_correct = null; elements.get(q.item_id).feedback.textContent = ''; updateProgress(); clearTimeout(timer);
      timer = setTimeout(() => flush().catch(e => error(e, flush)), 700);
    });
    return box;
  }
  function render() {
    $('tasks').replaceChildren(); $('numbers').replaceChildren(); elements.clear();
    for (const q of questions) {
      const card = node('article', undefined, 'card reshenie-task-card'); card.id = `task-${q.item_id}`;
      card.append(node('h2', `${q.position}. ${q.title || 'Задание ЕГЭ №' + q.source_task_num}`, 'reshenie-task-title'), condition(q));
      const feedback = node('p', q.is_correct === null ? '' : q.is_correct ? 'Правильно' : 'Неправильно', 'feedback'), save = node('p', '', 'save');
      const button = node('button', 'Проверить', 'btn btn-primary');
      const resolve = node('button', 'Сверить сохранённый ответ', 'btn btn-secondary'); resolve.hidden = !queue.items.get(q.item_id).conflict;
      resolve.onclick = async () => {
        try {
          const data = await api(`/api/thematic-attempts/${attempt.id}`), fresh = data.questions.find(x => x.item_id === q.item_id);
          if (!window.confirm(`Ваш ввод: ${JSON.stringify(queue.items.get(q.item_id).value)}\nНа сервере: ${JSON.stringify(fresh.answer)}\nЗагрузить ответ с сервера вместо местного ввода?`)) return;
          await queue.enqueue(() => { queue.seed(q.item_id, fresh.answer, fresh.revision); Object.assign(q, fresh); render(); });
        } catch (e) { error(e); }
      };
      button.onclick = async () => {
        if (empty(queue.items.get(q.item_id).value)) { feedback.textContent = 'Введите ответ'; return; }
        button.disabled = true;
        try {
          await flush();
          const body = {request_key: crypto.randomUUID(), expected_revision: queue.items.get(q.item_id).revision};
          const work = async () => {
            const answer = await api(`/api/thematic-attempts/${attempt.id}/check/${q.item_id}`, 'POST', body);
            if (!queue.dirty(q.item_id) && answer.revision === queue.items.get(q.item_id).revision) {
              q.is_correct = answer.is_correct;
              feedback.textContent = answer.is_correct ? 'Правильно' : 'Неправильно'; feedback.className = 'feedback ' + (answer.is_correct ? 'good' : 'bad');
            }
          };
          try { await work(); } catch (e) { error(e, work); }
        } catch (e) { error(e, flush); } finally { button.disabled = false; }
      };
      const number = node('button', q.position, 'number'); number.setAttribute('aria-label', 'Перейти к задаче ' + q.position);
      number.onclick = async () => { try { await flush(); } catch (e) { error(e, flush); } card.scrollIntoView({behavior: 'smooth', block: 'start'}); document.querySelectorAll('.number').forEach(n => n.removeAttribute('aria-current')); number.setAttribute('aria-current', 'true'); };
      elements.set(q.item_id, {feedback, save, resolve, number});
      card.append(controls(q, queue.items.get(q.item_id).value), button, feedback, save, resolve); $('tasks').append(card); $('numbers').append(number);
    }
    updateProgress();
  }
  async function sync() {
    if (!attempt || !queue || heartbeatBusy || finishing) return;
    heartbeatBusy = true;
    try {
      const data = await api(`/api/thematic-attempts/${attempt.id}`);
      if (data.state === 'finished') { resultLocation(attempt.id); return; }
      baseElapsed = data.elapsed_ms; syncedAt = performance.now();
      const wasBlocked = blocked; blocked = false; $('blocked').hidden = true; $('workspace').hidden = false;
      let redraw = wasBlocked;
      for (const q of data.questions) {
        const local = queue.items.get(q.item_id);
        if (local.pending) continue;
        if (q.revision !== local.revision) {
          if (queue.dirty(q.item_id) || local.conflict) { local.conflict = true; elements.get(q.item_id).resolve.hidden = false; status('Ответ изменён в другой вкладке. Местный ввод сохранён на странице.'); }
          else { queue.seed(q.item_id, q.answer, q.revision); Object.assign(questions.find(x => x.item_id === q.item_id), q); redraw = true; }
        }
      }
      if (redraw) render();
      if (wasBlocked) { status('Доступ восстановлен. Проверьте несохранённые ответы перед отправкой.'); retryWork = flush; $('retry').hidden = false; }
      updateProgress();
    } catch (e) { error(e, sync); } finally { heartbeatBusy = false; }
  }
  async function initialize() {
    attempt = await api(`/api/thematic-variants/${variant}/attempts`, 'POST', {request_key: startKey});
    try { sessionStorage.removeItem(storageKey); } catch {}
    if (attempt.state === 'finished') { resultLocation(attempt.id); return; }
    const data = await api(`/api/thematic-attempts/${attempt.id}`);
    questions = data.questions;
    queue = new ThematicSaveQueue((id, body) => api(`/api/thematic-attempts/${attempt.id}/answers/${id}`, 'PUT', body), () => crypto.randomUUID());
    questions.forEach(q => queue.seed(q.item_id, q.answer, q.revision));
    $('title').textContent = data.title; $('version').textContent = `Версия ${data.version_no} · обычный режим · без ограничения времени`;
    baseElapsed = data.elapsed_ms; syncedAt = performance.now(); blocked = false;
    $('blocked').hidden = true; $('workspace').hidden = false; $('retry').hidden = true; status(''); render();
  }
  $('retry').onclick = async () => { if (!retryWork) return; $('retry').disabled = true; try { await retryWork(); $('retry').hidden = true; status(''); } catch (e) { error(e, retryWork); } finally { $('retry').disabled = false; } };
  $('finish').onclick = () => { const skipped = [...queue.items.values()].filter(s => empty(s.value)).length; $('finish-note').textContent = skipped ? `Без ответа: ${skipped} из ${questions.length}.` : 'Вы ответили на все задачи.'; $('confirm').showModal(); };
  $('submit').onclick = async () => {
    if (finishing) return;
    finishing = true; clearTimeout(timer); $('submit').disabled = true;
    document.querySelectorAll('#tasks input,#tasks button,#finish').forEach(el => el.disabled = true);
    try {
      await flush();
      const answers = [...queue.items.entries()].map(([item_id, s]) => ({item_id, answer: structuredClone(s.value), expected_revision: s.revision}));
      if (!submitBody || JSON.stringify(submitBody.answers) !== JSON.stringify(answers)) submitBody = {request_key: crypto.randomUUID(), answers};
      const result = await api(`/api/thematic-attempts/${attempt.id}/submit`, 'POST', submitBody);
      $('confirm').close(); resultLocation(result.id);
    } catch (e) { $('confirm').close(); error(e, async () => { await sync(); if (!blocked) $('finish').click(); }); }
    finally { finishing = false; $('submit').disabled = false; document.querySelectorAll('#tasks input,#tasks button,#finish').forEach(el => el.disabled = false); }
  };
  document.querySelectorAll('[data-close]').forEach(b => b.onclick = () => $('confirm').close());
  $('confirm').addEventListener('click', e => { const r = $('confirm').getBoundingClientRect(); if (e.target === $('confirm') && (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom)) $('confirm').close(); });
  window.addEventListener('beforeunload', e => { if (queue && [...queue.items.keys()].some(id => queue.dirty(id))) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('visibilitychange', () => { if (queue && !blocked && !finishing) flush().catch(e => error(e, flush)); if (!document.hidden) sync(); });
  setInterval(() => { $('elapsed').textContent = time(baseElapsed + (blocked ? 0 : performance.now() - syncedAt)); }, 1000);
  setInterval(() => { if (queue) sync(); }, 10000);
  initialize().catch(e => error(e, initialize));
})();
