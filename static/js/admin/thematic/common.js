'use strict';
window.Thematic = {
  async api(path, method = 'GET', body) {
    const response = await fetch(path, {method, credentials: 'same-origin', headers: {
      'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
    }, body: body === undefined ? undefined : JSON.stringify(body)});
    let data;
    try { data = await response.json(); } catch { throw new Error('Не удалось получить ответ. Обновите страницу.'); }
    if (!response.ok) throw new Error(data.error || 'Операция не выполнена');
    return data;
  },
  key() { return crypto.randomUUID(); },
  node(tag, text, className) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (className) el.className = className;
    return el;
  },
  feedback(text, error = false) {
    const el = document.getElementById('feedback');
    el.textContent = text; el.className = 'feedback ' + (error ? 'error' : 'success');
  },
  states: {draft: 'Черновик', published: 'Опубликован', hidden: 'Скрыт'}
};
