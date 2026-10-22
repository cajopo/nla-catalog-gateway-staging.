'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const Data = require('../theme/assets/nla-wishlist-data.js');

const gid = id => 'gid://shopify/Product/' + id;
const vgid = id => 'gid://shopify/ProductVariant/' + id;
const option = (name, value) => ({ name, value });
function item(id = '1', game = 'magic', name = 'Card') {
  return { contractVersion: 1, productGid: gid(id), handle: 'card-' + id, game,
    productFamily: 'single', productSubtype: null, canonicalCardName: name, commercialTitle: name + ' shop title',
    cardMetadata: { expansionCode: 'SET', expansionName: 'Example Set', collectorNumber: id, rarity: 'Rare' },
    variants: [{ variantGid: vgid(id + '0'), selectedOptions: [option('Language', 'English')], priceText: '100.00', inventoryQuantity: 999 }] };
}
function product(record, id = '100', overrides = {}) {
  return { contractVersion: 1, productId: record.productGid, handle: record.handle, title: record.commercialTitle,
    currency: 'EUR', catalogOnly: false, requiresSellingPlan: false, image: '//cdn.shopify.com/s/files/card.jpg',
    sourceIds: { powerTools: { type: 'single_line_text_field', value: id }, sync: { type: 'number_integer', value: id } },
    page: 1, pages: 1, variantCount: 1,
    variants: [{ id: record.variants[0].variantGid.split('/').pop(), price: 199, available: true,
      inventoryQuantity: 3, inventoryPolicy: 'deny', inventoryManagement: 'shopify',
      selectedOptions: [option('Language', 'English'), option('Condition', 'Near Mint'), option('Edition', 'Normal')] }], ...overrides };
}
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null }, text: async () => JSON.stringify(data) });
function harness(records, products, extra = {}) {
  const requests = [];
  const fetch = async (address, init) => {
    const url = new URL(address); requests.push({ url, init });
    if (url.hostname === 'api.scryfall.com') return extra.scryfall ? extra.scryfall(url, init) : response({}, 404);
    if (url.pathname === '/apps/nla-catalog') {
      const body = JSON.parse(init.body);
      if (extra.catalog) return extra.catalog(body, requests);
      const matches = records.filter(value => value.game === body.request.game);
      return response({ contractVersion: 1, nextCursor: null, page: { contractVersion: 1,
        request: body.request, datasetGeneration: 'sha256:' + 'a'.repeat(64), items: matches,
        returnedProductCount: matches.length, returnedVariantCount: matches.length, hasNextPage: false } });
    }
    const handle = url.pathname.split('/').pop();
    if (extra.view) return extra.view(handle, url, init);
    return products[handle] ? response(products[handle]) : response({}, 404);
  };
  return { client: Data.createClient({ endpoint: '/apps/nla-catalog', rootUrl: '/', fetch }), requests };
}
const row = record => ({ game: record.game, productId: record.productGid, handle: record.handle, name: record.canonicalCardName,
  exact: true, languages: [], minCondition: null, foil: 'any', signed: 'any', altered: 'any', firstEdition: 'any' });

test('variant options are mapped explicitly; absent attributes stay unknown', () => {
  assert.deepEqual(Data.attributes([option('Language', 'Italian'), option('Condition', 'Mint'), option('Edition', 'Foil Normal')]),
    { language: 'it', condition: 'MT', foil: true, signed: null, altered: null, firstEdition: null });
  assert.equal(Data.attributes([option('Edition', 'First Edition')]).firstEdition, true);
  assert.equal(Data.attributes([option('Edition', 'Normal')]).firstEdition, null);
  assert.equal(Data.attributes([option('Signed', 'no')]).signed, false);
  assert.equal(Data.attributes([option('Language', 'English'), option('Language', 'Italian')]).language, null);
  assert.equal(Data.attributes([option('Language', 'English'), option('Lingua', 'Italian')]).language, null);
  assert.equal(Data.attributes([option('Language', '__proto__')]).language, null);
  assert.equal(Data.attributes([option('Language', 'Traditional Chinese')]).language, 'zh-TW');
});

test('source binding requires both exact types, matching nonzero decimal strings', () => {
  const p = product(item());
  assert.equal(Data.sourceId(p), '100');
  p.sourceIds.sync.value = '101'; assert.equal(Data.sourceId(p), null);
  p.sourceIds.sync.value = '100'; p.sourceIds.sync.type = 'single_line_text_field'; assert.equal(Data.sourceId(p), null);
  p.sourceIds.sync.type = 'number_integer'; p.sourceIds.sync.value = p.sourceIds.powerTools.value = '0'; assert.equal(Data.sourceId(p), null);
});

