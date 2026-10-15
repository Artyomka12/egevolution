'use strict';
window.ThematicStudent = {
  async api(url, method = 'GET', data) {
    let response;
    try {
      response = await fetch(url, {method, credentials: 'same-origin', headers: {
        'Content-Type': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
      }, body: data === undefined ? undefined : JSON.stringify(data)});
    } catch { throw Object.assign(new Error('Нет связи с сервером. Ответ остаётся на этой странице.'), {network: true}); }
    let body;
    try { body = await response.json(); } catch { throw Object.assign(new Error('Не удалось прочитать ответ сервера. Повторите запрос.'), {network: true}); }
    if (!response.ok) throw Object.assign(new Error(body.error || 'Запрос не выполнен'), {status: response.status, ...body});
    return body;
  },
  node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; },
  empty(value) { return value == null || (Array.isArray(value) ? value.every(ThematicStudent.empty) : !String(value).trim()); },
  time(ms) { const s = Math.floor(ms / 1000); return [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60].map(n => String(n).padStart(2, '0')).join(':'); },
  condition(q) {
    const {node} = ThematicStudent, box = node('div', undefined, 'task-description'), used = new Set();
    function image(m) { const img = node('img', undefined, 'task-image'); img.src = m.url; img.alt = m.alt_text || ''; img.loading = 'lazy'; return img; }
    q.description_html.forEach((html, index) => {
      const paragraph = node('div', undefined, 'condition-paragraph'); paragraph.innerHTML = html; box.append(paragraph);
      q.materials.forEach((m, i) => { if (m.role !== 'attachment' && m.after_paragraph === index) { box.append(image(m)); used.add(i); } });
    });
    q.materials.forEach((m, i) => {
      if (m.role === 'attachment') { const a = node('a', 'Скачать вложение', 'file-link'); a.href = m.url; const p = node('div', undefined, 'file-download'); p.append(a); box.append(p); }
      else if (!used.has(i)) box.append(image(m));
    });
    box.querySelectorAll('table').forEach(table => { const p = node('div', undefined, 'table-scroll'); table.replaceWith(p); p.append(table); });
    return box;
  }
};
