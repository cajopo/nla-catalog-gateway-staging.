import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../theme/snippets/nla-catalog-search.liquid', import.meta.url), 'utf8');
const script = source.match(/{% javascript %}([\s\S]*?){% endjavascript %}/)[1];
const generation = `sha256:${'a'.repeat(64)}`;
const clone = value => JSON.parse(JSON.stringify(value));

class Element extends EventTarget {
  value = ''; checked = false; hidden = true; disabled = false; textContent = ''; children = [];
  attributes = new Map(); dataset = {};
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  set innerHTML(_value) { throw new Error('metadata options must never use HTML'); }
  reportValidity() { return true; }
  focus() {}
  contains() { return false; }
}
class Component extends Element {
  constructor() {
    super();
    this.dataset = { mode: 'page', searchUrl: '/search', endpoint: '/apps/nla/catalog' };
    this.nodes = new Map();
    this.querySelector('form').elements = Object.fromEntries(
      ['game', 'family', 'q', 'stock', 'expansionCode', 'rarity'].map(key => [key, new Element()]));
    this.querySelector('form').elements.family.value = 'single';
    this.querySelector('form').elements.game.options = [
      { value: '', textContent: 'Choose game' }, { value: 'magic', textContent: 'Magic' },
      { value: 'pokemon', textContent: 'Pokémon' },
    ];
  }
  querySelector(selector) {
    if (!this.nodes.has(selector)) this.nodes.set(selector, new Element());
    return this.nodes.get(selector);
  }
}
const location = { origin: 'https://example.test', href: 'https://example.test/search?preview_theme_id=123' };
const classes = new Map();
const sent = [];
let transport;
const context = {
  HTMLElement: Component, window: new EventTarget(), location, URL, Event, AbortController,
  setTimeout: () => 1, clearTimeout: () => {},
  document: { title: '', createElement: () => new Element() },
  customElements: { get: name => classes.get(name), define: (name, value) => classes.set(name, value) },
  history: { pushState: (_state, _title, url) => { location.href = url.href; } },
  fetch: async (_url, options) => {
    const body = JSON.parse(options.body); sent.push({ body, signal: options.signal });
    return transport(body, options);
  },
};
vm.runInNewContext(script, context);
const Catalog = classes.get('nla-catalog-search');
const components = [];
function component(mode = 'page') {
  const value = new Catalog(); value.dataset.mode = mode;
  value.restore = () => {}; value.connectedCallback(); delete value.restore;
  value.game.value = 'magic'; value.input.value = 'Bolt';
  value.renderPage = () => {}; // Rendering is outside this VM test; this candidate still needs browser QA.
  value.renderSuggestions = () => {};
  components.push(value); return value;
}
function payload(body, { values, selectedCount = 1 } = {}) {
  const filters = body.request.filters;
  const result = {
    contractVersion: 1, nextCursor: null,
    page: { contractVersion: 1, datasetGeneration: generation, request: clone(body.request),
      items: [], returnedProductCount: 0, hasNextPage: false },
  };
  if (body.includeFacets) result.facets = ['expansionCode', 'rarity'].map(dimension => ({
    dimension, missingValueCount: 0, values: dimension === 'expansionCode' && values ? values
      : [{ value: filters[dimension] || (dimension === 'expansionCode' ? 'SET' : 'Rare'), count: selectedCount }],
  }));
  if (body.includeSuggestions) result.suggestions = [];
  return result;
}
transport = async body => ({ ok: true, json: async () => payload(body) });

const page = component();
const rawSet = `é %_'[]/<img src=x onerror=alert(1)>`;
const rawRarity = '超 Rare & "quoted"';
page.resetMetadata(rawSet, rawRarity);
page.stock.checked = true;
const requested = page.request();
const restoredUrl = page.url(requested, 'opaque-cursor', generation);
assert.equal(restoredUrl.searchParams.get('expansionCode'), rawSet);
assert.equal(restoredUrl.searchParams.get('rarity'), rawRarity);
assert.equal(restoredUrl.searchParams.get('preview_theme_id'), '123');
location.href = restoredUrl.href;
let restored;
page.load = options => { restored = { options, request: page.request() }; };
page.restore();
assert.deepEqual(clone(restored.request), clone(requested));
assert.equal(restored.options.cursor, 'opaque-cursor');
assert.equal(restored.options.generation, generation);
assert.equal(restored.options.invalid, false);
delete page.load;
await page.load(restored.options);
assert.equal(sent.at(-1).body.includeFacets, true);
assert.equal(sent.at(-1).body.cursor, 'opaque-cursor');
assert.equal(sent.at(-1).body.includeSuggestions, undefined);
assert.equal(page.generation, generation);
assert.equal(page.expansion.value, rawSet);
assert.equal(page.metadataFilters.disabled, false);
await page.load({ suggest: true });
assert.equal(sent.at(-1).body.includeFacets, undefined);
assert.equal(sent.at(-1).body.includeSuggestions, true);

