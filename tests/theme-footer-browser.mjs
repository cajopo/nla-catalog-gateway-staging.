import assert from 'node:assert/strict';
import { readFile, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';

const [candidate] = process.argv.slice(2);
assert(candidate, 'Usage: node tests/theme-footer-browser.mjs <candidate-from-theme-footer-games>');
const documents = Object.fromEntries(await Promise.all(['it', 'en'].map(async language =>
  [`/footer-${language}.html`, await readFile(join(candidate, `footer-${language}.html`))])));
const server = createServer((req, res) => {
  if (!documents[req.url]) { res.writeHead(404).end(); return; }
  res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(documents[req.url]);
});
server.listen(0, '127.0.0.1'); await once(server, 'listening');
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(tmpdir(), 'nla-footer-browser-135-'));
const executable = process.env.NLA_CHROME || (process.platform === 'win32' ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' : 'google-chrome');
const chrome = spawn(executable, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
  `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
try {
  const address = new URL(await new Promise((resolve, reject) => {
    let log = ''; const timer = setTimeout(() => reject(new Error('Chrome start timeout')), 20000);
    chrome.once('error', error => { clearTimeout(timer); reject(error); });
    chrome.stderr.on('data', data => { log += data.toString(); const match = log.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); } });
  }));
  const pages = await (await fetch(`http://${address.host}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Chrome connection timeout')), 10000);
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Chrome connection failed')); }, { once: true });
  });
  let serial = 0; const pending = new Map();
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data), slot = pending.get(message.id);
    if (slot) { pending.delete(message.id); clearTimeout(slot.timer); message.error ? slot.reject(message.error) : slot.resolve(message.result); }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++serial, timer = setTimeout(() => { pending.delete(id); reject(new Error(`Chrome timeout: ${method}`)); }, 10000);
    pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const value = await call('Runtime.evaluate', { expression, returnByValue: true });
    assert(!value.exceptionDetails, JSON.stringify(value.exceptionDetails)); return value.result.value;
  };
  await call('Page.enable');
  for (const language of ['it', 'en']) for (const width of [375, 1280]) {
    await call('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width === 375 });
    const path = `/footer-${language}.html`;
    await call('Page.navigate', { url: origin + path });
    let loaded = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (await evaluate(`location.pathname === ${JSON.stringify(path)} && document.readyState === 'complete' && !!document.querySelector('.nla-footer nav')`)) { loaded = true; break; }
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    assert(loaded, 'Footer did not load');
    const state = await evaluate(`({width:innerWidth,scroll:document.documentElement.scrollWidth,links:[...document.querySelectorAll('.nla-footer nav a')].map(a=>({title:a.textContent,url:a.getAttribute('href'),rect:(()=>{const r=a.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height}})()}))})`);
    assert.equal(state.width, width); assert(state.scroll <= width, 'Horizontal overflow'); assert.equal(state.links.length, 9);
    for (const link of state.links) assert(link.rect.width > 0 && link.rect.height > 0 && link.rect.x >= 0 && link.rect.right <= width && link.rect.bottom <= 900, 'Clipped footer link');
    assert.deepEqual(state.links.slice(-2).map(link => link.title), ['Riftbound', 'Disney Lorcana']);
    for (const game of ['riftbound', 'lorcana']) {
      const index = game === 'riftbound' ? 7 : 8;
      await evaluate(`document.querySelectorAll('.nla-footer nav a')[${index}].focus()`);
      const focused = await evaluate('document.activeElement.getAttribute("href")');
      assert.equal(focused, `${language === 'it' ? '/it' : ''}/search?view=nla-catalog&game=${game}&family=all`);
    }
    const screenshot = await call('Page.captureScreenshot', { format: 'png' });
    await writeFile(join(profile, `footer-${language}-${width}.png`), Buffer.from(screenshot.data, 'base64'));
    console.log(`PASS ${language} ${width}px: nine visible links, locale routes, focus, no overflow`);
  }
  console.log(`PASS 4/4 footer browser cases; screenshots=${profile}`);
} finally { socket?.close(); chrome.kill(); server.close(); }