test('exact preferences and minimum grading apply; flexible mode keeps all physical/price constraints', () => {
  const offer = { price: 1.99, set: 'SET', setName: 'Example Set', collectorNumber: '1', language: 'en', condition: 'NM', foil: false, signed: null, altered: null, firstEdition: null };
  assert.equal(Data.fits(offer, { exact: true, set: 'set', languages: ['English'], minCondition: 'EX' }), true);
  assert.equal(Data.fits(offer, { exact: true, minCondition: 'MT' }), false);
  assert.equal(Data.fits(offer, { exact: true, languages: ['Italian'] }), false);
  assert.equal(Data.fits(offer, { exact: false, set: 'OTHER', collectorNumber: '99', languages: ['it'], minCondition: 'MT' }), true);
  for (const constraint of [{ foil: 'yes' }, { signed: 'no' }, { altered: 'no' }, { firstEdition: 'no' }, { maxPrice: 1 }]) assert.equal(Data.fits(offer, { exact: false, ...constraint }), false);
  assert.equal(Data.fits({ ...offer, language: null }, { languages: ['unknown'] }), false);
  assert.equal(Data.fits(offer, { foil: 'unrecognized constraint' }), false);
  assert.equal(Data.fits({ ...offer, language: 'zh-CN' }, { languages: ['zh-CN'] }), true);
});

test('same-origin endpoints and root URLs are enforced', () => {
  assert.throws(() => Data.createClient({ endpoint: 'https://catalog-staging.nextlevelarena.it' }), /invalid_endpoint/);
  assert.throws(() => Data.createClient({ rootUrl: 'https://evil.example/' }), /invalid_endpoint/);
});

test('mixed-game search uses independent scoped requests and preserves exact product IDs', async () => {
  const records = ['magic', 'pokemon', 'yugioh', 'one-piece'].map((game, i) => item(String(i + 1), game));
  const h = harness(records, {});
  const result = await h.client.search('Card', '');
  assert.equal(result.items.length, 4); assert.equal(result.truncated, false);
  assert.equal(h.requests.length, 4);
  assert.ok(h.requests.every(value => value.init.method === 'POST' && JSON.parse(value.init.body).cursor === null));
});

test('stock and money come from current Shopify view, not stale catalog values', async () => {
  const one = item(); const h = harness([one], { [one.handle]: product(one) });
  const result = await h.client.resolve(row(one), { fresh: true });
  assert.equal(result.resolved, true); assert.equal(result.offers.length, 1);
  assert.equal(result.offers[0].stock, 3); assert.equal(result.offers[0].price, 1.99);
  assert.equal(result.offers[0].variantId, '10'); assert.equal(result.offers[0].cardmarketId, '100');
  assert.equal(result.candidates[0].cardmarketId, '100');
  const view = h.requests.find(value => value.url.searchParams.get('view'));
  assert.equal(view.url.searchParams.get('view'), 'nla-wishlist-data'); assert.equal(view.init.cache, 'no-store');
  assert.equal(view.init.headers.Accept, 'text/html');
  assert.equal(h.requests.find(value => value.url.pathname === '/apps/nla-catalog').init.headers.Accept, 'application/json');
});

test('stock is reread on every resolve and sold-out rows remain resolved', async () => {
  const one = item(); let stock = 3;
  const h = harness([one], {}, { view: () => { const p = product(one); p.variants[0].inventoryQuantity = stock; p.variants[0].available = stock > 0; return response(p); } });
  assert.equal((await h.client.resolve(row(one))).offers.length, 1);
  stock = 0; const soldOut = await h.client.resolve(row(one), { fresh: true });
  assert.equal(soldOut.resolved, true); assert.deepEqual(soldOut.offers, []);
});

test('an imported product ID and handle cannot invent a game when the gateway has no verified match', async () => {
  const pokemon = item('1', 'pokemon');
  for (const unavailable of [false, true]) {
    const h = harness([pokemon], { [pokemon.handle]: product(pokemon) }, unavailable ? { catalog: () => response({}, 503) } : {});
    const result = await h.client.resolve({ ...row(pokemon), game: 'magic' });
    assert.equal(result.resolved, false); assert.deepEqual(result.offers, []);
    assert.ok(result.warnings.includes('identity_required'));
    assert.equal(h.requests.filter(value => value.url.searchParams.get('view')).length, 0);
  }
});

