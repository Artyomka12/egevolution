'use strict';
(() => {
  const {$, node, api, time, percent, dialogs} = TestsUI;
  const states = {not_started: ['idle', 'Не начат'], active: ['active', 'В процессе'], pending_review: ['review', 'Ожидает проверки'], completed: ['done', 'Пройден']};
  let selected = null, busy = false, loading = false;
  const starts = new Map();
  const actionLabel = t => t.can_resume ? 'Продолжить тест' : t.can_start ? (t.last_attempt_id ? 'Пройти ещё раз' : 'Начать тест') : t.result_url ? 'Результат последней попытки' : 'Сейчас недоступен';
  function modal(t) {
    selected = t; const [cls, label] = states[t.status] || states.not_started;
    $('modal-title').textContent = t.title; $('modal-description').textContent = t.description || ''; $('modal-status').className = `status status-${cls}`; $('modal-status').textContent = label;
    $('modal-questions').textContent = t.question_count; $('modal-time').textContent = time(t.time_limit_seconds);
    $('modal-attempts').textContent = t.remaining_attempts === null ? 'Без ограничения' : String(t.remaining_attempts);
    $('modal-action').textContent = starts.has(t.id) ? 'Повторить запрос начала' : actionLabel(t); $('modal-action').disabled = busy || !(t.can_resume || t.can_start || t.result_url || starts.has(t.id));
    $('latest-result').hidden = !t.result_url || !(t.can_start || starts.has(t.id)); if (t.result_url) $('latest-result').href = t.result_url;
    $('modal-message').textContent = t.publication_state !== 'published' ? 'Тест скрыт. Доступны сохранённая попытка и её результат.' : (!t.can_start && !t.can_resume && !t.result_url ? 'Новые попытки сейчас недоступны.' : '');
  }
  async function open(t) {
    modal(t); if (!$('test-dialog').open) $('test-dialog').showModal();
    try { const fresh = await api(`/api/tests/${t.id}`); if (selected?.id === t.id && !busy) modal(fresh); }
    catch (e) { $('modal-message').textContent = e.message; if ([401, 403, 404].includes(e.status)) { $('modal-action').disabled = true; $('latest-result').hidden = true; } }
  }
  function render(tests) {
    $('test-grid').replaceChildren();
    tests.forEach(t => {
      const [cls, label] = states[t.status] || states.not_started, card = node('article', 'test-card card');
      const heading = node('h2'), button = node('button', 'card-open', t.title); button.type = 'button'; button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-controls', 'test-dialog'); button.onclick = () => open(t); heading.append(button);
      const meta = node('div', 'test-meta'); meta.append(node('span', '', `${t.question_count} вопросов`), node('span', '', `${Math.ceil(t.time_limit_seconds / 60)} мин`));
      const bottom = node('div', 'test-bottom');
      if (t.best) { const value = node('p', 'result-value', `${t.best.earned} / ${t.best.total} баллов `); value.append(node('span', '', `· ${percent(t.best.percentage)}`)); bottom.append(node('span', 'result-label', 'Лучший результат'), value); }
      else bottom.append(node('p', 'result-empty', t.status === 'pending_review' ? 'Результат после проверки' : 'Результатов пока нет'));
      const action = node('span', 'card-action', t.status === 'pending_review' ? 'Подробнее' : actionLabel(t)); action.setAttribute('aria-hidden', 'true'); action.append(node('span', '', '→')); bottom.append(action);
      card.append(node('span', `status status-${cls}`, label), heading, node('p', 'test-description', t.description || ''), meta, bottom); $('test-grid').append(card);
    });
    $('page-status').textContent = tests.length ? '' : 'Пока нет доступных тестов.';
  }
  async function load() {
    if (loading) return; loading = true;
    try { const result = await api('/api/tests'); render(result.tests); $('retry').hidden = true; if (selected && $('test-dialog').open && !busy) { const fresh = result.tests.find(t => t.id === selected.id); if (fresh) modal(fresh); else { $('test-dialog').close(); selected = null; } } }
    catch (e) { $('page-status').textContent = e.message; $('retry').hidden = false; if ([401, 403, 404].includes(e.status)) { $('test-grid').replaceChildren(); $('test-dialog').close(); selected = null; } }
    finally { loading = false; }
  }
  $('modal-action').onclick = async () => {
    if (!selected || busy) return;
    const t = selected;
    if (!starts.has(t.id) && t.can_resume) { location.assign(t.attempt_url); return; }
    if (!starts.has(t.id) && !t.can_start) { if (t.result_url) location.assign(t.result_url); return; }
    busy = true; $('modal-action').disabled = true;
    if (!starts.has(t.id)) starts.set(t.id, {request_key: crypto.randomUUID()});
    try { const a = await api(`/api/tests/${t.id}/attempts`, 'POST', starts.get(t.id)); starts.delete(t.id); location.assign(a.state === 'active' ? a.attempt_url : a.result_url); }
    catch (e) { if (e.status >= 400 && e.status < 500 && e.code !== 'BAD_RESPONSE') starts.delete(t.id); $('modal-message').textContent = e.message; }
    finally { busy = false; $('modal-action').disabled = false; $('modal-action').textContent = starts.has(t.id) ? 'Повторить запрос начала' : actionLabel(t); }
  };
  $('retry').onclick = load; dialogs(); load();
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  setInterval(() => { if (!document.hidden && !busy) load(); }, 30000);
})();
