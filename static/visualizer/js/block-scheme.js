/* ===================================================================
   block-scheme.js  —  Block Scheme renderer  v3
   Pipeline: parseCode → layoutTree → renderSVG
   =================================================================== */

const BS = {
  ASSIGN_W: 150, ASSIGN_H: 56, ASSIGN_SKEW: 22,
  ACTION_W: 140, ACTION_H: 50, ACTION_RX:   10,
  COND_W:   130, COND_H:   72,
  LOOP_W:   160, LOOP_H:   62, LOOP_FLAT:   36,
  TERM_W:   120, TERM_H:   44,
  RETURN_W: 150, RETURN_H: 56, RETURN_SKEW: 30,   // inverted trapezoid — narrower top, wider bottom
  V_GAP:     56,
  H_OFF:    130,   // branch x-offset for if-else
  BACK_PAD:  50,   // extra left padding for back arrows
  EXIT_PAD:  50,   // extra right padding for exit arrows
  WRAP_PAD:  90,   // extra right padding for "Нет" wrap inside loop
  SVG_PAD:   50,
  FRAME_NEST:  35,  // extra gap per side between nested loop frames
  FRAME_PAD_X: 25,  // x-padding from widest node to frame border
  FRAME_PAD_Y: 10,  // y-padding above loop top / below body bottom
  BACK_DOWN:   10,  // px down before turning left on back arrow
  FUNC_GAP_X: 130,  // horizontal clearance between main diagram and the function column
  FUNC_GAP_Y: 150,  // vertical gap between stacked function diagrams (> V_GAP*2.2 so addColArrows never bridges two diagrams)
};

let _uid = 0;
const uid = () => 'b' + (++_uid);

/* break всегда ведёт туда же, куда вёл бы естественный (небрейкнутый) выход
   из охватывающего цикла — просто раньше. Поэтому вместо того, чтобы решать
   геометрию break сразу при его размещении (когда цель ещё не известна —
   она определяется позже, когда обрабатывается то, что идёт ПОСЛЕ цикла),
   каждый break регистрируется здесь по id цикла и разрешается в реальное
   ребро в момент, когда для этого же цикла разрешается его собственный
   естественный выход (loopExitArrow/nestedLoopBackArrow/остаток тела).
   Сбрасывается в layoutProgram() на каждый новый разбор кода. */
let _pendingBreaks = new Map();   // loopNode.id -> [{fromCx, fromBottomY}]

function registerBreak(loopNode, fromCx, fromBottomY) {
  const arr = _pendingBreaks.get(loopNode.id) || [];
  arr.push({ fromCx, fromBottomY });
  _pendingBreaks.set(loopNode.id, arr);
}

function resolveBreaks(loopNode, targetCx, targetY, edges, targetLoopNode) {
  const pending = _pendingBreaks.get(loopNode.id);
  if (!pending) return;
  const D = BS.BACK_DOWN;
  for (const { fromCx, fromBottomY } of pending) {
    // Когда цель НИЖЕ точки break (обычный случай — выход из цикла к коду
    // после него/«Концу»), держим вертикальный участок на исходной колонке
    // (fromCx) максимально долго — вплоть до низа рамки цикла целиком — и
    // поворачиваем к targetCx только у самой цели. targetCx обычно совпадает
    // с колонкой того самого условия, что зарегистрировало break, а на ней
    // же лежат её «Нет»-стрелка и обратная стрелка цикла — начать движение к
    // targetCx РАНЬШЕ означало бы идти вдоль/через них на приличном участке
    // (запутанный «пучок» линий, из-за которого возник этот баг). При такой
    // геометрии единственное место, где путь break обязан коснуться той же
    // колонки — доля секунды у самого нижнего наконечника обратной стрелки
    // цикла (её курс уже давно свёрнул в сторону) — короткое, чёткое
    // перпендикулярное пересечение вместо развёрнутого наложения линий.
    // Когда цель ВЫШЕ (break внутри вложенного цикла, ведущий к продолжению
    // внешнего) — старая геометрия ("повернуть сразу и идти по общей
    // центральной колонке") резала диаграмму насквозь через условие/
    // вложенный цикл, лежащие на той же колонке (баг №1, найден на реальном
    // коде). Промежуточная версия вела линию вдоль границы рамки СВОЕГО
    // (внутреннего) цикла — код уже не резала, но эта граница не совпадает с
    // той, вдоль которой идёт родная стрелка возврата внешнего цикла
    // (nestedLoopBackArrow всегда возвращается через targetLoopNode.frameLeft,
    // а не через границу цикла, где стоит сам break) — рядом оказывались две
    // почти параллельные, но не совпадающие линии (баг №2, тоже найден на
    // реальном коде). Теперь break намеренно ведётся к ТОЙ ЖЕ границе, что и
    // родная стрелка (targetLoopNode.frameLeft) — визуально сливается с ней
    // вместо того, чтобы идти своим отдельным почти-параллельным путём.
    // targetLoopNode известен только когда цель — хексагон внешнего цикла
    // (резолвится лениво в resolveBackArrows(), т.к. на момент регистрации
    // break его frameLeft ещё не вычислен — тот же приём, что и у
    // nestedLoopBackArrow/isBackArrow ниже); если его нет — старый запасной
    // вариант (граница СВОЕГО цикла), чтобы не потерять ребро совсем.
    if (targetY >= fromBottomY) {
      const turnY = Math.max(fromBottomY + D, loopNode.frameBot + D);
      edges.push(ePath([P(fromCx, fromBottomY), P(fromCx, turnY),
                        P(targetCx, turnY), P(targetCx, targetY)]));
    } else if (targetLoopNode) {
      edges.push({ isBreakToOuter: true, fromCx, fromBottomY, loopNode, targetCx, targetY, targetLoopNode });
    } else {
      const clearY = loopNode.frameBot + D;
      const exitX = Math.abs(fromCx - loopNode.frameLeft) <= Math.abs(loopNode.frameRight - fromCx)
        ? loopNode.frameLeft : loopNode.frameRight;
      edges.push(ePath([P(fromCx, fromBottomY), P(fromCx, clearY),
                        P(exitX, clearY), P(exitX, targetY), P(targetCx, targetY)]));
    }
  }
  _pendingBreaks.delete(loopNode.id);
}

/* ═══════════════════════════════════════════════════════════════════
   LAYER 1 — PARSER
   ═══════════════════════════════════════════════════════════════════ */

/* Находит позицию двоеточия, завершающего заголовок составного оператора
   (if/elif/else/for/while/def) — первое ':' вне строковых литералов, вне
   скобок ()[]{} и вне комментария. Двоеточие среза (a[1:2]), словаря
   ({1:2}) или аннотации параметра def f(x: int) всегда на глубине скобок
   > 0 и корректно пропускается. Возвращает -1, если такого ':' нет. */
function findTopLevelColon(s) {
  let depth = 0, quote = null;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (quote) {
      if (ch === '\\') { i++; continue; }
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === '#') break;
    if (ch === '(' || ch === '[' || ch === '{') { depth++; continue; }
    if (ch === ')' || ch === ']' || ch === '}') { depth--; continue; }
    if (ch === ':' && depth === 0) return i;
  }
  return -1;
}

/* Разворачивает однострочные составные операторы (if x: y, for i in ...: y,
   while c: y, def f(): y) в стандартную двухстрочную форму, которую уже
   умеет разбирать остальной парсер — заголовок и синтетическая строка тела
   с отступом +4. Обе строки помечаются ТЕМ ЖЕ индексом исходной строки (i):
   Python выполняет и проверку условия, и тело такой строки как одно
   'line'-событие трассировки под одним номером строки, поэтому подсветка
   активного шага должна остаться привязана к реальному номеру строки, а не
   к синтетическому. Строки без keyword-заголовка (в т.ч. return с
   тернарником — return X if C else Y) не трогаются вообще — это
   отдельный, более сложный случай, сознательно не в scope этой правки. */
function expandInlineBodies(lines) {
  const KEYWORD_RE = /^(if|elif|else|for|while|def)\b/;
  const out = [];
  for (const l of lines) {
    if (!KEYWORD_RE.test(l.s)) { out.push(l); continue; }
    const colonPos = findTopLevelColon(l.s);
    if (colonPos === -1) { out.push(l); continue; }
    const header = l.s.slice(0, colonPos + 1);
    const body = l.s.slice(colonPos + 1).trim();
    if (!body || body.startsWith('#')) { out.push(l); continue; }
    out.push({ s: header, ind: l.ind, i: l.i });
    out.push({ s: body, ind: l.ind + 4, i: l.i });
  }
  return out;
}

/* ── Comprehension → loop/condition decomposition ─────────────────────
   Сложные print(..., [comprehension]) (и другие статические выражения с
   comprehension внутри) раньше рисовались одним плоским action-блоком с
   текстом comprehension внутри — не как настоящая структура цикл+условие
   +накопление. Ниже — детектор и синтезатор эквивалентных узлов loop/
   condition/action, переиспользующих уже существующие фигуры и раскладку
   (layoutSeq/placeLoop/layoutCond ничего не знают о том, что узлы
   синтетические — просто раскладывают обычные loop/condition как всегда).

   Scope v1 (согласовано с пользователем): только ОДИН `for`, максимум
   ОДИН `if`, без вложенных comprehension. Всё сложнее — комментарий не
   срабатывает, строка рисуется старым плоским блоком, как и раньше. */

/* Находит первое вхождение keyword как отдельного слова (окружённого
   пробелами) вне строк и вне скобок — та же техника глубины/кавычек, что
   и в findTopLevelColon(), но для произвольного слова, а не ':'. */
function findTopLevelKeyword(s, kw) {
  let depth = 0, quote = null;
  for (let i = 0; i <= s.length - kw.length; i++) {
    const ch = s[i];
    if (quote) { if (ch === '\\') { i++; continue; } if (ch === quote) quote = null; continue; }
    if (ch === '"' || ch === "'") { quote = ch; continue; }
    if (ch === '(' || ch === '[' || ch === '{') { depth++; continue; }
    if (ch === ')' || ch === ']' || ch === '}') { depth--; continue; }
    if (depth === 0 && s.slice(i, i + kw.length) === kw &&
        (i === 0 || /\s/.test(s[i - 1])) &&
        (i + kw.length >= s.length || /\s/.test(s[i + kw.length]))) {
      return i;
    }
  }
  return -1;
}

/* Разбирает "EXPR for VAR in ITER[ if COND]" (тело одного comprehension —
   без внешних скобок). Возвращает null, если это не простой одноуровневый
   comprehension (нет 'for', VAR — не простое имя, или внутри ITER/COND
   нашёлся ЕЩЁ один 'for' — вложенный comprehension, вне scope v1). */
function scanComprehensionBody(s) {
  const forIdx = findTopLevelKeyword(s, 'for');
  if (forIdx === -1) return null;
  const elementExpr = s.slice(0, forIdx).trim();
  const rest = s.slice(forIdx + 3);
  const inIdx = findTopLevelKeyword(rest, 'in');
  if (inIdx === -1) return null;
  const varName = rest.slice(0, inIdx).trim();
  if (!/^\w+$/.test(varName)) return null;   // tuple-unpacking (for k, v in ...) — вне scope
  const rest2 = rest.slice(inIdx + 2);
  const ifIdx = findTopLevelKeyword(rest2, 'if');
  const iterableExpr = (ifIdx === -1 ? rest2 : rest2.slice(0, ifIdx)).trim();
  const condExpr = ifIdx === -1 ? null : rest2.slice(ifIdx + 2).trim();
  if (!elementExpr || !varName || !iterableExpr) return null;
  // Второй 'for' внутри iterable/cond — вложенный comprehension, не поддерживаем
  if (findTopLevelKeyword(iterableExpr, 'for') !== -1) return null;
  if (condExpr && findTopLevelKeyword(condExpr, 'for') !== -1) return null;
  return { elementExpr, varName, iterableExpr, condExpr };
}

/* Находит первую пару [...] или {...} в строке, чьё содержимое — простой
   comprehension (см. scanComprehensionBody). Возвращает позиции скобок +
   разобранные части, либо null, если такой пары нет. */
