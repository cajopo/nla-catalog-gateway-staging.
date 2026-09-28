import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const source = await readFile(new URL('../theme/snippets/nla-catalog-search.liquid', import.meta.url), 'utf8');
const script = source.match(/{% javascript %}([\s\S]*?){% endjavascript %}/)[1];
class Element extends EventTarget {
  value = ''; checked = false; hidden = true; textContent = ''; children = [];
  attributes = new Map();
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { this.attributes.delete(name); }
  focus() {}
}
class Component extends Element {
  constructor() {
    super();
    this.dataset = { mode: 'header', searchUrl: '/search', endpoint: '/apps/nla/catalog' };
    this.nodes = new Map();
    const form = this.querySelector('form');
    form.elements = { game: new Element(), family: new Element(), q: new Element(), stock: new Element(), expansionCode: new Element(), rarity: new Element() };
    form.elements.family.value = 'single';
    form.elements.game.options = [
      { value: '', textContent: 'Choose a game' },
      { value: 'magic', textContent: 'Magic' },
      { value: 'pokemon', textContent: 'Pokémon' },
      { value: 'yugioh', textContent: 'Yu-Gi-Oh!' },
      { value: 'one-piece', textContent: 'One Piece' },
    ];
  }
  querySelector(selector) {
    if (!this.nodes.has(selector)) this.nodes.set(selector, new Element());
    return this.nodes.get(selector);
  }
}
const window = new EventTarget();
const location = { href: 'https://example.test/search?view=nla-catalog&game=magic&q=Lightning', origin: 'https://example.test' };
const classes = new Map();
let fetches = 0;
let responseOk = true;
const context = {
  HTMLElement: Component, window, location, URL, Event, AbortController, setTimeout, clearTimeout,
  document: { title: 'Native search: 1000 results', createElement: () => new Element() },
  customElements: { get: name => classes.get(name), define: (name, value) => classes.set(name, value) },
  history: { pushState: (_state, _title, url) => { location.href = url.href; } },
  fetch: async () => {
    fetches += 1;
    return { ok: responseOk, json: async () => ({ page: { datasetGeneration: 'generation' }, nextCursor: null,
      facets: [{ values: [] }, { values: [] }] }) };
  },
};
vm.runInNewContext(script, context);
const Catalog = classes.get('nla-catalog-search');
const header = new Catalog();
header.connectedCallback();
assert.equal(header.game.value, 'magic');
assert.equal(header.family.value, 'single');
assert.equal(context.document.title, 'Native search: 1000 results', 'header must not change other page titles');
const page = new Catalog();
page.restore = () => {};
page.dataset.mode = 'page';
page.connectedCallback();
page.validate = () => {};
page.renderPage = () => {};
page.querySelector('[data-message="results"]').textContent = 'Results';
page.game.value = 'pokemon'; page.family.value = 'sealed'; page.input.value = 'Box'; page.stock.checked = true;
header.controller = new AbortController();
const pendingHeaderRequest = header.controller;
await page.load({ navigate: true });
assert.equal(header.game.value, 'pokemon');
assert.equal(header.family.value, 'sealed');
assert.equal(header.input.value, 'Box');
assert.equal(header.stock.checked, true);
assert.equal(header.list.hidden, true);
assert.equal(pendingHeaderRequest.signal.aborted, true);
assert.equal(fetches, 1, 'syncing the header must not duplicate a catalog request');
assert.equal(context.document.title, 'Results — Pokémon: Box');
page.game.value = 'yugioh'; page.family.value = 'accessory'; page.input.value = 'Dragon';
responseOk = false;
await page.load({ navigate: true });
assert.equal(header.game.value, 'pokemon', 'failed navigation must not change the header');
assert.equal(header.family.value, 'sealed', 'failed navigation must not change the header family');
assert.equal(context.document.title, 'Results — Yu-Gi-Oh!: Dragon', 'failure must not leave an old title/count');
responseOk = true;
await page.load();
assert.equal(header.game.value, 'pokemon', 'non-navigation must not broadcast new state');
const pageTitle = context.document.title;
header.contains = () => false;
await header.load({ suggest: true });
assert.equal(context.document.title, pageTitle, 'typing in the header must not rename the current page');
await page.load({ saved: { ...page.request(), game: 'magic', q: '<Card> & "name"' } });
assert.equal(context.document.title, 'Results — Magic: <Card> & "name"', 'use the requested game and literal query');
page.game.value = ''; page.input.value = '';
const beforeUnscoped = fetches;
await page.load();
assert.equal(context.document.title, 'Results', 'unscoped restore must discard native/previous counts');
assert.equal(fetches, beforeUnscoped);
header.disconnectedCallback();
location.href = 'https://example.test/search?game=one-piece&q=Luffy';
window.dispatchEvent(new Event('nla:catalog-navigate'));
assert.equal(header.game.value, 'pokemon', 'disconnected listener must be removed');
console.log('PASS header/page URL synchronization, scoped document titles, abort, no duplicate fetch, error and cleanup');
