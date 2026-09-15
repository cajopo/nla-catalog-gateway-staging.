import assert from 'node:assert/strict';
import { readFile, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';

const root = fileURLToPath(new URL('../', import.meta.url));
const source = await readFile(join(root, 'theme/snippets/nla-catalog-search.liquid'), 'utf8');
const locale = JSON.parse(await readFile(join(root, 'theme/locales/it.json'), 'utf8')).nla_catalog;
const script = source.match(/{% javascript %}([\s\S]*?){% endjavascript %}/)[1];
const style = source.match(/{% stylesheet %}([\s\S]*?){% endstylesheet %}/)[1];
const htmlEscape = value => value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;');
function fixtureHtml(mode, endpoint) {
  const values = { mode, endpoint, instance_id: 'fixture', 'routes.search_url': '/search', 'routes.root_url': '/', 'shop.currency': 'EUR' };
  const markup = source.replace(/{% (doc|stylesheet|javascript) %}[\s\S]*?{% end\1 %}/g, '')
    .replace(/{{\s*'nla_catalog\.([a-z_]+)'\s*\|\s*t(?:\s*\|\s*escape)?\s*}}/g, (_, key) => htmlEscape(locale[key]))
    .replace(/{{\s*([\w.]+)[^}]*}}/g, (_, key) => htmlEscape(values[key]));
  assert(!markup.includes('{{') && !markup.includes('{%'));
  return `<!doctype html><html lang="it"><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>NLA UI fixture</title><style>body{background:#0d0e12;margin:16px;font:16px system-ui} ${style}</style></head><body>${markup}<script>${script}</script></body></html>`;
}

