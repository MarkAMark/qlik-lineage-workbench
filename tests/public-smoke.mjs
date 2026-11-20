import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

const browser = [process.env.QLIK_BROWSER,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'].find(p => p && existsSync(p));
assert(browser, 'Install Chrome/Edge or set QLIK_BROWSER.');
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'TracePublicBrowser-'));
const server = spawn(process.env.PYTHON || 'python', ['-B', 'tests/browser_server.py', temporary], { windowsHide: true });
let chrome, socket, sequence = 0;
const pending = new Map(), runtimeErrors = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function call(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 15000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function waitFor(expression, timeout = 20000) {
  const until = Date.now() + timeout;
  while (Date.now() < until) { if (await evaluate(expression)) return; await delay(100); }
  throw new Error('Timed out: ' + expression);
}
async function click(selector) {
  const point = await evaluate(`(() => { const e=document.querySelector(${JSON.stringify(selector)}); if(!e) throw Error('Missing element'); e.scrollIntoView({block:'center'}); const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
  await call('Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
  await call('Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
}
async function fill(selector, value) {
  await evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)});Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,${JSON.stringify(value)});e.dispatchEvent(new Event('input',{bubbles:true}));})()`);
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  const stopped = new Promise(resolve => child.once('exit', resolve));
  child.kill();
  await Promise.race([stopped, delay(4000)]);
}

try {
  const fixture = await new Promise((resolve, reject) => {
    let output = '', errors = '';
    const timer = setTimeout(() => reject(new Error('Fixture startup timed out: ' + errors)), 20000);
    server.stderr.on('data', data => { errors += data; });
    server.once('error', reject);
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${errors}`)); });
    server.stdout.on('data', data => { output += data; if (output.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(output.split('\n')[0])); } });
  });
  const profile = path.join(temporary, 'chrome-profile');
  chrome = spawn(browser, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
  let port;
  for (let i = 0; i < 150; i++) {
    try { port = Number((await fs.readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]); break; } catch { await delay(100); }
  }
  assert(port, 'Browser debugging port unavailable.');
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  socket = new WebSocket(tabs.find(tab => tab.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = event => {
    const message = JSON.parse(event.data), item = pending.get(message.id);
    if (item) { pending.delete(message.id); clearTimeout(item.timer); if (message.error) item.reject(new Error(JSON.stringify(message.error))); else item.resolve(message.result); }
    if (message.method === 'Runtime.exceptionThrown') runtimeErrors.push(message.params.exceptionDetails.text);
  };
  await call('Page.enable'); await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1080, deviceScaleFactor: 1, mobile: false });
  await call('Page.navigate', { url: fixture.base });
  await waitFor("!!document.querySelector('.onboarding')");
  assert.equal((await (await fetch(fixture.base + '/api/catalog')).json()).totals.apps, 0);
  for (const view of ['tables', 'assessment', 'sources', 'fields']) {
    await click(`[data-view="${view}"]`);
    assert(await evaluate("!!document.querySelector('.onboarding')"));
  }
  await click('.onboarding .button');
  await fill('input[aria-label="元数据目录路径"]', fixture.empty);
  await click('.modal-actions .primary');
  await waitFor("!!document.querySelector('.form-error')");
  assert.equal((await (await fetch(fixture.base + '/api/catalog')).json()).totals.apps, 0);
  await fill('input[aria-label="元数据目录路径"]', fixture.exports);
  await click('.modal-actions .primary');
  await waitFor("!document.querySelector('.import-modal') && document.querySelectorAll('.react-flow__edge').length>0");
  const catalog = await (await fetch(fixture.base + '/api/catalog')).json();
  assert.equal(catalog.totals.apps, 3); assert.equal(catalog.totals.streams, 3);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('.sidebar')).backgroundColor"), 'rgb(22, 58, 112)');
  assert.equal(await evaluate("document.querySelector('.field-panel').getBoundingClientRect().width"), 304);
  assert(await evaluate("document.querySelector('.selected-expression').textContent.includes('SUM(AMOUNT)')"));
  await click('.expression-code-action');
  await waitFor("document.querySelector('.node-code-dialog[open]')?.textContent.includes('SUM(AMOUNT)')");
  await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
  await waitFor("!document.querySelector('.node-code-dialog[open]')");
  const stream = catalog.streams.find(s => s.name === 'Stream Beta');
  await evaluate(`(() => {const e=document.querySelector('select[aria-label="选择 Stream"]');e.value=${JSON.stringify(stream.id)};e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await waitFor("document.querySelectorAll('.app-list>button').length===1 && document.querySelector('.context-app')?.textContent.includes('Stream Beta')");
  await click('[data-view="tables"]');
  await waitFor("document.querySelectorAll('.react-flow__node').length>0 && !document.querySelector('.onboarding')");
  await click('[data-view="sources"]');
  await waitFor("document.querySelector('.portfolio-page')?.textContent.includes('STREAM_BETA')");
  await click('[data-view="assessment"]');
  await waitFor("document.querySelector('.portfolio-page')?.textContent.includes('Shared App')");
  await click('[data-view="fields"]');
  await waitFor("!!document.querySelector('.selected-expression') && document.querySelectorAll('.react-flow__edge').length>0");
  assert.equal(await evaluate('document.documentElement.scrollWidth <= 1440'), true);
  assert.deepEqual(runtimeErrors, []);
  console.log('PASS: 1440px empty onboarding, navigation, invalid import, three-Stream import, field graph, code dialog, Stream switch, tables, sources and assessment.');
} finally {
  if (socket?.readyState === 1) { try { await call('Browser.close'); } catch { /* browser can close before responding */ } }
  socket?.close();
  for (const item of pending.values()) { clearTimeout(item.timer); item.reject(new Error('Browser closed')); }
  await stop(chrome); await stop(server);
  assert.equal(path.dirname(path.resolve(temporary)), path.resolve(os.tmpdir()));
  assert(path.basename(temporary).startsWith('TracePublicBrowser-'));
  await fs.rm(temporary, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
}
