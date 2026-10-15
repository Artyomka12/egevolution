/* Explicit draft saving and immutable publication; no client-side grading. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => {
    const node = document.createElement(tag); if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text; return node;
  };
  const labels = {single_choice: 'Один правильный ответ', multiple_choice: 'Несколько правильных ответов', free_text: 'Свободный ответ'};
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  const root = $('test-editor'), requestKeys = new Map(), images = new Map();
  let testId = root.dataset.testId ? Number(root.dataset.testId) : null;
  let revision = null, selected = null, deleting = null, changed = false, busy = false;
  let pendingPublication = null;
  let pendingUpload = null;
  let documentValue = {title: '', description: '', time_limit_seconds: null, attempt_limit: null, show_correct_answers: false, questions: []};
  const current = () => selected;
  const button = (text, cls, action) => {
    const b = el('button', cls, text); b.type = 'button'; b.addEventListener('click', action); return b;
  };
  function dirty() { changed = true; $('save-state').textContent = 'Есть несохранённые изменения'; $('notice').hidden = true; }
  function notice(message, error = false, fields = {}) {
    const box = $('notice'); box.replaceChildren(); box.hidden = false; box.className = 'notice' + (error ? ' error' : '');
    box.append(el('strong', '', message));
    if (Object.keys(fields).length) {
      const list = el('ul');
      for (const [field, text] of Object.entries(fields)) {
        const question = field.match(/^questions\.(\d+)/);
        list.append(el('li', '', (question ? `Вопрос ${Number(question[1]) + 1}: ` : '') + text));
      }
      box.append(list);
    }
    box.focus();
  }
  async function api(url, method = 'GET', payload) {
    const options = {method, credentials: 'same-origin', cache: 'no-store', headers: {'X-CSRFToken': csrf}};
    let operation;
    const multipart = typeof FormData !== 'undefined' && payload instanceof FormData;
    if (multipart) options.body = payload;
    else if (payload !== undefined) {
      operation = method + url + JSON.stringify(payload);
      if (!requestKeys.has(operation)) requestKeys.set(operation, crypto.randomUUID());
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify({...payload, request_key: requestKeys.get(operation)});
    }
    const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
    const positive = value => Number.isInteger(value) && value > 0;
    const valid = data => {
      if (!object(data)) return false;
      if (/\/media$/.test(url)) return positive(data.media_id) && typeof data.url === 'string' &&
        typeof data.alt_text === 'string' && positive(data.width) && positive(data.height);
      if (/\/publish$/.test(url)) return positive(data.test_id) && positive(data.version_id) &&
        positive(data.revision) && positive(data.draft_revision) && data.publication_state === 'published';
      if (url === '/api/admin/tests' || /\/draft$/.test(url)) {
        const doc = data.document;
        return positive(data.test_id) && positive(data.revision) && object(doc) &&
          typeof doc.title === 'string' && typeof doc.description === 'string' &&
          (doc.time_limit_seconds === null || positive(doc.time_limit_seconds)) &&
          (doc.attempt_limit === null || positive(doc.attempt_limit)) && typeof doc.show_correct_answers === 'boolean' &&
          Array.isArray(doc.questions) && doc.questions.every(q => object(q) && typeof q.title === 'string' &&
            typeof q.prompt_text === 'string' && (q.code_text === null || typeof q.code_text === 'string') &&
            ['single_choice', 'multiple_choice', 'free_text'].includes(q.question_type) &&
            ['auto', 'manual'].includes(q.grading_mode) && Array.isArray(q.options) &&
            q.options.every(o => object(o) && typeof o.text === 'string' && typeof o.is_correct === 'boolean') &&
            Array.isArray(q.accepted_answers) && q.accepted_answers.every(a => typeof a === 'string')) &&
          Array.isArray(data.media) && data.media.every(item => object(item) && positive(item.id) && typeof item.alt_text === 'string');
      }
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
        if (attempt < 2) { await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1))); continue; }
        throw new Error('Результат операции не подтверждён. Изменения остаются на странице. Повторите сохранение.');
      } finally { clearTimeout(timer); }
      if (response.status === 503 && attempt < 2) { await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1))); continue; }
      if (!response.ok) {
        if (response.status < 500) requestKeys.delete(operation);
        const error = new Error(data.error?.message || 'Не удалось выполнить операцию.');
        error.code = data.error?.code; error.status = response.status; error.fields = data.field_errors; throw error;
      }
      requestKeys.delete(operation); return data;
    }
  }
  function renderSettings() {
    $('test-title').value = documentValue.title; $('test-description').value = documentValue.description;
    $('time-limit').value = documentValue.time_limit_seconds == null ? '' : documentValue.time_limit_seconds / 60;
    $('attempt-limit').value = documentValue.attempt_limit ?? '';
    $('unlimited').checked = documentValue.attempt_limit == null;
    $('attempt-limit').disabled = $('unlimited').checked;
    $('show-answers').checked = documentValue.show_correct_answers;
  }
  function settings() {
    documentValue.title = $('test-title').value; documentValue.description = $('test-description').value;
    documentValue.time_limit_seconds = $('time-limit').value === '' ? null : Number($('time-limit').value) * 60;
    documentValue.attempt_limit = $('unlimited').checked || $('attempt-limit').value === '' ? null : Number($('attempt-limit').value);
    documentValue.show_correct_answers = $('show-answers').checked;
    if (!$('unlimited').checked && $('attempt-limit').value === '') {
      throw new Error('Укажите количество попыток или выберите «Без ограничений».');
    }
  }
  async function ensureTest() {
    if (testId) return;
    const data = await api('/api/admin/tests', 'POST', {});
    testId = data.test_id; revision = data.revision; root.dataset.testId = testId;
    history.replaceState(null, '', `/admin/tests/${testId}/edit`);
  }
  function rememberImages(media) { for (const image of media || []) images.set(image.id || image.media_id, image); }
  async function load() {
    if (!testId) { renderSettings(); render(); $('save-state').textContent = 'Новый тест'; return; }
    const data = await api(`/api/admin/tests/${testId}/draft`);
    documentValue = data.document; revision = data.revision; rememberImages(data.media);
    selected = documentValue.questions[0] || null; changed = false;
    renderSettings(); render(); $('save-state').textContent = 'Черновик сохранён';
  }
  async function locked(action) {
    if (busy) return;
    busy = true;
    const controls = [...document.querySelectorAll('input,textarea,select,button')].map(node => [node, node.disabled]);
    controls.forEach(([node]) => { node.disabled = true; });
    try { await action(); }
    catch (error) {
      if (error.code === 'REVISION_CONFLICT') {
        notice('Черновик изменён в другой вкладке. Ваш ввод сохранён на этой странице. Скопируйте нужные изменения перед загрузкой новой версии.', true);
        const reload = button('Загрузить сохранённую версию', 'action', () => {
          if (confirm('Заменить несохранённые изменения на этой странице сохранённой версией?')) locked(load);
        }); $('notice').append(reload);
      } else notice(error.message, true, error.fields);
      if (pendingUpload) {
        $('notice').append(button('Повторить загрузку изображения', 'action', () => locked(completeUpload)));
      }
    } finally {
      busy = false; controls.forEach(([node, disabled]) => { node.disabled = disabled; });
      $('attempt-limit').disabled = $('unlimited').checked;
    }
  }
  function save(publish) {
    return locked(async () => {
      if (pendingUpload) await completeUpload();
      if (pendingPublication !== null) {
        const previous = await api(`/api/admin/tests/${testId}/publish`, 'POST', {expected_revision: pendingPublication});
        revision = previous.draft_revision; pendingPublication = null;
        if (publish && !changed) {
          renderSettings(); render(); $('save-state').textContent = 'Опубликован';
          notice('Публикация подтверждена.'); return;
        }
      }
      settings(); await ensureTest();
      const saved = await api(`/api/admin/tests/${testId}/draft`, 'PUT', {document: documentValue, expected_revision: revision});
      revision = saved.revision;
      // The server's LF-normalized document becomes the next editable draft.
      const selectedIndex = documentValue.questions.indexOf(selected);
      documentValue = saved.document; selected = documentValue.questions[selectedIndex] || documentValue.questions[0] || null;
      rememberImages(saved.media); changed = false;
      $('save-state').textContent = 'Черновик сохранён';
      if (publish) {
        pendingPublication = revision;
        try {
          const published = await api(`/api/admin/tests/${testId}/publish`, 'POST', {expected_revision: revision});
          revision = published.draft_revision; pendingPublication = null;
        } catch (error) {
          if (error.status && error.status < 500) pendingPublication = null;
          throw error;
        }
      }
      renderSettings(); render();
      $('save-state').textContent = publish ? 'Опубликован' : 'Черновик сохранён';
      notice(publish ? 'Новая версия опубликована. Начатые попытки сохраняют прежнюю версию.' : 'Черновик сохранён.');
    });
  }
  function moveQuestion(question, delta) {
    const items = documentValue.questions, i = items.indexOf(question), j = i + delta;
    if (j < 0 || j >= items.length) return;
    [items[i], items[j]] = [items[j], items[i]]; dirty(); render();
    $('question-list').children[j].querySelector('.select-question').focus();
  }
  function renderList() {
    $('question-count').textContent = documentValue.questions.length; $('question-list').replaceChildren();
    documentValue.questions.forEach((q, i) => {
      const li = el('li', 'question-item' + (q === selected ? ' selected' : ''));
      const select = button('', 'select-question', () => { selected = q; render(); });
      select.setAttribute('aria-current', String(q === selected));
      select.append(el('strong', '', `${i + 1}. ${q.title || 'Новый вопрос'}`), el('small', '', labels[q.question_type]));
      const tools = el('div', 'question-tools');
      const up = button('↑', 'order-button', () => moveQuestion(q, -1));
      const down = button('↓', 'order-button', () => moveQuestion(q, 1));
      up.disabled = i === 0; down.disabled = i === documentValue.questions.length - 1;
      up.setAttribute('aria-label', `Вопрос ${i + 1} выше`); down.setAttribute('aria-label', `Вопрос ${i + 1} ниже`);
      const remove = button('Удалить', 'btn-delete', () => {
        deleting = q; $('delete-description').textContent = `«${q.title || 'Новый вопрос'}». Вопрос будет удалён из черновика.`;
        $('delete-dialog').showModal();
      });
      tools.append(up, down, remove); li.append(select, tools); $('question-list').append(li);
    });
  }
  function renderImage(q) {
    const image = images.get(q.media_id);
    $('image-preview').hidden = !q.media_id; $('remove-image').hidden = !q.media_id;
    if (q.media_id) {
      $('image-preview').src = `/api/admin/tests/${testId}/media/${q.media_id}`;
      $('image-preview').alt = image?.alt_text || 'Изображение в условии вопроса';
    } else $('image-preview').removeAttribute('src');
  }
  function moveItem(items, i, delta) {
    const j = i + delta; if (j < 0 || j >= items.length) return;
    [items[i], items[j]] = [items[j], items[i]]; dirty(); renderAnswers();
  }
  function itemTools(items, i, label) {
    const tools = el('div', 'option-actions');
    const up = button('↑', 'order-button', () => moveItem(items, i, -1));
    const down = button('↓', 'order-button', () => moveItem(items, i, 1));
    up.disabled = i === 0; down.disabled = i === items.length - 1;
    up.setAttribute('aria-label', `${label} ${i + 1} выше`); down.setAttribute('aria-label', `${label} ${i + 1} ниже`);
    const remove = button('×', 'btn-delete remove-option', () => { items.splice(i, 1); dirty(); renderAnswers(); });
    remove.setAttribute('aria-label', `Удалить: ${label.toLowerCase()} ${i + 1}`); tools.append(up, down, remove); return tools;
  }
  function renderAnswers() {
    const q = current(); if (!q) return;
    const free = q.question_type === 'free_text'; $('choice-section').hidden = free; $('free-section').hidden = !free;
    $('choice-hint').textContent = q.question_type === 'single_choice' ? 'Отметьте ровно один правильный вариант. Варианты содержат только текст.' : 'Отметьте правильные варианты. 1 балл — только за полностью совпавший набор; любое отличие — 0 баллов.';
    $('option-list').replaceChildren();
    q.options.forEach((option, i) => {
      const row = el('div', 'option-row'), check = el('input');
      check.type = q.question_type === 'single_choice' ? 'radio' : 'checkbox'; check.name = 'correct-option';
      check.checked = option.is_correct; check.setAttribute('aria-label', `Вариант ${i + 1} правильный`);
      check.addEventListener('change', () => {
        if (q.question_type === 'single_choice') q.options.forEach(item => { item.is_correct = false; });
        option.is_correct = check.checked; dirty();
      });
      const input = el('input'); input.type = 'text'; input.value = option.text;
      input.setAttribute('aria-label', `Текст варианта ${i + 1}`);
      input.addEventListener('input', () => { option.text = input.value; dirty(); });
      row.append(check, input, itemTools(q.options, i, 'Вариант')); $('option-list').append(row);
    });
    $('free-format').value = q.free_input_mode || 'singleline'; $('grading').value = q.grading_mode;
    $('accepted-section').hidden = q.grading_mode === 'manual'; $('manual-hint').hidden = q.grading_mode !== 'manual';
    $('accepted-list').replaceChildren();
    q.accepted_answers.forEach((answer, i) => {
      const row = el('div', 'option-row accepted-row');
      const input = el(q.free_input_mode === 'multiline' || answer.includes('\n') ? 'textarea' : 'input', 'exact-answer');
      if (input.tagName === 'INPUT') input.type = 'text'; else input.rows = 2;
      input.value = answer; input.spellcheck = false; input.setAttribute('aria-label', `Допустимая строка ${i + 1}`);
      input.addEventListener('input', () => { q.accepted_answers[i] = input.value; dirty(); });
      row.append(input, itemTools(q.accepted_answers, i, 'Допустимая строка')); $('accepted-list').append(row);
    });
  }
  function render() {
    renderList(); const q = current(); $('editor-fields').hidden = !q; $('editor-empty').hidden = !!q;
    $('editor-title').textContent = q ? `Вопрос ${documentValue.questions.indexOf(q) + 1}` : 'Редактор вопроса';
    if (!q) return;
    $('question-title').value = q.title; $('question-type').value = q.question_type;
    $('question-text').value = q.prompt_text; $('question-code').value = q.code_text || '';
    $('question-image').value = ''; $('image-alt').value = ''; $('image-message').textContent = '';
    renderImage(q); renderAnswers();
  }
  for (const [id, property] of [['question-title', 'title'], ['question-text', 'prompt_text'], ['question-code', 'code_text']]) {
    $(id).addEventListener('input', () => { if (!current()) return; current()[property] = $(id).value; dirty(); if (property === 'title') renderList(); });
  }
  $('question-type').addEventListener('change', () => {
    const q = current(); q.question_type = $('question-type').value;
    if (q.question_type === 'free_text') { q.options = []; q.free_input_mode = 'singleline'; q.accepted_answers = ['']; }
    else {
      q.free_input_mode = null; q.grading_mode = 'auto'; q.accepted_answers = [];
      if (!q.options.length) q.options = [{text: '', is_correct: false}, {text: '', is_correct: false}];
      if (q.question_type === 'single_choice') { let found = false; q.options.forEach(o => { o.is_correct = o.is_correct && !found; if (o.is_correct) found = true; }); }
    }
    dirty(); renderList(); renderAnswers();
  });
  $('free-format').addEventListener('change', () => { current().free_input_mode = $('free-format').value; dirty(); renderAnswers(); });
  $('grading').addEventListener('change', () => {
    const q = current(); q.grading_mode = $('grading').value;
    if (q.grading_mode === 'manual') q.accepted_answers = q.accepted_answers.filter(value => value.length > 0);
    else if (!q.accepted_answers.length) q.accepted_answers.push('');
    dirty(); renderAnswers();
  });
  $('add-option').addEventListener('click', () => { current().options.push({text: '', is_correct: false}); dirty(); renderAnswers(); $('option-list').lastElementChild.querySelector('input[type=text]').focus(); });
  $('add-accepted').addEventListener('click', () => { current().accepted_answers.push(''); dirty(); renderAnswers(); $('accepted-list').lastElementChild.querySelector('.exact-answer').focus(); });
  $('add-question').addEventListener('click', () => {
    selected = {title: '', prompt_text: '', code_text: null, question_type: 'single_choice', free_input_mode: null,
      grading_mode: 'auto', media_id: null, options: [{text: '', is_correct: false}, {text: '', is_correct: false}], accepted_answers: []};
    documentValue.questions.push(selected); dirty(); render(); $('question-title').focus();
  });
  const dialog = $('delete-dialog');
  $('confirm-delete').addEventListener('click', () => {
    const i = documentValue.questions.indexOf(deleting); if (i < 0) return;
    documentValue.questions.splice(i, 1); if (selected === deleting) selected = documentValue.questions[Math.min(i, documentValue.questions.length - 1)] || null;
    dialog.close(); dirty(); render(); $('add-question').focus();
  });
  for (const b of [dialog.querySelector('.close'), $('cancel-delete')]) b.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { deleting = null; });
  let outsideStart = false;
  const outside = event => { const r = dialog.getBoundingClientRect(); return event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom; };
  dialog.addEventListener('pointerdown', event => { outsideStart = event.target === dialog && outside(event); });
  dialog.addEventListener('click', event => { if (outsideStart && event.target === dialog && outside(event)) dialog.close(); });
  async function completeUpload() {
    const pending = pendingUpload;
    if (!pending) return;
    let data;
    try { data = await api(pending.url, 'POST', pending.form); }
    catch (error) {
      if (error.status && error.status < 500) pendingUpload = null;
      throw error;
    }
    pendingUpload = null;
    // The question may have been removed while an earlier request was unknown.
    if (!documentValue.questions.includes(pending.question)) return;
    images.set(data.media_id, data); pending.question.media_id = data.media_id; dirty();
    if (current() === pending.question) {
      renderImage(pending.question);
      $('image-message').textContent = 'Изображение загружено. Сохраните черновик, чтобы закрепить его в вопросе.';
    }
  }
  $('question-image').addEventListener('change', () => locked(async () => {
    if (pendingUpload) {
      throw new Error('Предыдущая загрузка ещё не подтверждена. Повторите её перед выбором нового изображения.');
    }
    const q = current(), file = $('question-image').files[0]; if (!q || !file) return;
    if (!['image/png', 'image/jpeg', 'image/gif'].includes(file.type) || file.size > 5 * 1024 * 1024) throw new Error('Выберите PNG, JPEG или GIF размером до 5 МБ.');
    await ensureTest();
    const form = new FormData(); form.append('file', file); form.append('alt_text', $('image-alt').value); form.append('request_key', crypto.randomUUID());
    pendingUpload = {question: q, form, url: `/api/admin/tests/${testId}/media`};
    await completeUpload();
  }));
  $('remove-image').addEventListener('click', () => { current().media_id = null; $('question-image').value = ''; $('image-message').textContent = ''; dirty(); renderImage(current()); });
  for (const id of ['test-title', 'test-description', 'time-limit', 'attempt-limit', 'show-answers']) $(id).addEventListener('input', dirty);
  $('unlimited').addEventListener('change', () => { $('attempt-limit').disabled = $('unlimited').checked; dirty(); });
  $('save-draft').addEventListener('click', () => save(false)); $('publish').addEventListener('click', () => save(true));
  $('settings-toggle').addEventListener('click', () => {
    const b = $('settings-toggle'), content = $('settings-content'), expanded = b.getAttribute('aria-expanded') !== 'true';
    b.setAttribute('aria-expanded', String(expanded)); const label = expanded ? 'Свернуть настройки теста' : 'Раскрыть настройки теста';
    b.setAttribute('aria-label', label); b.title = label; content.classList.toggle('is-collapsed', !expanded);
    content.inert = !expanded; content.setAttribute('aria-hidden', String(!expanded));
  });
  const saveBar = document.querySelector('.save-bar');
  new ResizeObserver(() => document.documentElement.style.setProperty('--save-bar-offset', `${Math.ceil(saveBar.getBoundingClientRect().height) + 16}px`)).observe(saveBar);
  window.addEventListener('beforeunload', event => { if (changed || busy || pendingUpload || pendingPublication !== null) { event.preventDefault(); event.returnValue = ''; } });
  locked(load);
})();