function findBracketComprehension(s) {
  for (let i = 0; i < s.length; i++) {
    if (s[i] !== '[' && s[i] !== '{') continue;
    const closeCh = s[i] === '[' ? ']' : '}';
    let depth = 1, quote = null, j = i + 1;
    for (; j < s.length; j++) {
      const ch = s[j];
      if (quote) { if (ch === '\\') { j++; continue; } if (ch === quote) quote = null; continue; }
      if (ch === '"' || ch === "'") { quote = ch; continue; }
      if (ch === '(' || ch === '[' || ch === '{') depth++;
      else if (ch === ')' || ch === ']' || ch === '}') { depth--; if (depth === 0) break; }
    }
    if (j >= s.length) continue;
    const comp = scanComprehensionBody(s.slice(i + 1, j));
    if (comp) return { openIdx: i, closeIdx: j, kind: s[i] === '[' ? 'list' : 'set', ...comp };
  }
  return null;
}

/* Находит any(...)/all(...), где ВЕСЬ аргумент — простой comprehension без
   фильтра (ровно паттерн реальных заданий №19-21: any(f(x) for x in ...)).
   Фильтр (if COND) внутри any/all — уже два условия сразу (фильтр + сама
   проверка истинности), вне scope v1 — тогда возвращаем null. */
