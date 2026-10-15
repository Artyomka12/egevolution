/* Test statistics inside the existing teacher view; no legacy metric changes. */
(() => {
  'use strict';
  const root = document.getElementById('tests-user-stats');
  if (!root) return;
  const $ = id => document.getElementById('tests-stats-' + id);
  const base = `/api/admin/users/${root.dataset.userId}/tests`;
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const dialog = $('dialog');
  let tests = [], loaded = false, loading = false, dialogGeneration = 0, opener = null;
  const expanded = new Set(), histories = new Map(), grants = new Map();
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  function button(text, callback) { const node = el('button', 'uts-action', text); node.type = 'button'; node.addEventListener('click', callback); return node; }
  function cell(text, label) { const node = el('td'); if (text instanceof Node) node.append(text); else node.textContent = text; if (label) node.dataset.label = label; return node; }
  const percent = value => value.toLocaleString('ru-RU', {maximumFractionDigits: 1}) + '%';
  const date = value => value ? new Date(value).toLocaleString('ru-RU', {timeZone: 'Europe/Moscow'}) : '—';
  const duration = seconds => { const value = Math.max(0, Math.floor(seconds)); return [Math.floor(value / 3600), Math.floor(value / 60) % 60, value % 60].map(part => String(part).padStart(2, '0')).join(':'); };
  const remaining = value => value === null ? 'без ограничений' : String(value);
  async function api(url, body, validate = () => true) {
    const options = {method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', headers: {'X-CSRFToken': csrf}};
    if (body) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    for (let attempt = 0; ; attempt++) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 15000);
      try {
        const response = await fetch(url, {...options, signal: controller.signal});
        let result;
        try { result = await response.json(); }
        catch (cause) {
          const error = new Error('Ответ сервера не удалось прочитать. Результат запроса не подтверждён.');
          if (!response.ok && response.status < 500) error.status = response.status;
          throw error;
        }
        if (!response.ok) {
          const error = new Error([result?.error?.message || 'Не удалось выполнить запрос.', ...Object.values(result?.field_errors || {})].join(' '));
          error.status = response.status; throw error;
        }
        if (!result || typeof result !== 'object' || Array.isArray(result) || !validate(result)) {
          throw new Error('Сервер вернул неполные данные. Результат запроса не подтверждён.');
        }
        return result;
      }
      catch (error) {
        if (error.status && error.status < 500) throw error;
        if (attempt >= 2) {
          if (error.name === 'AbortError') throw new Error('Сервер не ответил вовремя. Повторите тот же запрос.');
          throw error;
        }
      } finally {
        clearTimeout(timeout);
      }
      await new Promise(resolve => setTimeout(resolve, 350 * (attempt + 1)));
    }
  }
  function failClosed(error) {
    if (![401, 403].includes(error.status)) return false;
    tests = []; histories.clear(); expanded.clear(); loaded = false;
    $('rows').replaceChildren(); if (dialog.open) dialog.close();
    $('feedback').textContent = error.message; return true;
  }
  function resultText(attempt) {
    if (attempt.state === 'active') return 'В процессе';
    const summary = attempt.summary;
    return summary.is_final ? `${summary.earned} / ${summary.total} · ${percent(summary.percentage)}` : `Ожидает проверки: ${summary.pending_count}. Предварительно: ${summary.earned} из ${summary.checked_count} проверенных`;
  }
  function renderHistory(test, target) {
    const entry = histories.get(test.id);
    if (!entry) { target.append(el('p', 'uts-muted', 'Загрузка попыток…')); return; }
    if (entry.error) {
      target.append(el('p', 'uts-feedback', entry.error), button('Повторить загрузку', () => loadHistory(test, entry.items.length > 0)));
    }
    if (!entry.items.length && !entry.loading && !entry.error) target.append(el('p', 'uts-muted', 'Ученик ещё не проходил этот тест.'));
    if (entry.items.length) {
      const scroll = el('div', 'uts-table-scroll'), table = el('table', 'uts-attempts-table'), head = el('thead'), row = el('tr'), body = el('tbody');
      ['Номер', 'Дата и время', 'Затрачено', 'Результат', 'Действие'].forEach(text => row.append(el('th', '', text))); head.append(row);
      entry.items.forEach(attempt => {
        const tr = el('tr'), number = el('div'); number.append(el('div', '', `№ ${attempt.attempt_no}`), el('span', 'uts-muted', `Версия ${attempt.version_no}`));
        const details = button('Подробности', () => showAttempt(test, attempt, details));
        tr.append(cell(number), cell(date(attempt.submitted_at || attempt.started_at)), cell(duration(attempt.elapsed_seconds)), cell(resultText(attempt)), cell(details)); body.append(tr);
      });
      table.append(head, body); scroll.append(table); target.append(scroll);
    }
    if (entry.loading) target.append(el('p', 'uts-muted', 'Загрузка…'));
    else if (entry.next_offset !== null && !entry.error) target.append(button('Показать ещё', () => loadHistory(test, true)));
  }
  function render() {
    $('rows').replaceChildren(); $('empty').hidden = !loaded || tests.length !== 0;
    tests.forEach(test => {
      const row = el('tr'), title = el('strong', '', test.title), toggle = button(expanded.has(test.id) ? 'Свернуть' : 'Раскрыть', () => {
        if (expanded.has(test.id)) expanded.delete(test.id); else expanded.add(test.id);
        render(); root.querySelector(`[data-expand="${test.id}"]`)?.focus({preventScroll: true});
        if (expanded.has(test.id) && !histories.has(test.id)) loadHistory(test);
      });
      toggle.dataset.expand = test.id; toggle.setAttribute('aria-expanded', String(expanded.has(test.id))); toggle.setAttribute('aria-controls', `tests-stats-history-${test.id}`);
      row.append(cell(title, 'Название теста'), cell(String(test.used_attempts), 'Попытки'), cell(test.best ? `${test.best.earned} / ${test.best.total}` : '—', 'Лучший результат'), cell(test.best ? percent(test.best.percentage) : '—', 'Лучший процент'), cell(toggle, 'Подробности'));
      const detailRow = el('tr'); detailRow.id = `tests-stats-history-${test.id}`; detailRow.hidden = !expanded.has(test.id);
      const td = el('td', 'uts-attempts-cell'); td.colSpan = 5;
      const header = el('div', 'uts-attempts-header'), grant = button('Добавить попытки', () => showGrant(test, grant)); grant.dataset.grant = test.id;
      header.append(el('strong', '', 'Попытки ученика'), grant); td.append(header, el('p', 'uts-attempts-note', `Доступно новых попыток: ${remaining(test.remaining_attempts)}`));
      if (expanded.has(test.id)) renderHistory(test, td);
      detailRow.append(td); $('rows').append(row, detailRow);
    });
  }
  async function load() {
    if (loading) return;
    loading = true; $('reload').hidden = true; $('feedback').textContent = 'Загрузка тестов…';
    try {
      const result = await api(base); tests = result.tests; loaded = true; render(); $('feedback').textContent = '';
      tests.filter(test => expanded.has(test.id) && !histories.has(test.id)).forEach(test => loadHistory(test));
    }
    catch (error) { if (!failClosed(error)) $('feedback').textContent = error.message; $('reload').hidden = false; }
    finally { loading = false; }
  }
  async function loadHistory(test, append = false) {
    let entry = histories.get(test.id);
    if (entry?.loading) return;
    if (!entry || !append) entry = {items: [], next_offset: 0, loading: false, error: ''};
    entry.loading = true; entry.error = ''; histories.set(test.id, entry); render();
    try {
      const result = await api(`${base}/${test.id}/attempts?offset=${append ? entry.next_offset : 0}`);
      const byId = new Map((append ? entry.items : []).map(item => [item.attempt_id, item]));
      result.items.forEach(item => byId.set(item.attempt_id, item)); entry.items = [...byId.values()]; entry.next_offset = result.next_offset;
    } catch (error) { if (!failClosed(error)) entry.error = error.message; }
    finally { entry.loading = false; render(); }
  }
  function openDialog(title, source) {
    dialogGeneration++; opener = source; $('dialog-title').textContent = title; $('dialog-body').replaceChildren(); $('dialog-feedback').textContent = '';
    if (!dialog.open) dialog.showModal(); dialog.scrollTop = 0; return dialogGeneration;
  }
  function answerText(question) {
    if (question.answer === null || question.answer === '' || (Array.isArray(question.answer) && !question.answer.length)) return 'Ответ не дан';
    if (question.question_type === 'free_text') return question.answer;
    const selected = Array.isArray(question.answer) ? question.answer : [question.answer];
    return question.options.filter(option => selected.includes(option.id)).map(option => option.text).join('\n');
  }
  async function showAttempt(test, attempt, source) {
    const generation = openDialog(`${test.title} · попытка № ${attempt.attempt_no}`, source);
    $('dialog-feedback').textContent = 'Загрузка подробностей…';
    try {
      const result = await api(`/api/admin/tests/attempts/${attempt.attempt_id}`);
      if (generation !== dialogGeneration || !dialog.open) return;
      const body = $('dialog-body'); body.append(el('p', 'uts-muted', `Версия ${result.version_no} · ${date(result.submitted_at || result.started_at)} · Затрачено ${duration(result.elapsed_seconds)}`), el('p', 'uts-attempts-note', resultText(result)));
      result.questions.forEach(question => {
        const section = el('section', 'uts-attempt-question'); section.append(el('h3', '', `${question.position}. ${question.title}`), el('div', 'uts-prose', question.prompt_text));
        if (question.code_text) { const pre = el('pre'); pre.append(el('code', '', question.code_text)); section.append(pre); }
        if (question.media) { const image = el('img', 'uts-question-image'); image.src = question.media.url; image.alt = question.media.alt_text || ''; section.append(image); }
        if (question.options.length) { const list = el('ol', 'uts-options'); question.options.forEach(option => list.append(el('li', '', option.text))); section.append(list); }
        const answer = el('div', 'uts-answer'); answer.append(el('strong', '', 'Ответ ученика'), el('div', 'uts-prose', answerText(question))); section.append(answer);
        const state = result.state === 'active' ? 'active' : question.score === null ? 'pending' : question.was_unanswered ? 'skipped' : question.score === 1 ? 'correct' : 'incorrect';
        const labels = {active: 'В процессе', pending: 'Ожидает проверки', skipped: 'Пропущено', correct: 'Правильно', incorrect: 'Неправильно'};
        section.append(el('span', `uts-status uts-${state}`, labels[state]), el('span', 'uts-muted', question.score === null ? ' Баллы ещё не выставлены' : ` ${question.score} / 1 балл`)); body.append(section);
      }); $('dialog-feedback').textContent = '';
    } catch (error) { if (!failClosed(error) && generation === dialogGeneration && dialog.open) $('dialog-feedback').textContent = error.message; }
  }
  function showGrant(test, source) {
    const generation = openDialog('Добавить попытки', source), body = $('dialog-body');
    body.append(el('p', '', `${root.dataset.studentName} · ${test.title}`), el('p', 'uts-muted', 'Только для этого ученика и теста. Предыдущие результаты сохранятся.'));
    const form = el('form', 'uts-grant-form'), label = el('label', '', 'Количество'), input = el('input');
    input.type = 'number'; input.min = '1'; input.step = '1'; input.required = true; input.value = String(grants.get(test.id)?.body.amount || 1);
    input.disabled = grants.has(test.id); label.append(input);
    const submit = el('button', 'uts-action', grants.has(test.id) ? 'Повторить выдачу' : 'Добавить'); submit.type = 'submit';
    form.append(label, submit); body.append(form);
    if (grants.has(test.id)) $('dialog-feedback').textContent = 'Результат предыдущей выдачи не подтверждён. Повтор отправит тот же запрос.';
    let sending = false;
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (sending) return;
      let operation = grants.get(test.id);
      if (!operation) {
        const amount = Number(input.value);
        if (!Number.isSafeInteger(amount) || amount < 1) { $('dialog-feedback').textContent = 'Введите положительное целое число, представимое в браузере.'; return; }
        operation = {body: {amount, request_key: crypto.randomUUID()}}; grants.set(test.id, operation);
      }
      sending = true; input.disabled = true; submit.disabled = true; $('dialog-feedback').textContent = 'Выдача попыток…';
      try {
        const result = await api(`${base}/${test.id}/grants`, operation.body, result =>
          Number.isInteger(result.grant_id) && result.grant_id > 0 && (result.remaining_attempts === null
            || (Number.isInteger(result.remaining_attempts) && result.remaining_attempts >= 0)));
        grants.delete(test.id);
        test.remaining_attempts = result.remaining_attempts; render();
        if (generation === dialogGeneration && dialog.open) dialog.close();
        $('feedback').textContent = `Дополнительные попытки добавлены. Доступно: ${remaining(result.remaining_attempts)}.`;
      } catch (error) {
        if (error.status && error.status < 500) grants.delete(test.id);
        if (!failClosed(error) && generation === dialogGeneration && dialog.open) $('dialog-feedback').textContent = error.message + (grants.has(test.id) ? ' Повторите выдачу тем же запросом.' : '');
      } finally {
        sending = false;
        if (generation === dialogGeneration) { input.disabled = grants.has(test.id); submit.disabled = false; submit.textContent = grants.has(test.id) ? 'Повторить выдачу' : 'Добавить'; }
      }
    }); input.focus();
  }
  dialog.querySelector('.uts-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    // A queued close event may arrive after this dialog has already reopened.
    // Its old session must not invalidate the new grant form or steal focus.
    if (dialog.open) return;
    dialogGeneration++;
    if (opener?.isConnected) opener.focus({preventScroll: true});
    else if (opener?.dataset.grant) root.querySelector(`[data-grant="${opener.dataset.grant}"]`)?.focus({preventScroll: true});
  });
  let outsideStart = false;
  const outside = event => { const rect = dialog.getBoundingClientRect(); return event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom; };
  dialog.addEventListener('pointerdown', event => { outsideStart = event.target === dialog && outside(event); });
  dialog.addEventListener('click', event => { if (outsideStart && event.target === dialog && outside(event)) dialog.close(); });
  $('reload').addEventListener('click', load);
  document.addEventListener('user-stats-tab', event => { if (event.detail?.index === 4 && !loaded) load(); });
  window.addEventListener('focus', () => { if (loaded && !document.getElementById('panel-4').hidden && !dialog.open) { histories.clear(); load(); } });
  if (!document.getElementById('panel-4').hidden) load();
})();
