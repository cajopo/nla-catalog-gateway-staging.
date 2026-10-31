import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const [baseline, runtime] = process.argv.slice(2);
assert(baseline && runtime, 'Usage: node tests/theme-catalog-handoff.mjs <private-baseline> <liquidjs-runtime>');
const repo = fileURLToPath(new URL('..', import.meta.url));
const manifest = JSON.parse(await readFile(join(repo, 'theme/patches/catalog-handoff-143.json'), 'utf8'));
const patch = join(repo, 'theme/patches/catalog-handoff-143.patch');
const candidate = await mkdtemp(join(tmpdir(), 'nla-catalog-handoff-143-'));
const normalize = text => text.replace(/\r\n/g, '\n').trimEnd() + '\n';
const hash = text => createHash('sha256').update(text).digest('hex');
for (const [file, expected] of Object.entries(manifest.files)) {
  const source = normalize(await readFile(join(baseline, file), 'utf8'));
  assert.equal(hash(source), expected.beforeSha256, `Baseline changed: ${file}`);
  await mkdir(dirname(join(candidate, file)), { recursive: true });
  await writeFile(join(candidate, file), source);
}
function apply(...args) {
  const result = spawnSync('git', ['-c', 'core.autocrlf=false', 'apply', ...args, patch], { cwd: candidate, encoding: 'utf8', windowsHide: true });
  assert.equal(result.status, 0, result.stderr);
}
apply('--check'); apply();
for (const [file, expected] of Object.entries(manifest.files)) {
  assert.equal(hash(await readFile(join(candidate, file))), expected.afterSha256, `Candidate changed: ${file}`);
}
apply('--reverse', '--check'); apply('--reverse');
for (const [file, expected] of Object.entries(manifest.files)) {
  assert.equal(hash(await readFile(join(candidate, file))), expected.beforeSha256, `Rollback changed: ${file}`);
}
apply();
const added = normalize(await readFile(join(repo, 'theme', manifest.newFile), 'utf8'));
assert.equal(hash(added), manifest.newFileSha256, 'New snippet changed');
await writeFile(join(candidate, manifest.newFile), added);

const require = createRequire(join(resolve(runtime), 'package.json'));
const { Liquid } = require('liquidjs');
const { toLiquidHtmlAST } = require('@shopify/liquid-html-parser');
const sources = {};
for (const file of [...Object.keys(manifest.files), manifest.newFile]) {
  sources[file] = await readFile(join(candidate, file), 'utf8');
  if (file.endsWith('.liquid')) toLiquidHtmlAST(sources[file]);
}
const fixture = await mkdtemp(join(tmpdir(), 'nla-handoff-render-fixture-'));
await cp(join(candidate, 'snippets'), fixture, { recursive: true });
const engine = new Liquid({ root: fixture, extname: '.liquid', strictFilters: true });
for (const name of ['doc', 'stylesheet', 'javascript']) engine.registerTag(name, {
  parse(_token, tokens) { while (tokens.length && tokens.shift().name !== `end${name}`) {} },
  render() { return ''; },
});
engine.registerFilter('t', key => key);
engine.registerFilter('money', cents => `${(cents / 100).toFixed(2)} EUR`);
engine.registerFilter('money_with_currency', cents => `${(cents / 100).toFixed(2)} EUR`);
engine.registerFilter('image_url', () => '/synthetic.png');
engine.registerFilter('payment_button', () => '<button data-accelerated>Checkout</button>');
engine.registerFilter('placeholder_svg_tag', () => '');
engine.registerFilter('asset_url', value => value);
engine.registerFilter('stylesheet_tag', () => '');
await writeFile(join(fixture, 'loading-spinner.liquid'), '');
await writeFile(join(fixture, 'price.liquid'), '<span>native-price</span>');
for (const name of ['icon-close', 'icon-arrow', 'icon-plus']) await writeFile(join(fixture, `${name}.liquid`), '');
const variant = changes => ({ id: 456, available: true, inventory_management: 'shopify', inventory_policy: 'deny',
  inventory_quantity: 1, price: 200, quantity_rule: { min: 1, increment: 1, max: null }, ...changes });
