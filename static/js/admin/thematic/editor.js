'use strict';
(() => {
  const {api, node, key, feedback, states} = Thematic, $ = id => document.getElementById(id);
  const base = '/api/admin/thematic-variants';
  let ident = Number($('editor-root').dataset.variantId) || null;
  let state = {revision: 0, variant_revision: 1, state: 'draft', version_no: null};
  let selected = [], tasks = [], number = 1, busy = false, dirty = false, requestNo = 0;
  let createRequest = null, publishRequest = null;
  const cache = new Map(), sourceKey = t => `${t.source_task_num}:${t.source_task_id}`;

  function changed() { dirty = true; publishRequest = null; feedback('Есть несохранённые изменения'); }
  function documentValue() { return {title: $('variant-title').value, description: $('variant-description').value, items: selected.map(t => ({...t}))}; }
  function applyState(value) {
    state = value; ident = value.id;
    selected = value.document.items;
    $('status').textContent = states[value.state] + (value.version_no ? ` · версия ${value.version_no}` : '');
    $('version-note').textContent = value.version_no ? `Вы редактируете черновик опубликованного варианта. Изменения не влияют на действующую версию ${value.version_no} до повторной публикации.` : 'Сохранение черновика не публикует вариант для учеников.';
    dirty = false;
  }
  function image(material) {
    const img = node('img'); img.src = material.url; img.alt = material.alt; img.loading = 'lazy'; return img;
  }
  function condition(task) {
    const box = node('div', undefined, 'condition');
    const placed = new Set();
    (task.description_html || []).forEach((html, index) => {
      const p = node('div', undefined, 'condition-paragraph');
      // Only server-sanitized allowlisted markup. Inputs/titles use textContent.
      p.innerHTML = html; box.append(p);
      (task.materials || []).forEach((m, i) => {
        if (m.role === 'condition' && m.after_paragraph === index) { box.append(image(m)); placed.add(i); }
      });
    });
    (task.materials || []).forEach((m, i) => {
      if (m.role === 'condition' && !placed.has(i)) box.append(image(m));
      if (m.role === 'attachment') { const a = node('a', 'Скачать ' + m.name, 'back'); a.href = m.url; box.append(a); }
    });
    box.querySelectorAll('table').forEach(table => { const scroll = node('div', undefined, 'table-scroll'); table.replaceWith(scroll); scroll.append(table); });
    return box;
  }
  function showTask(task) {
    if (!task) return;
    $('task-dialog-title').textContent = task.title;
    $('task-dialog-body').replaceChildren(condition(task)); $('task-dialog').showModal();
  }
  function render() {
    $('numbers').replaceChildren();
    for (let n = 1; n <= 27; n++) {
      const b = node('button', String(n), 'number' + (selected.some(s => s.source_task_num === n) ? ' has-selected' : ''));
      b.setAttribute('aria-pressed', String(n === number)); b.onclick = () => loadBank(n); $('numbers').append(b);
    }
    $('topic-title').textContent = 'Задание №' + number;
    $('bank-count').textContent = `Задач в банке: ${tasks.length}`;
    $('bank').replaceChildren();
    tasks.forEach(task => {
      const added = selected.some(s => sourceKey(s) === sourceKey(task));
      const card = node('article', undefined, 'task-card' + (added ? ' added' : ''));
      const top = node('div', undefined, 'task-top'), heading = node('div');
      heading.append(node('span', `ЕГЭ №${task.source_task_num} · ID ${task.source_task_id}`, 'task-id'), node('h4', task.title));
      const add = node('button', added ? 'Добавлено' : 'Добавить', 'add'); add.disabled = added || busy;
      add.onclick = () => { selected.push({source_task_num: task.source_task_num, source_task_id: task.source_task_id, source_hash: task.source_hash}); changed(); render(); };
      top.append(heading, add);
      const details = node('details'); details.append(node('summary', 'Полное условие'));
      details.ontoggle = () => { if (details.open && details.children.length === 1) details.append(condition(task)); };
      card.append(top, details); $('bank').append(card);
    });
    $('selected-count').textContent = selected.length;
    $('selected').replaceChildren();
    if (!selected.length) $('selected').append(node('li', 'Добавьте задачи из банка слева', 'empty'));
    selected.forEach((ref, index) => {
      const task = cache.get(sourceKey(ref));
      const row = node('li', undefined, 'selected-item'), main = node('div', undefined, 'selected-main');
      const title = node('button', task?.title || `Задание №${ref.source_task_num}`, 'selected-title'); title.onclick = () => showTask(task);
      main.append(node('span', index + 1 + '.', 'position'), title);
      row.append(main, node('p', `ЕГЭ №${ref.source_task_num} · ID ${ref.source_task_id}`, 'selected-meta'));
      const actions = node('div', undefined, 'row-actions');
      [-1, 1, 0].forEach(direction => {
        const b = node('button', direction === -1 ? '↑' : direction === 1 ? '↓' : 'Удалить', direction ? 'small-btn' : 'small-btn remove');
        b.disabled = busy || (direction === -1 && index === 0) || (direction === 1 && index === selected.length - 1);
        b.setAttribute('aria-label', direction ? `Переместить задачу ${index + 1} ${direction < 0 ? 'вверх' : 'вниз'}` : `Удалить задачу ${index + 1}`);
        b.onclick = () => { if (direction) [selected[index], selected[index + direction]] = [selected[index + direction], selected[index]]; else selected.splice(index, 1); changed(); render(); };
        actions.append(b);
      });
      row.append(actions); $('selected').append(row);
    });
    ['save', 'publish', 'confirm-publish', 'variant-title', 'variant-description'].forEach(id => $(id).disabled = busy);
  }
  async function loadBank(n) {
    const serial = ++requestNo; number = n; tasks = []; render();
    $('bank-count').textContent = 'Загрузка…';
    try {
      const data = await api(`/api/admin/thematic-bank/${n}`);
      data.tasks.forEach(t => cache.set(sourceKey(t), t));
      if (serial !== requestNo) return;
      tasks = data.tasks; render();
    } catch (error) { if (serial === requestNo) { $('bank-count').textContent = 'Банк недоступен'; feedback(error.message, true); } }
  }
  async function save() {
    const document = documentValue();
    let data;
    if (ident) data = await api(`${base}/${ident}/draft`, 'PUT', {document, expected_revision: state.revision});
    else {
      const encoded = JSON.stringify(document);
      if (!createRequest || createRequest.encoded !== encoded) createRequest = {encoded, body: {document, request_key: key()}};
      data = await api(base, 'POST', createRequest.body);
      history.replaceState(null, '', `/admin/thematic-variants/${data.id}/edit`);
      createRequest = null;
    }
    applyState(data); feedback('Черновик сохранён. Действующая публикация не изменена.');
  }
  async function action(work) {
    if (busy) return;
    busy = true; render();
    try { await work(); } catch (error) { feedback(error.message, true); }
    finally { busy = false; render(); }
  }
  $('save').onclick = () => action(save);
  $('publish').onclick = () => {
    if (!$('variant-title').value.trim() || !selected.length) { feedback('Укажите название и добавьте хотя бы одну задачу', true); return; }
    $('publish-summary').textContent = `${$('variant-title').value}\nЗадач: ${selected.length}. По 1 баллу за каждую.`;
    $('publish-dialog').showModal();
  };
  $('confirm-publish').onclick = () => action(async () => {
    $('publish-dialog').close();
    if (!publishRequest) {
      if (dirty || !ident) await save();
      publishRequest = {expected_revision: state.revision, variant_revision: state.variant_revision, request_key: key()};
    }
    const result = await api(`${base}/${ident}/publish`, 'POST', publishRequest);
    applyState(result.draft); publishRequest = null; feedback(`Опубликована версия ${state.version_no}`);
  });
  ['variant-title', 'variant-description'].forEach(id => $(id).addEventListener('input', changed));
  document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => button.closest('dialog').close());
  document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog && (event.clientX < dialog.getBoundingClientRect().left || event.clientX > dialog.getBoundingClientRect().right || event.clientY < dialog.getBoundingClientRect().top || event.clientY > dialog.getBoundingClientRect().bottom)) dialog.close(); }));
  window.addEventListener('beforeunload', event => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } });
  new ResizeObserver(() => document.documentElement.style.setProperty('--sidebar-top', ($('action-bar').offsetHeight + 36) + 'px')).observe($('action-bar'));
  action(async () => {
    if (ident) {
      const data = await api(`${base}/${ident}/draft`);
      data.tasks.forEach(t => cache.set(sourceKey(t), t)); applyState(data);
      $('variant-title').value = data.document.title; $('variant-description').value = data.document.description;
    }
    feedback('Черновик и публикация сохраняются отдельно'); await loadBank(1);
  });
})();
