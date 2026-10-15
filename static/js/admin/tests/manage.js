/* Administrative catalog. All displayed state comes from the server. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const key = () => crypto.randomUUID();
  const pendingKeys = new Map();
  let tests = [], revision = null, deleting = null, busy = false, reviews = [], nextOffset = 0;
  let reviewLoading = false;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  function button(text, cls, action) {
    const b = el('button', cls, text); b.type = 'button'; b.addEventListener('click', action); return b;
  }
  function cell(label, content, cls = '') {
    const td = el('td', cls); td.dataset.label = label;
    if (content instanceof Node) td.append(content); else td.textContent = content;
    return td;
  }
  async function api(url, method = 'GET', body) {
    const options = {method, credentials: 'same-origin', cache: 'no-store', headers: {'X-CSRFToken': csrf}};
    let operation;
    if (body !== undefined) {
      const {request_key: proposedKey, ...payload} = body;
      operation = method + url + JSON.stringify(payload);
      if (!pendingKeys.has(operation)) pendingKeys.set(operation, proposedKey || key());
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify({...payload, request_key: pendingKeys.get(operation)});
    }
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const positive = value => Number.isInteger(value) && value > 0;
    const valid = data => {
      if (!object(data)) return false;
      if (url === '/api/admin/tests' && method === 'GET') return Array.isArray(data.tests) && positive(data.revision);
      if (url.startsWith('/api/admin/tests/review-queue')) return Array.isArray(data.items) &&
        data.items.every(item => object(item) && positive(item.attempt_id) && typeof item.title === 'string' &&
          typeof item.username === 'string' && Number.isInteger(item.pending_count) && item.pending_count > 0) &&
        (data.next_offset === null || Number.isInteger(data.next_offset) && data.next_offset >= 0);
      if (url === '/api/admin/tests/order') return positive(data.revision) && Array.isArray(data.test_ids) && data.test_ids.every(positive);
      if (/\/copy$/.test(url)) return positive(data.test_id) && positive(data.revision) && object(data.document);
      if (/\/(publish|visibility)$/.test(url)) return positive(data.test_id) && positive(data.version_id) &&
        positive(data.revision) && positive(data.draft_revision) && ['published', 'hidden'].includes(data.publication_state);
      if (method === 'DELETE' && /^\/api\/admin\/tests\/\d+$/.test(url)) return positive(data.test_id) && data.deleted === true;
      return true;
    };
    for (let attempt = 0; ; attempt++) {
      const controller = new AbortController(); let timer, response, data;
      try {
        ({response, data} = await Promise.race([
          (async () => {
            const result = await fetch(url, {...options, signal: controller.signal});
            const parsed = await result.json();
            if (!object(parsed) || (result.ok ? !valid(parsed) :
              !object(parsed.error) || typeof parsed.error.message !== 'string')) throw new Error('Unconfirmed response');
            return {response: result, data: parsed};
          })(),
          new Promise((_, reject) => {
            timer = setTimeout(() => { controller.abort(); reject(new Error('Request timeout')); }, 15000);
          })
        ]));
      } catch (_) {
        if (attempt < 2) { await new Promise(resolve => setTimeout(resolve, 400 * (attempt + 1))); continue; }
        throw new Error('Результат операции не подтверждён. Повторите действие: будет использован прежний запрос.');
      } finally { clearTimeout(timer); }
      if (response.status === 503 && attempt < 2) { await new Promise(resolve => setTimeout(resolve, 400 * (attempt + 1))); continue; }
      if (!response.ok) {
        if (response.status < 500) pendingKeys.delete(operation);
        const error = new Error(data.error?.message || 'Не удалось выполнить операцию.');
        error.status = response.status; error.fields = data.field_errors; throw error;
      }
      pendingKeys.delete(operation); return data;
    }
  }
  function announce(message) { $('feedback').textContent = message; }
  async function load() {
    const data = await api('/api/admin/tests'); tests = data.tests; revision = data.revision; render();
  }
  async function mutate(action, message) {
    if (busy) return;
    busy = true; document.querySelectorAll('main button').forEach(b => { b.disabled = true; });
    try { await action(); await load(); announce(message); }
    catch (error) {
      announce([error.message, ...Object.values(error.fields || {})].join(' '));
      if (error.status === 409) { try { await load(); } catch (_) { /* Keep original conflict visible. */ } }
    } finally { busy = false; render(); }
  }
  function move(test, delta) {
    const i = tests.indexOf(test), j = i + delta;
    if (j < 0 || j >= tests.length) return;
    const ids = tests.map(t => t.id); [ids[i], ids[j]] = [ids[j], ids[i]];
    return mutate(() => api('/api/admin/tests/order', 'PUT', {
      test_ids: ids, expected_revision: revision, request_key: key()
    }), 'Порядок тестов сохранён.');
  }
  function render() {
    $('tests-body').replaceChildren();
    tests.forEach((test, i) => {
      const row = el('tr'); row.dataset.testId = test.id;
      const name = el('div'); name.append(el('div', 'test-title', test.title || 'Новый тест'));
      const order = el('div', 'order-controls'); order.append(el('span', 'order-number', `№${i + 1}`));
      const up = button('↑ Выше', 'order-button', () => move(test, -1));
      const down = button('↓ Ниже', 'order-button', () => move(test, 1));
      up.disabled = busy || i === 0; down.disabled = busy || i === tests.length - 1;
      up.setAttribute('aria-label', `Переместить «${test.title}» выше`);
      down.setAttribute('aria-label', `Переместить «${test.title}» ниже`);
      order.append(up, down); name.append(order);
      const actions = el('div', 'actions');
      const edit = el('a', 'action test-link', 'Редактировать'); edit.href = `/admin/tests/${test.id}/edit`;
      const copy = button('Создать копию', 'action action-neutral', () => mutate(
        () => api(`/api/admin/tests/${test.id}/copy`, 'POST', {request_key: key()}), 'Создан черновик копии без истории.'));
      const published = test.publication_state === 'published';
      const visibility = button(published ? 'Скрыть' : 'Опубликовать', published ? 'action action-neutral' : 'action action-publish', () => mutate(
        () => test.current_version_id
          ? api(`/api/admin/tests/${test.id}/visibility`, 'PATCH', {published: !published, expected_revision: test.revision, request_key: key()})
          : api(`/api/admin/tests/${test.id}/publish`, 'POST', {expected_revision: test.draft_revision, request_key: key()}),
        published ? 'Тест скрыт. Начатые попытки продолжаются.' : 'Тест опубликован.'));
      const remove = button('Удалить', 'btn-delete', () => {
        deleting = test;
        $('delete-description').textContent = `«${test.title || 'Новый тест'}». Прохождений: ${test.submitted_count}. Активных попыток: ${test.active_count}.`;
        $('delete-dialog').showModal();
      });
      for (const b of [copy, visibility, remove]) b.disabled = busy;
      actions.append(edit, copy, visibility, remove);
      const state = {published: 'Опубликован', hidden: 'Скрыт', draft: 'Черновик'}[test.publication_state];
      row.append(cell('Название теста', name), cell('Вопросов', test.question_count),
        cell('Время', test.time_limit_seconds ? `${test.time_limit_seconds / 60} мин` : '—'),
        cell('Прохождений', `${test.submitted_count} · активных ${test.active_count}`),
        cell('Публикация', el('span', 'badge ' + (published ? 'published' : 'hidden-status'), state)),
        cell('Действия', actions, 'actions-cell'));
      $('tests-body').append(row);
    });
    $('tests-empty').hidden = tests.length !== 0;
  }
  async function loadReviews(append = false) {
    if (reviewLoading || (append && nextOffset == null)) return;
    reviewLoading = true; $('review-more').disabled = true; $('panel-review').setAttribute('aria-busy', 'true');
    try {
      const data = await api(`/api/admin/tests/review-queue?offset=${append ? nextOffset : 0}`);
      const received = append ? reviews.concat(data.items) : data.items;
      reviews = [...new Map(received.map(item => [item.attempt_id, item])).values()];
      nextOffset = data.next_offset;
      $('review-body').replaceChildren();
      for (const item of reviews) {
        const row = el('tr'), link = el('a', 'action test-link', 'Проверить');
        link.href = `/admin/tests/attempts/${item.attempt_id}/review`;
        const date = item.submitted_at ? new Date(item.submitted_at).toLocaleString('ru-RU', {timeZone: 'Europe/Moscow'}) : '—';
        row.append(cell('Ученик', item.student_name || item.username), cell('Название теста', item.title),
          cell('Дата прохождения', el('span', 'date', date)), cell('Непроверенных вопросов', el('span', 'pending-number', item.pending_count)),
          cell('Действия', link, 'actions-cell')); $('review-body').append(row);
      }
      $('review-empty').hidden = reviews.length !== 0; $('review-more').hidden = nextOffset == null;
    } catch (error) { announce(error.message); }
    finally {
      reviewLoading = false; $('review-more').disabled = false; $('panel-review').setAttribute('aria-busy', 'false');
    }
  }
  function selectTab(name) {
    for (const item of ['all', 'review']) {
      const active = item === name; $('tab-' + item).setAttribute('aria-selected', String(active));
      $('tab-' + item).tabIndex = active ? 0 : -1; $('panel-' + item).hidden = !active;
    }
    if (name === 'review') loadReviews();
  }
  for (const name of ['all', 'review']) {
    $('tab-' + name).addEventListener('click', () => selectTab(name));
    $('tab-' + name).addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); const target = event.key === 'Home' ? 'all' : event.key === 'End' ? 'review' : name === 'all' ? 'review' : 'all';
      selectTab(target); $('tab-' + target).focus();
    });
  }
  $('review-more').addEventListener('click', () => loadReviews(true));
  window.addEventListener('focus', () => {
    if ($('tab-review').getAttribute('aria-selected') === 'true') loadReviews();
  });
  const dialog = $('delete-dialog');
  for (const b of [dialog.querySelector('.close'), $('cancel-delete')]) b.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { deleting = null; });
  let outsideStart = false;
  const outside = event => { const r = dialog.getBoundingClientRect(); return event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom; };
  dialog.addEventListener('pointerdown', event => { outsideStart = event.target === dialog && outside(event); });
  dialog.addEventListener('click', event => { if (outsideStart && event.target === dialog && outside(event)) dialog.close(); });
  $('confirm-delete').addEventListener('click', async () => {
    if (!deleting || busy) return;
    const test = deleting; $('confirm-delete').disabled = true;
    await mutate(async () => {
      await api(`/api/admin/tests/${test.id}`, 'DELETE', {confirmed: true, expected_revision: test.revision, request_key: key()});
      dialog.close(); $('create-test').focus();
    }, 'Тест и все связанные попытки удалены.');
    $('confirm-delete').disabled = false;
  });
  load().catch(error => announce(error.message));
})();
