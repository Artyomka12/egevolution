/* ===== CodeMirror editor setup ===== */
const editor = CodeMirror.fromTextArea(document.getElementById('code-input'), {
  mode: 'python',
  lineNumbers: true,
  indentUnit: 4,
  tabSize: 4,
  indentWithTabs: false,
  lineWrapping: false,
  autofocus: true,
  extraKeys: {
    Tab: (cm) => cm.replaceSelection('    '),
  },
});
editor.setSize('100%', '280px');

/* ===== Minimal Python syntax highlighter for code-display panel ===== */
const PY_KEYWORDS = /\b(for|while|if|elif|else|in|not|and|or|is|break|continue|pass|return|def|True|False|None)\b/g;
const PY_BUILTINS = /\b(print|range|len|int|float|str|bool|abs|min|max|sum|round|sorted|list|tuple|dict|set|enumerate|zip|type)\b(?=\s*\()/g;
const PY_STRING  = /("""[\s\S]*?"""|'''[\s\S]*?'''|"[^"]*"|'[^']*')/g;
const PY_NUMBER  = /\b(\d+\.?\d*)\b/g;
const PY_COMMENT = /(#.*)/g;

function highlightPython(raw) {
  const esc = raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Process in order: comments, strings, keywords, builtins, numbers
  // Use placeholder approach to avoid re-processing injected HTML
  const parts = [];
  let last = 0;
  const tokens = [];

  // Collect all token positions
  const collect = (re, cls) => {
    let m;
    re.lastIndex = 0;
    while ((m = re.exec(esc)) !== null) {
      tokens.push({ start: m.index, end: m.index + m[0].length, text: m[0], cls });
    }
  };

  collect(PY_COMMENT, 'py-cmt');
  collect(PY_STRING,  'py-str');
  collect(PY_KEYWORDS,'py-kw');
  collect(PY_BUILTINS,'py-fn');
  collect(PY_NUMBER,  'py-num');

  // Sort by start position, resolve overlaps (first wins)
  tokens.sort((a, b) => a.start - b.start);
  const used = [];
  const filtered = [];
  for (const t of tokens) {
    if (used.some(u => t.start < u.end && t.end > u.start)) continue;
    filtered.push(t);
    used.push(t);
  }
  filtered.sort((a, b) => a.start - b.start);

  let result = '';
  let pos = 0;
  for (const t of filtered) {
    result += esc.slice(pos, t.start);
    result += `<span class="${t.cls}">${t.text}</span>`;
    pos = t.end;
  }
  result += esc.slice(pos);
  return result;
}

/* ===== Build code display from source code ===== */
function buildCodeDisplay(code) {
  const display = document.getElementById('code-display');
  display.innerHTML = '';
  const lines = code.split('\n');
  lines.forEach((line, idx) => {
    const row = document.createElement('div');
    row.className = 'code-line';
    row.dataset.line = idx + 1;

    const numEl = document.createElement('span');
    numEl.className = 'line-num';
    numEl.textContent = idx + 1;

    const content = document.createElement('span');
    content.className = 'line-content';
    content.innerHTML = highlightPython(line) || '&nbsp;';

    row.appendChild(numEl);
    row.appendChild(content);
    display.appendChild(row);
  });
}

function setActiveLine(lineNum) {
  document.querySelectorAll('.code-line').forEach(el => el.classList.remove('active'));
  const target = document.querySelector(`.code-line[data-line="${lineNum}"]`);
  if (target) {
    target.classList.add('active');
    target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  return target;
}

/* ===== Example codes ===== */
const EXAMPLES = {
  factorial: `def factorial(n):
    if n <= 1:
        return 1
    return n * factorial(n - 1)

print(factorial(5))`,

  fibonacci: `def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)

print(fib(6))`,

  bubble: `def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr

result = bubble_sort([5, 3, 8, 1, 9, 2])
print(result)`,

  digits: `n = 123456
digit_sum = 0
count = 0
while n > 0:
    digit = n % 10
    digit_sum += digit
    count += 1
    n = n // 10

print(digit_sum)
print(count)`,
};

document.getElementById('example-select').addEventListener('change', function () {
  const code = EXAMPLES[this.value];
  if (code) {
    editor.setValue(code);
    editor.setCursor({ line: 0, ch: 0 });
  }
  this.value = '';
});

/* ===== Visualization mode ===== */
let vizMode = 'classic';

document.querySelectorAll('.bs-mode-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.bs-mode-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    vizMode = btn.dataset.mode;
  });
});

