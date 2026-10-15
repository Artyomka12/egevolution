'use strict';
(() => {
  const {api, node, feedback, states} = Thematic, base = '/api/admin/thematic-variants';
  let catalog, busy = false;
  const deleteKeys = new Map();
  async function load() { catalog = await api(base); render(); }
  async function action(work) {
    if (busy) return;
    busy = true; render();
    try { await work(); await load(); feedback('Изменения сохранены'); }
    catch (error) { feedback(error.message, true); }
    finally { busy = false; render(); }
  }
  function button(text, work, disabled = false) {
    const b = node('button', text, 'small-btn'); b.disabled = busy || disabled; b.onclick = () => action(work); return b;
  }
  function render() {
    const target = document.getElementById('catalog'); target.replaceChildren();
    if (!catalog) return;
    if (!catalog.variants.length) { target.append(node('p', 'Тематических вариантов пока нет', 'empty')); return; }
    catalog.variants.forEach((v, index) => {
      const row = node('article', undefined, 'task-card');
      row.append(node('h3', v.document.title || 'Без названия'), node('p', v.document.description, 'muted'),
        node('p', `${v.document.items.length} задач в черновике · ${states[v.state]}${v.version_no ? ' · версия ' + v.version_no : ''}`, 'muted'));
      const actions = node('div', undefined, 'row-actions');
      const edit = node('a', 'Редактировать', 'back'); edit.href = `/admin/thematic-variants/${v.id}/edit`; actions.append(edit);
      const move = direction => {
        const ids = catalog.variants.map(x => x.id);
        [ids[index], ids[index + direction]] = [ids[index + direction], ids[index]];
        return api(base + '/order', 'PUT', {expected_revision: catalog.revision, ids});
      };
      actions.append(button('↑', () => move(-1), index === 0), button('↓', () => move(1), index === catalog.variants.length - 1));
      if (v.version_no) actions.append(button(v.state === 'hidden' ? 'Показать действующую версию' : 'Скрыть', () => api(`${base}/${v.id}/visibility`, 'PATCH', {
        state: v.state === 'hidden' ? 'published' : 'hidden', expected_revision: v.variant_revision
      })));
      actions.append(button('Удалить', async () => {
        if (!window.confirm('Удалить вариант? Все активные попытки будут завершены по сохранённым ответам. История и опубликованные материалы сохранятся. Восстановление не предусмотрено.')) return;
        const signature = `${v.id}:${v.variant_revision}`;
        if (!deleteKeys.has(signature)) deleteKeys.set(signature, Thematic.key());
        await api(`${base}/${v.id}`, 'DELETE', {confirmed: true, expected_revision: v.variant_revision, request_key: deleteKeys.get(signature)});
      }));
      row.append(actions); target.append(row);
    });
  }
  load().then(() => feedback('Публикация черновиков — в конструкторе')).catch(error => feedback(error.message, true));
})();
