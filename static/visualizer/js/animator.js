/* ===== Scope block registry ===== */
const scopeBlocks  = new Map(); // scopeId -> { el, x, y }
const scopeMeta    = new Map(); // scopeId -> { parentId, name, depth }
const nextX        = {};        // depth -> fallback column counter
const BLOCK_W      = 200;
const BLOCK_GAP_X  = 28;
const BLOCK_GAP_Y  = 165;
const BLOCK_PAD_Y  = 16;

/* ===== Precomputed centered tree layout ===== */
let precomputedPositions = new Map(); // scopeId -> { x, y }
let pendingRootX = -1; // centroid x of top-level calls; consumed by expandCanvas to scroll

function precomputeTreeLayout(steps) {
  precomputedPositions = new Map();
  const childrenOf = new Map(); // pid -> [sid, ...]
  const depthOf    = new Map(); // sid -> depth

  for (const step of steps) {
    if (step.event !== 'call') continue;
    const sid = step.scope_id;
    const pid = step.parent_id;
    depthOf.set(sid, step.depth);
    if (!childrenOf.has(pid)) childrenOf.set(pid, []);
    childrenOf.get(pid).push(sid);
    if (!childrenOf.has(sid)) childrenOf.set(sid, []);
  }

  let leafIdx = 0;

  function assignX(sid) {
    const kids  = childrenOf.get(sid) || [];
    const depth = depthOf.get(sid) || 0;
    // depth+1 so row 0 = global block (y=16), row 1 = depth-0 functions (y=181), etc.
    const y = (depth + 1) * BLOCK_GAP_Y + BLOCK_PAD_Y;

    if (kids.length === 0) {
      const x = leafIdx++ * (BLOCK_W + BLOCK_GAP_X);
      precomputedPositions.set(sid, { x, y });
      return x;
    }

    const childXs = kids.map(k => assignX(k));
    const cx = Math.round((childXs[0] + childXs[childXs.length - 1]) / 2);
    precomputedPositions.set(sid, { x: cx, y });
    return cx;
  }

  // Process all top-level function calls (children of global scope 0)
  for (const sid of (childrenOf.get(0) || [])) {
    assignX(sid);
  }

  // Compute centroid of top-level calls for scroll-to-root (applied in expandCanvas)
  const topLevel = childrenOf.get(0) || [];
  if (topLevel.length > 0 && precomputedPositions.size > 0) {
    const topXs = topLevel.map(sid => (precomputedPositions.get(sid) || { x: 0 }).x);
    pendingRootX = Math.round(topXs.reduce((a, b) => a + b, 0) / topXs.length);
  }
}

function getScopeBlock(scopeId) {
  const entry = scopeBlocks.get(scopeId);
  return entry ? entry.el : null;
}

/* ===== Animator state ===== */
let steps          = [];
let currentStep    = 0;
let isPlaying      = false;
let playTimer   = null;
let prevVars    = {};
let prevOutput  = [];

/* ===== Timing constants ===== */
const BALL_DELAY    = 200;
const BALL_FLY_MS   = 480;
const NO_BALL_PAUSE = 250;

/* ===== DOM refs ===== */
const consoleBody  = document.getElementById('console-body');
const scopeCanvas  = document.getElementById('scope-canvas');
const scopeArrows  = document.getElementById('scope-arrows');
const stepCurrent  = document.getElementById('step-current');
const stepTotal    = document.getElementById('step-total');
const ctrlFirst    = document.getElementById('ctrl-first');
const ctrlPrev     = document.getElementById('ctrl-prev');
const ctrlPlay     = document.getElementById('ctrl-play');
const ctrlNext     = document.getElementById('ctrl-next');
const ctrlLast     = document.getElementById('ctrl-last');
const speedSelect  = document.getElementById('speed-select');
const ballLayer    = document.getElementById('ball-layer');
const consoleAnchor = document.getElementById('console-anchor');

/* ===== Init ===== */
function startAnimation(stepsData, errorData) {
  pendingRootX = -1;           // clear any pending scroll from previous run
  steps = stepsData;
  currentStep = stepsData.length;
  prevVars = {};
  prevOutput = [];
  isPlaying = false;

  precomputeTreeLayout(stepsData);   // build centered tree positions upfront
  stepTotal.textContent = stepsData.length;
  clearAll();
  updateControls();
  togglePlay();
}

