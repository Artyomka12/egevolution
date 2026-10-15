'use strict';
document.querySelectorAll('.detail-toggle').forEach(button => {
  button.onclick = () => {
    const row = document.getElementById(button.getAttribute('aria-controls'));
    row.hidden = !row.hidden;
    button.setAttribute('aria-expanded', String(!row.hidden));
    button.textContent = row.hidden ? 'Условие' : 'Скрыть';
  };
});
document.querySelectorAll('.task-description table').forEach(table => {
  const wrapper = document.createElement('div'); wrapper.className = 'table-scroll';
  table.replaceWith(wrapper); wrapper.append(table);
});