function findCallComprehension(s) {
  const re = /\b(any|all)\(/g;
  let m;
  while ((m = re.exec(s))) {
    const openIdx = m.index + m[0].length - 1;
    let depth = 1, quote = null, j = openIdx + 1;
    for (; j < s.length; j++) {
      const ch = s[j];
      if (quote) { if (ch === '\\') { j++; continue; } if (ch === quote) quote = null; continue; }
      if (ch === '"' || ch === "'") { quote = ch; continue; }
      if (ch === '(' || ch === '[' || ch === '{') depth++;
      else if (ch === ')' || ch === ']' || ch === '}') { depth--; if (depth === 0) break; }
    }
    if (j >= s.length) continue;
    const comp = scanComprehensionBody(s.slice(openIdx + 1, j));
    if (comp && !comp.condExpr) return { kind: m[1], nameIdx: m.index, openIdx, closeIdx: j, ...comp };
  }
  return null;
}

let _compAccCounter = 0;

/* Строит loop(+condition) узлы для comprehension-присваивания/выражения
   (bracket-форма). Если вся строка — простое "VAR = [comp]", накопителем
   становится сама VAR (без придуманного имени); иначе — синтетический
   аккумулятор + завершающая строка-подстановка (напр. "print(_acc1)"). */
function buildBracketComprehensionNodes(l) {
  const found = findBracketComprehension(l.s);
  if (!found) return null;
  const prefix = l.s.slice(0, found.openIdx);
  const suffix = l.s.slice(found.closeIdx + 1);
  const directAssign = prefix.match(/^(\w+)\s*=\s*$/);
  const isDirect = directAssign && suffix.trim() === '';
  const accVar = isDirect ? directAssign[1] : `_acc${++_compAccCounter}`;
  const line = l.i + 1;

  const initNode = { id: uid(), type: 'assignment', label: `${accVar} = ${found.kind === 'list' ? '[]' : 'set()'}`, line };
  const addLabel = found.kind === 'list' ? `${accVar}.append(${found.elementExpr})` : `${accVar}.add(${found.elementExpr})`;
  const actionNode = { id: uid(), type: 'action', label: addLabel, line };
  const loopBody = found.condExpr
    ? [{ id: uid(), type: 'condition', label: found.condExpr, yes: [actionNode], no: [], hasElse: false, line }]
    : [actionNode];
  const loopNode = { id: uid(), type: 'loop', label: `${found.varName} in ${found.iterableExpr}`, body: loopBody, line };

  const nodes = [initNode, loopNode];
  if (!isDirect) {
    const tailText = (prefix + accVar + suffix).trim();
    const tailLine = { s: tailText, ind: l.ind, i: l.i };
    nodes.push(tailText.startsWith('return') ? parseReturn(tailLine) : parseStmt(tailLine));
  }
  return nodes;
}

/* Строит loop+condition для "return any(EXPR for VAR in ITER)"/"return
   all(...)" — единственная реально встречающаяся форма в заданиях №19-21.
   Любая другая обёртка (присваивание, print и т.п.) — вне scope v1. */
function buildAnyAllComprehensionNodes(l) {
  const m = l.s.match(/^return\s+(.+)$/);
  if (!m) return null;
  const found = findCallComprehension(m[1]);
  if (!found) return null;
  if (found.nameIdx !== 0 || found.closeIdx !== m[1].length - 1) return null;   // должно занимать ВСЮ return-строку
  const line = l.i + 1;
  const isAny = found.kind === 'any';
  const earlyReturn = { id: uid(), type: 'return', label: isAny ? 'return True' : 'return False', line };
  const condNode = {
    id: uid(), type: 'condition', label: found.elementExpr, line,
    yes: isAny ? [earlyReturn] : [],
    no:  isAny ? [] : [earlyReturn],
    hasElse: !isAny,   // "no"-ветка реально используется только для all() — иначе layoutCond её не отрисует (см. проверки node.hasElse && node.no.length>0)
  };
  const loopNode = { id: uid(), type: 'loop', label: `${found.varName} in ${found.iterableExpr}`, body: [condNode], line };
  const finalReturn = { id: uid(), type: 'return', label: isAny ? 'return False' : 'return True', line };
  return [loopNode, finalReturn];
}

function parseCode(src) {
  _uid = 0;
  const rawLines = src.split('\n')
    .map((t, i) => ({ s: t.trimStart(), ind: t.length - t.trimStart().length, i }))
    .filter(l => l.s.length > 0);
  const lines = expandInlineBodies(rawLines);
  const { nodes, functions } = parseBlock(lines, 0, 0);
  return { tree: nodes, functions };
}

/* def — не часть последовательного потока: тело парсится отдельно и
   всплывает через functions[], а не через nodes[] (своя диаграмма). */
function parseBlock(lines, si, indent) {
  const nodes = [];
  const functions = [];
  let i = si;
  while (i < lines.length) {
    const l = lines[i];
    if (l.ind < indent) break;
    if (l.ind > indent) { i++; continue; }
    if (l.s === 'else:' || l.s.startsWith('elif ')) break;
    if      (l.s.startsWith('def '))    { const r = parseFunctionDef(lines, i, indent); functions.push(r.node, ...r.functions); i = r.next; }
    else if (l.s.startsWith('for '))    { const r = parseLoop(lines, i, indent);  nodes.push(r.node); functions.push(...r.functions); i = r.next; }
    else if (l.s.startsWith('while ')) { const r = parseWhile(lines, i, indent); nodes.push(r.node); functions.push(...r.functions); i = r.next; }
    else if (l.s.startsWith('if '))    { const r = parseCond(lines, i, indent);  nodes.push(r.node); functions.push(...r.functions); i = r.next; }
    else if (l.s === 'return' || l.s.startsWith('return ')) {
      const compNodes = buildAnyAllComprehensionNodes(l) || buildBracketComprehensionNodes(l);
      if (compNodes) nodes.push(...compNodes);
      else nodes.push(parseReturn(l));
      i++;
    }
    else if (l.s === 'break')    { nodes.push({ id: uid(), type: 'break',    label: 'break',    line: l.i + 1 }); i++; }
    else if (l.s === 'continue') { nodes.push({ id: uid(), type: 'continue', label: 'continue', line: l.i + 1 }); i++; }
    else {
      const compNodes = buildBracketComprehensionNodes(l);
      if (compNodes) nodes.push(...compNodes);
      else nodes.push(parseStmt(l));
      i++;
    }
  }
  return { nodes, next: i, functions };
}

function parseStmt(l) {
  const s = l.s;
  if (s.startsWith('import ') || s.startsWith('from ')) {
    return { id: uid(), type: 'import', label: s, line: l.i + 1 };
  }
  const m = !s.startsWith('print') && s.match(/^(\w+)\s*=\s*(.+)$/);
  if (m) {
    const rhs = m[2].trim();
    const lit = /^-?\d+(\.\d+)?$/.test(rhs) || /^["'].*["']$/.test(rhs)
              || ['True','False','None'].includes(rhs);
    return { id: uid(), type: lit ? 'assignment' : 'action', label: s, line: l.i + 1 };
  }
  return { id: uid(), type: 'action', label: s, line: l.i + 1 };
}

function parseReturn(l) {
  return { id: uid(), type: 'return', label: l.s, line: l.i + 1 };
}

function parseFunctionDef(lines, i, indent) {
  const raw = lines[i].s;
  const m = raw.match(/^def\s+(\w+)\s*\(/);
  const name = m ? m[1] : 'function';
  const { nodes: body, next, functions } = parseBlock(lines, i + 1, indent + 4);
  return { node: { id: uid(), type: 'function', name, body, line: lines[i].i + 1 }, next, functions };
}

function parseLoop(lines, i, indent) {
  const m = lines[i].s.match(/^for\s+(\w+)\s+in\s+(range\([^)]+\))\s*:/);
  const label = m ? `${m[1]} in ${m[2]}` : lines[i].s.replace(/^for\s+/,'').replace(/:$/,'');
  const { nodes: body, next, functions } = parseBlock(lines, i + 1, indent + 4);
  return { node: { id: uid(), type: 'loop', label, body, line: lines[i].i + 1 }, next, functions };
}

function parseWhile(lines, i, indent) {
  const m = lines[i].s.match(/^while\s+(.+?)\s*:$/);
  const label = m ? m[1].trim() : lines[i].s.replace(/^while\s+/, '').replace(/:$/, '');
  const { nodes: body, next, functions } = parseBlock(lines, i + 1, indent + 4);
  return { node: { id: uid(), type: 'loop', label, body, line: lines[i].i + 1 }, next, functions };
}

function parseCond(lines, i, indent) {
  const raw = lines[i].s;
  const m = raw.match(/^(?:if|elif)\s+(.+?)\s*:$/);
  const label = m ? m[1].trim() : raw.replace(/^(?:if|elif)\s+/, '').replace(/:$/, '');
  const { nodes: yes, next: ay, functions: yesFns } = parseBlock(lines, i + 1, indent + 4);
  let no = [], next = ay, hasElse = false, noFns = [];
  if (ay < lines.length && lines[ay].ind === indent) {
    if (lines[ay].s === 'else:') {
      const r = parseBlock(lines, ay + 1, indent + 4);
      no = r.nodes; next = r.next; hasElse = true; noFns = r.functions;
    } else if (lines[ay].s.startsWith('elif ')) {
      // elif → рекурсивно превращается во вложенный if в no-ветви
      const r = parseCond(lines, ay, indent);
      no = [r.node]; next = r.next; hasElse = true; noFns = r.functions;
    }
  }
  return { node: { id: uid(), type: 'condition', label, yes, no, hasElse, line: lines[i].i + 1 }, next, functions: [...yesFns, ...noFns] };
}

/* ═══════════════════════════════════════════════════════════════════
   LAYER 2 — LAYOUT
   ═══════════════════════════════════════════════════════════════════ */

/* Главная диаграмма (Начало → tree → Конец) + одна диаграмма на каждую
   def, столбцом справа от главной, друг под другом в порядке определения.
   У диаграмм функций нет "Конец" — они просто обрываются на последнем
   блоке (обычно на return-трапеции). */
function layoutProgram(mainNodes, functions) {
  _pendingBreaks = new Map();
  const lnodes = [], edges = [];
  // role: 'start'/'end' — только у ЭТИХ двух узлов главной программы (не у
  // "Начало (имя_функции)"), чтобы step-анимация могла найти их напрямую по
  // роли: у них нет своей строки кода, значит обычный поиск bsFindNodeByLine
  // их не находит.
  const startNode = { id: uid(), type: 'terminal', label: 'Начало', role: 'start' };
  const endNode   = { id: uid(), type: 'terminal', label: 'Конец',  role: 'end'   };
  const mainCX = BS.SVG_PAD + 200;
  layoutSeq([startNode, ...mainNodes, endNode], mainCX, BS.SVG_PAD, null, lnodes, edges);

  if (functions && functions.length > 0) {
    let mainRight = mainCX;
    lnodes.forEach(n => { mainRight = Math.max(mainRight, n.cx + n.w / 2); });

    // Пробный проход при cx=0 для каждой функции: узнаём, насколько далеко
    // влево реально уйдёт её рамка/ветки (зависит от вложенности циклов и
    // условий — фиксированный отступ этого не учитывал и мог "наехать" на
    // главную диаграмму при глубокой вложенности). Худший случай определяет
    // общий funcCX для всей колонки — все "Начало (имя)" остаются на одной
    // вертикали, но зазор от главной диаграммы гарантирован для каждой.
    let worstLeft = 0;
    functions.forEach(fn => {
      const dryNodes = [], dryEdges = [];
      const dryStart = { id: uid(), type: 'terminal', label: `Начало (${fn.name})`, line: fn.line };
      layoutSeq([dryStart, ...fn.body], 0, BS.SVG_PAD, null, dryNodes, dryEdges);
      resolveBackArrows(dryEdges);
      worstLeft = Math.min(worstLeft, leftExtent(dryNodes, dryEdges));
    });

    const funcCX = mainRight + BS.FUNC_GAP_X - worstLeft;
    let funcY = BS.SVG_PAD;

    functions.forEach(fn => {
      const fnStart = { id: uid(), type: 'terminal', label: `Начало (${fn.name})`, line: fn.line };
      const bot = layoutSeq([fnStart, ...fn.body], funcCX, funcY, null, lnodes, edges);
      funcY = bot + BS.FUNC_GAP_Y;
    });
  }

  return { lnodes, edges };
}

/* Крайняя левая точка раскладки (узлы + рамки циклов + все точки рёбер) —
   используется, чтобы измерить, сколько места реально нужно диаграмме
   функции, прежде чем её позиционировать (см. layoutProgram). */
function leftExtent(lnodes, edges) {
  let minX = Infinity;
  lnodes.forEach(n => {
    minX = Math.min(minX, n.cx - n.w / 2);
    if (n.frameLeft != null) minX = Math.min(minX, n.frameLeft);
  });
  edges.forEach(e => (e.points || []).forEach(p => { minX = Math.min(minX, p.x); }));
  return minX;
}

/* True, если последний оператор ветки — return/break/continue (тупиковый
   блок: вниз по этой ветке дальше рисовать нечего, поток покидает
   последовательность целиком). Имя не переименовано в endsInJump и т.п.,
   чтобы не расширять диф на 6+ мест — семантика описана здесь. */
function endsInReturn(branchNodes) {
  if (branchNodes.length === 0) return false;
  const t = branchNodes[branchNodes.length - 1].type;
  return t === 'return' || t === 'break' || t === 'continue';
}

/* Lay out a sequence of siblings. loopCtx = enclosing LayoutNode or null.
   Returns bottom Y of the last placed item (no trailing V_GAP). */
/* Стрелка выхода из цикла в верх произвольного следующего узла — переиспользуется
   в layoutSeq()/linSeq() для узла ЛЮБОГО типа (loop/condition/обычный), идущего
   сразу за циклом. Раньше эта проверка (if lastLoop) была только в ветке
   "обычный узел" каждой из двух функций — переход "цикл → условие" и
   "цикл → цикл" терял стрелку выхода (баг, найденный пользователем). */
function loopExitArrow(lastLoop, toCx, toTopY) {
  const rx = lastLoop.cx + lastLoop.w / 2;
  const D  = BS.BACK_DOWN;
  return ePath([P(rx, lastLoop.cy), P(lastLoop.frameRight, lastLoop.cy),
                P(lastLoop.frameRight, toTopY - D), P(toCx, toTopY - D), P(toCx, toTopY)]);
}

function layoutSeq(nodes, cx, y0, loopCtx, lnodes, edges) {
  let y        = y0;
  let lastLoop = null;    // LayoutNode of last loop, for exit arrow
  let joinY    = null;    // Y of condition join point, for join→next arrow
  let joinReachable = false;   // false when joinY has no real incoming edge (dead-end branches)

  const addFromJoin = (toY) => {
    if (joinY !== null) {
      if (joinReachable) edges.push(ePath([P(cx, joinY), P(cx, toY)]));
      joinY = null;
      joinReachable = false;
    }
  };

  for (let i = 0; i < nodes.length; i++) {
    const node    = nodes[i];
    const hasNext = i + 1 < nodes.length;

    if (node.type === 'loop') {
      addFromJoin(y);   // connect condition join → loop top (if applicable)
      if (lastLoop) { edges.push(loopExitArrow(lastLoop, cx, y)); resolveBreaks(lastLoop, cx, y, edges); lastLoop = null; }
      const visBot = placeLoop(node, cx, y, lnodes, edges);
      lastLoop = lnodes.find(n => n.id === node.id);
      y = visBot;
      if (hasNext) y += BS.V_GAP;

    } else if (node.type === 'condition') {
      addFromJoin(y);   // connect prior condition join → this condition top
      if (lastLoop) { edges.push(loopExitArrow(lastLoop, cx, y)); resolveBreaks(lastLoop, cx, y, edges); lastLoop = null; }
      const { y: j, reachable } = layoutCond(node, cx, y, loopCtx, lnodes, edges);
      if (!loopCtx) { joinY = j; joinReachable = reachable; }   // track join for top-level conditions
      lastLoop = null;
      y = j;
      if (hasNext) y += BS.V_GAP;

    } else {
      const ln  = mkNode(node, cx, y);
      lnodes.push(ln);
      const top = ln.cy - ln.h / 2;

      if (lastLoop) {
        edges.push(loopExitArrow(lastLoop, ln.cx, top));
        resolveBreaks(lastLoop, ln.cx, top, edges);
        lastLoop = null;
      } else {
        addFromJoin(top);   // connect condition join → this node top
        // (remaining down arrows added by addColArrows)
      }

      y = ln.cy + ln.h / 2;
      if (hasNext) y += BS.V_GAP;
    }
  }

  // Диаграммы функций не имеют завершающего овала «Конец» (обрываются на
  // последнем блоке) — если условие без else оказалось последним оператором
  // тела функции, join-точка «Нет» остаётся не подключена ни к чему, т.к.
  // addFromJoin() вызывается только при обработке следующего узла, а его
  // здесь нет. Закрываем такой «повисший» join отдельным отрезком со
  // стрелкой — но только если в него реально что-то втекает (joinReachable),
  // иначе получаем "дух"-стрелку из пустоты (баг №8, найден пользователем:
  // если/else, где ОБЕ ветки заканчиваются return, ничего не подключает
  // joinY, а прежняя версия этой правки рисовала стрелку всё равно).
  if (joinY !== null && joinReachable) {
    edges.push(ePath([P(cx, joinY), P(cx, joinY + BS.V_GAP)]));
    joinY = null;
  }

  // Если последний оператор — сам цикл, и внутри него остались break без
  // разрешённой цели (т.к. дальше в последовательности ничего нет, естественный
  // выход из цикла тоже никуда не ведёт) — закрываем их той же заглушкой,
  // что и висящий joinY выше, вместо того чтобы молча потерять эти рёбра.
  if (lastLoop !== null && _pendingBreaks.has(lastLoop.id)) {
    const stubY = y + BS.V_GAP;
    edges.push(ePath([P(cx, y), P(cx, stubY)]));
    resolveBreaks(lastLoop, cx, stubY, edges);
  }

  return y;
}

/* Place a single non-structural node at (cx, topY), return LayoutNode. */
function mkNode(node, cx, topY) {
  const { w, h } = bsz(node.type);
  return { ...node, cx, cy: topY + h / 2, w, h };
}

function bsz(type) {
  if (type === 'assignment') return { w: BS.ASSIGN_W, h: BS.ASSIGN_H };
  if (type === 'condition')  return { w: BS.COND_W,   h: BS.COND_H   };
  if (type === 'loop')       return { w: BS.LOOP_W,   h: BS.LOOP_H   };
  if (type === 'terminal')   return { w: BS.TERM_W,   h: BS.TERM_H   };
  if (type === 'return')     return { w: BS.RETURN_W, h: BS.RETURN_H };
  if (type === 'import')     return { w: BS.ACTION_W, h: BS.ACTION_H };
  return { w: BS.ACTION_W, h: BS.ACTION_H };
}

/* ── Condition ────────────────────────────────────────────────────── */
function layoutCond(node, cx, topY, loopCtx, lnodes, edges, isLastInLoop = true) {
  const { w, h } = bsz('condition');
  const cy = topY + h / 2;
  lnodes.push({ ...node, cx, cy, w, h });

  const condBot   = cy + h / 2;
  const branchTop = condBot + BS.V_GAP;
  const yesCX     = cx - BS.H_OFF;
  const noCX      = cx + BS.H_OFF;

  /* Connects the end of a Да/Нет branch into a target point. If the
     branch's last element was itself a loop, route through its hexagon
     (loopExitConnector) instead of its raw bottom coordinate — keeps
     "exit always through the loop block" true everywhere a branch can
     end in a loop: inside a loop or not, last in the loop or not,
     with/without else. See Rule 9 generalization. */
  const mergeFrom = (lastLoop, fx, fy, tx, ty) => {
    if (lastLoop) {
      edges.push(loopExitConnector(lastLoop, tx, ty));
      resolveBreaks(lastLoop, tx, ty, edges);
    } else {
      const pts = Math.abs(fx - tx) < 2 ? [P(fx, fy), P(tx, ty)] : [P(fx, fy), P(fx, ty), P(tx, ty)];
      edges.push({ points: pts, noArrow: true });
    }
  };

  /* ── INSIDE LOOP, NOT LAST ── */
  if (loopCtx && !isLastInLoop) {
    const D = BS.BACK_DOWN;

    let yesBot = branchTop, yesLastLoop = null;
    if (node.yes.length > 0) {
      edges.push(ePath([P(cx - w/2, cy), P(cx - w/2, cy + D), P(yesCX, cy + D), P(yesCX, branchTop)], 'Да', 'left'));
      ({ bot: yesBot, lastLoop: yesLastLoop } = linSeq(node.yes, yesCX, branchTop, loopCtx, lnodes, edges));
    }
    const yesReturns = endsInReturn(node.yes);

    if (node.hasElse && node.no.length > 0) {
      edges.push(ePath([P(cx + w/2, cy), P(cx + w/2, cy + D), P(noCX, cy + D), P(noCX, branchTop)], 'Нет', 'right'));
      const { bot: noBot, lastLoop: noLastLoop } = linSeq(node.no, noCX, branchTop, loopCtx, lnodes, edges);
      const noReturns = endsInReturn(node.no);

      const yesJoin = node.yes.length > 0 ? yesBot : condBot;
      const joinY   = Math.max(yesJoin, noBot) + Math.round(BS.V_GAP / 2);

      if (node.yes.length > 0 && !yesReturns) {
        mergeFrom(yesLastLoop, yesCX, yesBot, cx, joinY);
      }
      if (!noReturns) mergeFrom(noLastLoop, noCX, noBot, cx, joinY);
      // reachable: хотя бы одна ветка реально доходит до joinY. Если обе (yes
      // непустая и заканчивается return, no непустая и заканчивается return) —
      // joinY существует только как координата, в неё ничего не втекает.
      return { y: joinY, reachable: (node.yes.length === 0 || !yesReturns) || !noReturns };

    } else {
      const stubX = cx + w / 2 + 8;
      const joinY = (node.yes.length > 0 ? yesBot : condBot) + Math.round(BS.V_GAP / 2);

      if (node.yes.length > 0) {
        if (!yesReturns) mergeFrom(yesLastLoop, yesCX, yesBot, cx, joinY);
      } else {
        edges.push({ points: [P(cx - w/2, cy), P(cx - w/2, joinY), P(cx, joinY)],
                     label: 'Да', labelSide: 'left', noArrow: true });
      }
      edges.push(ePath([P(cx + w/2, cy), P(cx + w/2, cy + D), P(stubX, cy + D)], 'Нет', 'right', true));
      edges.push({ points: [P(stubX, cy + D), P(stubX, joinY), P(cx, joinY)], noArrow: true });
      // Без else «Нет» всегда проходит насквозь (см. edges.push выше) — joinY
      // всегда достижим независимо от того, чем заканчивается ветка «Да».
      return { y: joinY, reachable: true };
    }
  }

  /* ── INSIDE LOOP, LAST ── */
  if (loopCtx) {
    const D = BS.BACK_DOWN;

    let yesBot = branchTop, yesLastLoop = null;
    if (node.yes.length > 0) {
      edges.push(ePath([P(cx - w/2, cy), P(cx - w/2, cy + D), P(yesCX, cy + D), P(yesCX, branchTop)], 'Да', 'left'));
      ({ bot: yesBot, lastLoop: yesLastLoop } = linSeq(node.yes, yesCX, branchTop, loopCtx, lnodes, edges));
    }
    const yesReturns = endsInReturn(node.yes);

    if (node.hasElse && node.no.length > 0) {
      edges.push(ePath([P(cx + w/2, cy), P(cx + w/2, cy + D), P(noCX, cy + D), P(noCX, branchTop)], 'Нет', 'right'));
      const { bot: noBot, lastLoop: noLastLoop } = linSeq(node.no, noCX, branchTop, loopCtx, lnodes, edges);
      const noReturns = endsInReturn(node.no);

      const yesJoin = node.yes.length > 0 ? yesBot : condBot;
      const joinY   = Math.max(yesJoin, noBot) + Math.round(BS.V_GAP / 2);

      if (node.yes.length > 0 && !yesReturns) {
        mergeFrom(yesLastLoop, yesCX, yesBot, cx, joinY);
      }
      if (!noReturns) mergeFrom(noLastLoop, noCX, noBot, cx, joinY);
      // Если обе ветки заканчиваются return — условие последнее в теле цикла,
      // и цикл на самом деле никогда не "продолжается" через эту точку:
      // обратная стрелка к началу цикла была бы висящей (см. баг №8).
      const reachableLast = (node.yes.length === 0 || !yesReturns) || !noReturns;
      if (reachableLast) edges.push(backArrow(cx, joinY, loopCtx));
      return { y: joinY, reachable: reachableLast };

    } else {
      const stubX = cx + w / 2 + 8;
      const joinY = (node.yes.length > 0 ? yesBot : condBot) + Math.round(BS.V_GAP / 2);

      if (node.yes.length > 0) {
        if (!yesReturns) mergeFrom(yesLastLoop, yesCX, yesBot, cx, joinY);
      } else {
        edges.push({ points: [P(cx - w/2, cy), P(cx - w/2, joinY), P(cx, joinY)],
                     label: 'Да', labelSide: 'left', noArrow: true });
      }
      edges.push(ePath([P(cx + w/2, cy), P(cx + w/2, cy + D), P(stubX, cy + D)], 'Нет', 'right', true));
      edges.push({ points: [P(stubX, cy + D), P(stubX, joinY), P(cx, joinY)], noArrow: true });
      // Без else «Нет» всегда проходит насквозь — joinY всегда достижим,
      // обратная стрелка к началу цикла всегда нужна.
      edges.push(backArrow(cx, joinY, loopCtx));
      return { y: joinY, reachable: true };
    }
  }

  /* ── TOP LEVEL ── */
  // YES branch
  let yesBot = branchTop, yesLastLoop = null;
  if (node.yes.length > 0) {
    edges.push(ePath([P(cx - w/2, cy), P(yesCX, cy), P(yesCX, branchTop)], 'Да', 'left'));
    ({ bot: yesBot, lastLoop: yesLastLoop } = linSeq(node.yes, yesCX, branchTop, null, lnodes, edges));
  }
  const yesReturns = endsInReturn(node.yes);

  // NO branch
  let noBot = branchTop, noLastLoop = null;
  const bpX = noCX + BS.ACTION_W / 2 + 8;
  if (node.hasElse && node.no.length > 0) {
    edges.push(ePath([P(cx + w/2, cy), P(noCX, cy), P(noCX, branchTop)], 'Нет', 'right'));
    ({ bot: noBot, lastLoop: noLastLoop } = linSeq(node.no, noCX, branchTop, null, lnodes, edges));
  } else {
    edges.push(ePath([P(cx + w/2, cy), P(bpX, cy)], 'Нет', 'right', true));
  }
  const noReturns = node.hasElse && endsInReturn(node.no);

  // Join Y
  const joinY = Math.max(yesBot, noBot) + BS.V_GAP;

  if (node.yes.length > 0) {
    if (!yesReturns) mergeFrom(yesLastLoop, yesCX, yesBot, cx, joinY);
  } else {
    mergeFrom(null, cx - w/2, cy, cx, joinY);
  }

  if (node.hasElse && node.no.length > 0) {
    if (!noReturns) mergeFrom(noLastLoop, noCX, noBot, cx, joinY);
  } else if (!node.hasElse) {
    edges.push({ points: [P(bpX, cy), P(bpX, joinY), P(cx, joinY)], noArrow: true });
  }

  // reachable: хотя бы одна ветка реально доходит до joinY. Если есть явный
  // else и обе ветки (yes и no) непустые и заканчиваются return — joinY
  // существует только как координата для позиционирования, но в неё ничего
  // не втекает (баг №8 — "дух"-стрелка между диаграммами функций).
  const yesReachable = node.yes.length === 0 || !yesReturns;
  const noReachable  = !node.hasElse || node.no.length === 0 || !noReturns;
  return { y: joinY, reachable: yesReachable || noReachable };
}

/* Lay out a branch sequence — pushes directly to lnodes/edges, returns bottom Y */
function linSeq(nodes, cx, y, loopCtx, lnodes, edges) {
  let bot      = y;
  let lastLoop = null;
  let joinY    = null;
  let joinReachable = false;   // false when joinY has no real incoming edge (dead-end branches)

  const flushJoin = (toY) => {
    if (joinY !== null) {
      if (joinReachable) edges.push(ePath([P(cx, joinY), P(cx, toY)]));
      joinY = null;
      joinReachable = false;
    }
  };

  for (let i = 0; i < nodes.length; i++) {
    const n       = nodes[i];
    const hasNext = i + 1 < nodes.length;

    if (n.type === 'loop') {
      flushJoin(bot);
      if (lastLoop) { edges.push(loopExitArrow(lastLoop, cx, bot)); resolveBreaks(lastLoop, cx, bot, edges); lastLoop = null; }
      const visBot = placeLoop(n, cx, bot, lnodes, edges);
      lastLoop = lnodes.find(ln => ln.id === n.id);
      bot = visBot;
      if (hasNext) bot += BS.V_GAP;

    } else if (n.type === 'condition') {
      flushJoin(bot);
      if (lastLoop) { edges.push(loopExitArrow(lastLoop, cx, bot)); resolveBreaks(lastLoop, cx, bot, edges); lastLoop = null; }
      const { y: j, reachable } = layoutCond(n, cx, bot, loopCtx, lnodes, edges, false);
      joinY    = j;
      joinReachable = reachable;
      lastLoop = null;
      bot = j;
      if (hasNext) bot += BS.V_GAP;

    } else if (n.type === 'break' || n.type === 'continue') {
      const ln  = mkNode(n, cx, bot);
      lnodes.push(ln);
      const top = ln.cy - ln.h / 2;
      if (lastLoop) { edges.push(loopExitArrow(lastLoop, cx, top)); resolveBreaks(lastLoop, cx, top, edges); lastLoop = null; }

      // Тупиковый узел — независимо от того, последний ли он в этой
      // последовательности, поток покидает её целиком.
      if (n.type === 'continue' && loopCtx) {
        edges.push(backArrow(cx, ln.cy + ln.h / 2, loopCtx));
      } else if (n.type === 'break' && loopCtx) {
        registerBreak(loopCtx, cx, ln.cy + ln.h / 2);
      }

      bot = ln.cy + ln.h / 2;
      if (hasNext) bot += BS.V_GAP;

    } else {
      const ln  = mkNode(n, cx, bot);
      lnodes.push(ln);
      const top = ln.cy - ln.h / 2;

      if (lastLoop) {
        edges.push(loopExitArrow(lastLoop, cx, top));
        resolveBreaks(lastLoop, cx, top, edges);
        lastLoop = null;
      } else {
        flushJoin(top);
      }

      bot = ln.cy + ln.h / 2;
      if (hasNext) bot += BS.V_GAP;
    }
  }

  return { bot, lastLoop };
}

/* ── Loop ─────────────────────────────────────────────────────────── */
function placeLoop(node, cx, topY, lnodes, edges) {
  const { w, h } = bsz('loop');
  const cy = topY + h / 2;
  const ln = { ...node, cx, cy, w, h };
  lnodes.push(ln);
  const frameStartIdx = lnodes.length - 1;  // index of this loop node in lnodes

  const loopBot = cy + h / 2;
  const bodyY   = loopBot + BS.V_GAP;
  const loopLX  = cx - w / 2;

  edges.push(ePath([P(cx, loopBot), P(cx, bodyY)]));

  let bodyBot      = bodyY;
  let visBot       = bodyY;
  let pendingJoinY  = null;   // join Y from a non-last condition → arrow to next element
  let pendingJoinReachable = false;   // false when pendingJoinY has no real incoming edge
  let lastInnerLoop = null;   // nested loop node → exit arrow to next element

  for (let bi = 0; bi < node.body.length; bi++) {
    const bn     = node.body[bi];
    const isLast = bi === node.body.length - 1;

    // Flush pending condition join
    if (pendingJoinY !== null) {
      if (pendingJoinReachable) edges.push(ePath([P(cx, pendingJoinY), P(cx, bodyBot)]));
      pendingJoinY = null;
      pendingJoinReachable = false;
    }

    // Flush exit arrow from previous nested loop
    if (lastInnerLoop !== null) {
      const rx = lastInnerLoop.cx + lastInnerLoop.w / 2;
      const D  = BS.BACK_DOWN;
      edges.push(ePath([P(rx, lastInnerLoop.cy), P(lastInnerLoop.frameRight, lastInnerLoop.cy),
                        P(lastInnerLoop.frameRight, bodyBot - D), P(cx, bodyBot - D), P(cx, bodyBot)]));
      resolveBreaks(lastInnerLoop, cx, bodyBot, edges);
      lastInnerLoop = null;
    }

    if (bn.type === 'condition') {
      const beforeLen = lnodes.length;

      if (isLast) {
        const { y: condJoinY } = layoutCond(bn, cx, bodyBot, ln, lnodes, edges);
        const { h: ch } = bsz('condition');
        bodyBot += ch;
        visBot = Math.max(visBot, condJoinY);
      } else {
        const { y: joinY, reachable } = layoutCond(bn, cx, bodyBot, ln, lnodes, edges, false);
        pendingJoinY = joinY;
        pendingJoinReachable = reachable;
        bodyBot = joinY;
      }

      for (let j = beforeLen; j < lnodes.length; j++) {
        visBot = Math.max(visBot, lnodes[j].cy + lnodes[j].h / 2);
      }

    } else if (bn.type === 'loop') {
      // Nested loop — recurse into placeLoop
      const innerVisBot = placeLoop(bn, cx, bodyBot, lnodes, edges);
      visBot   = Math.max(visBot, innerVisBot);
      bodyBot  = innerVisBot;

      if (isLast) {
        // Outer back arrow must originate from the inner loop's own hexagon
        // (its exit point), not from the last action inside its body.
        const innerLoopNode = lnodes.find(n => n.id === bn.id);
        edges.push(nestedLoopBackArrow(innerLoopNode, ln));
        // break внутри вложенного цикла, если сам он — последний оператор
        // внешнего, ведёт туда же, куда естественное завершение вложенного
        // цикла — к продолжению итерации внешнего (его собственный хексагон).
        resolveBreaks(innerLoopNode, ln.cx, ln.cy, edges, ln);
      } else {
        // Track for exit arrow to next body element
        lastInnerLoop = lnodes.find(n => n.id === bn.id);
      }

    } else if (bn.type === 'break' || bn.type === 'continue') {
      const bln = mkNode(bn, cx, bodyBot);
      lnodes.push(bln);
      bodyBot = bln.cy + bln.h / 2;
      visBot  = Math.max(visBot, bodyBot);

      // Оба — тупиковые узлы: поток покидает эту последовательность целиком,
      // независимо от того, последний ли это оператор тела (в отличие от
      // обычных операторов, где стрелка вниз рисуется только когда isLast).
      if (bn.type === 'continue') {
        edges.push(backArrow(cx, bodyBot, ln));
      } else {
        registerBreak(ln, cx, bodyBot);
      }

    } else {
      const bln = mkNode(bn, cx, bodyBot);
      lnodes.push(bln);
      bodyBot = bln.cy + bln.h / 2;
      visBot  = Math.max(visBot, bodyBot);

      if (isLast) {
        edges.push(backArrow(cx, bodyBot, ln));
      }
    }

    if (!isLast) { bodyBot += BS.V_GAP; visBot = Math.max(visBot, bodyBot); }
  }

  // ── Frame bounds ───────────────────────────────────────────────────
  // Expand from the loop hexagon outward, treating nested loop frames
  // as wider anchors so outer frames always enclose inner ones.
  let fL = cx - w / 2, fR = cx + w / 2;
  for (let j = frameStartIdx; j < lnodes.length; j++) {
    const nd = lnodes[j];
    if (nd.type === 'loop' && nd.frameLeft != null) {
      fL = Math.min(fL, nd.frameLeft  - BS.FRAME_NEST);
      fR = Math.max(fR, nd.frameRight + BS.FRAME_NEST);
    } else {
      fL = Math.min(fL, nd.cx - nd.w / 2);
      fR = Math.max(fR, nd.cx + nd.w / 2);
    }
  }
  ln.frameLeft  = fL - BS.FRAME_PAD_X;
  ln.frameRight = fR + BS.FRAME_PAD_X;
  ln.frameTop   = topY   - BS.FRAME_PAD_Y;
  ln.frameBot   = visBot + BS.FRAME_PAD_Y;
  // ───────────────────────────────────────────────────────────────────

  return visBot;   // caller (layoutSeq) uses this to position post-loop content
}

/* ── Helpers ──────────────────────────────────────────────────────── */
function P(x, y) { return { x, y }; }

function ePath(points, label, labelSide, noArrow) {
  return { points, label, labelSide, noArrow: !!noArrow };
}

/* Lazy back-arrow: stores a reference to the loop node.
   Resolved after all frames are computed via resolveBackArrows(). */
function backArrow(fromX, fromY, loopNode) {
  return { isBackArrow: true, fromX, fromY, loopNode };
}

/* Lazy "nested loop exit" back-arrow: when a loop is the LAST element of its
   parent's body, the parent's back-arrow must originate from the inner
   loop's own hexagon (its exit point), not from the last action inside its
   body. Routes right around the inner loop first (clearing both its shape
   and its own back-arrow sweep) before joining the parent's frame border. */
function nestedLoopBackArrow(innerLoopNode, outerLoopNode) {
  return { isNestedLoopBackArrow: true, innerLoopNode, outerLoopNode };
}

/* Lazy general-purpose "exit via hexagon" connector: whenever a sequence
   of statements (a condition branch, a loop body, ...) ends in a loop,
   anything that connects FROM the end of that sequence must originate
   from the loop's own hexagon — never from the last action inside it.
   Generalizes nestedLoopBackArrow's routing (right tip → frameRight →
   clear below its own back-arrow sweep) to an arbitrary destination
   point, instead of only "back to the parent loop's header". */
function loopExitConnector(loopNode, toX, toY) {
  return { isLoopExitConnector: true, loopNode, toX, toY };
}

/* Resolve all lazy back arrows once every loop has its frame set. */
function resolveBackArrows(edges) {
  for (const e of edges) {
    if (e.isBackArrow) {
      const ln  = e.loopNode;
      const lx  = ln.cx - ln.w / 2;   // loop hexagon left tip
      const D   = BS.BACK_DOWN;
      e.points  = [
        P(e.fromX, e.fromY),          // start at bottom of element
        P(e.fromX, e.fromY + D),      // go down a little first
        P(ln.frameLeft, e.fromY + D), // go left to frame border
        P(ln.frameLeft, ln.cy),       // go up along frame border
        P(lx, ln.cy),                 // go right into loop hexagon
      ];
      delete e.isBackArrow;
      delete e.loopNode;
      delete e.fromX;
      delete e.fromY;

    } else if (e.isNestedLoopBackArrow) {
      const inner = e.innerLoopNode;
      const outer = e.outerLoopNode;
      const D     = BS.BACK_DOWN;
      const innerRx  = inner.cx + inner.w / 2;   // inner loop's right tip
      const outerLx  = outer.cx - outer.w / 2;   // outer loop's left tip
      const clearY   = inner.frameBot + D;       // below inner loop's own back-arrow sweep
      e.points = [
        P(innerRx, inner.cy),                 // start at inner loop's exit point
        P(inner.frameRight, inner.cy),        // clear the hexagon shape
        P(inner.frameRight, clearY),          // go down, past inner's own back-arrow
        P(outer.frameLeft, clearY),           // go left to outer's frame border
        P(outer.frameLeft, outer.cy),         // go up along outer's frame border
        P(outerLx, outer.cy),                 // go right into outer loop hexagon
      ];
      delete e.isNestedLoopBackArrow;
      delete e.innerLoopNode;
      delete e.outerLoopNode;

    } else if (e.isBreakToOuter) {
      // break внутри вложенного цикла, ведущий к продолжению внешнего —
      // намеренно проведён к ТОЙ ЖЕ границе (targetLoopNode.frameLeft) и в
      // ту же точку входа (левый кончик хексагона), что и родная стрелка
      // возврата внешнего цикла выше (см. isNestedLoopBackArrow) — визуально
      // сливается с ней, а не идёт рядом отдельной почти-параллельной линией.
      const D = BS.BACK_DOWN;
      const clearY  = e.loopNode.frameBot + D;   // ниже рамки СВОЕГО (внутреннего) цикла целиком
      const outer   = e.targetLoopNode;
      const outerLx = outer.cx - outer.w / 2;
      e.points = [
        P(e.fromCx, e.fromBottomY),
        P(e.fromCx, clearY),
        P(outer.frameLeft, clearY),
        P(outer.frameLeft, e.targetY),
        P(outerLx, e.targetY),
      ];
      delete e.isBreakToOuter;
      delete e.fromCx;
      delete e.fromBottomY;
      delete e.loopNode;
      delete e.targetCx;
      delete e.targetY;
      delete e.targetLoopNode;

    } else if (e.isLoopExitConnector) {
      const ln     = e.loopNode;
      const rx     = ln.cx + ln.w / 2;        // loop's own exit point
      const D      = BS.BACK_DOWN;
      const clearY = ln.frameBot + D;          // below its own back-arrow sweep
      const tail   = Math.abs(ln.frameRight - e.toX) < 2
        ? [P(e.toX, clearY), P(e.toX, e.toY)]
        : [P(ln.frameRight, clearY), P(e.toX, clearY), P(e.toX, e.toY)];
      e.points = [P(rx, ln.cy), P(ln.frameRight, ln.cy), ...tail];
      delete e.isLoopExitConnector;
      delete e.loopNode;
      delete e.toX;
      delete e.toY;
    }
  }
}

/* ═══════════════════════════════════════════════════════════════════
   LAYER 3 — SVG RENDERER
   ═══════════════════════════════════════════════════════════════════ */

function renderSVG(lnodes, edges) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const grow = (x, y) => {
    if (x < x0) x0=x; if (y < y0) y0=y; if (x > x1) x1=x; if (y > y1) y1=y;
  };
  lnodes.forEach(n => { grow(n.cx-n.w/2,n.cy-n.h/2); grow(n.cx+n.w/2,n.cy+n.h/2); });
  edges.forEach(e => (e.points||[]).forEach(p => grow(p.x, p.y)));

  const pad = BS.SVG_PAD;
  x0-=pad; y0-=pad; x1+=pad; y1+=pad;
  const W=x1-x0, H=y1-y0;

  let s = `<svg id="bs-svg" xmlns="http://www.w3.org/2000/svg"
    width="${W}" height="${H}" viewBox="${x0} ${y0} ${W} ${H}">
  <defs>
    <style>
      .bs-terminal  {fill:var(--bs-terminal-fill);stroke:var(--bs-terminal-stroke);stroke-width:1.5}
      .bs-assignment{fill:var(--bs-assign-fill);stroke:var(--bs-assign-stroke);stroke-width:1.5}
      .bs-action    {fill:var(--bs-action-fill);stroke:var(--bs-action-stroke);stroke-width:1.5}
      .bs-condition {fill:var(--bs-cond-fill);stroke:var(--bs-cond-stroke);stroke-width:1.5}
      .bs-loop      {fill:var(--bs-loop-fill);stroke:var(--bs-loop-stroke);stroke-width:1.5}
      .bs-return    {fill:var(--bs-return-fill);stroke:var(--bs-return-stroke);stroke-width:1.5}
      .bs-import    {fill:var(--bs-import-fill);stroke:var(--bs-import-stroke);stroke-width:1.5}
      .bs-import-bar{stroke:var(--bs-import-stroke);stroke-width:1.5}
      .bs-terminal-txt  {fill:var(--bs-terminal-text)}
      .bs-assignment-txt{fill:var(--bs-assign-text)}
      .bs-action-txt    {fill:var(--bs-action-text)}
      .bs-condition-txt {fill:var(--bs-cond-text)}
      .bs-loop-txt      {fill:var(--bs-loop-text)}
      .bs-return-txt    {fill:var(--bs-return-text)}
      .bs-import-txt    {fill:var(--bs-import-text)}
      .bs-edge      {fill:none;stroke:var(--bs-edge);stroke-width:1.5}
      .bs-arrowhead {fill:var(--bs-edge)}
      .bs-label-yes {fill:var(--bs-yes);font-size:12px;font-weight:600;font-family:Inter,sans-serif}
      .bs-label-no  {fill:var(--bs-no);font-size:12px;font-weight:600;font-family:Inter,sans-serif}
      .bs-loop-frame{display:none}
    </style>
    <marker id="ar" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">
      <polygon class="bs-arrowhead" points="0 0,8 3,0 6"/>
    </marker>
  </defs>`;

  // Loop frames — rendered behind edges and blocks
  lnodes.forEach(n => {
    if (n.type === 'loop' && n.frameLeft != null) {
      const fw = f(n.frameRight - n.frameLeft);
      const fh = f(n.frameBot   - n.frameTop);
      s += `<rect class="bs-loop-frame" x="${f(n.frameLeft)}" y="${f(n.frameTop)}" width="${fw}" height="${fh}" rx="12"/>`;
    }
  });
  edges.forEach(e  => { s += drawEdge(e); });
  lnodes.forEach(n => {
    if (n.line != null || n.role) {
      const lineAttr = n.line != null ? ` data-line="${n.line}"` : '';
      const roleAttr = n.role ? ` data-role="${n.role}"` : '';
      s += `<g${lineAttr} data-type="${n.type}"${roleAttr}>${drawBlock(n)}</g>`;
    } else {
      s += drawBlock(n);
    }
  });
  return s + '</svg>';
}

function drawEdge(e) {
  if (!e.points || e.points.length < 2) return '';
  const d = e.points.map((p,i) => (i?'L':'M')+` ${f(p.x)} ${f(p.y)}`).join(' ');
  const mk = e.noArrow ? '' : ' marker-end="url(#ar)"';
  let r = `<path class="bs-edge" d="${d}"${mk}/>`;
  if (e.label) {
    const lp  = labelPos(e.points, e.labelSide);
    const cls = e.label === 'Да' ? 'bs-label-yes' : e.label === 'Нет' ? 'bs-label-no' : 'bs-label';
    r += `<text class="${cls}" x="${f(lp.x)}" y="${f(lp.y)}"
      text-anchor="${lp.anc}" dominant-baseline="middle">${e.label}</text>`;
  }
  return r;
}

function labelPos(pts, side) {
  let p0 = pts[0], p1 = pts[1];
  // If the first segment is a tiny exit-step (< 20px), use the next segment for the label
  if (pts.length > 2 && Math.abs(p1.x - p0.x) + Math.abs(p1.y - p0.y) < 20) {
    p0 = pts[1]; p1 = pts[2];
  }
  const mx=(p0.x+p1.x)/2, my=(p0.y+p1.y)/2;
  if (side==='left')  return { x: mx-12, y: my-8, anc: 'end'    };
  if (side==='right') return { x: mx+12, y: my-8, anc: 'start'  };
  return { x: mx, y: my-10, anc: 'middle' };
}

function drawBlock(n) {
  switch (n.type) {
    case 'assignment': return drawPara(n);
    case 'condition':  return drawDiam(n);
    case 'loop':       return drawHex(n);
    case 'terminal':   return drawOval(n);
    case 'return':     return drawTrap(n);
    case 'import':     return drawPredefinedProcess(n);
    default:           return drawRect(n);
  }
}

/* ── Block shapes — colours via CSS classes / SVG <style> ─────────── */
const TYPE_CLS = {
  terminal: 'bs-terminal', assignment: 'bs-assignment',
  action: 'bs-action', condition: 'bs-condition', loop: 'bs-loop',
  return: 'bs-return', import: 'bs-import',
};
const TXT_CLS = {
  terminal: 'bs-terminal-txt', assignment: 'bs-assignment-txt',
  action: 'bs-action-txt', condition: 'bs-condition-txt', loop: 'bs-loop-txt',
  return: 'bs-return-txt', import: 'bs-import-txt',
};

function drawOval(n) {
  const {cx,cy,w,h}=n;
  return `<ellipse class="${TYPE_CLS[n.type]||'bs-action'}" cx="${f(cx)}" cy="${f(cy)}" rx="${f(w/2)}" ry="${f(h/2)}"/>${drawTxt(n)}`;
}
function drawPara(n) {
  const {cx,cy,w,h}=n, sk=BS.ASSIGN_SKEW;
  const pts=`${f(cx-w/2+sk)},${f(cy-h/2)} ${f(cx+w/2+sk)},${f(cy-h/2)} ${f(cx+w/2-sk)},${f(cy+h/2)} ${f(cx-w/2-sk)},${f(cy+h/2)}`;
  return `<polygon class="${TYPE_CLS[n.type]||'bs-action'}" points="${pts}"/>${drawTxt(n)}`;
}
function drawRect(n) {
  const {cx,cy,w,h}=n;
  return `<rect class="${TYPE_CLS[n.type]||'bs-action'}" x="${f(cx-w/2)}" y="${f(cy-h/2)}" width="${w}" height="${h}" rx="${BS.ACTION_RX}" ry="${BS.ACTION_RX}"/>${drawTxt(n)}`;
}
function drawDiam(n) {
  const {cx,cy,w,h}=n;
  const pts=`${f(cx)},${f(cy-h/2)} ${f(cx+w/2)},${f(cy)} ${f(cx)},${f(cy+h/2)} ${f(cx-w/2)},${f(cy)}`;
  return `<polygon class="${TYPE_CLS[n.type]||'bs-action'}" points="${pts}"/>${drawTxt(n)}`;
}
function drawHex(n) {
  const {cx,cy,w,h}=n, fl=BS.LOOP_FLAT/2;
  const pts=`${f(cx-fl)},${f(cy-h/2)} ${f(cx+fl)},${f(cy-h/2)} ${f(cx+w/2)},${f(cy)} ${f(cx+fl)},${f(cy+h/2)} ${f(cx-fl)},${f(cy+h/2)} ${f(cx-w/2)},${f(cy)}`;
  return `<polygon class="${TYPE_CLS[n.type]||'bs-action'}" points="${pts}"/>${drawTxt(n)}`;
}
/* Перевёрнутая трапеция для return — уже сверху, шире снизу; тупиковый
   блок (без исходящей стрелки), в отличие от параллелограмма присваивания. */
function drawTrap(n) {
  const {cx,cy,w,h}=n, sk=BS.RETURN_SKEW, topHalf=w/2-sk, botHalf=w/2;
  const pts=`${f(cx-topHalf)},${f(cy-h/2)} ${f(cx+topHalf)},${f(cy-h/2)} ${f(cx+botHalf)},${f(cy+h/2)} ${f(cx-botHalf)},${f(cy+h/2)}`;
  return `<polygon class="${TYPE_CLS[n.type]||'bs-action'}" points="${pts}"/>${drawTxt(n)}`;
}
/* «Предопределённый процесс» — прямоугольник с двумя вертикальными чертами
   у краёв (классический флоучарт-символ вызова готового модуля/подпрограммы).
   Используется для строк import ... / from ... import ... */
function drawPredefinedProcess(n) {
  const {cx,cy,w,h}=n, inset=8;
  const rect = `<rect class="${TYPE_CLS[n.type]||'bs-action'}" x="${f(cx-w/2)}" y="${f(cy-h/2)}" width="${w}" height="${h}" rx="${BS.ACTION_RX}" ry="${BS.ACTION_RX}"/>`;
  const bars = [cx-w/2+inset, cx+w/2-inset]
    .map(x => `<line class="bs-import-bar" x1="${f(x)}" y1="${f(cy-h/2)}" x2="${f(x)}" y2="${f(cy+h/2)}"/>`)
    .join('');
  return `${rect}${bars}${drawTxt(n)}`;
}

/* ── Typography helpers ───────────────────────────────────────────── */

// Max chars per line and max lines per block type
const TYPE_WRAP = {
  terminal:   { maxChars: 14, maxLines: 2 },   // 2 lines: "Начало (name)" can be longer than plain "Начало"/"Конец"
  assignment: { maxChars: 20, maxLines: 2 },
  action:     { maxChars: 18, maxLines: 2 },
  condition:  { maxChars: 15, maxLines: 2 },
  loop:       { maxChars: 22, maxLines: 2 },
  return:     { maxChars: 20, maxLines: 2 },
  import:     { maxChars: 18, maxLines: 2 },
};

// Split into "words" for wrapping, but spaces inside ( ) or [ ] never split
// a word — arr[j + 1] and range(n - i - 1) stay whole.
function splitWords(label) {
  const words = [];
  let cur = '';
  let depth = 0;
  for (const ch of label) {
    if (ch === '(' || ch === '[') depth++;
    else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1);

    if (/\s/.test(ch) && depth === 0) {
      if (cur) words.push(cur);
      cur = '';
    } else {
      cur += ch;
    }
  }
  if (cur) words.push(cur);
  return words;
}

