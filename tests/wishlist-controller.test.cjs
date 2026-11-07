'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { allocate, fingerprint, cartDiff } = require('../theme/assets/nla-wishlist.js');

const row = (id, quantity, exact = true) => ({ id, quantity, exact, needsReview: false });
const offer = (variantId, stock, price = 1, exact = true) => ({ variantId: String(variantId), stock, price, exact });
const resolved = offers => ({ resolved: true, offers });
const emptyCart = () => ({ items: [], currency: 'EUR' });
const planFor = (rows, entries, cart = emptyCart()) => allocate(rows, new Map(entries), cart);
const lineMap = plan => Object.fromEntries(plan.lines.map(line => [line.id, line.quantity]));

test('allocates a bounded quantity from live offers and totals integer cents', () => {
  const plan = planFor([row('a', 4)], [['a', resolved([offer(10, 3, 0.1)])]]);
  assert.deepEqual(lineMap(plan), {10: 3});
  assert.equal(plan.quantity, 3);
  assert.equal(plan.requested, 4);
  assert.equal(plan.total, 0.3);
  assert.equal(plan.rows.get('a').quantity, 3);
});

test('shares one stock pool across duplicate wishlist rows', () => {
  const plan = planFor([row('a', 4), row('b', 4)], [
    ['a', resolved([offer(10, 5, 2)])], ['b', resolved([offer(10, 5, 2)])]
  ]);
  assert.deepEqual(lineMap(plan), {10: 5});
  assert.equal(plan.requested, 8);
  assert.equal(plan.quantity, 5);
  assert.equal(plan.total, 10);
});

test('uses the lower fresh stock when the same variant has inconsistent observations', () => {
  const plan = planFor([row('a', 4), row('b', 4)], [
    ['a', resolved([offer(10, 5)])], ['b', resolved([offer(10, 2)])]
  ]);
  assert.equal(plan.quantity, 2);
  assert.deepEqual(lineMap(plan), {10: 2});
});

test('deducts existing cart quantities once and counts them toward one requested row', () => {
  const plan = planFor([row('a', 2), row('b', 3)], [
    ['a', resolved([offer(10, 5)])], ['b', resolved([offer(10, 5)])]
  ], { items: [{variant_id: 10, quantity: 1}, {variant_id: 10, quantity: 1}] });
  assert.equal(plan.inCart, 2);
  assert.equal(plan.quantity, 3);
  assert.equal(plan.rows.get('a').inCart, 2);
  assert.equal(plan.rows.get('b').inCart, 0);
  assert.deepEqual(lineMap(plan), {10: 3});
});

test('existing unrelated cart lines never satisfy wishlist requirements', () => {
  const plan = planFor([row('a', 2)], [['a', resolved([offer(10, 4)])]], { items: [{variant_id: 99, quantity: 10}] });
  assert.equal(plan.inCart, 0);
  assert.equal(plan.quantity, 2);
});

test('existing cart quantities above observed stock cannot cause further additions', () => {
  const plan = planFor([row('a', 4)], [['a', resolved([offer(10, 2)])]], { items: [{variant_id: 10, quantity: 3}] });
  assert.equal(plan.inCart, 3);
  assert.equal(plan.quantity, 0);
  assert.deepEqual(plan.lines, []);
});

test('exact rows reserve scarce variants before flexible rows irrespective of display order', () => {
  const plan = planFor([row('flex', 1, false), row('exact', 1, true)], [
    ['flex', resolved([offer(10, 1, 1, true), offer(20, 1, 2, false)])],
    ['exact', resolved([offer(10, 1, 1, true)])]
  ]);
  assert.equal(plan.quantity, 2);
  assert.equal(plan.rows.get('exact').offers[0].variantId, '10');
  assert.equal(plan.rows.get('flex').offers[0].variantId, '20');
});

test('fewer compatible offers receive stock before flexible rows', () => {
  const plan = planFor([row('flex', 1, false), row('limited', 1, false)], [
    ['flex', resolved([offer(10, 1), offer(20, 1, 2, false)])],
    ['limited', resolved([offer(10, 1)])]
  ]);
  assert.equal(plan.quantity, 2);
  assert.equal(plan.rows.get('limited').offers[0].variantId, '10');
});