/* ===== Run button & view switching ===== */
const runBtn     = document.getElementById('run-btn');
const backBtn    = document.getElementById('back-btn');
const bsBackBtn  = document.getElementById('bs-back-btn');
const inputView  = document.getElementById('input-view');
const vizView    = document.getElementById('viz-view');
const bsView     = document.getElementById('bs-view');
const errorBanner= document.getElementById('error-banner');
const errorText  = document.getElementById('error-text');
const truncWarn  = document.getElementById('truncated-warn');

function showError(msg) {
  errorText.textContent = msg;
  errorBanner.classList.remove('hidden');
}
function clearError() {
  errorBanner.classList.add('hidden');
}

runBtn.addEventListener('click', async () => {
  clearError();
  const code = editor.getValue().trim();
  if (!code) { showError('Введите код'); return; }

  runBtn.classList.add('btn-loading');
  runBtn.textContent = 'Запуск...';

  // Block Scheme builds a static flowchart — no backend needed for that part
  if (vizMode === 'blockscheme') {
    try {
      inputView.classList.remove('active');
      bsView.classList.add('active');
      startBlockScheme(code);
      loadBlockSchemeTrace(code);   // background: powers highlighting/playback (3.3+)
    } catch (err) {
      showError('Ошибка построения схемы: ' + err.message);
    } finally {
      runBtn.classList.remove('btn-loading');
      runBtn.innerHTML = '<span class="btn-icon">▶</span> Запустить';
    }
    return;
  }

  try {
    const result = await traceCode(code);

    if (result.error && result.steps.length === 0) {
      showError(result.error.message);
      return;
    }

    inputView.classList.remove('active');

    // ── Classic mode ──
    buildCodeDisplay(code);
    if (result.truncated) {
      truncWarn.textContent = '⚠ Код содержит более 600 шагов — показаны первые 600';
      truncWarn.classList.remove('hidden');
    } else if (result.error) {
      const lineInfo = result.error.line ? ` (строка ${result.error.line})` : '';
      truncWarn.textContent = `⚠ Ошибка выполнения${lineInfo}: ${result.error.message}`;
      truncWarn.classList.remove('hidden');
    } else {
      truncWarn.classList.add('hidden');
    }
    vizView.classList.add('active');
    document.getElementById('viz-title').textContent = detectTitle(code);
    startAnimation(result.steps, result.error);

  } catch (err) {
    showError('Не удалось подключиться к серверу. Убедитесь, что бэкенд запущен.');
  } finally {
    runBtn.classList.remove('btn-loading');
    runBtn.innerHTML = '<span class="btn-icon">▶</span> Запустить';
  }
});

backBtn.addEventListener('click', () => {
  stopAnimation();
  vizView.classList.remove('active');
  inputView.classList.add('active');
});

bsBackBtn.addEventListener('click', () => {
  bsView.classList.remove('active');
  inputView.classList.add('active');
});

/* ===== Keyboard navigation ===== */
document.addEventListener('keydown', (e) => {
  if (!vizView.classList.contains('active')) return;
  if (e.key === 'ArrowRight') stepNext();
  if (e.key === 'ArrowLeft')  stepPrev();
  if (e.key === ' ') { e.preventDefault(); togglePlay(); }
});

/* ===== Block Scheme keyboard navigation (step cursor + playback — step 3.5) ===== */
document.addEventListener('keydown', (e) => {
  if (!bsView.classList.contains('active')) return;
  if (e.key === 'ArrowRight') { bsStopAutoplay(); bsStepNext(); }
  if (e.key === 'ArrowLeft')  { bsStopAutoplay(); bsStepPrev(); }
  if (e.key === ' ') { e.preventDefault(); bsTogglePlay(); }
});

/* ===== Detect code title ===== */
function detectTitle(code) {
  if (/\bfor\b/.test(code) && /\bwhile\b/.test(code)) return 'Циклы for и while';
  if (/\bfor\b/.test(code))   return 'Цикл for';
  if (/\bwhile\b/.test(code)) return 'Цикл while';
  if (/\bif\b/.test(code))    return 'Условный оператор if';
  if (/\bdef\b/.test(code))   return 'Функции';
  return 'Визуализация кода';
}

/* ===== Theme toggle ===== */
const themeToggle = document.getElementById('theme-toggle');

function applyTheme(dark) {
  document.documentElement.classList.toggle('dark', dark);
  themeToggle.textContent = dark ? '☀️' : '🌙';
}

// Restore saved preference
applyTheme(localStorage.getItem('theme') === 'dark');

themeToggle.addEventListener('click', () => {
  const isDark = document.documentElement.classList.contains('dark');
  localStorage.setItem('theme', isDark ? 'light' : 'dark');
  applyTheme(!isDark);
});