function stopAnimation() {
  clearTimeout(playTimer);
  isPlaying = false;
  updatePlayBtn();
}

/* ===== Scope block management ===== */
function createScopeBlock(scopeId, parentId, name, args, depth) {
  // Use precomputed centered tree position; fall back to greedy if missing
  let x, y;
  if (precomputedPositions.has(scopeId)) {
    ({ x, y } = precomputedPositions.get(scopeId));
  } else {
    if (nextX[depth] === undefined) nextX[depth] = 0;
    x = nextX[depth]++ * (BLOCK_W + BLOCK_GAP_X);
    y = (depth + 1) * BLOCK_GAP_Y + BLOCK_PAD_Y;
  }

  const el = document.createElement('div');
  el.className = 'scope-block active';
  el.dataset.scopeId = scopeId;

  const header = document.createElement('div');
  header.className = 'scope-block-header';
  header.textContent = formatScopeTitle(name, args);

  const vars = document.createElement('div');
  vars.className = 'scope-block-vars';
  vars.innerHTML = '<span class="empty-hint">Переменных пока нет</span>';

  el.appendChild(header);
  el.appendChild(vars);
  el.style.left  = x + 'px';
  el.style.top   = y + 'px';
  el.style.width = BLOCK_W + 'px';
  scopeCanvas.appendChild(el);

  gsap.from(el, { opacity: 0, scale: 0.85, duration: 0.25, ease: 'back.out(1.4)' });

  scopeBlocks.set(scopeId, { el, x, y });
  scopeMeta.set(scopeId, { parentId, name, depth });

  expandCanvas();
  drawArrow(parentId, scopeId);

  // Mark parent as waiting
  if (parentId !== 0) {
    const parentEntry = scopeBlocks.get(parentId);
    if (parentEntry) parentEntry.el.className = 'scope-block waiting';
  }
}

function markScopeReturned(scopeId, retVal) {
  const entry = scopeBlocks.get(scopeId);
  if (!entry) return;
  const el = entry.el;
  el.className = 'scope-block done';

  // Add return value section
  let retSection = el.querySelector('.scope-block-return');
  if (!retSection) {
    retSection = document.createElement('div');
    retSection.className = 'scope-block-return highlight';
    el.appendChild(retSection);
  }
  retSection.textContent = 'ret: ' + formatValue(retVal);
  retSection.classList.add('highlight');

  // Re-activate parent
  const meta = scopeMeta.get(scopeId);
  if (meta && meta.parentId !== 0) {
    const parentEntry = scopeBlocks.get(meta.parentId);
    if (parentEntry) parentEntry.el.className = 'scope-block active';
  }

  updateArrowReturn(scopeId);
  expandCanvas();
  redrawAllArrows();  // ret: section added — redraw from new bottom
}

function setActiveScopeBlock(scopeId) {
  // Deactivate all except done ones
  for (const [sid, entry] of scopeBlocks) {
    if (!entry.el.classList.contains('done')) {
      entry.el.className = sid === scopeId ? 'scope-block active' : 'scope-block';
    }
  }
}

function renderScopeVars(scopeId, vars, changedKeys) {
  const entry = scopeBlocks.get(scopeId);
  if (!entry) return;
  const container = entry.el.querySelector('.scope-block-vars');
  if (!container) return;

  const keys = Object.keys(vars);
  if (keys.length === 0) {
    container.innerHTML = '<span class="empty-hint">Переменных пока нет</span>';
    return;
  }
  container.innerHTML = '';
  for (const k of keys) {
    const card = document.createElement('div');
    card.className = 'var-card' + (changedKeys.includes(k) ? ' changed' : '');
    card.dataset.varName = k;

    const nameEl = document.createElement('div');
    nameEl.className = 'var-name';
    nameEl.textContent = k;

    const valEl = document.createElement('div');
    const displayVal = formatValue(vars[k]);
    valEl.className = 'var-value' + (displayVal.length > 8 ? ' long' : '');
    valEl.textContent = displayVal;

    card.appendChild(nameEl);
    card.appendChild(valEl);
    container.appendChild(card);
  }
  expandCanvas();
  redrawAllArrows();  // block grew — redraw arrows from its true bottom
}