for (const key of ['expansionCode', 'rarity']) {
  for (const suffix of [`${key}=`, `${key}=ONE&${key}=TWO`, `${key}=%00`]) {
    location.href = `https://example.test/search?view=nla-catalog&game=magic&q=Bolt&${suffix}`;
    const before = sent.length;
    const realLoad = page.load;
    let restoredLoad;
    page.load = options => { restoredLoad = realLoad.call(page, options); return restoredLoad; };
    page.restore();
    await restoredLoad;
    delete page.load;
    assert.equal(sent.length, before, `invalid URL ${suffix} must fail before fetch`);
    assert.equal(page.recovery.hidden, false);
  }
}
location.href = restoredUrl.href;
page.resetMetadata(rawSet, rawRarity); page.stock.checked = true;
page.nextCursor = 'previous-page'; page.generation = generation;
let filterLoad;
page.load = options => { filterLoad = { options, request: clone(page.request()) }; };
page.expansion.dispatchEvent(new Event('change'));
assert.deepEqual(clone(filterLoad.options), { navigate: true }, 'changing set starts at first page');
assert.equal(filterLoad.request.filters.expansionCode, rawSet);
assert.equal(filterLoad.request.filters.rarity, rawRarity);
assert.equal(filterLoad.request.filters.inStock, true);
page.rarity.value = 'New Rare'; page.rarity.dispatchEvent(new Event('change'));
assert.deepEqual(clone(filterLoad.options), { navigate: true }, 'changing rarity starts at first page');
assert.equal(filterLoad.request.filters.rarity, 'New Rare');
assert.equal(filterLoad.request.filters.expansionCode, rawSet);
assert.equal(filterLoad.request.filters.inStock, true);
delete page.load;

let submitted;
page.submit = () => { submitted = page.request(); };
page.game.value = 'pokemon'; page.game.dispatchEvent(new Event('change'));
assert.equal(page.expansion.value, ''); assert.equal(page.rarity.value, '');
assert.equal(submitted.filters.expansionCode, undefined);
assert.equal(submitted.filters.rarity, undefined);
delete page.submit;

const header = component('header');
header.restore();
assert.equal(header.metadataFilters.hidden, true);
assert.equal(header.expansion.value, ''); assert.equal(header.rarity.value, '');
header.resetMetadata('HIDDEN', 'HIDDEN');
assert.deepEqual(clone(header.request().filters), { inStock: true, productSubtype: null });
await header.load({ suggest: true });
assert.equal(sent.at(-1).body.includeFacets, undefined);
assert.equal(sent.at(-1).body.request.filters.expansionCode, undefined);

const validator = component(); validator.resetMetadata('SELECTED', 'Rare');
const body = { contractVersion: 1, cursor: null, request: clone(validator.request()), includeFacets: true };
const valid = payload(body, { selectedCount: 0 });
assert.doesNotThrow(() => validator.validate(valid, body, generation));
const reject = mutate => {
  const value = clone(valid); mutate(value);
  assert.throws(() => validator.validate(value, body, generation), /unavailable/);
};
reject(value => { value.page.request.filters.expansionCode = 'OTHER'; });
reject(value => { delete value.page.request.filters.rarity; });
reject(value => { value.page.request.filters.extra = 'unexpected'; });
reject(value => { value.page.datasetGeneration = `sha256:${'b'.repeat(64)}`; });
const item = { productGid: 'gid://shopify/Product/1', game: 'magic', productFamily: 'single',
  handle: 'bolt', canonicalCardName: 'Bolt', commercialTitle: 'Bolt print',
  cardMetadata: { expansionCode: 'SELECTED', rarity: 'Rare' },
  variants: [{ priceText: '0', inventoryQuantity: 0 }] };