const generation = 'sha256:' + 'a'.repeat(64);
const requests = [];
function product(id, game, name, available = true) {
  return { contractVersion: 1, productGid: `gid://shopify/Product/${id}`, handle: `card-${id}`, commercialTitle: name,
    canonicalCardName: name, game, productFamily: 'single', productSubtype: null,
    variants: [{ variantGid: `gid://shopify/ProductVariant/${id}`, title: 'Default', selectedOptions: [],
      priceText: available ? '1.20' : '0.00', compareAtPriceText: null, inventoryQuantity: available ? 1 : 0,
      inventoryPolicy: 'DENY', inventoryTracked: true }] };
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname !== '/apps/nla/catalog') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end(fixtureHtml(url.searchParams.get('mode') || 'page', url.searchParams.has('unconfigured') ? '' : '/apps/nla/catalog'));
    return;
  }
  let raw = '';
  for await (const chunk of req) raw += chunk;
  const body = JSON.parse(raw); requests.push(body);
  const { request, cursor } = body;
  const q = request.q || '';
  const names = request.game === 'magic' ? ['Lightning Bolt', 'Lightning Bolt (foil)'] : ['Pikachu', 'Pikachu (promo)'];
  let items = names.map((name, index) => product(25000 + index, request.game, name, index === 0));
  if (q === 'empty') items = [];
  else if (q === 'xss') items = [product(25002, request.game, '<img src=x onerror="window.pwned=1">')];
  else if (!['slow', 'fast', 'leak', 'duplicate', 'restart', 'malformed', 'loop'].includes(q)) {
    items = items.filter(item => item.canonicalCardName.toLowerCase().includes(q.toLowerCase()));
  }
  if (request.filters.inStock) items = items.filter(item => item.variants[0].inventoryQuantity > 0);
  if (q === 'leak') items[0].game = 'one-piece';
  if (q === 'duplicate') items = [items[0], items[0]];
  const allItems = items;
  if (cursor) items = items.slice(1); else items = items.slice(0, 1);
  const nextCursor = !cursor && allItems.length > 1 ? 'opaque-next-page' : null;
  const data = { contractVersion: 1, nextCursor: q === 'loop' && cursor ? cursor : nextCursor,
    page: { contractVersion: 1, datasetGeneration: generation, request, requestContextSha256: 'b'.repeat(64),
      returnedProductCount: items.length, returnedVariantCount: items.length, items,
      hasNextPage: q === 'loop' && cursor ? true : nextCursor !== null } };
  if (q === 'duplicate') { data.page.items = allItems; data.page.returnedProductCount = allItems.length; }
  if (body.includeSuggestions) data.suggestions = allItems.map(item => ({ canonicalCardName: q === 'fast' ? 'Fast answer' : item.canonicalCardName,
    matchingProductCount: 1, availableProductCount: item.variants[0].inventoryQuantity > 0 ? 1 : 0 }));
  res.setHeader('Content-Type', 'application/json');
  if (q === 'restart' && cursor) { res.statusCode = 409; res.end(JSON.stringify({ code: 'restart_required' })); return; }
  if (q === 'malformed') { res.end('{invalid'); return; }
  if (q === 'slow') await new Promise(resolve => setTimeout(resolve, 700));
  res.end(JSON.stringify(data));
});
server.listen(0, '127.0.0.1'); await once(server, 'listening');
const origin = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(tmpdir(), 'nla-theme-browser-'));
const executable = process.env.NLA_CHROME || (process.platform === 'win32' ? 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' : 'google-chrome');
const chrome = spawn(executable, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
  `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
let socket;
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
try {
  const browserUrl = await new Promise((resolve, reject) => {
    let log = '';
    const timer = setTimeout(() => reject(new Error('Chrome did not start')), 20000);
    chrome.once('error', reject);
    chrome.stderr.on('data', data => {
      log += data.toString(); const match = log.match(/DevTools listening on (ws:\/\/\S+)/);
      if (match) { clearTimeout(timer); resolve(match[1]); }
    });
  });
  const address = new URL(browserUrl);
  const pages = await (await fetch(`http://${address.host}/json/list`)).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Chrome debugging connection timed out')), 10000);
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Chrome debugging connection failed')); }, { once: true });
  });
  let nextId = 0; const pending = new Map(); const errors = [];
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
    if (message.id) { const slot = pending.get(message.id); if (!slot) return; clearTimeout(slot.timer); pending.delete(message.id); message.error ? slot.reject(message.error) : slot.resolve(message.result); }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Chrome command timed out: ${method}`)); }, 10000);
    pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
  });
  await call('Runtime.enable'); await call('Page.enable');
  const evaluate = async expression => {
    const result = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text);
    return result.result.value;
  };
  async function waitFor(expression) {
    for (let i = 0; i < 100; i++) { if (await evaluate(expression)) return; await delay(30); }
    throw new Error(`Timed out: ${expression}`);
  }
  async function navigate(query) {
    await call('Page.navigate', { url: origin + '/search?' + query });
    await waitFor('Boolean(document.querySelector("nla-catalog-search")?.events)');
  }
  const el = 'document.querySelector("nla-catalog-search")';
  const visible = `${el}.page.hidden === false`;
  const query = async value => {
    await evaluate(`${el}.input.value = ${JSON.stringify(value)}; ${el}.form.requestSubmit()`);
  };
  let passed = 0;
  async function check(name, action) { await action(); passed += 1; console.log(`PASS ${name}`); }
  await check('explicit game, sold-out default and opaque next-page navigation', async () => {
    await navigate('game=magic'); await waitFor(visible);
    assert.equal(requests.at(-1).request.filters.inStock, null);
    assert.equal(await evaluate(`${el}.results.firstChild.dataset.productGid`), 'gid://shopify/Product/25000');
    await evaluate(`${el}.querySelector('[data-action="next"]').click()`); await waitFor(`${visible} && ${el}.results.textContent.includes('Esaurito')`);
    assert.equal(await evaluate(`${el}.results.firstChild.dataset.productGid`), 'gid://shopify/Product/25001');
    assert.match(await evaluate('location.search'), /cursor=opaque-next-page/);
    assert.match(await evaluate(`${el}.results.textContent`), /Prezzo n\/d/);
  });
  await check('back, forward and refresh recover the same cursor page', async () => {
    await evaluate('history.back()'); await waitFor(`${visible} && ${el}.results.firstChild?.dataset.productGid.endsWith('/25000')`);
    await evaluate('history.forward()'); await waitFor(`${visible} && ${el}.results.firstChild?.dataset.productGid.endsWith('/25001')`);
    await call('Page.reload'); await waitFor(`${visible} && ${el}.results.firstChild?.dataset.productGid.endsWith('/25001')`);
  });
  await check('game change resets cursor and stock remains explicit', async () => {
    await evaluate(`${el}.game.value='pokemon'; ${el}.game.dispatchEvent(new Event('change'))`);
    await waitFor(`${visible} && ${el}.results.textContent.includes('Pikachu')`);
    assert.equal(requests.at(-1).cursor, null);
    assert(!await evaluate('location.search.includes("cursor=")'));
    await evaluate(`${el}.stock.click()`); await waitFor(`${visible} && ${el}.querySelector('[data-action="next"]').hidden`);
    assert.equal(requests.at(-1).request.filters.inStock, true);
  });
  await check('scoped adaptive suggestions and keyboard selection', async () => {
    await navigate('game=magic'); await waitFor(visible);
    await evaluate(`${el}.input.focus(); ${el}.input.value='Light'; ${el}.input.dispatchEvent(new Event('input'))`);
    await waitFor(`${el}.list.children.length === 2`);
    assert.equal(requests.at(-1).includeSuggestions, true);
    assert.match(await evaluate(`${el}.list.textContent`), /Esaurito/);
    await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowUp', code: 'ArrowUp' });
    assert.equal(await evaluate(`${el}.input.getAttribute('aria-activedescendant')`), 'NlaSuggestions-fixture-1');
    await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown' });
    assert.equal(await evaluate(`${el}.input.getAttribute('aria-activedescendant')`), 'NlaSuggestions-fixture-0');
    await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter' }); await waitFor(visible);
    assert.equal(await evaluate(`${el}.input.value`), 'Lightning Bolt');
  });
  await check('slow obsolete response cannot replace newer suggestions', async () => {
    await evaluate(`${el}.input.focus(); ${el}.input.value='slow'; ${el}.input.dispatchEvent(new Event('input'))`); await delay(320);
    await evaluate(`${el}.input.value='fast'; ${el}.input.dispatchEvent(new Event('input'))`);
    await waitFor(`${el}.list.textContent.includes('Fast answer')`); await delay(800);
    assert.match(await evaluate(`${el}.list.textContent`), /Fast answer/);
  });
  await check('leaving search cannot reopen delayed suggestions', async () => {
    await evaluate(`${el}.input.focus(); ${el}.input.value='slow'; ${el}.input.dispatchEvent(new Event('input'))`); await delay(320);
    await evaluate(`const outside = document.createElement('button'); outside.textContent='Outside'; document.body.append(outside); outside.focus()`);
    await delay(800); assert.equal(await evaluate(`${el}.list.hidden`), true);
  });
  for (const bad of ['leak', 'duplicate', 'malformed']) await check(`reject ${bad} response`, async () => {
    await query(bad); await waitFor(`${el}.status.textContent.includes('indisponibile')`);
    assert.equal(await evaluate(`${el}.page.hidden`), true);
  });
  await check('restart required is explicit, with no native fallback', async () => {
    await query('restart'); await waitFor(visible);
    await evaluate(`${el}.querySelector('[data-action="next"]').click()`);
    await waitFor(`${el}.status.textContent.includes('catalogo è cambiato')`);
    await evaluate(`${el}.querySelector('[data-action="restart"]').click()`); await waitFor(visible);
    assert.equal(requests.at(-1).cursor, null);
  });
  await check('repeated cursor rejected without showing a duplicate page', async () => {
    await query('loop'); await waitFor(visible); await evaluate(`${el}.querySelector('[data-action="next"]').click()`);
    await waitFor(`${el}.status.textContent.includes('indisponibile')`);
  });
  await check('untrusted titles stay text and product links stay Shopify-local', async () => {
    await query('xss'); await waitFor(visible);
    assert.equal(await evaluate('Boolean(window.pwned)'), false);
    assert.equal(await evaluate(`${el}.results.querySelectorAll('img').length`), 0);
    assert.equal(await evaluate(`${el}.results.querySelector('a').getAttribute('href')`), '/products/card-25002');
  });
  await check('empty state is distinct from unavailable service', async () => {
    await query('empty'); await waitFor(`${visible} && ${el}.results.children.length === 0`);
    assert.equal(await evaluate(`${el}.status.textContent`), locale.empty);
  });
  await check('header chooses game without navigation and submits catalog URL', async () => {
    await navigate('mode=header'); const before = requests.length;
    await evaluate(`${el}.game.value='magic'; ${el}.game.dispatchEvent(new Event('change'))`); await delay(100);
    assert.equal(requests.length, before);
    await query('Lightning'); await waitFor(`${visible} && ${el}.results.textContent.includes('Lightning')`);
    assert.match(await evaluate('location.search'), /view=nla-catalog/);
  });
  await check('header stock change immediately removes old sold-out suggestions', async () => {
    await navigate('mode=header&game=magic');
    await evaluate(`${el}.input.focus(); ${el}.input.value='Lightning'; ${el}.input.dispatchEvent(new Event('input'))`);
    await waitFor(`${el}.list.children.length === 2`);
    assert.equal(await evaluate(`${el}.stock.click(); ${el}.list.hidden && ${el}.list.children.length === 0`), true);
    await waitFor(`${el}.list.children.length === 1`);
    assert.equal(requests.at(-1).request.filters.inStock, true);
  });
  await check('unconfigured endpoint fails visibly without a catalog request', async () => {
    const before = requests.length; await navigate('game=magic&unconfigured=1');
    await waitFor(`${el}.status.textContent.includes('non è ancora collegato')`); assert.equal(requests.length, before);
  });
  await check('back to an unscoped URL hides all previous-game results', async () => {
    await navigate('');
    await evaluate(`${el}.game.value='magic'; ${el}.game.dispatchEvent(new Event('change'))`); await waitFor(visible);
    await evaluate('history.back()'); await waitFor(`${el}.game.value === ''`);
    assert.equal(await evaluate(`${el}.page.hidden`), true);
    assert.equal(await evaluate(`${el}.results.children.length`), 0);
  });
  await check('responsive layout at 320, 375, 430 and 1280 pixels', async () => {
    await navigate('game=magic'); await waitFor(visible);
    for (const width of [320, 375, 430, 1280]) {
      await call('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 });
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, `overflow at ${width}`);
    }
    const screenshot = await call('Page.captureScreenshot', { format: 'png' });
    await writeFile(join(profile, 'catalog-fixture.png'), Buffer.from(screenshot.data, 'base64'));
    console.log(`SCREENSHOT ${join(profile, 'catalog-fixture.png')}`);
  });
  assert.deepEqual(errors, []);
  console.log(`${passed} browser checks passed; fixture responses, not Shopify E2E.`);
} finally {
  socket?.close(); chrome.kill(); server.closeAllConnections(); server.close();
}
