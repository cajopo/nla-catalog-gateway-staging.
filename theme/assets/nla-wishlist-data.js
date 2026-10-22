/* Read-only catalog/identity adapter. Shopify alone owns stock, prices and cart. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  root.NlaWishlistData = api;
})(typeof globalThis !== 'undefined' ? globalThis : window, function () {
  'use strict';

  const GAMES = ['magic', 'pokemon', 'yugioh', 'one-piece'];
  const PRODUCT_ID = /^gid:\/\/shopify\/Product\/[1-9][0-9]{0,63}$/;
  const VARIANT_ID = /^gid:\/\/shopify\/ProductVariant\/[1-9][0-9]{0,63}$/;
  const DECIMAL_ID = /^[1-9][0-9]{0,63}$/;
  const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const PAGE_SIZE = 24;
  const DEFAULT_SEARCH_LIMIT = 96;
  const MAX_PRODUCTS = 2000;
  const VARIANT_PAGES = 9;
  const MAX_BYTES = 2 * 1024 * 1024;
  const CONDITIONS = ['MT', 'NM', 'EX', 'GD', 'LP', 'PL', 'PO'];
  const normalize = value => typeof value === 'string' ? value.normalize('NFKC').trim().toLowerCase() : '';
  const validString = (value, max = 1024) => typeof value === 'string' && value.length <= max && !/[\u0000-\u001f]/.test(value);
  const decimalId = value => typeof value === 'string' && DECIMAL_ID.test(value);
  const conditionNames = { mint: 'MT', m: 'MT', mt: 'MT', 'near mint': 'NM', nm: 'NM', excellent: 'EX', ex: 'EX', good: 'GD', gd: 'GD', 'light played': 'LP', 'lightly played': 'LP', lp: 'LP', played: 'PL', pl: 'PL', poor: 'PO', po: 'PO' };
  const languageNames = {
    english: 'en', inglese: 'en', en: 'en', italian: 'it', italiano: 'it', it: 'it',
    french: 'fr', francese: 'fr', fr: 'fr', german: 'de', tedesco: 'de', de: 'de',
    spanish: 'es', spagnolo: 'es', es: 'es', portuguese: 'pt', portoghese: 'pt', pt: 'pt',
    japanese: 'ja', giapponese: 'ja', ja: 'ja', jp: 'ja', korean: 'ko', coreano: 'ko', ko: 'ko', kr: 'ko',
    russian: 'ru', russo: 'ru', ru: 'ru', 'simplified chinese': 'zh-CN', 'chinese simplified': 'zh-CN', 'zh-hans': 'zh-CN', 'zh-cn': 'zh-CN', zhs: 'zh-CN',
    'traditional chinese': 'zh-TW', 'chinese traditional': 'zh-TW', 'zh-hant': 'zh-TW', 'zh-tw': 'zh-TW', zht: 'zh-TW'
  };
  const lookup = (map, value) => Object.hasOwn(map, normalize(value)) ? map[normalize(value)] : null;
  const language = value => lookup(languageNames, value);
  const condition = value => lookup(conditionNames, value);
  const triState = value => value === true || value === 'yes' ? true : value === false || value === 'no' ? false : null;
  const explicitBoolean = value => lookup({ yes: true, true: true, si: true, 'sì': true, no: false, false: false }, value);
  const productId = value => PRODUCT_ID.test(value || '') ? value : decimalId(value) ? 'gid://shopify/Product/' + value : null;
  const boundedLimit = (value, fallback) => Number.isSafeInteger(value) && value > 0 ? Math.min(MAX_PRODUCTS, value) : fallback;

  function abort(signal) {
    if (signal?.aborted) throw signal.reason || new DOMException('Aborted', 'AbortError');
  }

  function canonical(value) {
    if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
    if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + canonical(value[key])).join(',') + '}';
    return JSON.stringify(value);
  }

  function sourceId(data) {
    const power = data?.sourceIds?.powerTools;
    const sync = data?.sourceIds?.sync;
    return power?.type === 'single_line_text_field' && sync?.type === 'number_integer'
      && decimalId(power.value) && power.value === sync.value ? power.value : null;
  }

  function attributes(options) {
    const result = { language: null, condition: null, foil: null, signed: null, altered: null, firstEdition: null };
    const values = new Map();
    for (const item of options || []) {
      if (!validString(item?.name, 128) || !validString(item?.value, 256)) continue;
      const key = normalize(item.name);
      if (values.has(key)) { values.set(key, null); continue; }
      values.set(key, item.value);
    }
    const get = keys => {
      const present = keys.filter(key => values.has(key)).map(key => values.get(key));
      return present.some(value => value === null) || new Set(present.map(normalize)).size !== 1 ? undefined : present[0];
    };
    result.language = language(get(['language', 'lingua']));
    result.condition = condition(get(['condition', 'condizione']));
    for (const [key, names] of Object.entries({ foil: ['foil'], signed: ['signed', 'firmata'], altered: ['altered', 'altered art', 'alterata'], firstEdition: ['first edition', 'prima edizione'] })) {
      result[key] = explicitBoolean(get(names));
    }
    // Known explicit option values, never commercial titles or missing flags.
    const finish = normalize(get(['edition', 'finish', 'finitura', 'edizione']));
    const finishes = { normal: false, 'non foil': false, nonfoil: false, 'non-foil': false, foil: true, 'foil normal': true, 'reverse holo': true, 'reverse foil': true, 'foil first edition': true, 'first edition': false, 'foil unlimited': true, unlimited: false };
    if (result.foil === null && Object.hasOwn(finishes, finish)) result.foil = finishes[finish];
    if (result.firstEdition === null && ['first edition', 'foil first edition'].includes(finish)) result.firstEdition = true;
    if (result.firstEdition === null && ['unlimited', 'foil unlimited'].includes(finish)) result.firstEdition = false;
    return result;
  }

  function fits(offer, row) {
    if (!offer || !row || !Number.isFinite(offer.price) || offer.price <= 0) return false;
    if (row.maxPrice != null && row.maxPrice !== '') {
      const max = Number(row.maxPrice);
      if (!Number.isFinite(max) || max < 0 || offer.price > max) return false;
    }
    for (const key of ['foil', 'signed', 'altered', 'firstEdition']) {
      if (![undefined, null, '', 'any', 'yes', 'no', true, false].includes(row[key])) return false;
      const wanted = triState(row[key]);
      if (wanted !== null && offer[key] !== wanted) return false;
    }
    if (row.exact !== false) {
      if (row.set && ![offer.set, offer.setName].some(value => normalize(value) === normalize(row.set))) return false;
      if (row.collectorNumber && normalize(offer.collectorNumber) !== normalize(row.collectorNumber)) return false;
      const requested = Array.isArray(row.languages) ? row.languages : typeof row.languages === 'string' ? row.languages.split(/[,;]+/).filter(value => value.trim()) : [];
      if (requested.length && (!offer.language || !requested.map(language).includes(offer.language))) return false;
      if (row.minCondition) {
        const minimum = condition(row.minCondition);
        if (!minimum || !offer.condition || CONDITIONS.indexOf(offer.condition) < 0 || CONDITIONS.indexOf(offer.condition) > CONDITIONS.indexOf(minimum)) return false;
      }
    }
    return true;
  }

  function hasUnknownConstraint(offer, row) {
    if (['foil', 'signed', 'altered', 'firstEdition'].some(key => triState(row[key]) !== null && offer[key] === null)) return true;
    return row.exact !== false && ((row.minCondition && !offer.condition) || ((row.languages?.length || 0) > 0 && !offer.language));
  }

  function createClient(options = {}) {
    const origin = typeof location !== 'undefined' ? location.origin : 'https://nextlevelarena.it';
    const base = new URL(options.rootUrl || '/', origin);
    const endpoint = new URL(options.endpoint || '/apps/nla-catalog', origin);
    if (base.origin !== origin || base.search || base.hash || !base.pathname.endsWith('/')
      || endpoint.origin !== origin || !endpoint.pathname.startsWith('/apps/') || endpoint.search || endpoint.hash) throw new Error('invalid_endpoint');
    const fetcher = options.fetch || globalThis.fetch.bind(globalThis);
    const found = new Map();
    const oracleCache = new Map();
    let oracleQueue = Promise.resolve();
    let lastOracleStart = 0;
    let oraclePaused = false;

    async function readJson(url, init, signal) {
      abort(signal);
      const response = await fetcher(url.href, { ...init, signal, redirect: 'error' });
      if (!response.ok) { const error = new Error('http_' + response.status); error.status = response.status; throw error; }
      const length = response.headers?.get?.('content-length');
      if (length && Number(length) > MAX_BYTES) throw new Error('response_too_large');
      let text = '';
      if (response.body?.getReader) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let bytes = 0;
        try {
          while (true) {
            abort(signal);
            const part = await reader.read();
            if (part.done) break;
            bytes += part.value.byteLength;
            if (bytes > MAX_BYTES) { await reader.cancel(); throw new Error('response_too_large'); }
            text += decoder.decode(part.value, { stream: true });
          }
          text += decoder.decode();
        } finally { reader.releaseLock(); }
      } else text = await response.text();
      if (text.length > MAX_BYTES) throw new Error('response_too_large');
      abort(signal);
      return JSON.parse(text);
    }

    function productUrl(handle) {
      if (!validString(handle, 255) || !/^[a-z0-9][a-z0-9-]*$/.test(handle)) throw new Error('invalid_handle');
      return new URL('products/' + encodeURIComponent(handle), base);
    }

    function validProduct(item, game) {
      if (!item || !PRODUCT_ID.test(item.productGid) || item.game !== game || item.productFamily !== 'single'
        || !validString(item.canonicalCardName) || !item.canonicalCardName.trim() || !Array.isArray(item.variants) || !item.variants.length) return false;
      try { productUrl(item.handle); } catch { return false; }
      return item.variants.every(variant => VARIANT_ID.test(variant.variantGid) && Array.isArray(variant.selectedOptions));
    }

    async function search(query, game = '', { signal, limit = DEFAULT_SEARCH_LIMIT } = {}) {
      const q = typeof query === 'string' ? query.trim() : '';
      if (!q || Array.from(q).length > 256 || (game && !GAMES.includes(game))) return { items: [], truncated: false };
      const items = [];
      const seen = new Set();
      let truncated = false;
      const searchLimit = boundedLimit(limit, DEFAULT_SEARCH_LIMIT);
      const searchPages = Math.ceil(searchLimit / PAGE_SIZE);
      // Bound all-game search: games share one page-size contract but never share cursors.
      for (const selectedGame of game ? [game] : GAMES) {
        const request = { contractVersion: 1, game: selectedGame, productFamily: 'single', q, filters: { inStock: null, productSubtype: null }, pageSize: PAGE_SIZE, sort: 'product_gid_asc' };
        let cursor = null;
        let generation = null;
        let gameCount = 0;
        const cursors = new Set();
        for (let pageNumber = 0; pageNumber < searchPages; pageNumber++) {
          const data = await readJson(endpoint, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify({ contractVersion: 1, cursor, request }) }, signal);
          const page = data.page;
          if (data.contractVersion !== 1 || page?.contractVersion !== 1 || canonical(page.request) !== canonical(request)
            || !/^sha256:[a-f0-9]{64}$/.test(page.datasetGeneration) || (generation && generation !== page.datasetGeneration)
            || !Array.isArray(page.items) || page.items.length > PAGE_SIZE || page.returnedProductCount !== page.items.length
            || typeof page.hasNextPage !== 'boolean' || page.hasNextPage !== (data.nextCursor !== null)
            || (data.nextCursor !== null && (!validString(data.nextCursor, 16384) || !data.nextCursor || cursors.has(data.nextCursor)))) throw new Error('invalid_catalog');
          generation = page.datasetGeneration;
          for (const item of page.items) {
            if (!validProduct(item, selectedGame) || seen.has(item.productGid)) throw new Error('invalid_catalog');
            seen.add(item.productGid);
            if (gameCount++ >= searchLimit) { truncated = true; continue; }
            items.push(item); found.set(item.productGid, item);
            if (found.size > 1000) found.delete(found.keys().next().value);
          }
          cursor = data.nextCursor;
          if (!cursor) break;
          cursors.add(cursor);
          if (pageNumber === searchPages - 1) truncated = true;
        }
      }
      return { items, truncated };
    }

    async function freshProduct(item, signal) {
      const variants = [];
      const ids = new Set();
      let first;
      let truncated = false;
      for (let number = 1; number <= VARIANT_PAGES; number++) {
        const url = productUrl(item.handle);
        url.searchParams.set('view', 'nla-wishlist-data');
        url.searchParams.set('page', String(number));
        // Shopify's JSON Accept negotiation bypasses alternate Liquid views.
        const data = await readJson(url, { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'text/html' } }, signal);
        if (data.contractVersion !== 1 || data.productId !== item.productGid || data.handle !== item.handle
          || data.page !== number || !Number.isSafeInteger(data.pages) || data.pages < 1
          || !Number.isSafeInteger(data.variantCount) || data.variantCount < 1 || data.variantCount > 10000
          || !Array.isArray(data.variants) || data.variants.length > 250
          || typeof data.catalogOnly !== 'boolean' || typeof data.requiresSellingPlan !== 'boolean'
          || (first && (data.pages !== first.pages || data.variantCount !== first.variantCount || sourceId(data) !== sourceId(first) || data.currency !== first.currency))) throw new Error('invalid_product_data');
        first ||= data;
        for (const variant of data.variants) {
          if (!decimalId(variant.id) || ids.has(variant.id) || !Number.isSafeInteger(variant.price) || variant.price < 0
            || typeof variant.available !== 'boolean' || !Number.isSafeInteger(variant.inventoryQuantity)
            || !['deny', 'continue'].includes(variant.inventoryPolicy)
            || (variant.inventoryManagement !== null && !validString(variant.inventoryManagement, 64))
            || !Array.isArray(variant.selectedOptions) || variant.selectedOptions.length > 10
            || variant.selectedOptions.some(option => !validString(option?.name, 128) || !validString(option?.value, 256))) throw new Error('invalid_product_data');
          ids.add(variant.id); variants.push(variant);
        }
        if (number === data.pages) break;
        if (number === VARIANT_PAGES) truncated = true;
      }
      if (!truncated && variants.length !== first.variantCount) throw new Error('incomplete_product_data');
      return { ...first, variants, sourceId: sourceId(first), truncated };
    }

    async function oracleFor(id, signal) {
      if (!decimalId(id)) return null;
      abort(signal);
      if (oracleCache.has(id)) return oracleCache.get(id);
      if (oraclePaused) return null;
      const task = oracleQueue.catch(() => {}).then(async () => {
        abort(signal);
        if (oraclePaused) return null;
        const wait = Math.max(0, 160 - (Date.now() - lastOracleStart));
        if (wait) await new Promise(resolve => setTimeout(resolve, wait));
        abort(signal);
        lastOracleStart = Date.now();
        try {
          const card = await readJson(new URL('https://api.scryfall.com/cards/cardmarket/' + id), { credentials: 'omit', headers: { Accept: 'application/json' } }, signal);
          if (card.object !== 'card' || !Number.isSafeInteger(card.cardmarket_id) || String(card.cardmarket_id) !== id
            || !UUID.test(card.oracle_id) || !validString(card.name) || !card.name.trim()) return null;
          return { cardmarketId: id, oracleId: card.oracle_id.toLowerCase(), name: card.name };
        } catch (error) {
          abort(signal);
          if (error.status === 429) oraclePaused = true;
          return null;
        }
      });
      oracleQueue = task;
      oracleCache.set(id, task);
      try { return await task; } catch (error) { oracleCache.delete(id); throw error; }
      finally { if (oracleCache.size > 500) oracleCache.delete(oracleCache.keys().next().value); }
    }

    function offerFor(item, product, variant, isExact) {
      const metadata = item.cardMetadata || {};
      const url = productUrl(item.handle);
      url.searchParams.set('variant', variant.id);
      let image = null;
      if (validString(product.image, 2048) && product.image) {
        try {
          const parsed = new URL(product.image, origin);
          if (parsed.protocol === 'https:' && !parsed.username && !parsed.password && !parsed.port && (parsed.origin === origin || parsed.hostname === 'cdn.shopify.com')) image = parsed.href;
        } catch { /* Missing images do not change identity or purchase eligibility. */ }
      }
      return { variantId: variant.id, productId: item.productGid, handle: item.handle,
        name: item.canonicalCardName || product.title, game: item.game,
        set: metadata.expansionCode || null, setName: metadata.expansionName || null,
        collectorNumber: metadata.collectorNumber || null, image, url: url.href,
        ...attributes(variant.selectedOptions), price: variant.price / 100,
        stock: variant.available && variant.inventoryManagement ? Math.max(0, variant.inventoryQuantity) : 0,
        exact: isExact, cardmarketId: product.sourceId };
    }

    async function resolve(row, { signal, scanLimit = PAGE_SIZE } = {}) {
      abort(signal);
      scanLimit = boundedLimit(scanLimit, PAGE_SIZE);
      const warnings = new Set();
      const empty = () => ({ offers: [], candidates: [], warnings: [...warnings], resolved: false, truncated: false });
      if (!row || !GAMES.includes(row.game)) { warnings.add('game_required'); return empty(); }
      const selectedId = productId(row.productId);
      const requestedSource = decimalId(row.cardmarketId) ? row.cardmarketId : null;
      let anchorOracle = null;
      let query = typeof row.canonicalName === 'string' && row.canonicalName ? row.canonicalName : typeof row.name === 'string' ? row.name : '';
      if (row.game === 'magic' && requestedSource && !selectedId) {
        anchorOracle = await oracleFor(requestedSource, signal);
        if (anchorOracle) query = anchorOracle.name;
        else warnings.add('identity_lookup_unavailable');
      }
      let searchResult = { items: [], truncated: false };
      try { searchResult = await search(query, row.game, { signal, limit: Math.max(DEFAULT_SEARCH_LIMIT, Math.min(MAX_PRODUCTS, scanLimit + PAGE_SIZE)) }); }
      catch { abort(signal); warnings.add('catalog_unavailable'); }
      const candidates = searchResult.items.slice();
      let selected = selectedId && (candidates.find(item => item.productGid === selectedId) || found.get(selectedId));
      if (selected?.game !== row.game) selected = null;
      if (selected && !candidates.some(item => item.productGid === selectedId)) candidates.unshift(selected);
      const exactSelection = Boolean(selected && row.exact !== false);
      let truncated = exactSelection ? false : searchResult.truncated || candidates.length > scanLimit;
      const targets = exactSelection ? [selected] : candidates.slice(0, scanLimit);
      if (selected && !targets.some(item => item.productGid === selectedId)) targets.unshift(selected);
      const loaded = [];
      let next = 0;
      await Promise.all(Array.from({ length: Math.min(3, targets.length) }, async () => {
        while (next < targets.length) {
          const item = targets[next++];
          try { loaded.push({ item, product: await freshProduct(item, signal) }); }
          catch { abort(signal); warnings.add('fresh_data_unavailable'); }
        }
      }));
      const hydrationComplete = loaded.length === targets.length;
      const selectedLoaded = loaded.find(entry => entry.item.productGid === selectedId);
      for (const { item, product } of loaded) {
        const candidate = candidates.find(value => value.productGid === item.productGid);
        if (candidate) {
          // Enrich a new public object; do not mutate the saved gateway response.
          const index = candidates.indexOf(candidate);
          candidates[index] = { ...candidate, cardmarketId: product.sourceId,
            selectionReason: item.productGid === selectedId ? 'selected_product' : 'confirm_printing' };
        }
      }
      let anchorId = selectedId;
      if (!selectedId && requestedSource && hydrationComplete) {
        const matches = loaded.filter(entry => entry.product.sourceId === requestedSource);
        if (matches.length === 1 && !truncated) anchorId = matches[0].item.productGid;
      }
      // A verified source set code + collector number can identify a unique printing.
      // Names only generate candidates and are never themselves the identity binding.
      if (!selectedId && !requestedSource && !row.metaProductId && row.set && row.collectorNumber && !truncated && hydrationComplete) {
        const matches = candidates.filter(item => normalize(item.cardMetadata?.expansionCode) === normalize(row.set)
          && normalize(item.cardMetadata?.collectorNumber) === normalize(row.collectorNumber));
        if (matches.length === 1) anchorId = matches[0].productGid;
      }
      const anchor = loaded.find(entry => entry.item.productGid === anchorId);
      if (selectedLoaded && requestedSource && selectedLoaded.product.sourceId !== requestedSource) {
        warnings.add('identity_mismatch');
        return { ...empty(), candidates, warnings: [...warnings], truncated };
      }
      if (row.exact === false && row.game === 'magic' && anchor?.product.sourceId && !anchorOracle) anchorOracle = await oracleFor(anchor.product.sourceId, signal);
      const approved = new Set((Array.isArray(row.confirmedProductIds) ? row.confirmedProductIds : []).map(productId).filter(Boolean));
      const offers = [];
      for (const { item, product } of loaded) {
        abort(signal);
        truncated ||= product.truncated;
        let accepted = item.productGid === anchorId;
        if (!accepted && row.exact === false && anchorId && approved.has(item.productGid)) accepted = true;
        if (!accepted && row.exact === false && anchorId && anchorOracle && product.sourceId && item.game === 'magic') {
          const proof = await oracleFor(product.sourceId, signal);
          accepted = proof !== null && proof.oracleId === anchorOracle.oracleId;
        }
        if (!accepted) continue;
        if (product.currency !== 'EUR') { warnings.add('currency_unsupported'); continue; }
        if (product.catalogOnly || product.requiresSellingPlan) continue;
        for (const variant of product.variants) {
          const offer = offerFor(item, product, variant, item.productGid === anchorId);
          offer.exact = item.productGid === anchorId && fits(offer, { ...row, exact: true });
          if (hasUnknownConstraint(offer, row)) warnings.add('unknown_attributes');
          if (offer.stock > 0 && fits(offer, row)) offers.push(offer);
        }
      }
      if (!anchor) warnings.add('identity_required');
      if (row.exact === false && candidates.some(item => item.productGid !== anchorId && !offers.some(offer => offer.productId === item.productGid))) warnings.add('alternatives_require_confirmation');
      if (truncated) warnings.add('results_truncated');
      offers.sort((a, b) => Number(b.exact) - Number(a.exact) || a.price - b.price || a.variantId.localeCompare(b.variantId));
      return { offers, candidates, warnings: [...warnings], resolved: Boolean(anchor), truncated };
    }

    return Object.freeze({ search, resolve });
  }

  return Object.freeze({ createClient, fits, attributes, sourceId });
});
