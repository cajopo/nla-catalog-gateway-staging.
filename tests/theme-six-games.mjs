import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cp, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';

const source = process.argv[2];
assert(source, 'Usage: node tests/theme-six-games.mjs <private-current-theme-directory>');
const patch = fileURLToPath(new URL('../theme/patches/multigame-20261027.patch', import.meta.url));
const baseline = {
  'sections/nla-header.liquid': '09180b38f5628d5667d1d845b2e12f4054203ccda7bf755797f4d29df736477f',
  'assets/nla-wishlist-core.js': '8d5fad578a8699b564ef75bc60daba8131fcd33f784a97db2cf36762bb9e3176',
  'assets/nla-wishlist-data.js': '01c9c475567f6029b291f6d5d446fa405f0838e02aafbf410b36d723dd6d30e1',
  'assets/nla-wishlist.js': 'd9e5a888fa14087aaec50db039723f2691b3e3bca1590f1a0a86972e2794d59e',
  'snippets/nla-wishlist.liquid': '8f55da527364d328f118526d468bb87a73037e5525d7c675cbdf67d0d584ae83',
};
for (const [file, sha256] of Object.entries(baseline)) {
  const data = await readFile(join(source, file));
  assert.equal(createHash('sha256').update(data).digest('hex'), sha256, `Source changed: ${file}`);
}
const candidate = await mkdtemp(join(tmpdir(), 'nla-six-games-124-'));
await cp(resolve(source), candidate, { recursive: true });
for (const args of [['apply', '--check', patch], ['apply', patch], ['apply', '--reverse', '--check', patch]]) {
  const result = spawnSync('git', args, { cwd: candidate, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr || result.error?.message);
}
await cp(fileURLToPath(new URL('../theme/snippets/nla-new-game-navigation.liquid', import.meta.url)),
  join(candidate, 'snippets/nla-new-game-navigation.liquid'));
await cp(fileURLToPath(new URL('../theme/snippets/nla-catalog-search.liquid', import.meta.url)),
  join(candidate, 'snippets/nla-catalog-search.liquid'));
for (const locale of ['en.default.json', 'it.json']) {
  const current = (await readFile(join(candidate, 'locales', locale), 'utf8')).replace(/^\s*\/\*[\s\S]*?\*\/\s*/, '');
  const complete = JSON.parse(current);
  const fragment = JSON.parse(await readFile(new URL(`../theme/locales/${locale}`, import.meta.url), 'utf8'));
  for (const game of ['riftbound', 'lorcana']) complete.nla_catalog[game] = fragment.nla_catalog[game];
  await writeFile(join(candidate, 'locales', locale), JSON.stringify(complete, null, 2) + '\n');
}
const header = await readFile(join(candidate, 'sections/nla-header.liquid'), 'utf8');
assert.equal((header.match(/{% if forloop.index == 4 %}/g) || []).length, 2);
assert.match(header, /render 'nla-new-game-navigation', mode: 'mobile'/);
assert.match(header, /render 'nla-new-game-navigation', mode: 'desktop'/);
const require = createRequire(import.meta.url);
const core = require(join(candidate, 'assets/nla-wishlist-core.js'));
const data = require(join(candidate, 'assets/nla-wishlist-data.js'));
const games = ['magic', 'pokemon', 'yugioh', 'one-piece', 'riftbound', 'lorcana'];
const clone = value => JSON.parse(JSON.stringify(value));
for (const [label, expected] of [['Magic', 'magic'], ['Pokémon', 'pokemon'], ['Yu-Gi-Oh!', 'yugioh'],
  ['One Piece', 'one-piece'], ['Riftbound', 'riftbound'], ['Riftbound TCG', 'riftbound'],
  ['Lorcana', 'lorcana'], ['Disney Lorcana', 'lorcana'], ['Disney Lorcana TCG', 'lorcana']]) {
  const row = core.normalizeRow({ name: 'Shared fixture name', game: label, quantity: 1 });
  assert.equal(row.game, expected, `Wishlist game alias: ${label}`);
  const csv = core.exportCSV([row]);
  const imported = core.parseFile(csv, 'wishlist.csv');
  assert.equal(imported.rows[0].game, expected, `${label}: export/import preserves game`);
}
const unknown = core.normalizeRow({ name: 'Shared fixture name', game: 'unknown-card-game', quantity: 1 });
assert.equal(unknown.game, '', 'Do not infer game from the card title');
assert.equal(core.normalizeRow({ name: 'Riftbound fixture', quantity: 1 }).game, '');
const snippet = await readFile(join(candidate, 'snippets/nla-wishlist.liquid'), 'utf8');
for (const selector of ['data-wl="game"', 'data-wl="paste-game"', 'name="game" required']) {
  const select = [...snippet.matchAll(/<select([^>]*)>([\s\S]*?)<\/select>/g)].find(match => match[1].includes(selector));
  assert(select, selector);
  assert.deepEqual([...select[2].matchAll(/<option value="([^"]+)"/g)].map(match => match[1]).sort(), [...games].sort());
}
const ui = await readFile(join(candidate, 'assets/nla-wishlist.js'), 'utf8');
assert.match(ui, /riftbound: 'Riftbound', lorcana: 'Disney Lorcana'/);

const sent = [];
let tamper = () => {};
let paginate = false;
const client = data.createClient({ fetch: async (url, init) => {
  assert.equal(new URL(url).pathname, '/apps/nla-catalog');
  const body = JSON.parse(init.body); sent.push(body);
  const { request, cursor } = body;
  const version = ['riftbound', 'lorcana'].includes(request.game) ? 2 : 1;
  assert.equal(body.contractVersion, version);
  assert.equal(request.contractVersion, version);
  assert.equal(request.productFamily, 'single');
  if (cursor) assert.equal(cursor, `cursor-${request.game}`, 'Opaque cursors stay inside their game');
  const id = 100 + games.indexOf(request.game) * 10 + (cursor ? 1 : 0);
  const nextCursor = paginate && !cursor ? `cursor-${request.game}` : null;
  const response = { contractVersion: version, nextCursor,
    page: { contractVersion: version, request: clone(request), datasetGeneration: `sha256:${'a'.repeat(64)}`,
      hasNextPage: Boolean(nextCursor), returnedProductCount: 1,
      items: [{ contractVersion: version, productGid: `gid://shopify/Product/${id}`, handle: `fixture-${id}`,
        game: request.game, productFamily: 'single', canonicalCardName: 'Shared fixture name',
        variants: [{ variantGid: `gid://shopify/ProductVariant/${id}`, selectedOptions: [] }] }] } };
  tamper(response);
  return { ok: true, text: async () => JSON.stringify(response) };
} });
for (const game of games) {
  const found = await client.search('Shared fixture name', game);
  assert.equal(found.items.length, 1);
  assert.equal(found.items[0].game, game);
  assert.equal(found.truncated, false);
}
paginate = true; sent.length = 0;
const mixed = await client.search('Shared fixture name');
assert.equal(mixed.items.length, 12, 'Mixed wishlist searches all six games');
assert.equal(new Set(mixed.items.map(item => item.game)).size, 6);
assert.deepEqual(sent.filter(body => !body.cursor).map(body => body.request.game), games);
assert.equal(sent.length, 12, 'Each game traverses its own second page');
paginate = false;
for (const game of ['riftbound', 'lorcana']) {
  for (const mutate of [
    value => { value.contractVersion = 1; },
    value => { value.page.contractVersion = 1; },
    value => { value.page.request.contractVersion = 1; },
    value => { value.page.items[0].contractVersion = 1; },
    value => { value.page.items[0].game = game === 'riftbound' ? 'lorcana' : 'riftbound'; },
  ]) {
    tamper = mutate;
    await assert.rejects(client.search('Shared fixture name', game), /invalid_catalog/);
  }
}
tamper = () => {};
const count = sent.length;
assert.deepEqual(await client.search('Shared fixture name', 'unknown-card-game'), { items: [], truncated: false });
assert.equal(sent.length, count);
for (const file of ['sections/nla-home.liquid', 'assets/nla-hot-buylist.js', 'assets/nla-hot-buylist.css', 'snippets/nla-hot-buylist.liquid']) {
  assert.deepEqual(await readFile(join(source, file)), await readFile(join(candidate, file)), `${file} must remain byte-for-byte unchanged`);
}
console.log('PASS guarded additive patch/reverse, six-game wishlist aliases/import/export/search/pagination, contract rejection and unchanged home');
console.log(`CANDIDATE ${candidate}`);
