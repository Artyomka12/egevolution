'use strict';
(() => {
  const {$, node, api, time, percent, answerText} = TestsUI;
  const id = Number($('tests-result').dataset.attemptId), expanded = new Set();
  let result = JSON.parse($('tests-bootstrap').textContent), loading = false, denied = false;
  $('tests-bootstrap').remove();
  const labels = {correct: 'Правильно', incorrect: 'Неправильно', skipped: 'Пропущено', pending: 'Ожидает проверки'};
  function answerBlock(title, text, cls = '') { const block = node('section', `answer-block ${cls}`); block.append(node('h4', '', title), node('p', 'full-answer', text)); return block; }
  function render() {
    const s = result.summary, final = result.state === 'graded' && s.is_final;
    $('verification-status').className = `result-status ${final ? 'status-neutral' : 'status-pending'}`; $('verification-status').textContent = final ? 'Проверка завершена' : 'Ожидает ручной проверки';
    $('score-label').textContent = final ? 'Итоговый результат' : 'Предварительный результат'; $('total-score').textContent = `${s.earned} из ${final ? s.total : s.checked_count} баллов`;
    $('score-note').textContent = final ? `${percent(s.percentage)} от максимального балла` : 'Только за проверенные вопросы. Итог будет доступен после проверки.';
    $('review-progress').textContent = `${s.checked_count} из ${s.total} проверено`; $('review-note').textContent = final ? 'Проверка всех вопросов завершена.' : `Ожидают преподавателя: ${s.pending_count}.`;
    $('elapsed').textContent = time(result.elapsed_seconds); $('attempt-note').textContent = `Лимит — ${time(result.time_limit_seconds)} · Попытка №${result.attempt_no}`;
    const body = $('result-rows'), focused = document.activeElement?.dataset.questionId; body.replaceChildren();
    result.questions.forEach((q, i) => {
      const row = node('tr', 'summary-row'), toggle = node('button', 'row-toggle'); toggle.type = 'button'; toggle.dataset.questionId = String(q.id); toggle.setAttribute('aria-expanded', String(expanded.has(q.id))); toggle.setAttribute('aria-controls', `detail-${q.id}`); toggle.setAttribute('aria-label', `Подробности вопроса ${i + 1}`);
      const arrow = node('span', 'chevron', '›'); arrow.setAttribute('aria-hidden', 'true'); toggle.append(node('span', '', i + 1), arrow);
      const number = node('td'); number.append(toggle); const answer = node('td'); answer.append(node('span', 'answer-preview', answerText(q, q.answer)));
      const status = node('td'); status.append(node('span', `result-status status-${q.status}`, labels[q.status])); const points = node('td', 'score-cell', q.score === null ? '—' : `${q.score} / 1`); if (q.score === null) points.setAttribute('aria-label', 'Баллы ещё не выставлены'); row.append(number, answer, status, points);
      const detail = node('tr', 'detail-row'); detail.id = `detail-${q.id}`; detail.hidden = !expanded.has(q.id); row.classList.toggle('is-open', !detail.hidden);
      const cell = node('td'); cell.colSpan = 4; const content = node('div', 'question-detail'); content.append(node('p', 'detail-type', `Вопрос ${i + 1}`), node('h3', '', q.title || `Вопрос ${i + 1}`), node('p', 'detail-condition', q.prompt_text));
      if (q.code_text) content.append(node('pre', '', q.code_text));
      if (q.media) { const img = node('img', 'detail-image'); img.src = q.media.url; img.alt = q.media.alt_text || ''; content.append(img); }
      if (q.options.length) { const options = node('ol', 'detail-options'); q.options.forEach(o => options.append(node('li', '', o.text))); content.append(options); }
      content.append(answerBlock('Ответ ученика', answerText(q, q.answer)));
      const review = node('section', 'answer-block'); review.append(node('h4', '', 'Результат проверки'), node('span', `result-status status-${q.status}`, labels[q.status]), node('p', 'review-text', q.score === null ? 'Ответ передан преподавателю. Баллы ещё не выставлены.' : `Получено баллов: ${q.score} из 1.`)); content.append(review);
      if (final && q.reference) {
        const reference = q.reference.option_ids ? answerText(q, q.reference.option_ids) : q.reference.accepted_answers.join('\n'); content.append(answerBlock('Правильный ответ', reference, 'reference-answer'));
      } else content.append(node('p', 'hidden-answer-note', !final && q.reference_pending ? 'Правильный ответ будет доступен после завершения проверки.' : 'Правильный ответ не отображается.'));
      cell.append(content); detail.append(cell);
      row.onclick = () => { detail.hidden = !detail.hidden; if (detail.hidden) expanded.delete(q.id); else expanded.add(q.id); toggle.setAttribute('aria-expanded', String(!detail.hidden)); row.classList.toggle('is-open', !detail.hidden); };
      body.append(row, detail);
    });
    if (focused) body.querySelector(`[data-question-id="${Number(focused)}"]`)?.focus({preventScroll: true});
  }
  async function refresh() {
    if (loading || denied || document.hidden) return;
    loading = true;
    try { result = await api(`/api/tests/attempts/${id}/result`); render(); $('page-status').textContent = ''; $('retry').hidden = true; }
    catch (e) { $('page-status').textContent = e.message; $('retry').hidden = false; if ([401, 403, 404].includes(e.status)) { denied = true; $('result-content').replaceChildren(); $('retry').hidden = true; result = null; } }
    finally { loading = false; }
  }
  $('retry').onclick = refresh; render();
  setInterval(() => { if (result?.state === 'pending_review') refresh(); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();
