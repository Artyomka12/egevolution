/* Individual administrative grading. Answers and references are never edited. */
(() => {
  'use strict';
  const root = document.querySelector('.tests-review');
  if (!root) return;
  const $ = id => document.getElementById('review-' + id);
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const endpoint = `/api/admin/tests/attempts/${root.dataset.attemptId}`;
  const labels = {active: 'В процессе', pending: 'Ожидает проверки', skipped: 'Пропущено', correct: 'Правильно', incorrect: 'Неправильно'};
  let data = null, selected = 0, busy = false, pendingGrade = null, reading = false;
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const percent = value => value.toLocaleString('ru-RU', {maximumFractionDigits: 1}) + '%';
  const date = value => value ? new Date(value).toLocaleString('ru-RU', {timeZone: 'Europe/Moscow'}) : '—';
  function state(question) {
    return data.state === 'active' ? 'active' : question.score === null ? 'pending' : question.was_unanswered ? 'skipped' : question.score === 1 ? 'correct' : 'incorrect';
  }
  function announce(message) { $('feedback').textContent = message; }
  async function api(url, body, validate = () => true) {
    const options = {method: body ? 'PUT' : 'GET', credentials: 'same-origin', cache: 'no-store', headers: {'X-CSRFToken': csrf}};
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
  function validGradeResponse(result, operation) {
    const summary = result.summary;
    if (result.attempt_id !== Number(root.dataset.attemptId) || result.question_id !== operation.question_id
        || ![0, 1].includes(result.score) || !['manual', 'override'].includes(result.grading_source)
        || !Number.isInteger(result.grade_revision) || result.grade_revision < 1
        || !Number.isInteger(result.result_revision) || result.result_revision < 1
        || !['pending_review', 'graded'].includes(result.state) || !summary) return false;
    if (!['earned', 'total', 'checked_count', 'pending_count'].every(key => Number.isInteger(summary[key]) && summary[key] >= 0)
        || summary.total < 1 || summary.earned > summary.checked_count
        || summary.checked_count + summary.pending_count !== summary.total
        || result.pending_count !== summary.pending_count) return false;
    return summary.pending_count === 0
      ? result.state === 'graded' && summary.is_final === true && summary.final_score === summary.earned
        && Number.isFinite(summary.percentage) && summary.percentage >= 0 && summary.percentage <= 100
      : result.state === 'pending_review' && summary.is_final === false && summary.final_score === null && summary.percentage === null;
  }
  function deny(error) {
    if (![401, 403, 404].includes(error.status)) return false;
    data = null; pendingGrade = null;
    $('summary').hidden = true; $('workspace').hidden = true; $('retry').hidden = true;
    $('detail').replaceChildren(); $('question-list').replaceChildren();
    announce(error.message); return true;
  }
  function answerText(question) {
    if (question.answer === null || question.answer === '' || (Array.isArray(question.answer) && !question.answer.length)) return 'Ответ не дан';
    if (question.question_type === 'free_text') return question.answer;
    const ids = Array.isArray(question.answer) ? question.answer : [question.answer];
    return question.options.filter(option => ids.includes(option.id)).map(option => option.text).join('\n');
  }
  function answerBlock(title, text) {
    const block = el('div'); block.append(el('h3', '', title), el('div', 'answer prose', text)); return block;
  }
  function renderSummary() {
    $('summary').hidden = false; $('workspace').hidden = false;
    $('student').textContent = data.student.name || data.student.username;
    $('test').textContent = data.title;
    $('meta').textContent = `Попытка № ${data.attempt_no} · Версия ${data.version_no} · ${date(data.submitted_at || data.started_at)}`;
    const summary = data.summary;
    $('result-label').textContent = !summary ? 'Прохождение продолжается' : summary.is_final ? 'Окончательный результат' : 'Предварительный результат';
    $('result-value').textContent = !summary ? 'В процессе' : summary.is_final ? `${summary.earned} из ${summary.total} баллов · ${percent(summary.percentage)}` : `${summary.earned} из ${summary.checked_count} проверенных`;
    $('counts').textContent = summary ? `Проверено: ${summary.checked_count} из ${summary.total} · Ожидают: ${summary.pending_count}` : 'Проверка станет доступна после отправки.';
    $('next').disabled = !data.can_grade || !summary?.pending_count || busy;
    $('next-hint').textContent = !summary ? 'Попытка ещё не отправлена' : summary.pending_count ? `Осталось проверить: ${summary.pending_count}` : 'Все вопросы проверены';
  }
  function renderList() {
    $('question-list').replaceChildren();
    data.questions.forEach((question, index) => {
      const item = el('li'), button = el('button', 'question-button');
      button.type = 'button'; button.dataset.question = question.id;
      button.setAttribute('aria-current', String(index === selected));
      button.append(el('strong', '', `${question.position}. ${question.title}`), el('span', 'status ' + state(question), labels[state(question)]));
      button.addEventListener('click', () => { selected = index; render(); $('question-list').querySelector(`[data-question="${question.id}"]`).focus({preventScroll: true}); });
      item.append(button); $('question-list').append(item);
    });
  }
  function renderDetail() {
    const question = data.questions[selected], detail = $('detail'); detail.replaceChildren();
    if (!question) return;
    const top = el('div', 'detail-top'); top.append(el('h2', '', `${question.position}. ${question.title}`), el('span', 'points-badge', 'Максимум: 1 балл'));
    const prompt = el('div', 'content-block'); prompt.append(el('h3', '', 'Исходное условие'), el('div', 'prose', question.prompt_text));
    if (question.code_text) { const pre = el('pre'); pre.append(el('code', '', question.code_text)); prompt.append(pre); }
    if (question.media) { const image = el('img', 'diagram'); image.src = question.media.url; image.alt = question.media.alt_text || ''; prompt.append(image); }
    if (question.options.length) { const list = el('ol', 'original-options'); question.options.forEach(option => list.append(el('li', '', option.text))); prompt.append(list); }
    const answers = el('div', 'content-block'); answers.append(answerBlock('Ответ ученика', answerText(question)));
    if (question.reference) {
      answers.classList.add('answer-comparison');
      const reference = question.reference.accepted_answers || question.options.filter(option => question.reference.option_ids.includes(option.id)).map(option => option.text);
      answers.append(answerBlock(question.reference.accepted_answers?.length > 1 ? 'Допустимые ответы' : 'Правильный ответ', reference.join('\n')));
    }
    const grading = el('div', 'grading'), meta = el('div', 'grading-meta'), method = el('div'), grade = el('div');
    method.append(el('h3', '', 'Способ проверки'), el('div', 'muted', (question.grading_mode === 'manual' ? 'Ручная' : 'Автоматическая') + (question.grading_source === 'override' ? ' · оценка исправлена вручную' : '')));
    grade.append(el('h3', '', 'Текущая оценка'), el('span', 'status ' + state(question), labels[state(question)]), el('span', 'muted', question.score === null ? ' Не выставлена' : ` ${question.score} / 1 балл`));
    meta.append(method, grade); grading.append(meta);
    if (data.can_grade) {
      grading.append(el('h3', '', question.grading_mode === 'manual' ? 'Выставить оценку' : 'Исправить оценку вручную'));
      const actions = el('div', 'grade-actions');
      for (const score of [1, 0]) {
        const button = el('button', score ? 'action action-publish' : 'btn-delete', score ? 'Правильно · 1 балл' : 'Неправильно · 0 баллов');
        button.type = 'button'; button.dataset.grade = score; button.setAttribute('aria-pressed', String(question.score === score));
        button.disabled = busy || !!pendingGrade || (question.was_unanswered && score === 1);
        button.addEventListener('click', () => {
          if (busy || pendingGrade) return;
          pendingGrade = {question_id: question.id, body: {score, expected_grade_revision: question.grade_revision, request_key: crypto.randomUUID()}};
          saveGrade();
        }); actions.append(button);
      }
      grading.append(actions);
      if (question.was_unanswered) grading.append(el('p', 'muted review-skip-note', 'Пропущенный вопрос всегда получает 0 баллов.'));
    } else grading.append(el('p', 'muted', 'Оценивание доступно только после отправки попытки.'));
    detail.append(top, prompt, answers, grading);
  }
  function render() { if (data) { renderSummary(); renderList(); renderDetail(); } $('retry').hidden = !pendingGrade || busy; }
  async function load(initial = false) {
    if (reading) return;
    reading = true;
    try {
      const fresh = await api(endpoint);
      if (data && fresh.result_revision < data.result_revision) return;
      const current = data?.questions[selected]?.id; data = fresh;
      const index = data.questions.findIndex(question => question.id === current);
      selected = index >= 0 ? index : Math.max(0, data.questions.findIndex(question => question.score === null));
      render(); if (initial) announce('');
    } catch (error) { if (!deny(error)) announce(error.message); }
    finally { reading = false; }
  }
  async function saveGrade() {
    if (!pendingGrade || busy) return;
    const operation = pendingGrade; busy = true; render(); announce('Сохранение оценки…');
    try {
      const result = await api(`${endpoint}/grades/${operation.question_id}`, operation.body, result => validGradeResponse(result, operation));
      pendingGrade = null;
      const question = data.questions.find(item => item.id === result.question_id);
      Object.assign(question, {score: result.score, grade_revision: result.grade_revision, grading_source: result.grading_source});
      Object.assign(data, {summary: result.summary, result_revision: result.result_revision, state: result.state});
      announce('Оценка сохранена.');
    } catch (error) {
      if (!deny(error)) {
        if (error.status && error.status < 500) { pendingGrade = null; if (error.status === 409) await load(); }
        announce(error.message + (pendingGrade ? ' Повторное сохранение безопасно: будет отправлен тот же запрос.' : ''));
      }
    } finally {
      busy = false; render();
      if (!pendingGrade && data) $('detail').querySelector(`[data-grade="${operation.body.score}"]:not(:disabled)`)?.focus({preventScroll: true});
    }
  }
  $('retry').addEventListener('click', saveGrade);
  $('next').addEventListener('click', () => {
    if (!data?.can_grade) return;
    for (let offset = 1; offset <= data.questions.length; offset++) {
      const index = (selected + offset) % data.questions.length;
      if (data.questions[index].score === null) { selected = index; render(); $('detail').querySelector('h2')?.scrollIntoView({block: 'nearest'}); break; }
    }
  });
  window.addEventListener('focus', () => { if (!busy && !pendingGrade) load(); });
  load(true);
})();