function formatScopeTitle(name, args) {
  if (!args || Object.keys(args).length === 0) return name + '()';
  const argStr = Object.entries(args).map(([k, v]) => `${k}=${formatValue(v)}`).join(', ');
  const full = `${name}(${argStr})`;
  return full.length > 26 ? full.slice(0, 24) + '…)' : full;
}

/* ===== SVG Arrows ===== */
function drawArrow(parentId, childId) {
  const parentEntry = scopeBlocks.get(parentId);
  const childEntry  = scopeBlocks.get(childId);

  // For parentId=0 (global), no arrow
  if (!parentEntry || !childEntry) return;

  const arrowId = `arrow-${parentId}-${childId}`;
  let g = scopeArrows.querySelector(`#${arrowId}`);
  if (!g) {
    g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.id = arrowId;
    scopeArrows.appendChild(g);
  }
  g.innerHTML = '';

  const p  = parentEntry;
  const c  = childEntry;
  const px = p.x + BLOCK_W / 2;
  const py = p.y + p.el.offsetHeight;  // true bottom of parent block (dynamic height)
  const cx = c.x + BLOCK_W / 2;
  const cy = c.y;                       // top of child block

  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  // Cubic Bezier: control points pull vertically so the curve exits/enters straight down/up
  path.setAttribute('d', `M${px},${py} C${px},${py + 40} ${cx},${cy - 40} ${cx},${cy}`);
  path.setAttribute('stroke', '#4F7EF7');
  path.setAttribute('stroke-width', '1.5');
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke-dasharray', '4,3');
  path.setAttribute('marker-end', 'url(#arrowhead)');

  g.appendChild(path);
  ensureArrowDefs();
}

function updateArrowReturn(childId) {
  const meta = scopeMeta.get(childId);
  if (!meta) return;
  const arrowId = `arrow-${meta.parentId}-${childId}`;
  const g = scopeArrows.querySelector(`#${arrowId}`);
  if (!g) return;
  const path = g.querySelector('path');
  if (path) {
    path.setAttribute('stroke', '#059669');
    path.setAttribute('stroke-dasharray', 'none');
  }
}

function ensureArrowDefs() {
  if (scopeArrows.querySelector('defs')) return;
  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
  defs.innerHTML = `
    <marker id="arrowhead" markerWidth="8" markerHeight="6"
            refX="6" refY="3" orient="auto">
      <polygon points="0 0, 8 3, 0 6" fill="#4F7EF7"/>
    </marker>`;
  scopeArrows.insertBefore(defs, scopeArrows.firstChild);
}

function redrawAllArrows() {
  for (const [childId, meta] of scopeMeta) {
    drawArrow(meta.parentId, childId);
  }
}

function expandCanvas() {
  let maxRight = 0, maxBottom = 0;
  for (const [, entry] of scopeBlocks) {
    const r = entry.x + entry.el.offsetWidth  + 24;
    const b = entry.y + entry.el.offsetHeight + 24;
    if (r > maxRight)  maxRight  = r;
    if (b > maxBottom) maxBottom = b;
  }
  if (maxRight  > 0) scopeCanvas.style.minWidth  = maxRight  + 'px';
  if (maxBottom > 0) scopeCanvas.style.minHeight = maxBottom + 'px';
  scopeArrows.style.width  = Math.max(maxRight,  scopeCanvas.offsetWidth)  + 'px';
  scopeArrows.style.height = Math.max(maxBottom, scopeCanvas.offsetHeight) + 'px';

  // Scroll to root centroid the first time the canvas is wide enough to actually scroll
  if (pendingRootX >= 0 && maxRight > scopeCanvas.clientWidth + 50) {
    scopeCanvas.scrollLeft = Math.max(0, pendingRootX - Math.round(scopeCanvas.clientWidth / 3));
    pendingRootX = -1;
  }
}

/* ===== Global scope block ===== */
let globalBlock = null;

function ensureGlobalBlock() {
  if (globalBlock) return;
  const el = document.createElement('div');
  el.className = 'scope-block active';
  el.dataset.scopeId = '0';

  const header = document.createElement('div');
  header.className = 'scope-block-header';
  header.textContent = 'Глобальный';

  const vars = document.createElement('div');
  vars.className = 'scope-block-vars';
  vars.innerHTML = '<span class="empty-hint">Переменных пока нет</span>';

  el.appendChild(header);
  el.appendChild(vars);
  el.style.left  = '0px';
  el.style.top   = BLOCK_PAD_Y + 'px';
  el.style.width = BLOCK_W + 'px';
  scopeCanvas.appendChild(el);
  scopeBlocks.set(0, { el, x: 0, y: BLOCK_PAD_Y });
  globalBlock = el;
}

