/* Local browser rehearsal: fresh synthetic Flask fixture and disposable Chrome profile.
 * No existing server/browser is controlled. Requires Node 22+ and installed Chrome/Edge.
 */
'use strict';
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'ege-tests-browser-'));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const python = process.env.EGE_PYTHON || 'python';
const browserExe = [
  path.join(process.env.ProgramFiles || 'C:/Program Files', 'Google/Chrome/Application/chrome.exe'),
  path.join(process.env['ProgramFiles(x86)'] || 'C:/Program Files (x86)', 'Microsoft/Edge/Application/msedge.exe')
].find(fs.existsSync);
if (!browserExe) throw new Error('Installed Chrome/Edge required');
let server, browser, socket, origin, session;
let sequence = 0, serverLog = '', browserLog = '';
const pending = new Map(), exceptions = [], layouts = [];
async function until(check, message, timeout = 15000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { const result = await check(); if (result) return result; await sleep(100); }
  throw new Error(message);
}
function command(method, params = {}, useSession = true) {
  const id = ++sequence;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, {resolve, reject, timer});
    socket.send(JSON.stringify({id, method, params, ...(useSession && session ? {sessionId: session} : {})}));
  });
}
async function evaluate(expression) {
  const response = await command('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
  return response.result.value;
}
async function navigate(route) {
  await command('Page.navigate', {url: origin + route});
  await until(() => evaluate(`location.pathname === ${JSON.stringify(route.split('?')[0])} && document.readyState === 'complete'`), `Navigation ${route}`);
  await sleep(150);
}
async function api(route, method = 'GET', body, token) {
  return evaluate(`(async () => {
    const response = await fetch(${JSON.stringify(route)}, {method:${JSON.stringify(method)},
      headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('meta[name="csrf-token"]')?.content || '',
      'X-Test-Writer-Token':${JSON.stringify(token || '')}}, ${body === undefined ? '' : `body:JSON.stringify(${JSON.stringify(body)}),`} credentials:'same-origin'});
    const data = await response.json(); if (!response.ok) throw Error(response.status + ' ' + JSON.stringify(data)); return data;
  })()`);
}
async function login(username) {
  await command('Network.clearBrowserCookies');
  await navigate('/login');
  await evaluate(`(async () => { const form = document.querySelector('form'); const body = new FormData(form);
    body.set('username', ${JSON.stringify(username)}); body.set('password','local-tests-only');
    const response = await fetch('/login',{method:'POST',body}); if (!response.ok) throw Error('Login failed'); })()`);
}
async function captures(name) {
  for (const width of [360, 768, 1440, 1920]) {
    await command('Emulation.setDeviceMetricsOverride', {width, height: 1000, deviceScaleFactor: 1, mobile: false});
    await sleep(100);
    const layout = await evaluate(`({width:innerWidth,scroll:document.documentElement.scrollWidth,
      cards:document.querySelector('#test-grid') ? getComputedStyle(document.querySelector('#test-grid')).gridTemplateColumns : null})`);
    layouts.push({name, ...layout});
    const screenshot = await command('Page.captureScreenshot', {format:'png', captureBeyondViewport:false});
    fs.writeFileSync(path.join(output, `${name}-${width}.png`), Buffer.from(screenshot.data, 'base64'));
  }
}
const key = () => `browser-${require('node:crypto').randomUUID()}`;
async function main() {
  server = spawn(python, ['-B','-X','utf8','scripts/run_tests_local.py','--worker-interval','1','--stop-on-stdin-close'],
    {cwd:root,windowsHide:true,stdio:['pipe','pipe','pipe']});
  server.stdout.on('data', data => { serverLog += data; });
  server.stderr.on('data', data => { serverLog += data; });
  origin = await until(() => serverLog.match(/Local tests site: (http:\/\/127\.0\.0\.1:\d+)/)?.[1], 'Fixture server failed', 30000);
  const profile = path.join(output, 'browser-profile');
  browser = spawn(browserExe, ['--headless=new','--no-first-run','--no-default-browser-check',
    '--disable-background-networking','--disable-component-update','--disable-sync',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
    '--remote-debugging-port=0',`--user-data-dir=${profile}`,'about:blank'], {windowsHide:true,stdio:'pipe'});
  browser.stderr.on('data', data => { browserLog += data; });
  browser.stdout.on('data', data => { browserLog += data; });
  const activePort = path.join(profile, 'DevToolsActivePort');
  await until(() => fs.existsSync(activePort), 'Disposable browser failed');
  const [port, endpoint] = fs.readFileSync(activePort, 'utf8').trim().split(/\r?\n/);
  socket = new WebSocket(`ws://127.0.0.1:${port}${endpoint}`);
  await new Promise((resolve,reject) => { socket.addEventListener('open',resolve,{once:true}); socket.addEventListener('error',reject,{once:true}); });
  socket.addEventListener('message', event => {
    const msg = JSON.parse(event.data);
    if (msg.id) { const item = pending.get(msg.id); if (!item) return; clearTimeout(item.timer); pending.delete(msg.id);
      msg.error ? item.reject(new Error(msg.error.message)) : item.resolve(msg.result); }
    if (msg.method === 'Runtime.exceptionThrown') exceptions.push(msg.params.exceptionDetails);
  });
  const target = await command('Target.createTarget',{url:'about:blank'},false);
  session = (await command('Target.attachToTarget',{targetId:target.targetId,flatten:true},false)).sessionId;
  await command('Page.enable'); await command('Runtime.enable'); await command('Network.enable');
  await login('tests-admin'); await navigate('/admin/tests');
  const tests = [];
  for (const title of ['Системы счисления и логика','Практика программирования','Алгоритмы и обработка информации','Информационные модели']) {
    const draft = await api('/api/admin/tests','POST',{request_key:key()});
    const document = {title,description:'Локальная проверка интерфейса на вымышленных данных.',time_limit_seconds:1800,
      attempt_limit:3,show_correct_answers:true,questions:[
        {title:'Единицы информации',prompt_text:'Сколько бит содержится в одном байте?',code_text:null,question_type:'single_choice',
          free_input_mode:null,grading_mode:'auto',media_id:null,options:[{text:'4 бита',is_correct:false},{text:'8 бит',is_correct:true}],accepted_answers:[]},
        {title:'Выберите языки программирования',prompt_text:'Отметьте все подходящие ответы.',code_text:null,question_type:'multiple_choice',
          free_input_mode:null,grading_mode:'auto',media_id:null,options:[{text:'Python',is_correct:true},{text:'HTML',is_correct:false},{text:'C++',is_correct:true}],accepted_answers:[]},
        {title:'Объясните алгоритм',prompt_text:'Опишите результат программы и объясните решение.',code_text:'x = 5\nprint(x * 2 + 3)',question_type:'free_text',
          free_input_mode:'multiline',grading_mode:'manual',media_id:null,options:[],accepted_answers:[]}]};
    const saved = await api(`/api/admin/tests/${draft.id}/draft`,'PUT',{document,expected_revision:draft.revision,request_key:key()});
    await api(`/api/admin/tests/${draft.id}/publish`,'POST',{expected_revision:saved.revision,request_key:key()});
    tests.push(draft.id);
  }
  await navigate('/admin/tests'); await until(() => evaluate("document.querySelectorAll('#test-rows tr').length > 0 || document.body.innerText.includes('Системы счисления')"),'Admin catalog empty');
  await captures('admin'); await navigate(`/admin/tests/${tests[0]}/edit`); await sleep(250); await captures('editor');
  await login('tests-student'); await navigate('/tests');
  const attempts = [];
  for (let i=0;i<3;i++) {
    const started = await api(`/api/tests/${tests[i]}/attempts`,'POST',{request_key:key()});
    const attempt = await api(`/api/tests/attempts/${started.attempt_id}`);
    const writer = await api(`/api/tests/attempts/${attempt.attempt_id}/claim`,'POST',{expected_generation:attempt.generation,writer_client_id:key()});
    if (i===0) {
      const q = attempt.questions[2];
      await api(`/api/tests/attempts/${attempt.attempt_id}/answers/${q.id}`,'PUT',
        {answer:'Программа выведет 13. Умножение выполняется до сложения.',expected_revision:0,mutation_id:key(),generation:writer.generation},writer.writer_token);
    }
    if (i<2) await api(`/api/tests/attempts/${attempt.attempt_id}/submit`,'POST',{request_key:key(),generation:writer.generation},writer.writer_token);
    attempts.push(attempt.attempt_id);
  }
  await navigate('/tests'); await until(() => evaluate("document.querySelectorAll('#test-grid > *').length === 4"),'Student catalog empty');
  await captures('catalog');
  await navigate(`/tests/attempts/${attempts[2]}`);
  await evaluate("document.getElementById('claim').click()");
  await until(() => evaluate("document.getElementById('writer-notice').hidden && !document.getElementById('finish').disabled"),'Explicit writer claim failed');
  await evaluate("document.querySelectorAll('#answer-area input')[1].click()");
  await until(async () => (await api(`/api/tests/attempts/${attempts[2]}`)).questions[0].revision === 1,'UI autosave failed');
  await captures('attempt');
  await evaluate("document.querySelector('#finish').click()");
  assert.equal(await evaluate("document.querySelector('#finish-dialog').open"),true);
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  assert.equal(await evaluate("document.querySelector('#finish-dialog').open"),false);
  await evaluate("document.querySelector('#finish').click();document.querySelector('#confirm-finish').click()");
  await until(() => evaluate("!document.querySelector('#completion').hidden"),'UI submit failed');
  await navigate(`/tests/attempts/${attempts[0]}/result`);
  await evaluate("document.querySelector('.row-toggle').click()");
  assert.equal(await evaluate("document.querySelectorAll('.reference-answer').length"),0);
  await captures('result-pending');
  await navigate(`/tests/attempts/${attempts[1]}/result`);
  await evaluate("document.querySelector('.row-toggle').click()");
  assert.equal(await evaluate("document.querySelectorAll('.reference-answer').length"),2);
  await captures('result-graded');
  await login('tests-admin'); await navigate(`/admin/tests/attempts/${attempts[0]}/review`);
  await until(() => evaluate("document.body.innerText.includes('Объясните алгоритм')"),'Review not rendered'); await captures('review');
  await evaluate("document.querySelector('[data-grade=\"1\"]').click()");
  await until(() => evaluate("document.querySelector('#review-feedback').innerText.includes('Оценка сохранена')"),'UI grade not saved');
  assert.equal((await api(`/api/admin/tests/attempts/${attempts[0]}`)).state,'graded');
  await navigate('/admin/user/2');
  assert.equal(await evaluate("document.querySelector('[role=tab][aria-selected=true]').textContent.trim()"),'Задания');
  await evaluate("document.querySelector('[data-tab=\"0\"]').focus()");
  await command('Input.dispatchKeyEvent',{type:'keyDown',key:'End',code:'End',windowsVirtualKeyCode:35});
  await command('Input.dispatchKeyEvent',{type:'keyUp',key:'End',code:'End',windowsVirtualKeyCode:35});
  assert.equal(await evaluate("document.activeElement.dataset.tab"),'4');
  await evaluate("document.querySelector('[data-tab=\"4\"]').click()");
  await until(() => evaluate("document.querySelector('#tests-user-stats')?.innerText.includes('Системы счисления')"),'Statistics not rendered');
  await captures('user-stats');
  await evaluate("document.querySelector('[data-expand]').click()");
  await until(() => evaluate("document.querySelector('.uts-attempts-table tbody button')"),'History not rendered');
  await captures('user-history');
  await evaluate("document.querySelector('.uts-attempts-table tbody button').click()");
  await until(() => evaluate("document.querySelectorAll('.uts-attempt-question').length === 3"),'Attempt details not rendered');
  await captures('user-details');
  await evaluate("document.querySelector('#tests-stats-dialog .uts-close').click();document.querySelector('[data-grant]').click()");
  await captures('user-grant');
  await evaluate("document.querySelector('.uts-grant-form input').value='2';document.querySelector('.uts-grant-form').requestSubmit()");
  await until(() => evaluate("!document.querySelector('#tests-stats-dialog').open"),'UI grant failed');
  const stats = await api('/api/admin/users/2/tests');
  assert.equal(stats.tests.find(item => item.id === tests[0]).remaining_attempts,4);
  assert.equal(exceptions.length,0,JSON.stringify(exceptions));
  assert.deepEqual(layouts.filter(row => row.scroll > row.width+2),[], 'Horizontal page overflow');
  console.log(JSON.stringify({status:'PASS',screenshots:layouts.length,output,layouts}));
}
(async () => {
  try { await main(); }
  catch (error) { console.error(error.stack); process.exitCode=1; }
  finally {
    fs.writeFileSync(path.join(output,'report.json'),JSON.stringify({layouts,exceptions},null,2));
    fs.writeFileSync(path.join(output,'fixture.log'),serverLog);
    fs.writeFileSync(path.join(output,'browser.log'),browserLog);
    if (socket?.readyState === WebSocket.OPEN) { try { await command('Browser.close',{},false); } catch {} socket.close(); }
    if (server) { server.stdin.end(); await until(() => server.exitCode !== null,'Fixture shutdown',10000).catch(error => console.error(error.message)); }
    console.log('Browser artifacts:',output);
  }
})();