function product(changes = {}, variants = [variant()]) {
  return { id: 123, title: 'Synthetic card', url: '/products/synthetic', tags: ['nla_catalog_only'],
    available: variants.some(v => v.available), variants, selected_or_first_available_variant: variants[0],
    metafields: { sync: { productid: { type: 'number_integer', value: 789 } }, powertools: { id: { type: 'single_line_text_field', value: '789' } } },
    ...changes };
}
const ready = (p, v = p.selected_or_first_available_variant) => engine.renderFile('nla-catalog-variant-ready', { product: p, variant: v }).then(v => v.trim() === 'true');
const invalid = [
  variant({ inventory_quantity: 0 }), variant({ inventory_quantity: -1 }), variant({ available: false }),
  variant({ inventory_management: null }), variant({ price: 0 }), variant({ price: null }),
  variant({ id: null }), variant({ id: 0 }), variant({ inventory_policy: 'unknown' }),
  variant({ inventory_quantity: 0, inventory_policy: 'continue' }),
];
assert.equal(await ready(product()), true);
assert.equal(await ready(product({}, [variant({ inventory_policy: 'continue' })])), true);
for (const v of invalid) assert.equal(await ready(product({}, [v])), false);
for (const change of [
  { id: null }, { id: 0 }, { metafields: {} },
  { metafields: { sync: { productid: { type: 'number_integer', value: 789 } }, powertools: { id: { type: 'single_line_text_field', value: '790' } } } },
  { metafields: { sync: { productid: { type: 'single_line_text_field', value: '789' } }, powertools: { id: { type: 'single_line_text_field', value: '789' } } } },
]) assert.equal(await ready(product(change)), false);

const main = sources['sections/main-product.liquid'];
const prelude = main.match(/{% liquid\s+assign variant_images[\s\S]*?%}/)[0];
const pdpBlocked = p => engine.parseAndRender(prelude + '{{ catalog_only }}', { product: p }).then(v => v.trim() === 'true');
assert.equal(await pdpBlocked(product()), false);
assert.equal(await pdpBlocked(product({}, [variant({ price: 0 }), variant({ id: 457 })])), true);
assert.equal(await pdpBlocked(product({}, [variant({ inventory_quantity: 0 })])), true);
const picker = main.split("{%- when 'variant_picker' -%}")[1].split("{%- when 'buy_buttons' -%}")[0];
assert(picker.includes("render 'product-variant-picker'")); assert(!picker.includes('catalog_only'));
const formBranch = main.split("{%- when 'buy_buttons' -%}")[1].split("{%- when 'rating' -%}")[0];
assert(formBranch.includes("render 'buy-buttons'")); assert(!formBranch.includes('catalog_only'));
const mockFormTag = source => source.replace(/{%-?\s*form\s+'product',[\s\S]*?-?%}/g, '<form>').replace(/{%-?\s*endform\s*-?%}/g, '</form>');
const buttons = mockFormTag(sources['snippets/buy-buttons.liquid']);
const renderButtons = p => engine.parseAndRender(buttons, { product: p, block: { settings: { show_dynamic_checkout: true } },
  section: { id: 'fixture' }, section_id: 'fixture', product_form_id: 'product-form-fixture', form: {}, show_pickup_availability: false });
function disabled(html) {
  const tag = html.match(/<button\s+[^>]*id="ProductSubmitButton-fixture"[^>]*>/)[0];
  return /\sdisabled(?:\s|>)/.test(tag);
}
for (const v of invalid) assert.equal(disabled(await renderButtons(product({}, [v]))), true);
assert.equal(disabled(await renderButtons(product())), false);
assert.equal(disabled(await renderButtons(product({}, [variant({ quantity_rule: { min: 2, increment: 1 } })]))), true);
assert(!(await renderButtons(product())).includes('data-accelerated'));
assert((await renderButtons(product({ tags: [] }))).includes('data-accelerated'));
// The same fresh section render moves both directions when a selected variant changes.
assert.deepEqual(await Promise.all([variant({ price: 0 }), variant(), variant({ inventory_quantity: 0 })].map(async v => disabled(await renderButtons(product({}, [v]))))), [true, false, true]);