test('flexible allocation does not leave fillable requests missing due to greedy ties', () => {
  const plan = planFor([row('a', 1, false), row('b', 1, false), row('c', 1, false)], [
    ['a', resolved([offer(10, 1, 1), offer(20, 1, 2)])],
    ['b', resolved([offer(10, 1, 1), offer(30, 1, 2)])],
    ['c', resolved([offer(10, 1, 1), offer(30, 1, 2)])]
  ]);
  assert.equal(plan.quantity, 3, 'A may use 20, leaving 10 and 30 to satisfy B and C');
  assert.deepEqual(lineMap(plan), {10: 1, 20: 1, 30: 1});
});

test('does not allocate unresolved or review-blocked imported rows', () => {
  const a = row('a', 1); a.needsReview = true;
  const plan = planFor([a, row('b', 2), row('c', 1)], [
    ['a', resolved([offer(10, 3)])],
    ['b', {resolved: false, offers: [offer(20, 3)]}]
  ]);
  assert.equal(plan.quantity, 0);
  assert.equal(plan.inCart, 0);
  assert.equal(plan.requested, 4);
});

test('zero, negative and non-finite stock do not produce cart lines', () => {
  const plan = planFor([row('a', 10)], [['a', resolved([
    offer(10, 0), offer(20, -2), offer(30, NaN), offer(40, Infinity)
  ])]]);
  assert.equal(plan.quantity, 0);
  assert.deepEqual(plan.lines, []);
});

test('rejects invalid variant identifiers and non-finite or negative prices', () => {
  const plan = planFor([row('a', 10)], [['a', resolved([
    offer('gid://shopify/ProductVariant/10', 4), offer('0', 4), offer('-2', 4),
    offer(30, 4, NaN), offer(40, 4, Infinity), offer(50, 4, -1)
  ])]]);
  assert.equal(plan.quantity, 0);
  assert.deepEqual(plan.lines, []);
});

test('prefers exact printing and then lower live price while retaining requested quantity', () => {
  const plan = planFor([row('a', 3, false)], [['a', resolved([
    offer(10, 1, 1, false), offer(20, 1, 5, true), offer(30, 1, 2, false)
  ])]]);
  assert.deepEqual(plan.rows.get('a').offers.map(o => o.variantId), ['20', '10', '30']);
  assert.equal(plan.quantity, 3);
  assert.equal(plan.total, 8);
});

test('allocation does not mutate wishlist rows, resolutions or cart', () => {
  const rows = [row('a', 2)];
  const entries = [['a', resolved([offer(10, 3)])]];
  const cart = { items: [{variant_id: 10, quantity: 1}] };
  const before = JSON.stringify({rows, entries, cart});
  planFor(rows, entries, cart);
  assert.equal(JSON.stringify({rows, entries, cart}), before);
});

test('cart-ready lines aggregate duplicate variants across rows without unsafe numeric conversion', () => {
  const id = '9007199254740993';
  const plan = planFor([row('a', 1), row('b', 2)], [
    ['a', resolved([offer(id, 3)])], ['b', resolved([offer(id, 3)])]
  ]);
  assert.equal(plan.lines.length, 1);
  assert.equal(plan.lines[0].id, id);
  assert.equal(plan.lines[0].quantity, 3);
});

test('fingerprint is independent of line order and numeric versus string ID representation', () => {
  const a = {lines: [{id: '10', quantity: 1, price: 1.5}, {id: '20', quantity: 3, price: 2}]};
  const b = {lines: [{id: 20, quantity: 3, price: 2}, {id: 10, quantity: 1, price: 1.5}]};
  assert.equal(fingerprint(a), fingerprint(b));
});

test('fingerprint detects changed price, variant or quantity before posting the cart', () => {
  const original = fingerprint({lines: [{id: '10', quantity: 1, price: 1.5}]});
  for (const line of [
    {id: '10', quantity: 1, price: 1.51},
    {id: '20', quantity: 1, price: 1.5},
    {id: '10', quantity: 2, price: 1.5}
  ]) assert.notEqual(fingerprint({lines: [line]}), original);
});

test('cartDiff counts only the newly added amount for requested variants', () => {
  const before = {items: [{variant_id: 10, quantity: 2}, {variant_id: 99, quantity: 5}]};
  const after = {items: [{variant_id: 10, quantity: 4}, {variant_id: 99, quantity: 8}]};
  assert.equal(cartDiff(before, after, [{id: '10', quantity: 2}]), 2);
});

