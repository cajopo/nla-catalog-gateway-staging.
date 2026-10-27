import assert from 'node:assert/strict';
import { readFile, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { arenaFixture } from './theme-six-games-fixture.mjs';

const [arenaTheme, liquidRuntime] = process.argv.slice(2);
const arenaHtml = arenaTheme ? await arenaFixture(arenaTheme, liquidRuntime) : null;

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
const imageRequests = [];
const imageFixtures = new Map();
let activeImages = 0; let maxActiveImages = 0;
function product(id, game, name, available = true) {
  return { contractVersion: ['riftbound', 'lorcana'].includes(game) ? 2 : 1,
    productGid: `gid://shopify/Product/${id}`, handle: `card-${id}`, commercialTitle: name,
    canonicalCardName: name, game, productFamily: 'single', productSubtype: null,
    cardMetadata: { expansionCode: id % 2 ? 'SET-B' : 'SET-A', rarity: id % 2 ? 'rare' : 'common' },
    variants: [{ variantGid: `gid://shopify/ProductVariant/${id}`, title: 'Default', selectedOptions: [],
      priceText: available ? '1.20' : '0.00', compareAtPriceText: null, inventoryQuantity: available ? 1 : 0,
      inventoryPolicy: 'DENY', inventoryTracked: true }] };
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (arenaHtml && url.pathname === '/arena-fixture') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(arenaHtml); return;
  }
  if (arenaHtml && url.pathname.startsWith('/assets/')) {
    const name = url.pathname.slice('/assets/'.length);
    if (!/^[a-z0-9.-]+$/.test(name)) { res.writeHead(404).end(); return; }
    try {
      const file = await readFile(join(arenaTheme, 'assets', name));
      res.setHeader('Content-Type', name.endsWith('.js') ? 'text/javascript' : name.endsWith('.css') ? 'text/css' : 'image/png');
      res.end(file);
    } catch { res.writeHead(404).end(); }
    return;
  }
  const productMatch = url.pathname.match(/^\/(?:it\/)?products\/([^/]+)\.js$/);
  if (productMatch) {
    const handle = decodeURIComponent(productMatch[1]); imageRequests.push(url.pathname);
    activeImages += 1; maxActiveImages = Math.max(maxActiveImages, activeImages);
    try {
      const fixture = imageFixtures.get(handle) || {};
      await new Promise(resolve => setTimeout(resolve, fixture.delay || 40));
      res.statusCode = fixture.status || 200; res.setHeader('Content-Type', 'application/json');
      if (fixture.malformed) res.end('{invalid');
      else res.end(JSON.stringify({ id: Number(handle.replace('card-', '')), handle,
        featured_image: 'https://cdn.shopify.com/nla-fixture.png', ...fixture.product }));
    } finally { activeImages -= 1; }
    return;
  }
  if (!['/apps/nla/catalog', '/apps/nla-catalog'].includes(url.pathname)) {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    res.end(fixtureHtml(url.searchParams.get('mode') || 'page', url.searchParams.has('unconfigured') ? '' : '/apps/nla/catalog'));
    return;
  }
  let raw = '';
  for await (const chunk of req) raw += chunk;
  const body = JSON.parse(raw); requests.push(body);
  const { request, cursor } = body;
  const q = request.q || '';
  const names = { magic: ['Lightning Bolt', 'Lightning Bolt (foil)'], pokemon: ['Pikachu', 'Pikachu (promo)'],
    yugioh: ['Dragon fixture', 'Dragon fixture (foil)'], 'one-piece': ['Pirate fixture', 'Pirate fixture (foil)'],
    riftbound: ['Riftbound fixture', 'Riftbound fixture (foil)'], lorcana: ['Lorcana fixture', 'Lorcana fixture (foil)'] }[request.game];
  let items = names.map((name, index) => product(25000 + index, request.game, name, index === 0));
  if (q === 'empty') items = [];
  else if (q === 'xss') items = [product(25002, request.game, '<img src=x onerror="window.pwned=1">')];
  else if (!['slow', 'fast', 'leak', 'duplicate', 'restart', 'malformed', 'loop'].includes(q)) {
    items = items.filter(item => item.canonicalCardName.toLowerCase().includes(q.toLowerCase()));
  }
  if (request.filters.inStock) items = items.filter(item => item.variants[0].inventoryQuantity > 0);
  const scopedItems = items;
  const dimensions = ['expansionCode', 'rarity'];
  const facets = dimensions.map(dimension => {
    const other = dimensions.find(key => key !== dimension);
    const counts = new Map();
    for (const item of scopedItems) {
      if (request.filters[other] && item.cardMetadata[other] !== request.filters[other]) continue;
      const value = item.cardMetadata[dimension];
      counts.set(value, (counts.get(value) || 0) + 1);
    }
    const selected = request.filters[dimension];
    if (selected && !counts.has(selected)) counts.set(selected, 0);
    return { dimension, missingValueCount: 0, values: [...counts].map(([value, count]) => ({ value, count })) };
  });
  items = items.filter(item => dimensions.every(key => !request.filters[key] || item.cardMetadata[key] === request.filters[key]));
  if (q === 'leak') items[0].game = 'one-piece';
  if (q === 'duplicate') items = [items[0], items[0]];
  const allItems = items;
  if (cursor) items = items.slice(1); else items = items.slice(0, 1);
  const nextCursor = !cursor && allItems.length > 1 ? 'opaque-next-page' : null;
  const data = { contractVersion: body.contractVersion, nextCursor: q === 'loop' && cursor ? cursor : nextCursor,
    page: { contractVersion: body.contractVersion, datasetGeneration: generation, request, requestContextSha256: 'b'.repeat(64),
      returnedProductCount: items.length, returnedVariantCount: items.length, items,
      hasNextPage: q === 'loop' && cursor ? true : nextCursor !== null } };
  if (q === 'duplicate') { data.page.items = allItems; data.page.returnedProductCount = allItems.length; }
  if (body.includeFacets) data.facets = facets;
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
    if (message.method === 'Fetch.requestPaused') {
      const { requestId, request } = message.params;
      const args = request.url.endsWith('/broken.png')
        ? ['Fetch.failRequest', { requestId, errorReason: 'Failed' }]
        : ['Fetch.fulfillRequest', { requestId, responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'image/png' }],
          body: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lXcAAAAASUVORK5CYII=' }];
      call(...args).catch(error => errors.push(String(error))); return;
    }
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails.text);
    if (message.id) { const slot = pending.get(message.id); if (!slot) return; clearTimeout(slot.timer); pending.delete(message.id); message.error ? slot.reject(message.error) : slot.resolve(message.result); }
  });
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++nextId;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Chrome command timed out: ${method}`)); }, 10000);
    pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
  });
  await call('Runtime.enable'); await call('Page.enable');
  await call('Fetch.enable', { patterns: [{ urlPattern: 'https://cdn.shopify.com/*' }] });
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
  const visible = `${el}?.page?.hidden === false`;
  const query = async value => {
    await evaluate(`${el}.input.value = ${JSON.stringify(value)}; ${el}.form.requestSubmit()`);
  };
  let passed = 0;
  async function check(name, action) { await action(); passed += 1; console.log(`PASS ${name}`); }
  await check('explicit game, sold-out default and opaque next-page navigation', async () => {
    await navigate('game=magic'); await waitFor(visible);
    assert.equal(requests.at(-1).request.filters.inStock, null);
    assert.equal(await evaluate(`${el}.results.firstChild.dataset.productGid`), 'gid://shopify/Product/25000');
    assert.match(await evaluate(`${el}.results.textContent`), /1\.20 EUR/);
    await evaluate(`${el}.querySelector('[data-action="next"]').click()`); await waitFor(`${visible} && ${el}.results.textContent.includes('SOLD OUT')`);
    assert.equal(await evaluate(`${el}.results.firstChild.dataset.productGid`), 'gid://shopify/Product/25001');
    assert.match(await evaluate('location.search'), /cursor=opaque-next-page/);
    assert.doesNotMatch(await evaluate(`${el}.results.textContent`), /Prezzo n\/d|0\.00 EUR/);
    assert.equal(await evaluate(`${el}.results.firstChild.querySelectorAll('p').length`), 1);
    assert.equal(await evaluate(`${el}.results.firstChild.querySelector('p').textContent`), 'SOLD OUT');
    assert.equal(await evaluate(`getComputedStyle(${el}.results.firstChild.querySelector('p')).color`), 'rgb(255, 69, 69)');
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
    assert.match(await evaluate(`${el}.list.textContent`), /SOLD OUT/);
    assert.equal(await evaluate(`getComputedStyle(${el}.list.querySelector('.nla-catalog__sold-out')).color`), 'rgb(255, 69, 69)');
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
    assert.equal(await evaluate(`${el}.results.querySelectorAll('img[src="x"]').length`), 0);
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
  for (const [game, title, other] of [['riftbound', 'Riftbound', 'lorcana'], ['lorcana', 'Lorcana', 'riftbound']]) {
    await check(`${game} version 2 search, filters, cursor, back and reload`, async () => {
      await navigate(`game=${game}&q=fixture`); await waitFor(visible);
      assert.equal(requests.at(-1).contractVersion, 2);
      assert.equal(requests.at(-1).request.contractVersion, 2);
      assert.match(await evaluate(`${el}.results.textContent`), new RegExp(title));
      assert.deepEqual(await evaluate(`Array.from(${el}.game.options, option => option.value)`),
        ['', 'magic', 'pokemon', 'yugioh', 'one-piece', 'riftbound', 'lorcana']);
      await evaluate(`${el}.querySelector('[data-action="next"]').click()`);
      await waitFor(`${visible} && ${el}.results.firstChild?.dataset.productGid.endsWith('/25001')`);
      await call('Page.reload');
      await waitFor(`${visible} && ${el}.results.firstChild?.dataset.productGid.endsWith('/25001')`);
      assert.equal(requests.at(-1).cursor, 'opaque-next-page');
      await evaluate(`${el}.expansion.value='SET-B'; ${el}.expansion.dispatchEvent(new Event('change'))`);
      await waitFor(`${visible} && location.search.includes('expansionCode=SET-B')`);
      assert.equal(requests.at(-1).cursor, null);
      await evaluate(`${el}.game.value='${other}'; ${el}.game.dispatchEvent(new Event('change'))`);
      await waitFor(`${visible} && ${el}.pageRequest.game === '${other}'`);
      assert.equal(requests.at(-1).request.filters.expansionCode, undefined);
      assert.equal(requests.at(-1).request.filters.rarity, undefined);
      assert.equal(requests.at(-1).cursor, null);
      assert.doesNotMatch(await evaluate(`${el}.results.textContent`), new RegExp(title));
      await evaluate('history.back()');
      await waitFor(`${visible} && ${el}.pageRequest.game === '${game}'`);
      assert.equal(await evaluate(`${el}.expansion.value`), 'SET-B');
      assert.match(await evaluate(`${el}.results.textContent`), new RegExp(title));
    });
    await check(`${game} header keyboard suggestions and responsive selector`, async () => {
      await navigate(`mode=header&game=${game}`);
      await evaluate(`${el}.input.focus(); ${el}.input.value='fixture'; ${el}.input.dispatchEvent(new Event('input'))`);
      await waitFor(`${el}.list.children.length === 2`);
      assert.equal(requests.at(-1).request.game, game);
      assert.equal(requests.at(-1).contractVersion, 2);
      assert.match(await evaluate(`${el}.list.textContent`), new RegExp(title));
      await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown' });
      await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter' });
      await waitFor(`${visible} && ${el}.pageRequest.game === '${game}'`);
      assert.equal(await evaluate(`${el}.input.value`), `${title} fixture`);
      for (const width of [320, 375, 430, 1280]) {
        await call('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 });
        assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, `${game} overflow at ${width}`);
      }
    });
  }
  const renderImages = async items => {
    await evaluate(`(async () => { if (!${el}.testImageHook) { ${el}.testImageHook = ${el}.loadImages.bind(${el});
      ${el}.loadImages = (...args) => (${el}.testImagesReady = ${el}.testImageHook(...args)); }
      ${el}.renderPage({page:{items:${JSON.stringify(items)}}}, ${el}.request()); ${el}.page.hidden = false;
      await ${el}.testImagesReady; })()`);
  };
  await check('visible-page images use identity-verified locale URLs, four workers and unchanged cards', async () => {
    await navigate('mode=header&game=magic'); await delay(100); maxActiveImages = 0;
    await evaluate(`${el}.dataset.rootUrl='/it/'`);
    const items = Array.from({ length: 24 }, (_, i) => product(30000 + i, 'magic', `Image card ${i}`, i % 2 === 0));
    items[3].variants[0].priceText = '2.50';
    const before = imageRequests.length; await renderImages(items);
    await waitFor(`${el}.results.querySelectorAll('img').length === 24`);
    assert.equal(imageRequests.length - before, 24); assert.equal(maxActiveImages, 4);
    assert(imageRequests.slice(before).every(path => path.startsWith('/it/products/')));
    assert.deepEqual(await evaluate(`Array.from(${el}.results.children, node => node.dataset.productGid)`), items.map(item => item.productGid));
    assert.equal(await evaluate(`${el}.results.querySelector('img').loading`), 'lazy');
    assert.equal(await evaluate(`${el}.results.querySelector('img').decoding`), 'async');
    assert.equal(await evaluate(`${el}.results.querySelector('img').alt`), 'Image card 0');
    assert.match(await evaluate(`${el}.results.children[1].textContent`), /SOLD OUT/);
    assert.doesNotMatch(await evaluate(`${el}.results.children[1].textContent`), /Prezzo n\/d|0\.00 EUR/);
    assert.match(await evaluate(`${el}.results.children[3].textContent`), /SOLD OUT.*2\.50 EUR/);
    assert.equal(await evaluate(`getComputedStyle(${el}.results.querySelector('img')).objectFit`), 'contain');
    await renderImages(items); assert.equal(imageRequests.length - before, 24, 'cached images must not refetch');
    for (let page = 1; page <= 4; page++) await renderImages(items.map((item, index) => product(30000 + page * 24 + index, 'magic', item.commercialTitle)));
    assert.equal(await evaluate(`${el}.imageCache.size`), 96);
  });
  await check('missing, mismatched, unsafe and failed images leave cards and translated fallback intact', async () => {
    const fixtures = [
      { product: { id: 1 } }, { product: { handle: 'wrong' } }, { product: { featured_image: null } },
      { product: { featured_image: 'https://evil.example/card.png' } },
      { product: { featured_image: 'javascript:alert(1)' } },
      { product: { featured_image: 'http://cdn.shopify.com/card.png' } },
      { product: { featured_image: 'https://user@cdn.shopify.com/card.png' } },
      { status: 404 }, { malformed: true }, { product: { featured_image: 'https://cdn.shopify.com/broken.png' } }
    ];
    const items = fixtures.map((fixture, i) => {
      imageFixtures.set(`card-${40000 + i}`, fixture); return product(40000 + i, 'magic', `Fallback ${i}`);
    });
    await renderImages(items); await evaluate(`${el}.results.querySelector('img')?.scrollIntoView()`);
    await waitFor(`${el}.results.querySelectorAll('img').length === 0`);
    assert.equal(await evaluate(`${el}.results.children.length`), items.length);
    assert(await evaluate(`Array.from(${el}.results.querySelectorAll('.nla-catalog__media')).every(node => node.textContent === ${JSON.stringify(locale.image_notice)})`));
  });
  await check('obsolete image requests cannot replace a newer page or alter its identity', async () => {
    imageFixtures.set('card-50000', { delay: 600 });
    const old = product(50000, 'magic', 'Old card'); const fresh = product(50001, 'magic', 'New card');
    await evaluate(`${el}.renderPage({page:{items:[${JSON.stringify(old)}]}}, ${el}.request())`);
    await delay(60); await renderImages([fresh]); await delay(700);
    assert.equal(await evaluate(`${el}.results.firstChild.dataset.productGid`), fresh.productGid);
    assert.equal(await evaluate(`${el}.results.querySelector('img').alt`), 'New card');
    assert.equal(await evaluate(`${el}.imageCache.has(${JSON.stringify(old.productGid + '|' + old.handle)})`), false);
  });
  if (arenaHtml) {
    await check('current Arena desktop/mobile menus add two games before utility links', async () => {
      await call('Page.navigate', { url: origin + '/arena-fixture' });
      await waitFor('document.querySelector("[data-wl=refresh]") !== null');
      const expected = ['Magic', 'Pokémon', 'One Piece', 'Yu-Gi-Oh!', 'Riftbound', 'Disney Lorcana', 'Eventi', 'Vendi carte', 'Il negozio'];
      for (const selector of ['.nla-desktop-nav > ul', '.nla-mobile-menu__panel nav > ul']) {
        const names = await evaluate(`Array.from(document.querySelector(${JSON.stringify(selector)}).children, node => node.querySelector('summary,a').textContent.trim())`);
        assert.deepEqual(names, expected);
        for (const game of ['riftbound', 'lorcana']) {
          const links = await evaluate(`Array.from(document.querySelectorAll(${JSON.stringify(selector)} + ' a'), link => link.href).filter(href => new URL(href).searchParams.get('game') === '${game}')`);
          assert.equal(links.length, 4);
          assert.deepEqual(links.map(link => new URL(link).searchParams.get('family')), ['all', 'single', 'sealed', 'accessory']);
          assert(links.every(link => new URL(link).pathname === '/it/search' && new URL(link).searchParams.get('view') === 'nla-catalog'));
        }
      }
    });
    await check('current Arena six-game navigation and wishlist fit desktop/mobile widths', async () => {
      for (const width of [320, 375, 430, 1024, 1280]) {
        await call('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: width < 600 });
        await evaluate(`document.querySelector('.nla-mobile-menu').open = ${width < 990}`);
        await evaluate(`document.querySelectorAll('details').forEach(node => { if (node.querySelector('summary')?.textContent.trim() === 'Disney Lorcana') node.open = true; })`);
        assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, `Arena overflow at ${width}`);
        const navigation = width < 990 ? '.nla-mobile-menu__panel' : '.nla-desktop-nav';
        const bounds = await evaluate(`Array.from(document.querySelectorAll('${navigation} a')).filter(a => new URL(a.href).searchParams.get('game') === 'lorcana').map(a => { const b=a.getBoundingClientRect(); return [b.left,b.right,b.width,b.height]; })`);
        assert(bounds.every(([left, right, size, height]) => left >= 0 && right <= width && size > 0 && height > 0), `Navigation outside viewport at ${width}`);
        if ([375, 1280].includes(width)) {
          const shot = await call('Page.captureScreenshot', { format: 'png' });
          const path = join(profile, `navigation-${width}.png`);
          await writeFile(path, Buffer.from(shot.data, 'base64')); console.log(`SCREENSHOT ${path}`);
        }
      }
    });
    for (const [game, label] of [['riftbound', 'Riftbound'], ['lorcana', 'Disney Lorcana']]) {
      await check(`current wishlist ${game} search and keyboard selection`, async () => {
        await evaluate(`document.querySelectorAll('nla-wishlist details').forEach(node => { node.open = true; })`);
        await evaluate(`document.querySelector('[data-wl=game]').value='${game}'; document.querySelector('[data-wl=search]').value='fixture'; document.querySelector('[data-wl=game]').dispatchEvent(new Event('change'))`);
        await waitFor(`document.querySelector('[data-wl=search-results]').textContent.includes('${label}')`);
        assert.equal(requests.at(-1).contractVersion, 2);
        assert.equal(requests.at(-1).request.game, game);
        await evaluate(`document.querySelector('[data-wl=search]').focus()`);
        await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'ArrowDown', code: 'ArrowDown' });
        assert.equal(await evaluate(`document.activeElement.closest('[data-wl=search-results]') !== null`), true);
      });
    }
  }
  assert.deepEqual(errors, []);
  console.log(`${passed} browser checks passed; fixture responses, not Shopify E2E.`);
} finally {
  socket?.close(); chrome.kill(); server.closeAllConnections(); server.close();
}