const withItem = clone(valid); withItem.page.items = [clone(item)]; withItem.page.returnedProductCount = 1;
assert.doesNotThrow(() => validator.validate(withItem, body, generation));
for (const key of ['expansionCode', 'rarity']) {
  const value = clone(withItem); value.page.items[0].cardMetadata[key] = 'OTHER';
  assert.throws(() => validator.validate(value, body, generation), /unavailable/);
}
const missingMetadata = clone(withItem); delete missingMetadata.page.items[0].cardMetadata;
assert.throws(() => validator.validate(missingMetadata, body, generation), /unavailable/);
for (const facets of [undefined, null, {}, [], [valid.facets[0]], [...valid.facets].reverse()]) {
  reject(value => { value.facets = facets; });
}
for (const count of [-1, 1.5, true, '1', Number.MAX_SAFE_INTEGER + 1]) {
  reject(value => { value.facets[0].values[0].count = count; });
  reject(value => { value.facets[0].missingValueCount = count; });
}
for (const badValue of ['', 'x'.repeat(1025), '\u0000', '\ud800', null, 7]) {
  reject(value => { value.facets[0].values[0].value = badValue; });
}
reject(value => { value.facets[0].values.push(clone(value.facets[0].values[0])); });
reject(value => { value.facets[0].values = []; });
reject(value => { value.facets[0].values = [null]; });
reject(value => { value.facets[0].dimension = 'rarity'; });
assert.throws(() => validator.validate(valid, { ...body, includeFacets: false }, generation), /unavailable/);

const large = Array.from({ length: 130 }, (_, index) => ({ value: `SET-${String(index).padStart(3, '0')}`, count: 1 }));
large.push({ value: rawSet, count: 0 });
page.game.value = 'magic'; page.resetMetadata(rawSet, rawRarity);
transport = async request => ({ ok: true, json: async () => payload(request, { values: large }) });
await page.load();
assert.equal(page.expansion.children.length, 132, 'all option plus all 131 values, no top-100 cutoff');
assert.equal(page.expansion.value, rawSet);
assert.equal(page.expansion.children.at(-1).textContent, `${rawSet} (0)`);
assert.equal(page.expansion.children.at(-1).value, rawSet);