const card = sources['snippets/card-product.liquid'];
const renderCard = (p, quick_add = 'none') => engine.parseAndRender(mockFormTag(card), { card_product: p, section_id: 'fixture', quick_add });
const mixed = product({}, [variant({ price: 0 }), variant({ id: 457, price: 300 }), variant({ id: 458, price: 200 })]);
const mixedCard = await renderCard(mixed);
assert(mixedCard.includes('2.00 EUR')); assert(!mixedCard.includes('nla-card__unavailable'));
assert((await renderCard(product({}, [variant({ inventory_quantity: 0 })]))).includes('nla-card__unavailable'));
assert(!(await renderCard(product(), 'bulk')).includes('<quick-add-bulk'));
assert((await renderCard(product(), 'standard')).includes('name="add"'));

const adapter = createRequire(import.meta.url)(join(candidate, 'assets/nla-wishlist-data.js'));
async function resolveWishlist({ catalogOnly = true, qty = 1, price = 200, available = true, tracked = 'shopify', policy = 'deny', identity = '789', game = 'yugioh', recordGame = game, sellingPlan = false, requested = {} } = {}) {
  const version = ['riftbound', 'lorcana'].includes(game) ? 2 : 1;
  const productGid = 'gid://shopify/Product/123', variantGid = 'gid://shopify/ProductVariant/456';
  const item = { contractVersion: version, productGid, handle: 'synthetic', game: recordGame, productFamily: 'single', canonicalCardName: 'Synthetic card', variants: [{ variantGid, selectedOptions: [] }] };
  const client = adapter.createClient({ fetch: async (_url, init) => {
    const data = init.method === 'POST'
      ? { contractVersion: version, nextCursor: null, page: { contractVersion: version, request: JSON.parse(init.body).request, datasetGeneration: 'sha256:' + 'a'.repeat(64), items: [item], returnedProductCount: 1, hasNextPage: false } }
      : { contractVersion: 1, productId: productGid, handle: 'synthetic', title: 'Synthetic card', currency: 'EUR', catalogOnly, requiresSellingPlan: sellingPlan, image: null,
        sourceIds: { powerTools: { type: 'single_line_text_field', value: identity }, sync: { type: 'number_integer', value: '789' } }, page: 1, pages: 1, variantCount: 1,
        variants: [{ id: '456', price, available, inventoryQuantity: qty, inventoryPolicy: policy, inventoryManagement: tracked, selectedOptions: [] }] };
    return { ok: true, text: async () => JSON.stringify(data) };
  } });
  return client.resolve({ game, productId: productGid, name: 'Synthetic card', exact: true, ...requested });
}
for (const game of ['magic', 'pokemon', 'yugioh', 'one-piece', 'riftbound', 'lorcana']) {
  const result = await resolveWishlist({ game }); assert.equal(result.offers.length, 1); assert.equal(result.offers[0].stock, 1);
}
for (const changes of [{ qty: 0 }, { qty: -1 }, { available: false }, { tracked: null }, { price: 0 }, { price: null },
  { identity: '790' }, { identity: '' }, { sellingPlan: true }, { qty: 0, policy: 'continue' }, { policy: 'unknown' },
  { recordGame: 'pokemon' }, { requested: { cardmarketId: '790' } }, { requested: { languages: ['it'] } },
  { requested: { minCondition: 'NM' } }, { requested: { foil: 'yes' } }]) {
  assert.equal((await resolveWishlist(changes)).offers.length, 0, JSON.stringify(changes));
}
assert.equal((await resolveWishlist({ catalogOnly: false })).offers.length, 1);
assert.equal((await resolveWishlist({ policy: 'continue' })).offers.length, 1);
const receipt = { status: 'passed', candidate, sourceTheme: manifest.sourceTheme, shopifyChanged: false,
  checks: ['exact source/candidate hashes', 'reverse patch restores baseline', 'four official Liquid AST parses',
    'identity/stock/price/policy readiness', 'selected variant and quantity rules', 'stock-first/price-first remain blocked',
    'mixed-variant card price', 'no tagged accelerated/bulk bypass', 'six-game wishlist and fresh variant facts'] };
await writeFile(join(candidate, 'handoff-test-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt));