/* ===== Render step ===== */
function renderStep(index, onDone) {
  if (index < 0 || index >= steps.length) return;

  const step = steps[index];
  currentStep = index;
  stepCurrent.textContent = index + 1;

  const event = step.event || 'line';

  if (event === 'call') {
    createScopeBlock(step.scope_id, step.parent_id, step.scope_name, step.args, step.depth);
    if (onDone) onDone();
    return;
  }

  if (event === 'return') {
    markScopeReturned(step.scope_id, step.return_value);
    if (onDone) onDone();
    return;
  }

  // line event
  setActiveLine(step.line);
  const scopeId  = step.scope_id !== undefined ? step.scope_id : 0;
  ensureGlobalBlock();
  setActiveScopeBlock(scopeId);

  const newVars   = step.variables || {};
  const newOutput = step.output    || [];

  const changedVars = [];
  for (const k of Object.keys(newVars)) {
    if (JSON.stringify(newVars[k]) !== JSON.stringify(prevVars[k])) changedVars.push(k);
  }
  const newLines = newOutput.slice(prevOutput.length);

  renderScopeVars(scopeId, newVars, changedVars);
  renderConsole(newOutput, newLines.length);
  prevVars   = { ...newVars };
  prevOutput = [...newOutput];
  updateControls();

  if (onDone) onDone();
}

/* ===== Console panel ===== */
function renderConsole(output, newCount) {
  if (output.length === 0) {
    consoleBody.innerHTML = '<span class="empty-hint">Вывода пока нет</span>';
    consoleBody.appendChild(consoleAnchor);
    return;
  }
  const existingLines = consoleBody.querySelectorAll('.console-line').length;
  if (existingLines === 0) consoleBody.innerHTML = '';

  const startIdx = consoleBody.querySelectorAll('.console-line').length;
  for (let i = startIdx; i < output.length; i++) {
    const line = document.createElement('div');
    line.className = 'console-line' + (i >= output.length - newCount ? ' new' : '');
    line.textContent = output[i];
    consoleBody.appendChild(line);
  }
  consoleBody.appendChild(consoleAnchor);
}

function formatValue(v) {
  if (v === null) return 'None';
  if (v === true) return 'True';
  if (v === false) return 'False';
  if (typeof v === 'string') return `"${v}"`;
  if (Array.isArray(v)) return '[' + v.map(formatValue).join(', ') + ']';
  if (typeof v === 'object') {
    const entries = Object.entries(v).map(([k, val]) => `'${k}': ${formatValue(val)}`);
    return '{' + entries.join(', ') + '}';
  }
  return String(v);
}

function clearAll() {
  // Clear scope canvas (remove blocks, reset registry)
  const svg = scopeArrows;
  while (scopeCanvas.firstChild) scopeCanvas.removeChild(scopeCanvas.firstChild);
  scopeCanvas.appendChild(svg);
  svg.innerHTML = '';
  scopeCanvas.style.minWidth  = '';
  scopeCanvas.style.minHeight = '';
  scopeBlocks.clear();
  scopeMeta.clear();
  for (const k in nextX) delete nextX[k];
  globalBlock = null;
  scopeCanvas.scrollLeft = 0;

  consoleBody.innerHTML = '<span class="empty-hint">Вывода пока нет</span>';
  consoleBody.appendChild(consoleAnchor);
  prevVars = {};
  prevOutput = [];
}