test('cartDiff reports partial additions and aggregates duplicate Shopify cart lines', () => {
  const before = {items: [{variant_id: 10, quantity: 1}]};
  const after = {items: [{variant_id: 10, quantity: 1}, {variant_id: 10, quantity: 2}, {variant_id: 20, quantity: 1}]};
  assert.equal(cartDiff(before, after, [{id: '10', quantity: 3}, {id: '20', quantity: 2}]), 3);
});

test('cartDiff never reports removed quantities as negative additions or excess concurrent additions as its own', () => {
  const before = {items: [{variant_id: 10, quantity: 4}, {variant_id: 20, quantity: 1}]};
  const after = {items: [{variant_id: 10, quantity: 2}, {variant_id: 20, quantity: 10}]};
  assert.equal(cartDiff(before, after, [{id: '10', quantity: 2}, {id: '20', quantity: 2}]), 2);
});

test('empty wishlist and unchanged cart produce empty plans and zero additions', () => {
  const plan = planFor([], []);
  assert.equal(plan.quantity, 0);
  assert.equal(plan.requested, 0);
  assert.equal(plan.total, 0);
  assert.equal(fingerprint(plan), '[]');
  assert.equal(cartDiff(emptyCart(), emptyCart(), []), 0);
});

test('reroutes cart credits as well as new quantities to maximize filled cards', () => {
  const plan = planFor([row('a', 1, false), row('b', 1, false), row('c', 1, false)], [
    ['a', resolved([offer(10, 1, 1), offer(20, 1, 2)])],
    ['b', resolved([offer(10, 1, 1), offer(30, 1, 2)])],
    ['c', resolved([offer(10, 1, 1), offer(30, 1, 2)])]
  ], {items: [{variant_id: 10, quantity: 1}]});
  assert.equal(plan.inCart, 1);
  assert.equal(plan.quantity, 2);
  assert.deepEqual(lineMap(plan), {20: 1, 30: 1});
  assert.equal(plan.rows.get('a').offers[0].variantId, '20');
});

test('does not buy extra copies when residual reassignment can cover requests using the existing cart', () => {
  const plan = planFor([row('a', 1, false), row('b', 1, false)], [
    ['a', resolved([offer(10, 2, 1), offer(20, 1, 2)])],
    ['b', resolved([offer(10, 2, 1), offer(30, 1, 2)])]
  ], {items: [{variant_id: 10, quantity: 1}, {variant_id: 20, quantity: 1}]});
  assert.equal(plan.inCart, 2);
  assert.equal(plan.quantity, 0);
  assert.deepEqual(plan.lines, []);
});

test('moves large residual capacities together without exceeding any variant pool', () => {
  const plan = planFor([row('a', 999, false), row('b', 999, false), row('c', 999, false)], [
    ['a', resolved([offer(10, 999, 1), offer(20, 999, 2)])],
    ['b', resolved([offer(10, 999, 1), offer(30, 999, 2)])],
    ['c', resolved([offer(10, 999, 1), offer(30, 999, 2)])]
  ]);
  assert.equal(plan.quantity, 2997);
  assert.deepEqual(lineMap(plan), {10: 999, 20: 999, 30: 999});
});

test('keeps an earlier exact row filled while rerouting its compatible variants', () => {
  const plan = planFor([row('exact', 1, true), row('flex', 1, false)], [
    ['exact', resolved([offer(10, 1, 1), offer(20, 1, 2)])],
    ['flex', resolved([offer(10, 1, 1)])]
  ]);
  assert.equal(plan.quantity, 2);
  assert.equal(plan.rows.get('exact').quantity, 1);
  assert.equal(plan.rows.get('exact').offers[0].variantId, '20');
});