test('flexible variants on the selected printing are exact only when all exact preferences match', async () => {
  const one = item('1', 'pokemon'); const p = product(one);
  p.variants.push({ ...p.variants[0], id: '11', selectedOptions: [option('Language', 'Italian'), option('Condition', 'Near Mint'), option('Edition', 'Normal')] });
  p.variantCount = 2;
  const h = harness([one], { [one.handle]: p });
  const result = await h.client.resolve({ ...row(one), exact: false, languages: ['it'], minCondition: 'NM' });
  assert.equal(result.offers.length, 2);
  assert.equal(result.offers.find(offer => offer.language === 'en').exact, false);
  assert.equal(result.offers.find(offer => offer.language === 'it').exact, true);
});

test('failed hydration cannot make source ID or set and collector matching falsely unique', async () => {
  const a = item('1', 'pokemon'); const b = item('2', 'pokemon');
  b.cardMetadata.collectorNumber = '1';
  for (const identity of [{ cardmarketId: '100' }, { set: 'SET', collectorNumber: '1' }]) {
    const h = harness([a, b], { [a.handle]: product(a) });
    const result = await h.client.resolve({ game: 'pokemon', name: 'Card', exact: true, ...identity });
    assert.equal(result.resolved, false); assert.deepEqual(result.offers, []);
    assert.equal(result.candidates.length, 2); assert.ok(result.warnings.includes('fresh_data_unavailable'));
  }
});

test('an unsupported MetaProductID requires confirmation even with a unique set and collector', async () => {
  const one = item('1', 'pokemon'); const h = harness([one], { [one.handle]: product(one) });
  const input = { game: 'pokemon', name: 'Card', exact: true, metaProductId: '200', set: 'SET', collectorNumber: '1' };
  const unconfirmed = await h.client.resolve(input);
  assert.equal(unconfirmed.resolved, false); assert.deepEqual(unconfirmed.offers, []); assert.equal(unconfirmed.candidates.length, 1);
  const confirmed = await h.client.resolve({ ...input, productId: one.productGid, handle: one.handle });
  assert.equal(confirmed.resolved, true); assert.equal(confirmed.offers.length, 1);
});

test('a unique name alone never binds an imported row; set and collector can bind a printing', async () => {
  const one = item(); const h = harness([one], { [one.handle]: product(one) });
  const named = await h.client.resolve({ game: 'magic', name: 'Card', exact: true });
  assert.equal(named.resolved, false); assert.equal(named.offers.length, 0); assert.equal(named.candidates.length, 1);
  const printed = await h.client.resolve({ game: 'magic', name: 'Card', exact: true, set: 'SET', collectorNumber: '1' });
  assert.equal(printed.resolved, true); assert.equal(printed.offers.length, 1);
});

test('same-name Pokémon are candidates until an explicit alternative selection', async () => {
  const a = item('1', 'pokemon', 'Pikachu'); const b = item('2', 'pokemon', 'Pikachu');
  const h = harness([a, b], { [a.handle]: product(a, '100'), [b.handle]: product(b, '200') });
  const r = { ...row(a), exact: false };
  const first = await h.client.resolve(r); assert.deepEqual(first.offers.map(value => value.productId), [a.productGid]);
  assert.equal(first.candidates.length, 2);
  const confirmed = await h.client.resolve({ ...r, confirmedProductIds: [b.productGid] });
  assert.deepEqual(new Set(confirmed.offers.map(value => value.productId)), new Set([a.productGid, b.productGid]));
  assert.equal(h.requests.filter(value => value.url.hostname === 'api.scryfall.com').length, 0);
});

test('MKM import uses verified source IDs and rejects a changed source binding', async () => {
  const one = item('1', 'pokemon'); const h = harness([one], { [one.handle]: product(one, '100') });
  const imported = await h.client.resolve({ game: 'pokemon', name: 'Card', cardmarketId: '100', exact: true });
  assert.equal(imported.resolved, true); assert.equal(imported.offers.length, 1);
  const mismatch = await h.client.resolve({ ...row(one), cardmarketId: '200' });
  assert.equal(mismatch.resolved, false); assert.deepEqual(mismatch.offers, []); assert.ok(mismatch.warnings.includes('identity_mismatch'));
});