/* ===== Ball animation ===== */
function animateBall(fromEl, toEl, color, onComplete, fast = false) {
  if (!fromEl || !toEl) { if (onComplete) onComplete(); return; }

  const fromRect = fromEl.getBoundingClientRect();
  const toRect   = toEl.getBoundingClientRect();

  const startX = fromRect.right;
  const startY = fromRect.top + fromRect.height / 2;
  const endX   = toRect.left + toRect.width / 2;
  const endY   = toRect.top  + toRect.height / 2;

  const DURATION = fast ? 0.22 : 0.45;

  const ball = document.createElement('div');
  ball.className = 'anim-ball';
  Object.assign(ball.style, {
    width: '14px', height: '14px',
    left:  startX + 'px',
    top:   (startY - 7) + 'px',
    background: color,
    boxShadow: `0 0 8px ${color}80`,
  });
  ballLayer.appendChild(ball);

  gsap.to(ball, {
    left: endX - 7,
    top:  endY - 7,
    duration: DURATION,
    ease: 'power2.inOut',
    onComplete: () => {
      if (onComplete) onComplete();
      gsap.to(ball, { scale: 0, opacity: 0, duration: 0.2, onComplete: () => ball.remove() });
    },
  });

  for (let i = 1; i <= 3; i++) {
    const dot = document.createElement('div');
    dot.className = 'anim-trail';
    const size = 14 - i * 3;
    Object.assign(dot.style, {
      width:  size + 'px',
      height: size + 'px',
      left:   startX + 'px',
      top:    (startY - size / 2) + 'px',
      background: color,
      opacity: (0.4 - i * 0.1).toFixed(2),
    });
    ballLayer.appendChild(dot);
    gsap.to(dot, {
      left: endX - size / 2, top: endY - size / 2,
      duration: DURATION, delay: i * 0.06, ease: 'power2.inOut',
      onComplete: () => gsap.to(dot, { scale: 0, opacity: 0, duration: 0.15, onComplete: () => dot.remove() }),
    });
  }
}

/* ===== Playback ===== */
function stepNext() {
  if (currentStep < steps.length - 1) renderStep(currentStep + 1);
  else stopAnimation();
}

function stepPrev() {
  // Rebuild from scratch up to currentStep-1 for correct scope state
  if (currentStep <= 0) return;
  stopAnimation();
  replayUpTo(currentStep - 1);
}

function replayUpTo(targetIdx) {
  pendingRootX = -1;  // cancel auto-scroll during manual navigation
  clearAll();
  prevVars = {};
  prevOutput = [];
  ensureGlobalBlock();
  for (let i = 0; i <= targetIdx; i++) {
    const step = steps[i];
    const event = step.event || 'line';
    if (event === 'call') {
      createScopeBlock(step.scope_id, step.parent_id, step.scope_name, step.args, step.depth);
    } else if (event === 'return') {
      markScopeReturned(step.scope_id, step.return_value);
    } else {
      const scopeId = step.scope_id !== undefined ? step.scope_id : 0;
      const newVars = step.variables || {};
      const changedVars = Object.keys(newVars).filter(
        k => JSON.stringify(newVars[k]) !== JSON.stringify(prevVars[k])
      );
      renderScopeVars(scopeId, newVars, changedVars);
      renderConsole(step.output || [], 0);
      prevVars   = { ...newVars };
      prevOutput = [...(step.output || [])];
    }
  }
  currentStep = targetIdx;
  const lastLine = steps[targetIdx];
  if ((lastLine.event || 'line') === 'line') setActiveLine(lastLine.line);
  stepCurrent.textContent = targetIdx + 1;
  updateControls();
}