test('all 2,744 three-card compatibility/cart combinations reach maximal coverage with no avoidable purchases', () => {
  function oracle(masks, cartMask) {
    let bestCoverage = -1, bestExisting = -1;
    function visit(index, used, coverage) {
      if (index === 3) {
        let existing = 0;
        for (let variant = 0; variant < 3; variant++) if ((used & (1 << variant)) && (cartMask & (1 << variant))) existing++;
        if (coverage > bestCoverage || (coverage === bestCoverage && existing > bestExisting)) {
          bestCoverage = coverage; bestExisting = existing;
        }
        return;
      }
      visit(index + 1, used, coverage);
      for (let variant = 0; variant < 3; variant++) {
        const bit = 1 << variant;
        if ((masks[index] & bit) && !(used & bit)) visit(index + 1, used | bit, coverage + 1);
      }
    }
    visit(0, 0, 0);
    return {coverage: bestCoverage, existing: bestExisting};
  }
  for (let a = 1; a < 8; a++) for (let b = 1; b < 8; b++) for (let c = 1; c < 8; c++) for (let cartMask = 0; cartMask < 8; cartMask++) {
    const masks = [a, b, c];
    const rows = masks.map((_, i) => row(String(i), 1, false));
    const entries = masks.map((mask, i) => [String(i), resolved([0,1,2].filter(v => mask & (1 << v)).map(v => offer(v + 1, 1, v + 1)))]);
    const cart = {items: [0,1,2].filter(v => cartMask & (1 << v)).map(v => ({variant_id: v + 1, quantity: 1}))};
    const expected = oracle(masks, cartMask);
    const plan = planFor(rows, entries, cart);
    const context = JSON.stringify({masks, cartMask});
    assert.equal(plan.quantity + plan.inCart, expected.coverage, context);
    assert.equal(plan.inCart, expected.existing, context);
    for (const line of plan.lines) assert.equal(line.quantity, 1, context);
  }
});