const pending = [];
for (const family of ['all', 'single', 'sealed', 'accessory']) {
  const familyPage = component();
  familyPage.family.value = family;
  familyPage.input.value = 'Élite display %_'; familyPage.stock.checked = true;
  familyPage.resetMetadata('OLD', 'Rare');
  let familyLoad;
  familyPage.load = options => { familyLoad = { options, request: clone(familyPage.request()) }; };
  familyPage.family.dispatchEvent(new Event('change'));
  assert.equal(familyPage.expansion.value, ''); assert.equal(familyPage.rarity.value, '');
  assert.equal(familyLoad.request.productFamily, family);
  assert.equal(familyLoad.request.q, 'Élite display %_', 'family change must never discard a typed query');
  assert.equal(familyLoad.request.filters.inStock, true);
  assert.deepEqual(clone(familyLoad.options), { navigate: true }, 'family change resets cursor');
  assert.equal(familyPage.metadataFilters.hidden, family !== 'single');
  const familyUrl = familyPage.url(familyLoad.request, 'family-cursor', generation);
  assert.equal(familyUrl.searchParams.get('family'), family);
  location.href = familyUrl.href;
  familyPage.restore();
  assert.equal(familyLoad.options.invalid, false);
  assert.equal(familyLoad.options.cursor, 'family-cursor');
  assert.equal(familyLoad.request.productFamily, family);
  delete familyPage.load;
  await familyPage.load({ cursor: 'family-cursor', generation });
  assert.equal(sent.at(-1).body.request.productFamily, family);
  assert.equal(sent.at(-1).body.request.q, 'Élite display %_');
  assert.equal(sent.at(-1).body.includeFacets, family === 'single' ? true : undefined);
  assert.equal(sent.at(-1).body.includeSuggestions, undefined);
  assert.equal(familyPage.metadataFilters.disabled, family !== 'single');
  const count = sent.length;
  await familyPage.load({ suggest: true });
  assert.equal(sent.length - count, family === 'single' ? 1 : 0, 'non-single typing does not request unsupported suggestions');
  if (family !== 'single') {
    await familyPage.load();
    assert.equal(sent.at(-1).body.includeSuggestions, undefined);
    assert.equal(sent.at(-1).body.includeFacets, undefined);
    const familyBody = { contractVersion: 1, cursor: null, request: clone(familyPage.request()) };
    const response = payload(familyBody);
    response.page.items = (family === 'all' ? ['single', 'sealed', 'accessory'] : [family]).map((kind, index) => ({
      ...clone(item), productGid: `gid://shopify/Product/${index + 1}`, productFamily: kind,
      canonicalCardName: kind === 'single' ? 'Bolt' : null,
    }));
    response.page.returnedProductCount = response.page.items.length;
    assert.doesNotThrow(() => familyPage.validate(response, familyBody, generation));
    for (const mutate of [
      value => { value.page.items[0].game = 'pokemon'; },
      value => { value.page.items[0].productFamily = 'unclassified'; },
      value => { value.page.items[0].canonicalCardName = {}; },
      value => { value.suggestions = []; },
      value => { value.facets = []; },
    ]) {
      const changed = clone(response); mutate(changed);
      assert.throws(() => familyPage.validate(changed, familyBody, generation), /unavailable/);
    }
    if (family !== 'all') {
      response.page.items[0].productFamily = 'single';
      assert.throws(() => familyPage.validate(response, familyBody, generation), /unavailable/);
    }
  }
}
for (const suffix of ['family=', 'family=wrong', 'family=all&family=single',
  'family=sealed&rarity=Rare', 'family=all&expansionCode=M11']) {
  location.href = `https://example.test/search?game=magic&q=box&${suffix}`;
  const before = sent.length;
  let done;
  page.load = options => { done = Catalog.prototype.load.call(page, options); return done; };
  page.restore(); await done; delete page.load;
  assert.equal(sent.length, before, `invalid family/filter URL ${suffix} must not fetch`);
  assert.equal(page.recovery.hidden, false);
}
location.href = 'https://example.test/search?game=magic&q=Bolt';
page.load = () => {}; page.restore(); delete page.load;
assert.equal(page.family.value, 'single', 'existing links remain single-card searches');
assert.equal(page.metadataFilters.hidden, false);
header.family.value = 'sealed'; header.input.value = 'Box';
const oldHeader = new AbortController(); header.controller = oldHeader;
const beforeFamily = sent.length;
header.family.dispatchEvent(new Event('change'));
assert.equal(oldHeader.signal.aborted, true);
assert.equal(header.list.hidden, true);
assert.equal(sent.length, beforeFamily);
assert.equal(header.input.value, 'Box');
assert.equal(header.url(header.request()).searchParams.get('family'), 'sealed');
page.family.value = 'single'; page.input.value = 'Bolt';
transport = body => new Promise(resolve => pending.push({ body, resolve }));
const oldLoad = page.load();
assert.equal(page.metadataFilters.disabled, true);
const oldSignal = sent.at(-1).signal;
page.resetMetadata('NEW', 'Rare');
const newLoad = page.load();
assert.equal(oldSignal.aborted, true);
pending[1].resolve({ ok: true, json: async () => payload(pending[1].body) });
await newLoad;
pending[0].resolve({ ok: true, json: async () => payload(pending[0].body) });
await oldLoad;
assert.equal(page.expansion.value, 'NEW', 'stale request cannot replace current selection');
assert.equal(page.expansion.children[1].value, 'NEW');
assert.equal(page.metadataFilters.disabled, false);
const cancelled = page.load();
const activeSignal = sent.at(-1).signal;
page.cancel();
assert.equal(activeSignal.aborted, true);
assert.equal(page.metadataFilters.disabled, false, 'cancel immediately unlocks page filters');
pending[2].resolve({ ok: true, json: async () => payload(pending[2].body) });
await cancelled;
assert.equal(page.expansion.value, 'NEW');
page.game.value = ''; page.cancel();
assert.equal(page.metadataFilters.disabled, true, 'no game cannot enable metadata controls');

for (const value of components) value.disconnectedCallback();
console.log('PASS metadata + four-family URL/cursor restore, family/query/stock retention, single-only suggestions/facets, strict game/family validation, stale responses and cancellation');