function scheduleNextStep() {
  if (!isPlaying) return;
  if (currentStep >= steps.length - 1) { stopAnimation(); return; }

  const curIdx   = currentStep;
  const nextIdx  = currentStep + 1;
  const curStep  = steps[curIdx];
  const nextStep = steps[nextIdx];

  const nextEvent = nextStep.event || 'line';
  const postPause = parseInt(speedSelect.value, 10);
  const fast      = postPause === 0;

  // call step: no ball, short pause
  if (nextEvent === 'call') {
    playTimer = setTimeout(() => renderStep(nextIdx, scheduleNextStep), fast ? 125 : NO_BALL_PAUSE);
    return;
  }

  // return step: fire return ball, then advance
  if (nextEvent === 'return') {
    const retDelay = fast ? 40 : 80;
    const retTotal = fast ? 260 : BALL_FLY_MS + 80;
    setTimeout(() => fireReturnBall(nextStep.scope_id, nextStep.return_value, fast), retDelay);
    playTimer = setTimeout(() => renderStep(nextIdx, scheduleNextStep), retTotal);
    return;
  }

  // Look ahead: what does current line produce?
  const curVars    = curStep.variables  || {};
  const nextVars   = nextStep.variables || {};
  const curOutput  = curStep.output     || [];
  const nextOutput = nextStep.output    || [];

  const changedVars = Object.keys(nextVars).filter(
    k => JSON.stringify(nextVars[k]) !== JSON.stringify(curVars[k])
  );
  const newLines = nextOutput.slice(curOutput.length);

  const ballSrcEl = document.querySelector(`.code-line[data-line="${curStep.line}"]`);
  const hasCon    = newLines.length > 0 && ballSrcEl;
  const memBalls  = changedVars.filter(() => !!ballSrcEl);
  const ballCount = memBalls.length + (hasCon ? 1 : 0);

  if (ballCount === 0) {
    playTimer = setTimeout(() => renderStep(nextIdx, scheduleNextStep), fast ? 125 : NO_BALL_PAUSE);
    return;
  }

  playTimer = setTimeout(() => {
    let landed = 0;
    const onBallLand = () => {
      landed++;
      if (landed < ballCount) return;

      const scopeId = nextStep.scope_id !== undefined ? nextStep.scope_id : 0;
      renderScopeVars(scopeId, nextVars, changedVars);
      renderConsole(nextOutput, newLines.length);
      prevVars   = { ...nextVars };
      prevOutput = [...nextOutput];

      playTimer = setTimeout(() => {
        if (!isPlaying) return;
        renderStep(nextIdx, scheduleNextStep);
      }, postPause);
    };

    // One ball per changed variable → targets the scope block's vars section
    // (specific var cards don't exist until onBallLand renders them)
    memBalls.forEach((varName, i) => {
      const scopeId = nextStep.scope_id !== undefined ? nextStep.scope_id : 0;
      const block   = getScopeBlock(scopeId) || getScopeBlock(0);
      const target  = (block && block.querySelector('.scope-block-vars')) || block;
      setTimeout(() => animateBall(ballSrcEl, target, '#4F7EF7', onBallLand, fast), i * 60);
    });

    if (hasCon) {
      const conTarget = consoleAnchor || document.getElementById('console-panel');
      setTimeout(() => animateBall(ballSrcEl, conTarget, '#059669', onBallLand, fast), memBalls.length * 60);
    }
  }, fast ? 80 : BALL_DELAY);
}

/* ===== Return-value ball (child scope → parent scope) ===== */
function fireReturnBall(childScopeId, retVal, fast = false) {
  const meta = scopeMeta.get(childScopeId);
  if (!meta) return;

  const childEntry  = scopeBlocks.get(childScopeId);
  // parentId=0 means global scope — still a valid target
  const parentEntry = scopeBlocks.get(meta.parentId);
  if (!childEntry || !parentEntry) return;

  const fromEl = childEntry.el.querySelector('.scope-block-return') || childEntry.el;
  const toEl   = parentEntry.el.querySelector('.scope-block-vars') || parentEntry.el;
  animateBall(fromEl, toEl, '#8B5CF6', null, fast);
}

function togglePlay() {
  if (isPlaying) {
    clearTimeout(playTimer);
    isPlaying = false;
    updatePlayBtn();
    return;
  }

  isPlaying = true;
  updatePlayBtn();

  if (currentStep >= steps.length - 1) {
    clearAll();
    ensureGlobalBlock();
    prevVars = {};
    prevOutput = [];
    renderStep(0, scheduleNextStep);
  } else {
    scheduleNextStep();
  }
}

function updatePlayBtn() {
  ctrlPlay.textContent = isPlaying ? '⏸' : '▶';
}

function updateControls() {
  ctrlFirst.disabled = currentStep === 0;
  ctrlPrev.disabled  = currentStep === 0;
  ctrlNext.disabled  = currentStep >= steps.length - 1;
  ctrlLast.disabled  = currentStep >= steps.length - 1;
  updatePlayBtn();
}

/* ===== Control listeners ===== */
ctrlFirst.addEventListener('click', () => {
  stopAnimation();
  clearAll();
  ensureGlobalBlock();
  prevVars = {};
  prevOutput = [];
  renderStep(0);
});
ctrlPrev.addEventListener('click', () => { stopAnimation(); stepPrev(); });
ctrlPlay.addEventListener('click', togglePlay);
ctrlNext.addEventListener('click', () => { stopAnimation(); stepNext(); });
ctrlLast.addEventListener('click', () => {
  stopAnimation();
  replayUpTo(steps.length - 1);
});
