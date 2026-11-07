(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.NlaWishlistCore = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  // Pure parsing only: no catalog matching, network, storage or DOM insertion.
  var LIMITS = Object.freeze({ bytes: 2097152, rows: 1000, columns: 128, cell: 8192, depth: 24 });
  var FORMAT = 'NLA_WISHLIST_V1';
  var fields = ['id', 'name', 'game', 'quantity', 'productId', 'cardmarketId', 'metaProductId', 'handle', 'canonicalName', 'confirmedProductIds',
    'set', 'collectorNumber', 'languages', 'minCondition', 'foil', 'signed', 'altered',
    'firstEdition', 'maxPrice', 'exact', 'notes', 'extras'];
  var aliases = Object.create(null);
  function key(value) { return String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]/g, ''); }
  function addAliases(field, values) { values.concat(field).forEach(function (v) { aliases[key(v)] = field; }); }
  addAliases('id', ['rowId']);
  addAliases('name', ['cardName', 'productName', 'enName', 'nome', 'carta']);
  addAliases('game', ['gameName', 'idGame', 'tcg', 'gioco']);
  addAliases('quantity', ['count', 'amount', 'qty', 'quantita']);
  addAliases('productId', ['shopifyProductId', 'shopifyProductGid']);
  addAliases('cardmarketId', ['idProduct', 'mkmId', 'mkmProductId']);
  addAliases('metaProductId', ['idMetaproduct']);
  addAliases('handle', []);
  addAliases('canonicalName', []);
  addAliases('confirmedProductIds', []);
  addAliases('set', ['expansion', 'expansionName', 'setName', 'setCode', 'expansionCode', 'edizione']);
  addAliases('collectorNumber', ['cardNumber', 'number', 'nr', 'numero']);
  addAliases('languages', ['language', 'idLanguage', 'lingua', 'lingue']);
  addAliases('minCondition', ['condition', 'minimumCondition', 'condizione']);
  addAliases('foil', ['isFoil', 'finish']);
  addAliases('signed', ['isSigned', 'firmata']);
  addAliases('altered', ['isAltered', 'alterata']);
  addAliases('firstEdition', ['isFirstEd', 'firstEd', 'primaEdizione']);
  addAliases('maxPrice', ['wishPrice', 'maxPriceEUR', 'maximumPrice', 'prezzoMassimo']);
  addAliases('exact', ['exactVersion', 'versioneEsatta']);
  addAliases('notes', ['annotation', 'note', 'comments']);
  addAliases('extras', []);
  var games = Object.create(null);
  [['magic', ['magic', 'mtg', 'magic the gathering', '1']], ['pokemon', ['pokemon', 'pokemon tcg']],
    ['yugioh', ['yugioh', 'yu-gi-oh!', 'yugioh tcg']], ['one-piece', ['one piece', 'one piece tcg', 'op']]]
    .forEach(function (entry) { entry[1].forEach(function (s) { games[key(s)] = entry[0]; }); });
  // MKM numeric language IDs are documented in API 2.0 Articles.
  var languageIds = { '1': 'en', '2': 'fr', '3': 'de', '4': 'es', '5': 'it', '6': 'zh-CN',
    '7': 'ja', '8': 'pt', '9': 'ru', '10': 'ko', '11': 'zh-TW' };
  var languageNames = { en: 'en', english: 'en', inglese: 'en', fr: 'fr', french: 'fr', francese: 'fr',
    de: 'de', german: 'de', tedesco: 'de', it: 'it', italian: 'it', italiano: 'it', es: 'es', spanish: 'es',
    spagnolo: 'es', pt: 'pt', portuguese: 'pt', portoghese: 'pt', ja: 'ja', jp: 'ja', japanese: 'ja',
    giapponese: 'ja', ru: 'ru', russian: 'ru', russo: 'ru', ko: 'ko', korean: 'ko', coreano: 'ko',
    zhcn: 'zh-CN', simplifiedchinese: 'zh-CN', zhtw: 'zh-TW', traditionalchinese: 'zh-TW' };
  var conditions = { m: 'MT', mt: 'MT', mint: 'MT', nm: 'NM', nearmint: 'NM', ex: 'EX', excellent: 'EX',
    gd: 'GD', good: 'GD', lp: 'LP', lightplayed: 'LP', lightlyplayed: 'LP', pl: 'PL', played: 'PL', po: 'PO', poor: 'PO' };
  var informationKeys = ['idwant', 'idwantslist', 'wantlistname', 'wantslistname', 'fromprice', 'mailalert',
    'type', 'producturl', 'url', 'rarity', 'catid', 'sideboard', 'netdeckid', 'preconstructeddeckid', 'sourceproduct', 'sourcemetaproduct'];
  function own(obj, k) { return Object.prototype.hasOwnProperty.call(obj, k); }
  function lookup(obj, k) { return own(obj, k) ? obj[k] : undefined; }
  function empty(value) { return value === null || value === undefined || value === ''; }
  function isObject(value) { return value !== null && typeof value === 'object' && !Array.isArray(value); }
  function clone(value, depth) {
    if ((depth || 0) > LIMITS.depth) throw new Error('Struttura troppo annidata.');
    if (Array.isArray(value)) return value.map(function (v) { return clone(v, (depth || 0) + 1); });
    if (isObject(value)) {
      var result = Object.create(null);
      Object.keys(value).forEach(function (k) { result[k] = clone(value[k], (depth || 0) + 1); });
      return result;
    }
    return value;
  }
  function rawText(value) { return empty(value) ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value); }
  function string(value) { return rawText(value).trim(); }
  function tri(value) {
    if (empty(value)) return null;
    if (value === true || value === false) return value;
    var s = string(value).toLowerCase();
    if (['true', 'yes', 'y', 'si', 'sì', '1'].indexOf(s) >= 0) return true;
    if (['false', 'no', 'n', '0'].indexOf(s) >= 0) return false;
    if (['any', 'all', '*', 'either', 'indifferente', 'no preference', 'null'].indexOf(s) >= 0) return null;
    return undefined;
  }
  function gameValue(value) {
    if (isObject(value)) value = value.name || value.gameName || value.abbreviation || value.idGame;
    return games[key(empty(value) ? '' : value)] || '';
  }
  function normalizeRow(input, options) {
    options = options || {};
    var errors = [], warnings = [], extras = Object.create(null), raw = Object.create(null);
    var invalid = Object.create(null);
    function fail(field, value, message) { invalid[field] = clone(value); errors.push(message); }
    if (!isObject(input)) { input = { name: '', invalidRow: clone(input) }; errors.push('La riga non è un oggetto.'); }
    var source = clone(input);
    ['product', 'metaproduct'].forEach(function (type) {
      var nested = source[type];
      if (!isObject(nested)) return;
      extras[type === 'product' ? 'sourceProduct' : 'sourceMetaproduct'] = nested;
      var mapping = { enName: 'name', name: 'name', gameName: 'game', game: 'game', idGame: 'game',
        expansionName: 'set', expansion: 'set', nr: 'collectorNumber', idProduct: 'cardmarketId', idMetaproduct: 'metaProductId' };
      var preferences = ['foil', 'signed', 'altered', 'firstEdition', 'languages', 'minCondition', 'maxPrice'];
      Object.keys(nested).forEach(function (k) {
        var field = aliases[key(k)];
        if (preferences.indexOf(field) >= 0) mapping[k] = field;
      });
      Object.keys(mapping).forEach(function (k) {
        var field = mapping[k];
        if (own(nested, k) && ['cardmarketId', 'metaProductId', 'game'].concat(preferences).indexOf(field) >= 0) {
          Object.keys(source).forEach(function (s) {
            if (aliases[key(s)] !== field) return;
            var same = field === 'game' ? gameValue(source[s]) && gameValue(source[s]) === gameValue(nested[k]) :
              ['foil', 'signed', 'altered', 'firstEdition'].indexOf(field) >= 0 ? tri(source[s]) !== undefined && tri(source[s]) === tri(nested[k]) :
                string(source[s]) === string(nested[k]);
            if (!same) {
              fail(field, [source[s], nested[k]], 'Dati sorgente in conflitto: ' + field + '.');
            }
          });
        }
        if (own(nested, k) && !own(source, field) && !Object.keys(source).some(function (s) { return aliases[key(s)] === field; })) source[field] = nested[k];
      });
      // API product metadata is retained verbatim; unknown nested purchase fields
      // must still be surfaced rather than hidden inside the informational object.
      var metadata = ['idcategory', 'categoryname', 'category', 'locname', 'image', 'imageurl', 'website', 'links',
        'priceguide', 'rarity', 'reprint', 'countreprints', 'idexpansion', 'abbreviation', 'expansionicon', 'dateadded'];
      Object.keys(nested).forEach(function (k) {
        if (!own(mapping, k) && metadata.indexOf(key(k)) < 0) extras[type + '.' + k] = nested[k];
      });
      delete source[type];
    });
    var exportFormat = source._nlaFormat === FORMAT;
    Object.keys(source).forEach(function (original) {
      if (['needsReview', 'errors', 'warnings'].indexOf(original) >= 0) return;
      if (original === '_nlaFormat' && exportFormat) return;
      var field = aliases[key(original)], value = source[original];
      if (exportFormat && typeof value === 'string' && /^'(?:'|[\s]*[=+@-])/.test(value)) value = value.slice(1);
      if (!field) { extras[original] = value; return; }
      if (own(raw, field) && JSON.stringify(raw[field]) !== JSON.stringify(value)) {
        fail(field, [raw[field], value], 'Colonne in conflitto per ' + field + '.');
      } else raw[field] = value;
    });
    if (!empty(raw.extras)) {
      try {
        var suppliedExtras = typeof raw.extras === 'string' ? JSON.parse(raw.extras) : raw.extras;
        if (!isObject(suppliedExtras)) throw new Error('extras');
        Object.keys(suppliedExtras).forEach(function (k) { extras[k] = clone(suppliedExtras[k]); });
      } catch (_) { fail('extras', raw.extras, 'Campi aggiuntivi non validi.'); }
    }
    // Keep invalid constraints blocking after storage/export. The editor can explicitly
    // clear one using options.editedFields; changing its value also revalidates it.
    var editedFields = Array.isArray(options.editedFields) ? options.editedFields : [];
    if (isObject(extras._invalidFields)) {
      Object.keys(extras._invalidFields).forEach(function (k) {
        var previous = extras._reviewValues;
        if (editedFields.indexOf(k) < 0 && (!isObject(previous) || !own(previous, k) ||
          JSON.stringify(raw[k]) === JSON.stringify(previous[k]) || !own(raw, k))) raw[k] = extras._invalidFields[k];
      });
    }
    var row = { id: string(options.id || raw.id) || 'row-1', name: string(raw.name), game: '', quantity: 1,
      productId: null, cardmarketId: null, metaProductId: null, set: string(raw.set), collectorNumber: string(raw.collectorNumber),
      handle: string(raw.handle), canonicalName: string(raw.canonicalName), confirmedProductIds: [],
      languages: [], minCondition: null, foil: null, signed: null, altered: null, firstEdition: null,
      maxPrice: null, exact: true, notes: rawText(raw.notes), extras: extras };
    ['id', 'name', 'set', 'collectorNumber', 'notes', 'handle', 'canonicalName'].forEach(function (field) {
      if (row[field].length > LIMITS.cell || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(row[field])) fail(field, raw[field], 'Testo non valido o troppo lungo: ' + field + '.');
      if (!empty(raw[field]) && typeof raw[field] === 'object') fail(field, raw[field], 'Testo atteso: ' + field + '.');
    });
    var sourceGame = empty(raw.game) ? options.defaultGame : raw.game;
    row.game = gameValue(sourceGame);
    if (!row.game) fail('game', sourceGame === undefined ? '' : sourceGame, empty(sourceGame) ? 'Seleziona il gioco della carta.' : 'Gioco non riconosciuto.');
    if (!empty(raw.quantity)) {
      var q = string(raw.quantity);
      if (!/^[1-9]\d{0,2}$/.test(q)) { row.quantity = null; fail('quantity', raw.quantity, 'Quantità non valida: usare un intero da 1 a 999.'); }
      else row.quantity = Number(q);
    }
    ['productId', 'cardmarketId', 'metaProductId'].forEach(function (field) {
      if (empty(raw[field])) return;
      var value = string(raw[field]);
      var valid = /^[1-9]\d*$/.test(value) && value.length <= 20;
      if (field === 'productId') valid = valid || /^gid:\/\/shopify\/Product\/[1-9]\d{0,19}$/.test(value);
      if (typeof raw[field] === 'number' && !Number.isSafeInteger(raw[field])) valid = false;
      if (valid) row[field] = value;
      else fail(field, raw[field], 'Identificatore non valido: ' + field + '.');
    });
    if (row.handle && !/^[a-z0-9][a-z0-9-]{0,254}$/.test(row.handle)) fail('handle', raw.handle, 'Handle prodotto non valido.');
    if (!empty(raw.confirmedProductIds)) {
      var bindings = raw.confirmedProductIds;
      if (typeof bindings === 'string') {
        try { bindings = JSON.parse(bindings); } catch (_) { bindings = null; }
      }
      if (!Array.isArray(bindings) || bindings.length > LIMITS.rows || bindings.some(function (value) {
        return (typeof value === 'number' && !Number.isSafeInteger(value)) ||
          !/^(?:gid:\/\/shopify\/Product\/)?[1-9]\d{0,19}$/.test(string(value));
      })) fail('confirmedProductIds', raw.confirmedProductIds, 'Elenco identificatori prodotto non valido.');
      else bindings.forEach(function (value) { value = string(value); if (row.confirmedProductIds.indexOf(value) < 0) row.confirmedProductIds.push(value); });
    }
    if (!row.name && !row.productId && !row.cardmarketId && !row.metaProductId) errors.push('Manca il nome o un identificatore della carta.');
    var langValue = raw.languages;
    if (!empty(langValue)) {
      if (typeof langValue === 'string' && langValue.trim().charAt(0) === '[') {
        try { langValue = JSON.parse(langValue); } catch (_) { fail('languages', raw.languages, 'Elenco lingue non valido.'); }
      }
      var langItems = Array.isArray(langValue) ? langValue : (isObject(langValue) ? [langValue] : string(langValue).split(/[,;|/]/));
      var anyLanguage = false;
      langItems.forEach(function (value) {
        if (isObject(value)) {
          value = value.idLanguage || value.languageName || value.langName || value.name;
          if (empty(value)) { fail('languages', raw.languages, 'Oggetto lingua non riconosciuto.'); return; }
        }
        var token = string(value), normalized = key(token);
        if (!token || ['any', 'all', 'tutte', 'qualsiasi'].indexOf(normalized) >= 0 || token === '*') { anyLanguage = true; return; }
        var lang = lookup(languageIds, token) || lookup(languageNames, normalized);
        if (!lang) fail('languages', raw.languages, 'Lingua non riconosciuta: ' + token + '.');
        else if (row.languages.indexOf(lang) < 0) row.languages.push(lang);
      });
      if (anyLanguage && row.languages.length) fail('languages', raw.languages, 'Lingue specifiche e qualsiasi lingua sono in conflitto.');
    }
    if (!empty(raw.minCondition) && !['any', 'all', '*', 'indifferente'].includes(string(raw.minCondition).toLowerCase())) {
      row.minCondition = lookup(conditions, key(raw.minCondition)) || null;
      if (!row.minCondition) fail('minCondition', raw.minCondition, 'Condizione non riconosciuta.');
    }
    ['foil', 'signed', 'altered', 'firstEdition'].forEach(function (field) {
      var supplied = raw[field];
      if (field === 'foil' && typeof supplied === 'string') {
        if (key(supplied) === 'foil') supplied = true;
        else if (['nonfoil', 'normal'].indexOf(key(supplied)) >= 0) supplied = false;
      }
      var value = tri(supplied);
      if (value === undefined) fail(field, raw[field], 'Preferenza non valida: ' + field + '.');
      else row[field] = value;
    });
    if (!empty(raw.exact)) {
      var exact = tri(raw.exact);
      if (exact !== true && exact !== false) fail('exact', raw.exact, 'Versione esatta deve essere sì o no.');
      else row.exact = exact;
    }
    if (!empty(raw.maxPrice)) {
      var money = string(raw.maxPrice).match(/^(?:(EUR|€)\s*)?(\d+(?:[.,]\d{1,2})?)(?:\s*(EUR|€))?$/i);
      if (!money || (money[1] && money[3]) || !Number.isSafeInteger(Math.round(Number(money[2].replace(',', '.')) * 100))) fail('maxPrice', raw.maxPrice, 'Prezzo massimo EUR non valido o ambiguo.');
      else row.maxPrice = Number(money[2].replace(',', '.'));
    }
    Object.keys(extras).forEach(function (k) {
      if (k === '_invalidFields' || k === '_reviewValues') return;
      warnings.push('Campo aggiuntivo conservato: ' + k + '.');
      if (informationKeys.indexOf(key(k)) < 0) errors.push('Verifica il campo non applicato: ' + k + '.');
    });
    if (Object.keys(invalid).length) {
      extras._invalidFields = invalid;
      extras._reviewValues = Object.create(null);
      Object.keys(invalid).forEach(function (k) { extras._reviewValues[k] = clone(row[k]); });
    } else { delete extras._invalidFields; delete extras._reviewValues; }
    row.errors = errors; row.warnings = warnings; row.needsReview = errors.length > 0;
    return row;
  }

  function result() { return { rows: [], errors: [], warnings: [] }; }
  function append(out, input, options) {
    if (out.rows.length >= LIMITS.rows) throw new Error('Limite di ' + LIMITS.rows + ' righe superato.');
    var row = normalizeRow(input, { defaultGame: options && options.defaultGame, id: 'row-' + (out.rows.length + 1) });
    out.rows.push(row);
    row.errors.forEach(function (s) { out.errors.push('Riga ' + out.rows.length + ': ' + s); });
    row.warnings.forEach(function (s) { out.warnings.push('Riga ' + out.rows.length + ': ' + s); });
  }
  function checkedText(text) {
    if (typeof text !== 'string') throw new Error('Il contenuto del file deve essere testo.');
    var bytes = typeof TextEncoder === 'function' ? new TextEncoder().encode(text).length : unescape(encodeURIComponent(text)).length;
    if (bytes > LIMITS.bytes) throw new Error('File troppo grande: massimo 2 MiB.');
    if (text.indexOf('\0') >= 0) throw new Error('Il file contiene caratteri binari non validi.');
    return text.replace(/^\uFEFF/, '');
  }
  function csvRecords(text, delimiter) {
    var rows = [], row = [], cell = '', quoted = false, afterQuote = false;
    function field() { row.push(cell); cell = ''; afterQuote = false; if (row.length > LIMITS.columns) throw new Error('Troppe colonne nel file.'); }
    function record() { field(); if (row.some(function (v) { return v.trim() !== ''; })) rows.push(row); row = []; if (rows.length > LIMITS.rows + 1) throw new Error('Troppe righe nel file.'); }
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (quoted) {
        if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else { quoted = false; afterQuote = true; } }
        else cell += c;
      } else if (c === delimiter) field();
      else if (c === '\n' || c === '\r') { record(); if (c === '\r' && text[i + 1] === '\n') i++; }
      else if (c === '"') { if (cell !== '' || afterQuote) throw new Error('Virgolette CSV non valide.'); quoted = true; }
      else if (afterQuote) { if (c !== ' ' && c !== '\t') throw new Error('Testo inatteso dopo le virgolette CSV.'); }
      else cell += c;
      if (cell.length > LIMITS.cell) throw new Error('Una cella supera il limite consentito.');
    }
    if (quoted) throw new Error('Virgolette CSV non chiuse.');
    if (cell !== '' || row.length || afterQuote) record();
    return rows;
  }
  function parseCSV(text, options, tabOnly) {
    var candidates = (tabOnly ? ['\t'] : [',', ';', '\t']).map(function (d) {
      try { var rows = csvRecords(text, d); return { rows: rows, score: rows.length ? rows[0].filter(function (h) { return !!aliases[key(h)] || h === '_nlaFormat'; }).length : 0 }; }
      catch (e) { return { error: e.message, score: -1 }; }
    });
    candidates.sort(function (a, b) { return b.score - a.score; });
    var chosen = candidates[0];
    if (chosen.score < 1) throw new Error(chosen.error || 'Intestazioni CSV non riconosciute: indicare almeno nome o identificatore.');
    var records = chosen.rows, header = records.shift(), seen = Object.create(null), out = result();
    header.forEach(function (h) { var k = key(h); if (!k || own(seen, k)) throw new Error('Intestazione vuota o duplicata nel CSV.'); seen[k] = true; });
    if (!header.some(function (h) { return ['name', 'cardmarketId', 'metaProductId', 'productId'].indexOf(aliases[key(h)]) >= 0; })) throw new Error('Il CSV non ha una colonna nome o identificatore.');
    records.forEach(function (record, index) {
      if (record.length !== header.length) throw new Error('Numero di colonne errato alla riga ' + (index + 2) + '.');
      var raw = Object.create(null); header.forEach(function (h, j) { raw[h] = record[j]; }); append(out, raw, options);
    });
    return out;
  }
  function parseText(text, options) {
    var out = result();
    try {
      text = checkedText(text);
      text.split(/\r\n|\r|\n/).forEach(function (line) {
        line = line.trim(); if (!line) return;
        var raw = { name: line }, gamePrefix = line.match(/^\[([^\]]+)\]\s*(.*)$/);
        if (gamePrefix) { raw.game = gamePrefix[1]; line = gamePrefix[2]; }
        var amount = line.match(/^([+-]?\d+(?:[.,]\d+)?)\s*[x×]?\s+(.+)$/i);
        if (amount) { raw.quantity = amount[1]; line = amount[2]; }
        var setMatch = line.match(/\s+\(([^()]+)\)\s*$/);
        if (setMatch && !/^v\./i.test(setMatch[1])) { raw.set = setMatch[1]; line = line.slice(0, setMatch.index); }
        var version = line.match(/\s+\((V\.[^()]+)\)\s*$/i);
        if (version) { raw.version = version[1]; line = line.slice(0, version.index); }
        raw.name = line.trim(); append(out, raw, options);
      });
    } catch (e) { return { rows: [], errors: [e.message], warnings: [] }; }
    return out;
  }
  function fromJSON(value, options) {
    var out = result();
    function visit(node, context, depth) {
      if (depth > LIMITS.depth) throw new Error('JSON troppo annidato.');
      if (Array.isArray(node)) { node.forEach(function (v) { visit(v, context, depth + 1); }); return; }
      if (!isObject(node)) throw new Error('Formato JSON wishlist non riconosciuto.');
      var next = { defaultGame: context.defaultGame };
      if (own(node, 'game')) next.defaultGame = node.game;
      else if (own(node, 'idGame')) next.defaultGame = node.idGame;
      var wrappers = ['response', 'wantslist', 'wantslists', 'wishlist', 'wishlists', 'item', 'items', 'want', 'wants', 'rows'];
      var nested = wrappers.filter(function (k) { return own(node, k) && (Array.isArray(node[k]) || isObject(node[k])); });
      if (nested.length) { nested.forEach(function (k) { visit(node[k], next, depth + 1); }); return; }
      append(out, node, next);
    }
    visit(value, options || {}, 0); return out;
  }
  function fromXML(text, options) {
    if (/<!\s*(?:DOCTYPE|ENTITY)/i.test(text)) throw new Error('DTD ed entità XML non sono consentite.');
    if (typeof root.DOMParser !== 'function') throw new Error('Importazione XML disponibile nel browser.');
    var doc = new root.DOMParser().parseFromString(text, 'application/xml');
    if (doc.getElementsByTagName('parsererror').length) throw new Error('XML non valido.');
    function object(element, depth) {
      if (depth > LIMITS.depth) throw new Error('XML troppo annidato.');
      var children = Array.from(element.children || []), data = Object.create(null);
      if (!children.length && !element.attributes.length) return element.textContent;
      Array.from(element.attributes || []).forEach(function (a) { data[a.name] = a.value; });
      children.forEach(function (child) {
        var k = child.localName, value = object(child, depth + 1);
        if (own(data, k)) { if (!Array.isArray(data[k])) data[k] = [data[k]]; data[k].push(value); }
        else data[k] = value;
      });
      return data;
    }
    var rootName = doc.documentElement.localName.toLowerCase();
    if (rootName === 'deck') {
      var out = result();
      Array.from(doc.getElementsByTagName('Cards')).forEach(function (card) { append(out, object(card, 0), options); });
      if (!out.rows.length) throw new Error('Il file DEK non contiene carte.');
      out.warnings.push('DEK: CatID è conservato come dato sorgente, non come identificatore Cardmarket.');
      return out;
    }
    if (['response', 'wantslist', 'wantslists', 'wishlist', 'want', 'item'].indexOf(rootName) < 0) throw new Error('Formato XML wishlist non riconosciuto.');
    return fromJSON(object(doc.documentElement, 0), options);
  }
  function parseFile(text, filename, options) {
    try {
      text = checkedText(text);
      if (!text.trim()) return { rows: [], errors: ['Il file è vuoto.'], warnings: [] };
      var ext = string(filename).toLowerCase().split('.').pop();
      if (ext === 'json' || (!filename && /^[\[{]/.test(text.trim()))) return fromJSON(JSON.parse(text), options);
      if (ext === 'xml' || ext === 'dek' || (!filename && /^</.test(text.trim()))) return fromXML(text, options);
      if (ext === 'csv' || ext === 'tsv') return parseCSV(text, options, ext === 'tsv');
      if (ext === 'txt' || !filename) return parseText(text, options);
      return { rows: [], errors: ['Formato non supportato: usare CSV, TSV, TXT, JSON, XML o DEK.'], warnings: [] };
    } catch (e) { return { rows: [], errors: [e.message], warnings: [] }; }
  }
  function exportCSV(rows) {
    if (!Array.isArray(rows) || rows.length > LIMITS.rows) throw new Error('Elenco righe non valido.');
    function cell(value) {
      var text = empty(value) ? '' : (typeof value === 'object' ? JSON.stringify(value) : String(value));
      // Quoting alone does not prevent spreadsheet formula evaluation.
      if (/^(?:'|[\s]*[=+@-])/.test(text)) text = "'" + text;
      return '"' + text.replace(/"/g, '""') + '"';
    }
    var header = ['_nlaFormat'].concat(fields);
    var records = [header.map(cell).join(',')];
    rows.forEach(function (row) {
      records.push([FORMAT].concat(fields.map(function (field) {
        if (row.extras && row.extras._invalidFields && own(row.extras._invalidFields, field)) return row.extras._invalidFields[field];
        return row[field];
      })).map(cell).join(','));
    });
    return '\uFEFF' + records.join('\r\n') + '\r\n';
  }
  return Object.freeze({ parseFile: parseFile, parseText: parseText, normalizeRow: normalizeRow, exportCSV: exportCSV, limits: LIMITS });
}));