function editorHarness(imported) {
  const fs = require('node:fs');
  const vm = require('node:vm');
  const path = require('node:path');
  const core = require('../theme/assets/nla-wishlist-core.js');
  let document;
  class Element {
    constructor(tag) { this.tagName = tag; this.dataset = {}; this.children = []; this.listeners = {}; this.attributes = {}; this.className = ''; this._value = ''; this.checked = false; }
    get childNodes() { return this.children; }
    get value() { return this._value; }
    set value(raw) {
      const text = raw == null ? '' : String(raw);
      this._value = this.allowed && !this.allowed.includes(text) ? ''
        : this.type === 'number' && text && !/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(text) ? '' : text;
    }
    append(...children) { for (const child of children) { if (child && typeof child === 'object') child.parentNode = this; this.children.push(child); } }
    prepend(...children) { for (const child of children) if (child && typeof child === 'object') child.parentNode = this; this.children.unshift(...children); }
    after(child) { if (this.parentNode) { child.parentNode = this.parentNode; this.parentNode.children.splice(this.parentNode.children.indexOf(this) + 1, 0, child); } }
    remove() { if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(child => child !== this); }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    getAttribute(key) { return this.attributes[key] ?? null; }
    addEventListener(type, callback) { (this.listeners[type] ||= []).push(callback); }
    dispatch(type, detail = {}) { const event = {target: this, preventDefault() {}, ...detail}; for (const listener of this.listeners[type] || []) listener.call(this, event); }
    focus() { document.activeElement = this; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    scrollIntoView() {}
    matches(selector) {
      const data = selector.match(/^\[data-wl="([^"]+)"\]$/);
      if (data) return this.dataset.wl === data[1];
      if (selector.startsWith('.')) return this.className.split(' ').includes(selector.slice(1));
      return this.tagName === selector;
    }
    querySelectorAll(selector) {
      const result = [];
      const walk = el => { for (const child of el.children) if (child instanceof Element) { if (child.matches(selector)) result.push(child); walk(child); } };
      walk(this); return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  }
  const component = new Element('nla-wishlist'); component.dataset.locale = 'it'; component.dataset.endpoint = '/apps/nla-catalog';
  const hooks = Object.create(null);
  for (const hook of ['status','list-select','list-name','new-list','search','game','search-results','import','file','paste-game','paste-text','paste-import','import-cancel','import-confirm','export','exact','editor-cancel','editor-form','add-all','summary','rows','editor','import-preview','import-preview-content']) {
    const element = new Element(hook === 'editor-form' ? 'form' : hook === 'editor' ? 'dialog' : 'div');
    element.dataset.wl = hook; hooks[hook] = element; component.append(element);
  }
  const form = hooks['editor-form']; form.elements = Object.create(null);
  const grid = new Element('div'); grid.className = 'wl-editor__grid'; form.append(grid);
  for (const name of ['name','game','quantity','set','collectorNumber','languages','minCondition','foil','signed','altered','firstEdition','maxPrice','notes','exact']) {
    const control = new Element('input'); control.name = name;
    if (['quantity','maxPrice'].includes(name)) control.type = 'number';
    if (name === 'minCondition') control.allowed = ['', 'MT','NM','EX','GD','LP','PL','PO'];
    if (name === 'game') control.allowed = ['magic','pokemon','one-piece','yugioh'];
    if (['foil','signed','altered','firstEdition'].includes(name)) control.allowed = ['any','yes','no'];
    form.elements[name] = control; grid.append(control);
  }
  document = {activeElement: null, body: new Element('body'), createElement: tag => new Element(tag), createTextNode: text => ({textContent: text}), querySelectorAll: selector => selector.startsWith('nla-wishlist') ? [component] : [], querySelector: () => null, dispatchEvent() {}};
  const saved = {version: 1, selected: 'list-1', lists: [{id: 'list-1', name: 'Test list', rows: [core.normalizeRow({...imported, id: 'row-1', name: 'Card', game: 'magic'}, {id: 'row-1'})]}]};
  let written;
  const context = vm.createContext({document, location: {origin: 'https://nextlevelarena.it', hostname: 'nextlevelarena.it'},
    NlaWishlistCore: core, NlaWishlistData: {createClient: () => ({resolve: () => new Promise(() => {})})},
    Shopify: {routes: {root: '/'}}, localStorage: {getItem: () => JSON.stringify(saved), setItem: (_key,value) => {written = JSON.parse(value);}},
    fetch: () => new Promise(() => {}), addEventListener() {}, crypto: {randomUUID: () => 'new-id'}, URL, Intl, AbortController, setTimeout, clearTimeout
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../theme/assets/nla-wishlist.js'), 'utf8'), context);
  const edit = hooks.rows.querySelectorAll('button').find(button => button.textContent === 'Modifica');
  assert.ok(edit, 'the mounted wishlist exposes its real edit button');
  edit.dispatch('click');
  assert.equal(hooks.editor.open, true);
  return {
    form,
    edit(name, value) { form.elements[name].value = value; form.dispatch('change', {target: form.elements[name]}); },
    save() { form.dispatch('submit'); assert.ok(written, 'the real controller saves the edited list'); return written.lists[0].rows[0]; }
  };
}

test('editor preserves invalid imported constraints when only notes change despite browser select/number sanitization', () => {
  const harness = editorHarness({foil: 'etched', minCondition: 'MP', maxPrice: 'not-a-price', cardmarketId: 'bad-id'});
  assert.equal(harness.form.elements.minCondition.value, '');
  assert.equal(harness.form.elements.maxPrice.value, '');
  assert.equal(harness.form.elements.foil.value, 'any');
  harness.edit('notes', 'Only my personal note changed');
  const saved = harness.save();
  assert.equal(saved.needsReview, true);
  assert.equal(saved.extras._invalidFields.foil, 'etched');
  assert.equal(saved.extras._invalidFields.minCondition, 'MP');
  assert.equal(saved.extras._invalidFields.maxPrice, 'not-a-price');
  assert.equal(saved.extras._invalidFields.cardmarketId, 'bad-id');
  assert.equal(saved.notes, 'Only my personal note changed');
});

test('editor clears a blocking constraint only when its own control is explicitly corrected', () => {
  const harness = editorHarness({foil: 'etched'});
  harness.edit('foil', 'no');
  const saved = harness.save();
  assert.equal(saved.needsReview, false);
  assert.equal(saved.foil, false);
  assert.equal(saved.extras._invalidFields, undefined);
});

test('editor correcting one invalid preference preserves every other unresolved preference', () => {
  const harness = editorHarness({foil: 'etched', minCondition: 'MP'});
  harness.edit('foil', 'yes');
  const saved = harness.save();
  assert.equal(saved.needsReview, true);
  assert.equal(saved.foil, true);
  assert.equal(saved.extras._invalidFields.foil, undefined);
  assert.equal(saved.extras._invalidFields.minCondition, 'MP');
});