// Greedy word-wrap: returns array of lines
function wrapLabel(label, type) {
  const { maxChars, maxLines } = TYPE_WRAP[type] || { maxChars: 18, maxLines: 2 };
  if (label.length <= maxChars) return [label];

  const words = splitWords(label);
  if (words.length <= 1) return [label];   // single word, can't wrap

  const lines = [];
  let cur = words[0];

  for (let i = 1; i < words.length; i++) {
    if (cur.length + 1 + words[i].length <= maxChars) {
      cur += ' ' + words[i];
    } else {
      lines.push(cur);
      if (lines.length >= maxLines - 1) {
        cur = words.slice(i).join(' ');   // last line gets all remaining words
        break;
      }
      cur = words[i];
    }
  }
  lines.push(cur);
  return lines;
}

// Scale font size: larger for short labels, smaller for long / multi-line
function bsFontSize(label, numLines) {
  if (numLines > 1) return 10;
  const len = label.length;
  if (len <= 6)  return 14;
  if (len <= 12) return 13;
  if (len <= 18) return 12;
  if (len <= 24) return 11;
  return 10;
}

function drawTxt(n) {
  const lines  = wrapLabel(n.label, n.type);
  const fs     = bsFontSize(n.label, lines.length);
  const lineH  = Math.round(fs * 1.3);
  const cls    = TXT_CLS[n.type] || 'bs-action-txt';
  const common = `font-size="${fs}" font-family="Inter,sans-serif" font-weight="500" text-anchor="middle" dominant-baseline="middle"`;

  if (lines.length === 1) {
    return `<text class="${cls}" x="${f(n.cx)}" y="${f(n.cy)}" ${common}>${xe(lines[0])}</text>`;
  }

  // Multi-line: first tspan anchored so the whole block is vertically centred at n.cy
  const y0 = f(n.cy - (lines.length - 1) * lineH / 2);
  const tspans = lines.map((l, i) =>
    i === 0
      ? `<tspan x="${f(n.cx)}" y="${y0}">${xe(l)}</tspan>`
      : `<tspan x="${f(n.cx)}" dy="${lineH}">${xe(l)}</tspan>`
  ).join('');

  return `<text class="${cls}" ${common}>${tspans}</text>`;
}

