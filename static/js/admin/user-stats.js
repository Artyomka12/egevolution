(() => {
  'use strict';
  const avatar = document.querySelector('.user-stats-avatar img');
  if (avatar) {
    avatar.addEventListener('error', () => { avatar.hidden = true; });
    if (avatar.complete && !avatar.naturalWidth) avatar.hidden = true;
  }
  const strip = document.querySelector('.user-stats-tabs');
  if (!strip) return;
  const tabs = Array.from(strip.querySelectorAll('[role="tab"]'));
  function select(index, focus) {
    tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden = i !== index;
    });
    const tab = tabs[index];
    if (focus) tab.focus({preventScroll: true});
    const rect = tab.getBoundingClientRect(), bounds = strip.getBoundingClientRect();
    if (rect.left < bounds.left) strip.scrollLeft -= bounds.left - rect.left + 5;
    else if (rect.right > bounds.right) strip.scrollLeft += rect.right - bounds.right + 5;
    document.dispatchEvent(new CustomEvent('user-stats-tab', {detail: {index}}));
  }
  strip.addEventListener('click', event => {
    const index = tabs.indexOf(event.target.closest('[role="tab"]'));
    if (index >= 0) select(index, false);
  });
  strip.addEventListener('keydown', event => {
    const index = tabs.indexOf(event.target);
    if (index < 0) return;
    const keys = {ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index + tabs.length - 1) % tabs.length, Home: 0, End: tabs.length - 1};
    if (Object.hasOwn(keys, event.key)) {
      event.preventDefault();
      select(keys[event.key], true);
    }
  });
  window.addEventListener('resize', () => {
    select(tabs.findIndex(tab => tab.getAttribute('aria-selected') === 'true'), false);
  });
})();