test('Magic alternatives require the same verified Scryfall oracle ID, never same names', async () => {
  const a = item('1'); const b = item('2'); const c = item('3');
  const oracle = '909b3d90-5762-461b-b49a-004a9e72733d';
  const h = harness([a, b, c], { [a.handle]: product(a, '100'), [b.handle]: product(b, '200'), [c.handle]: product(c, '300') }, {
    scryfall: (url, init) => { assert.equal(init.credentials, 'omit'); return response({ object: 'card', cardmarket_id: Number(url.pathname.split('/').pop()), name: 'Card', oracle_id: url.pathname.endsWith('/300') ? 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' : oracle }); }
  });
  const result = await h.client.resolve({ ...row(a), exact: false });
  assert.deepEqual(new Set(result.offers.map(value => value.productId)), new Set([a.productGid, b.productGid]));
  const lookups = h.requests.filter(value => value.url.hostname === 'api.scryfall.com').length;
  await h.client.resolve({ ...row(a), exact: false });
  assert.equal(h.requests.filter(value => value.url.hostname === 'api.scryfall.com').length, lookups);
});

test('Magic ID-only import uses Scryfall name for discovery, then binds original source ID', async () => {
  const one = item(); const h = harness([one], { [one.handle]: product(one, '100') }, {
    scryfall: () => response({ object: 'card', cardmarket_id: 100, name: 'Card', oracle_id: '909b3d90-5762-461b-b49a-004a9e72733d' })
  });
  const result = await h.client.resolve({ game: 'magic', cardmarketId: '100', exact: true });
  assert.equal(result.resolved, true); assert.equal(result.offers.length, 1);
  assert.equal(JSON.parse(h.requests.find(value => value.init.method === 'POST').init.body).request.q, 'Card');
});

test('429 pauses optional external identity lookups without retries or losing exact offers', async () => {
  const a = item(); const b = item('2');
  const h = harness([a, b], { [a.handle]: product(a, '100'), [b.handle]: product(b, '200') }, { scryfall: () => response({}, 429) });
  const result = await h.client.resolve({ ...row(a), exact: false });
  assert.equal(result.offers.length, 1);
  await h.client.resolve({ ...row(b), exact: false });
  assert.equal(h.requests.filter(value => value.url.hostname === 'api.scryfall.com').length, 1);
});

test('bad view identity, untracked stock, catalog-only and unsupported currency fail closed', async () => {
  const one = item();
  const badId = product(one, '100', { productId: gid('99') });
  const untracked = product(one); untracked.variants[0].inventoryManagement = null;
  for (const p of [badId, untracked, product(one, '100', { catalogOnly: true }), product(one, '100', { currency: 'USD' })]) {
    const result = await harness([one], { [one.handle]: p }).client.resolve(row(one));
    assert.equal(result.offers.length, 0);
  }
});

test('unknown signed/altered flags cannot satisfy no, including in flexible mode', async () => {
  const one = item(); const h = harness([one], { [one.handle]: product(one) });
  const result = await h.client.resolve({ ...row(one), exact: false, signed: 'no' });
  assert.equal(result.offers.length, 0); assert.ok(result.warnings.includes('unknown_attributes'));
});

test('search paging is bounded, reports truncation and never binds a partial unique set match', async () => {
  const records = Array.from({ length: 4 }, (_, i) => item(String(i + 1)));
  let calls = 0;
  const h = harness(records, Object.fromEntries(records.map((value, i) => [value.handle, product(value, String(100 + i))])), {
    catalog: body => { const one = records[calls++ % 4]; return response({ contractVersion: 1, nextCursor: 'cursor' + calls,
      page: { contractVersion: 1, request: body.request, datasetGeneration: 'sha256:' + 'a'.repeat(64), items: [one], returnedProductCount: 1, hasNextPage: true } }); }
  });
  const result = await h.client.resolve({ game: 'magic', name: 'Card', set: 'SET', collectorNumber: '1' });
  assert.equal(calls, 4); assert.equal(result.truncated, true); assert.equal(result.resolved, false);
});

test('progressive scanning includes the 25th approved printing and clears truncation after the last page', async () => {
  const records = Array.from({ length: 25 }, (_, i) => item(String(i + 1), 'pokemon'));
  const h = harness(records, Object.fromEntries(records.map((value, i) => [value.handle, product(value, String(100 + i))])), {
    catalog: body => {
      const offset = body.cursor ? Number(body.cursor) : 0; const batch = records.slice(offset, offset + 24);
      const nextCursor = offset + 24 < records.length ? String(offset + 24) : null;
      return response({ contractVersion: 1, nextCursor, page: { contractVersion: 1, request: body.request,
        datasetGeneration: 'sha256:' + 'a'.repeat(64), items: batch, returnedProductCount: batch.length, hasNextPage: nextCursor !== null } });
    }
  });
  const input = { ...row(records[0]), exact: false, confirmedProductIds: records.map(value => value.productGid) };
  const first = await h.client.resolve(input);
  assert.equal(first.offers.length, 24); assert.equal(first.truncated, true);
  const more = await h.client.resolve(input, { scanLimit: 48, fresh: true });
  assert.equal(more.offers.length, 25); assert.equal(more.truncated, false);
  assert.ok(more.offers.some(offer => offer.variantId === '250'));
});

test('explicit search limits reach later pages but never exceed 2000 products per game', async () => {
  let calls = 0;
  const h = harness([], {}, { catalog: body => {
    const offset = body.cursor ? Number(body.cursor) : 0;
    const batch = Array.from({ length: 24 }, (_, i) => item(String(offset + i + 1), 'pokemon')); calls++;
    return response({ contractVersion: 1, nextCursor: String(offset + 24), page: { contractVersion: 1,
      request: body.request, datasetGeneration: 'sha256:' + 'a'.repeat(64), items: batch, returnedProductCount: 24, hasNextPage: true } });
  } });
  const result = await h.client.search('Card', 'pokemon', { limit: 5000 });
  assert.equal(result.items.length, 2000); assert.equal(result.truncated, true); assert.equal(calls, 84);
});

test('cursor loops and changed dataset generations are rejected', async () => {
  for (const changedGeneration of [false, true]) {
    let count = 0;
    const h = harness([], {}, { catalog: body => response({ contractVersion: 1, nextCursor: 'same', page: {
      contractVersion: 1, request: body.request, datasetGeneration: 'sha256:' + (changedGeneration && count++ ? 'b' : 'a').repeat(64), items: [], returnedProductCount: 0, hasNextPage: true } }) });
    await assert.rejects(() => h.client.search('Card', 'magic'), /invalid_catalog/);
  }
});

test('aborted requests do not silently resolve to an empty wishlist', async () => {
  const controller = new AbortController(); controller.abort();
  const h = harness([], {});
  await assert.rejects(() => h.client.resolve({ game: 'magic', name: 'Card' }, { signal: controller.signal }), { name: 'AbortError' });
  assert.equal(h.requests.length, 0);
});

test('fresh view paginates all variants and rejects duplicates across pages', async () => {
  const one = item();
  for (const duplicate of [false, true]) {
    const h = harness([one], {}, { view: (_handle, url) => {
      const p = product(one, '100', { pages: 2, variantCount: 2, page: Number(url.searchParams.get('page')) });
      if (p.page === 2 && !duplicate) p.variants[0].id = '11';
      return response(p);
    } });
    const result = await h.client.resolve(row(one));
    assert.equal(result.offers.length, duplicate ? 0 : 2);
    if (duplicate) assert.ok(result.warnings.includes('fresh_data_unavailable'));
  }
});

test('exact selections hydrate only the selected product even when search has alternatives', async () => {
  const a = item(); const b = item('2');
  const h = harness([a, b], { [a.handle]: product(a), [b.handle]: product(b) });
  const result = await h.client.resolve({ ...row(a), productId: '1' });
  assert.equal(result.offers.length, 1);
  assert.equal(h.requests.filter(value => value.url.searchParams.has('view')).length, 1);
});

test('an exact verified selection is not marked truncated by unrelated search alternatives', async () => {
  const records = Array.from({ length: 97 }, (_, i) => item(String(i + 1), 'pokemon', 'Pikachu'));
  const one = records[0];
  const h = harness(records, { [one.handle]: product(one) }, { catalog: body => {
    const offset = body.cursor ? Number(body.cursor) : 0; const batch = records.slice(offset, offset + 24);
    const nextCursor = offset + 24 < records.length ? String(offset + 24) : null;
    return response({ contractVersion: 1, nextCursor, page: { contractVersion: 1, request: body.request,
      datasetGeneration: 'sha256:' + 'a'.repeat(64), items: batch, returnedProductCount: batch.length, hasNextPage: nextCursor !== null } });
  } });
  const result = await h.client.resolve(row(one));
  assert.equal(result.resolved, true); assert.equal(result.offers.length, 1);
  assert.equal(result.truncated, false); assert.ok(!result.warnings.includes('results_truncated'));
  assert.equal(h.requests.filter(value => value.url.searchParams.has('view')).length, 1);
  assert.equal(h.requests.filter(value => value.url.pathname === '/apps/nla-catalog').length, 4);
});

test('HTML-served alternate template escapes markup while keeping JSON string data', () => {
  const fs = require('node:fs'); const path = require('node:path');
  const template = fs.readFileSync(path.join(__dirname, '../theme/templates/product.nla-wishlist-data.liquid'), 'utf8');
  assert.match(template, /layout none/);
  assert.match(template, /paginate product\.variants by 250/);
  assert.match(template, /replace: '<', '\\u003c'/);
  assert.doesNotMatch(template, /product\.metafields\s*\|\s*json/);
});