function f(v)  { return Math.round(v*10)/10; }
function xe(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

/* ─── Add implicit vertical arrows between consecutive same-column nodes ─── */
function addColArrows(lnodes, edges) {
  const cols = {};
  lnodes.forEach(n => { const k=Math.round(n.cx); (cols[k]=cols[k]||[]).push(n); });
  Object.values(cols).forEach(col => {
    col.sort((a,b)=>a.cy-b.cy);
    for (let i=0; i<col.length-1; i++) {
      const a=col[i], b=col[i+1];
      if (a.type === 'return') continue;   // тупиковый блок — никогда не тянем стрелку вниз
      const aBot=a.cy+a.h/2, bTop=b.cy-b.h/2;
      const gap=bTop-aBot;
      if (gap<=0 || gap>BS.V_GAP*2.2) continue;
      // Skip if an edge already starts near aBot (back arrow, explicit edge, etc.)
      const used = edges.some(e => e.points && e.points.length>0
        && Math.abs(e.points[0].x - a.cx)<4
        && Math.abs(e.points[0].y - aBot)<4);
      if (!used) edges.push({ points:[P(a.cx,aBot),P(b.cx,bTop)] });
    }
  });
}

/* ═══════════════════════════════════════════════════════════════════
   PUBLIC API
   ═══════════════════════════════════════════════════════════════════ */

let bsLnodes = [];   // last built layout — needed by the flow-cursor path finder (step 4.1)
let bsEdges  = [];
let bsPathCache = new Map();   // "fromLine->toLine" → resolved path | null (no path found)

function startBlockScheme(code) {
  try {
    const { tree, functions } = parseCode(code);
    const { lnodes, edges } = layoutProgram(tree, functions);
    resolveBackArrows(edges);   // must run before addColArrows
    addColArrows(lnodes, edges);
    document.getElementById('bs-canvas').innerHTML = renderSVG(lnodes, edges);
    bsLnodes = lnodes;
    bsEdges  = edges;
    bsPathCache = new Map();
    bsBuildCodeDisplay(code);
    bsStopAutoplay();
    bsStepIndex  = -1;
    bsPrevVars   = {};
    bsPrevOutput = [];
    bsAnimating  = false;
    bsRenderVars({}, []);
    bsRenderConsole([]);
    bsHideTraceStatus();
    bsUpdateControls();
  } catch (err) {
    document.getElementById('bs-canvas').innerHTML =
      `<div style="color:red;padding:16px">Ошибка построения схемы: ${xe(err.message)}</div>`;
    console.error('[BlockScheme]', err);
  }
}

/* ── Trace state (consumed by playback features — steps 3.3+) ───────
   The static diagram above never depends on this: it's a best-effort
   background fetch that lets later steps drive highlighting/playback. */
let bsTrace    = { steps: null, error: null, truncated: false };
let bsTraceGen = 0;   // guards against a stale (slow) response overwriting a newer one

function getBlockSchemeTrace() { return bsTrace; }

/* scope_id (уникален для каждого конкретного вызова, в т.ч. рекурсивного) →
   строка, с которой этот вызов был сделан. Строится один раз на всю
   трассировку: строка непосредственно ПЕРЕД 'call'-шагом всегда и есть
   место вызова — работает одинаково для любого блока, включая рекурсию
   и вызов одной функции из другой. Используется, чтобы отправить
   значение return обратно туда, откуда был сделан именно этот вызов. */
function buildCallSiteMap(steps) {
  const map = new Map();
  for (let i = 1; i < steps.length; i++) {
    if (steps[i].event === 'call') map.set(steps[i].scope_id, steps[i - 1].line);
  }
  return map;
}
let bsCallSiteLine = new Map();

async function loadBlockSchemeTrace(code, fileContent) {
  const gen = ++bsTraceGen;
  bsTrace = { steps: null, error: null, truncated: false };
  bsHideTraceStatus();
  try {
    const result = await traceCode(code, fileContent);
    if (gen !== bsTraceGen) return;   // a newer call already superseded this one
    bsTrace = {
      steps:     result.steps || [],
      error:     result.error || null,
      truncated: !!result.truncated,
    };
    bsCallSiteLine = buildCallSiteMap(bsTrace.steps);
    if (bsTrace.error) {
      bsShowTraceStatus(`Трассировка недоступна: ${bsTrace.error.message}`, true);
    } else if (bsTrace.truncated) {
      bsShowTraceStatus('Код содержит более 1500 шагов — показаны первые 1500', false);
    }
    if (bsTrace.steps.length) {
      bsShowStartState();   // стоп на "Начало" — первый клик "дальше" пустит шарик к первому блоку
    } else {
      bsUpdateControls();         // no steps at all — keep buttons disabled
    }
  } catch (err) {
    if (gen !== bsTraceGen) return;
    // Server unreachable/erroring — static diagram stays usable, just no trace data
    bsTrace = { steps: null, error: { message: err.message }, truncated: false };
    bsShowTraceStatus(`Не удалось загрузить трассировку: ${err.message}`, true);
    bsUpdateControls();
  }
}

/* Trace status banner — surfaces runtime errors, validation errors, and
   step-limit (MAX_STEPS) truncation that loadBlockSchemeTrace() already
   detects but previously left unreported in the UI. */
function bsShowTraceStatus(message, isError) {
  const el  = document.getElementById('bs-trace-warn');
  const txt = document.getElementById('bs-trace-warn-text');
  if (!el || !txt) return;
  txt.textContent = message;
  el.className = isError ? 'error-banner' : 'warn-banner';
}

function bsHideTraceStatus() {
  const el = document.getElementById('bs-trace-warn');
  if (el) el.className = 'hidden';
}

/* ── Code panel + active-step highlighting (step 3.3) ────────────────
   bsBuildCodeDisplay/bsSetActiveLine mirror editor.js's Classic View
   helpers but operate on a fully separate panel (#bs-code-display,
   .bs-code-line) so the two views never share mutable DOM state. */
let bsStepIndex = -1;

function bsBuildCodeDisplay(code) {
  const display = document.getElementById('bs-code-display');
  if (!display) return;
  display.innerHTML = '';
  code.split('\n').forEach((line, idx) => {
    const row = document.createElement('div');
    row.className = 'bs-code-line';
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

function bsSetActiveLine(lineNum) {
  document.querySelectorAll('.bs-code-line').forEach(el => el.classList.remove('active'));
  const target = document.querySelector(`.bs-code-line[data-line="${lineNum}"]`);
  if (target) {
    target.classList.add('active');
    target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

/* isReturn — true, когда текущий шаг трассировки сам является событием
   'return' (не просто 'line'). Условие с однострочным телом (if x: return y)
   делит номер строки со своим return — на обычном 'line'-шаге ветка ещё
   могла не сработать (условие ложно), поэтому по умолчанию подсвечивается
   заголовок условия; но если это именно 'return'-событие, ветка точно
   взята, и подсветку нужно переключить на сам блок return (по вложенному
   элементу с классом .bs-return — сам data-line стоит на обёртке <g>,
   у которой своего класса формы нет). */
/* "Начало"/"Конец" главной программы не привязаны ни к одной строке кода
   (см. layoutProgram) — обычный bsFindNodeByLine их не находит, ищем по
   отдельной метке role, проставленной только этим двум узлам. */
function bsFindByRole(role) {
  return bsLnodes.find(n => n.role === role);
}

function bsHighlightRole(role) {
  const svg = document.getElementById('bs-svg');
  if (!svg) return;
  svg.querySelectorAll('.bs-block-active').forEach(el => el.classList.remove('bs-block-active'));
  const target = svg.querySelector(`[data-role="${role}"]`);
  if (target) target.classList.add('bs-block-active');
}

/* Несколько узлов на одной строке — обычный случай для однострочных
   if/for (expandInlineBodies) и теперь ещё для decomposed comprehension
   (loop+condition+action на line comprehension'а). И там, и там наиболее
   содержательный узел — не сам loop/condition-"заголовок", а то, что
   внутри (action/return/assignment) — если такого нет (напр. any()/all()
   без action-узла), берём condition, и только потом loop как последний
   резерв. */
function bsPreferredMatch(matches) {
  if (matches.length <= 1) return matches[0] || null;
  const list = Array.from(matches);
  return list.find(el => el.dataset.type !== 'condition' && el.dataset.type !== 'loop')
      || list.find(el => el.dataset.type !== 'loop')
      || list[0];
}

function bsSetActiveBlock(lineNum, isReturn) {
  const svg = document.getElementById('bs-svg');
  if (!svg) return;
  svg.querySelectorAll('.bs-block-active').forEach(el => el.classList.remove('bs-block-active'));
  const matches = svg.querySelectorAll(`[data-line="${lineNum}"]`);
  let target = bsPreferredMatch(matches);
  if (isReturn) {
    const returnMatch = Array.from(matches).find(el => el.querySelector('.bs-return'));
    if (returnMatch) target = returnMatch;
  }
  if (target) {
    target.classList.add('bs-block-active');
    target.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

function renderBlockSchemeStep(index) {
  const steps = bsTrace.steps;
  if (!steps || !steps.length) return;
  bsStepIndex = Math.max(0, Math.min(index, steps.length - 1));
  const step = steps[bsStepIndex];
  if (!step) return;

  if (step.line != null) {
    bsSetActiveLine(step.line);
    bsSetActiveBlock(step.line, step.event === 'return');
  }

  const vars   = step.variables || {};
  const output = step.output    || [];
  const changedVars = Object.keys(vars).filter(
    k => JSON.stringify(vars[k]) !== JSON.stringify(bsPrevVars[k])
  );
  bsRenderVars(vars, changedVars);
  bsRenderConsole(output);
  bsPrevVars   = { ...vars };
  bsPrevOutput = [...output];
  bsUpdateControls();
}

/* Состояние "до первого шага" — bsStepIndex = -1, подсвечен овал "Начало",
   панели пустые. Раньше запуск сразу подсвечивал первое действие, минуя
   "Начало" целиком; теперь это отдельная остановка, с которой первый клик
   "дальше" анимирует шарик от "Начало" к первому реальному блоку (см.
   bsStepNext). */
function bsShowStartState() {
  bsStepIndex  = -1;
  bsPrevVars   = {};
  bsPrevOutput = [];
  bsSetActiveLine(null);
  bsHighlightRole('start');
  bsRenderVars({}, []);
  bsRenderConsole([]);
  bsUpdateControls();
}

/* Симметричное состояние "после последнего шага" — bsStepIndex = steps.length
   (на единицу больше последнего реального индекса), подсвечен овал "Конец".
   Переменные/консоль оставляем как после последнего реального шага —
   меняется только то, что подсвечено на диаграмме. */
function bsShowEndState() {
  const steps = bsTrace.steps;
  if (!steps || !steps.length) return;
  renderBlockSchemeStep(steps.length - 1);
  bsStepIndex = steps.length;
  bsSetActiveLine(null);
  bsHighlightRole('end');
  bsUpdateControls();
}

let bsAnimating = false;   // guards against overlapping token flights from rapid key presses

function bsStepPrev() {
  if (bsAnimating || bsStepIndex === -1) return;
  if (bsStepIndex === 0) { bsShowStartState(); return; }   // назад в "Начало"
  renderBlockSchemeStep(bsStepIndex - 1);   // snap back, no token animation (mirrors Classic View)
                                             // из состояния "Конец" (bsStepIndex===steps.length)
                                             // корректно возвращает на последний реальный шаг
}

/* Forward step: diff current vs. next step, fly one token per changed
   variable + one for new console output, then commit the new state.
   Reuses animator.js's animateBall()/formatValue() — generic, no DOM
   assumptions tied to Classic View — rather than duplicating GSAP code. */
function bsStepNext(onDone) {
  if (bsAnimating) return;   // ignore presses while a token is mid-flight
  const steps = bsTrace.steps;
  if (!steps || !steps.length) { if (onDone) onDone(); return; }

  // Уже на "Конец" (bsStepIndex === steps.length) — дальше идти некуда.
  if (bsStepIndex >= steps.length) { if (onDone) onDone(); return; }

  // "Начало" → первый реальный шаг: шарик летит от овала "Начало" к первому
  // подсвеченному блоку, вместо того чтобы тот сразу оказывался подсвечен
  // без всякого перехода.
  if (bsStepIndex === -1) {
    const startNode = bsFindByRole('start');
    const firstStep = steps[0];
    const toNode = firstStep.line != null ? bsFindNodeByLine(firstStep.line) : null;
    const commit = () => { renderBlockSchemeStep(0); if (onDone) onDone(); };
    if (startNode && toNode) {
      bsAnimating = true;
      bsAnimateFlowCursor([P(startNode.cx, startNode.cy), P(toNode.cx, toNode.cy)], null, () => {
        bsAnimating = false;
        commit();
      });
    } else {
      commit();
    }
    return;
  }

  // Последний реальный шаг → "Конец": симметрично — шарик летит от последнего
  // подсвеченного блока к овалу "Конец", вместо того чтобы работа тихо
  // обрывалась на последнем действии без видимого завершения.
  if (bsStepIndex === steps.length - 1) {
    const lastStep  = steps[bsStepIndex];
    const endNode   = bsFindByRole('end');
    const fromNode  = lastStep.line != null ? bsFindNodeByLine(lastStep.line) : null;
    const commit = () => { bsShowEndState(); if (onDone) onDone(); };
    if (fromNode && endNode) {
      bsAnimating = true;
      bsAnimateFlowCursor([P(fromNode.cx, fromNode.cy), P(endNode.cx, endNode.cy)], null, () => {
        bsAnimating = false;
        commit();
      });
    } else {
      commit();
    }
    return;
  }

  const curStep  = steps[bsStepIndex];
  const nextIdx  = bsStepIndex + 1;
  const nextStep = steps[nextIdx];

  const curVars  = curStep.variables  || {};
  const nextVars = nextStep.variables || {};
  const curOut   = curStep.output     || [];
  const nextOut  = nextStep.output    || [];

  const changedVars = Object.keys(nextVars).filter(
    k => JSON.stringify(nextVars[k]) !== JSON.stringify(curVars[k])
  );
  const newLines = nextOut.slice(curOut.length);

  // Flow cursor (вариант A, баг №10): раньше был "чисто декоративным",
  // запускался параллельно и не учитывался при переходе к следующему шагу —
  // на длинных стрелках (длительность растёт с длиной пути, см.
  // BS_FLOW_MAX_MS) серый шарик мог долетать позже, чем уже стартовали
  // шарики следующего шага. Теперь каждый запуск кладётся в pending[] и
  // считается наравне с шариками переменных/консоли — следующий шаг стартует
  // только когда реально приземлилось всё, включая серый шарик.
  const pending = [];   // each: (done) => void — done() вызывается по приземлению

  if (nextStep.event === 'call') {
    // Entering a function (incl. recursive self-calls and calls made from
    // inside another function's own diagram) — args fly on an invisible
    // straight line from the call-site block to that function's "Начало".
    const fromNode = bsFindNodeByLine(curStep.line);
    const toNode   = bsFindNodeByLine(nextStep.line);
    if (fromNode && toNode) {
      const path = [P(fromNode.cx, fromNode.cy), P(toNode.cx, toNode.cy)];
      const args = Object.entries(nextStep.args || {});
      if (args.length === 0) {
        pending.push(done => bsAnimateFlowCursor(path, null, done));
      } else {
        const stagger = BS_FLOW_STAGGER_MS / bsSpeed;
        args.forEach(([name, val], i) => {
          const label = `${name}=${formatValue(val)}`;
          pending.push(done => setTimeout(() => bsAnimateFlowCursor(path, label, done), i * stagger));
        });
      }
    }
  } else if (nextStep.event === 'return') {
    // Leaving a function — the returned value flies back to wherever THIS
    // specific call instance was made from (scope_id-keyed, so recursion
    // and nested cross-function calls resolve to the correct call site).
    const callSiteLine = bsCallSiteLine.get(nextStep.scope_id);
    const fromNode = bsFindNodeByLine(nextStep.line);
    const toNode   = callSiteLine != null ? bsFindNodeByLine(callSiteLine) : null;
    if (fromNode && toNode) {
      const path = [P(fromNode.cx, fromNode.cy), P(toNode.cx, toNode.cy)];
      pending.push(done => bsAnimateFlowCursor(path, formatValue(nextStep.return_value), done));
    }
  } else if (curStep.line != null && nextStep.line != null && curStep.line !== nextStep.line) {
    const path = bsFindEdgePath(curStep.line, nextStep.line);
    if (path) {
      if (changedVars.length === 0) {
        pending.push(done => bsAnimateFlowCursor(path, null, done));
      } else {
        const stagger = BS_FLOW_STAGGER_MS / bsSpeed;   // 4.4: relay pacing follows playback speed too
        changedVars.forEach((varName, i) => {
          const label = `${varName}=${formatValue(nextVars[varName])}`;
          pending.push(done => setTimeout(() => bsAnimateFlowCursor(path, label, done), i * stagger));
        });
      }
    }
  }

  // curStep being a 'return' event means control is conceptually already back
  // at the call site, not still on the return statement's own line — any new
  // output/variables reported on nextStep really belong there. Reuses
  // bsCallSiteLine (the same scope_id → call-site-line map the call/return
  // flow-chips already use) instead of the plain "last active block" lookup.
  let srcEl = document.querySelector('#bs-svg .bs-block-active');
  if (curStep.event === 'return') {
    const callSiteLine = bsCallSiteLine.get(curStep.scope_id);
    if (callSiteLine != null) {
      const callSiteEl = document.querySelector(`#bs-svg [data-line="${callSiteLine}"]`);
      if (callSiteEl) srcEl = callSiteEl;
    }
  }
  const hasCon = newLines.length > 0 && !!srcEl;
  const memBalls  = srcEl ? changedVars : [];
  const ballCount = memBalls.length + (hasCon ? 1 : 0) + pending.length;

  if (ballCount === 0) { renderBlockSchemeStep(nextIdx); if (onDone) onDone(); return; }

  bsAnimating = true;
  let landed = 0;
  const onLand = () => {
    if (++landed < ballCount) return;
    renderBlockSchemeStep(nextIdx);
    bsAnimating = false;
    if (onDone) onDone();
  };

  const fast = bsSpeed >= 2;   // scale the flight itself, not just the inter-step pause
  memBalls.forEach(() => animateBall(srcEl, document.getElementById('bs-vars-body'), '#4F7EF7', onLand, fast));
  if (hasCon) animateBall(srcEl, document.getElementById('bs-console-body'), '#059669', onLand, fast);
  pending.forEach(start => start(onLand));
}

/* ── Flow cursor — travels the real arrow geometry, block to block (4.1) ──
   Purely geometric: zero changes to the layout engine. Walks the already-
   built `edges` array from a point near the source block's perimeter,
   chaining through edges by point-coincidence, until landing near the
   destination block. Falls back to no animation if no chain is found. */
const BS_FLOW_MARGIN     = 20;   // px — how close an edge endpoint must be to a block to "belong" to it
const BS_FLOW_MAX_HOPS   = 8;    // safety cap on chained edge segments
const BS_FLOW_MIN_MS     = 350;
const BS_FLOW_MAX_MS     = 1400;
const BS_FLOW_PX_PER_MS  = 1.1;  // governs duration scaling with path length
const BS_FLOW_STAGGER_MS = 110;  // delay between simultaneous chips on the same path (4.3)

function bsNearNode(pt, node) {
  return pt.x >= node.cx - node.w / 2 - BS_FLOW_MARGIN &&
         pt.x <= node.cx + node.w / 2 + BS_FLOW_MARGIN &&
         pt.y >= node.cy - node.h / 2 - BS_FLOW_MARGIN &&
         pt.y <= node.cy + node.h / 2 + BS_FLOW_MARGIN;
}

/* Узел с данным номером строки — используется для перелётов вызов/возврат,
   которые идут не по нарисованным рёбрам, а напрямую между двумя блоками
   (в т.ч. на разных диаграммах, или из блока в него же самого при
   рекурсии). Условие/цикл с однострочным телом (if x: y) делят номер
   строки со своим телом — оба вызывающих места (вход в call/return) уже
   вызываются ПОСЛЕ того, как известно, что ветка реально взята, поэтому
   среди нескольких узлов с одинаковой строкой всегда нужен содержательный
   узел тела (return/action/assignment), а не сам заголовок условия/цикла. */
function bsFindNodeByLine(line) {
  const candidates = bsLnodes.filter(n => n.line === line);
  if (candidates.length <= 1) return candidates[0];
  return candidates.find(n => n.type !== 'condition' && n.type !== 'loop')
      || candidates.find(n => n.type !== 'loop')
      || candidates[0];
}

function bsFindEdgePath(fromLine, toLine) {
  const cacheKey = `${fromLine}->${toLine}`;
  if (bsPathCache.has(cacheKey)) return bsPathCache.get(cacheKey);

  const result = (() => {
    const fromNode = bsFindNodeByLine(fromLine);
    const toNode   = bsFindNodeByLine(toLine);
    if (!fromNode || !toNode) return null;

    const startEdges = bsEdges.filter(e => e.points && e.points.length >= 2 && bsNearNode(e.points[0], fromNode));

    for (const startEdge of startEdges) {
      const chain = [startEdge];
      let current = startEdge;
      for (let hop = 0; hop < BS_FLOW_MAX_HOPS; hop++) {
        const last = current.points[current.points.length - 1];
        if (bsNearNode(last, toNode)) {
          return chain.flatMap((e, i) => i === 0 ? e.points : e.points.slice(1));
        }
        const next = bsEdges.find(e => e !== current && !chain.includes(e) && e.points &&
          Math.abs(e.points[0].x - last.x) < 3 && Math.abs(e.points[0].y - last.y) < 3);
        if (!next) break;
        chain.push(next);
        current = next;
      }
    }
    return null;
  })();

  bsPathCache.set(cacheKey, result);
  return result;
}

function bsPathLength(points) {
  let len = 0;
  for (let i = 1; i < points.length; i++) {
    len += Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
  }
  return len;
}

const BS_FLOW_CHIP_MAX_CHARS = 12;   // longer values are truncated with an ellipsis on the chip itself

/* points: polyline in SVG-space to travel. label: optional "name=value" text —
   when present, rides a small chip instead of a plain dot (step 4.2). */
/* onComplete — вызывается, когда шарик реально долетел (или сразу, если
   лететь некуда/нечем). С варианта A (баг №10) вызывающая сторона
   (bsStepNext) считает эти вызовы наравне с шариками переменных/консоли —
   раньше эта анимация была "чисто декоративной, не блокирующей" и могла
   всё ещё лететь по длинной стрелке, когда уже стартовал следующий шаг. */
function bsAnimateFlowCursor(points, label, onComplete) {
  const svg = document.getElementById('bs-svg');
  if (!svg || points.length < 2) { if (onComplete) onComplete(); return; }

  const NS = 'http://www.w3.org/2000/svg';
  const baseMs = Math.min(BS_FLOW_MAX_MS, Math.max(BS_FLOW_MIN_MS, bsPathLength(points) / BS_FLOW_PX_PER_MS));
  const duration = (baseMs / bsSpeed) / 1000;   // 4.4: 2x flies twice as fast, 0.5x half as fast
  const segDur   = duration / (points.length - 1);

  if (!label) {
    const dot = document.createElementNS(NS, 'circle');
    dot.setAttribute('class', 'bs-flow-cursor');
    dot.setAttribute('r', 6);
    dot.setAttribute('cx', points[0].x);
    dot.setAttribute('cy', points[0].y);
    svg.appendChild(dot);

    const tl = gsap.timeline({ onComplete: () => { dot.remove(); if (onComplete) onComplete(); } });
    for (let i = 1; i < points.length; i++) {
      tl.to(dot, { attr: { cx: points[i].x, cy: points[i].y }, duration: segDur, ease: 'none' });
    }
    return;
  }

  const text  = label.length > BS_FLOW_CHIP_MAX_CHARS ? label.slice(0, BS_FLOW_CHIP_MAX_CHARS - 1) + '…' : label;
  const chipW = Math.min(110, Math.max(36, text.length * 7 + 16));

  const g = document.createElementNS(NS, 'g');
  g.setAttribute('class', 'bs-flow-chip');

  const rect = document.createElementNS(NS, 'rect');
  rect.setAttribute('class', 'bs-flow-chip-bg');
  rect.setAttribute('x', -chipW / 2);
  rect.setAttribute('y', -12);
  rect.setAttribute('width', chipW);
  rect.setAttribute('height', 24);
  rect.setAttribute('rx', 12);
  g.appendChild(rect);

  const txt = document.createElementNS(NS, 'text');
  txt.setAttribute('class', 'bs-flow-chip-text');
  txt.setAttribute('text-anchor', 'middle');
  txt.setAttribute('dominant-baseline', 'middle');
  txt.setAttribute('y', 1);
  txt.textContent = text;
  g.appendChild(txt);

  svg.appendChild(g);
  gsap.set(g, { x: points[0].x, y: points[0].y });   // GSAP translates SVG elements via x/y natively

  const tl = gsap.timeline({ onComplete: () => { g.remove(); if (onComplete) onComplete(); } });
  for (let i = 1; i < points.length; i++) {
    tl.to(g, { x: points[i].x, y: points[i].y, duration: segDur, ease: 'none' });
  }
}

/* ── Playback controls (step 3.5) ─────────────────────────────────── */
const BS_SPEED_PAUSE = { 0.5: 900, 1: 450, 2: 180 };   // ms between landing and the next step
let bsSpeed     = 1;
let bsIsPlaying = false;
let bsPlayTimer = null;

function bsUpdatePlayBtn() {
  const btn = document.getElementById('bs-ctrl-play');
  if (btn) btn.textContent = bsIsPlaying ? '⏸' : '▶';
}

function bsUpdateControls() {
  const steps   = bsTrace.steps;
  const len     = steps ? steps.length : 0;
  const atStart = bsStepIndex < 0;        // -1 = стоим на "Начало", дальше назад некуда
  const atEnd   = !len || bsStepIndex >= len;   // len = стоим на "Конец", дальше вперёд некуда
  const first = document.getElementById('bs-ctrl-first');
  const prev  = document.getElementById('bs-ctrl-prev');
  const next  = document.getElementById('bs-ctrl-next');
  const last  = document.getElementById('bs-ctrl-last');
  if (first) first.disabled = atStart;
  if (prev)  prev.disabled  = atStart;
  if (next)  next.disabled  = atEnd;
  if (last)  last.disabled  = atEnd;
  bsUpdatePlayBtn();
}

function bsStopAutoplay() {
  bsIsPlaying = false;
  clearTimeout(bsPlayTimer);
  bsUpdatePlayBtn();
}

function bsGotoStart() {
  bsStopAutoplay();
  if (!bsTrace.steps || !bsTrace.steps.length) return;
  bsShowStartState();
}

function bsGotoEnd() {
  bsStopAutoplay();
  if (!bsTrace.steps || !bsTrace.steps.length) return;
  bsShowEndState();
}

function bsScheduleNextStep() {
  if (!bsIsPlaying) return;
  const steps = bsTrace.steps;
  if (!steps || bsStepIndex >= steps.length) { bsStopAutoplay(); return; }
  bsStepNext(() => {
    if (!bsIsPlaying) return;
    bsPlayTimer = setTimeout(bsScheduleNextStep, BS_SPEED_PAUSE[bsSpeed] || 450);
  });
}

function bsTogglePlay() {
  if (bsIsPlaying) { bsStopAutoplay(); return; }
  if (!bsTrace.steps || !bsTrace.steps.length) return;
  if (bsStepIndex >= bsTrace.steps.length) {   // at the very end — restart from "Начало"
    bsShowStartState();
  }
  bsIsPlaying = true;
  bsUpdatePlayBtn();
  bsScheduleNextStep();
}

function bsSetSpeed(speed) {
  bsSpeed = speed;
  document.querySelectorAll('.bs-speed-btn').forEach(b => {
    b.classList.toggle('bs-speed-active', parseFloat(b.dataset.speed) === speed);
  });
}

/* Wire up Block Scheme playback buttons (mirrors animator.js's Classic View wiring,
   kept in this file so each view owns its own controls). */
document.getElementById('bs-ctrl-first')?.addEventListener('click', bsGotoStart);
document.getElementById('bs-ctrl-prev') ?.addEventListener('click', () => { bsStopAutoplay(); bsStepPrev(); });
document.getElementById('bs-ctrl-play') ?.addEventListener('click', bsTogglePlay);
document.getElementById('bs-ctrl-next') ?.addEventListener('click', () => { bsStopAutoplay(); bsStepNext(); });
document.getElementById('bs-ctrl-last') ?.addEventListener('click', bsGotoEnd);
document.querySelectorAll('.bs-speed-btn').forEach(btn => {
  btn.addEventListener('click', () => bsSetSpeed(parseFloat(btn.dataset.speed)));
});

/* ── Variables / console panels (step 3.4 — token landing targets) ── */
let bsPrevVars   = {};
let bsPrevOutput = [];

function bsRenderVars(vars, changedKeys) {
  const container = document.getElementById('bs-vars-body');
  if (!container) return;
  const keys = Object.keys(vars);
  if (keys.length === 0) {
    container.innerHTML = '<span class="bs-panel-empty">—</span>';
    return;
  }
  container.innerHTML = '';
  for (const k of keys) {
    const card = document.createElement('div');
    card.className = 'bs-var-card' + (changedKeys.includes(k) ? ' changed' : '');
    card.dataset.varName = k;

    const nameEl = document.createElement('div');
    nameEl.className = 'bs-var-name';
    nameEl.textContent = k;

    const valEl = document.createElement('div');
    valEl.className = 'bs-var-value';
    valEl.textContent = formatValue(vars[k]);

    card.appendChild(nameEl);
    card.appendChild(valEl);
    container.appendChild(card);
  }
}

function bsRenderConsole(output) {
  const container = document.getElementById('bs-console-body');
  if (!container) return;
  if (output.length === 0) {
    container.innerHTML = '<span class="bs-panel-empty">—</span>';
    return;
  }
  const existingLines = container.querySelectorAll('.bs-console-line').length;
  if (existingLines === 0) container.innerHTML = '';
  for (let i = existingLines; i < output.length; i++) {
    const line = document.createElement('div');
    line.className = 'bs-console-line new';
    line.textContent = output[i];
    container.appendChild(line);
  }
}
