(function (root, factory) {
  'use strict';
  var api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else { root.NlaWishlist = api; api.mount(); }
}(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
  'use strict';

  // One stock pool per variant, even when several list rows want the same card.
  function allocate(rows, resolutions, cart) {
    var stock = new Map(), inCart = new Map(), result = new Map(), lines = new Map();
    function quantity(value) { var n = Number(value); return Number.isFinite(n) ? Math.max(0, Math.floor(n)) : 0; }
    (cart.items || []).forEach(function (i) {
      var id = String(i.variant_id || i.id); inCart.set(id, (inCart.get(id) || 0) + quantity(i.quantity));
    });
    rows.forEach(function (r) {
      result.set(r.id, { requested: quantity(r.quantity), inCart: 0, quantity: 0, offers: [] });
      (resolutions.get(r.id)?.offers || []).forEach(function (o) {
        var id = String(o.variantId), n = Math.max(0, Math.floor(o.stock));
        if (Number.isFinite(n)) stock.set(id, stock.has(id) ? Math.min(stock.get(id), n) : n);
      });
    });
    var pools = new Map();
    stock.forEach(function (n, id) {
      var existing = inCart.get(id) || 0;
      pools.set(id, {
        cart: { kind: 'pool', id: id, existing: true, capacity: existing, used: 0, owners: new Map() },
        free: { kind: 'pool', id: id, existing: false, capacity: Math.max(0, n - existing), used: 0, owners: new Map() }
      });
    });
    var states = rows.map(function (r) {
      var resolution = resolutions.get(r.id), seen = new Set();
      var offers = (!r.needsReview && resolution?.resolved ? resolution.offers || [] : [])
        .filter(function (o) { return Number.isFinite(o.price) && o.price >= 0 && /^[1-9]\d*$/.test(String(o.variantId)); })
        .slice().sort(function (a, b) { return Number(b.exact) - Number(a.exact) || a.price - b.price || String(a.variantId).localeCompare(String(b.variantId)); })
        .filter(function (o) { var id = String(o.variantId); if (seen.has(id)) return false; seen.add(id); return true; });
      var state = { kind: 'row', row: r, requested: result.get(r.id).requested, assigned: 0, offers: offers, edges: [], flow: new Map() };
      // Existing cart copies are consumed before proposing new purchases.
      ['cart', 'free'].forEach(function (type) {
        offers.forEach(function (o) { var pool = pools.get(String(o.variantId))?.[type]; if (pool?.capacity > 0) state.edges.push(pool); });
      });
      return state;
    }).sort(function (a, b) { return Number(b.row.exact) - Number(a.row.exact) || a.offers.length - b.offers.length; });

    // Residual paths move previous allocations to other compatible variants while
    // retaining each earlier row's filled quantity. Whole capacities move at once.
    function pathFrom(start, cartOnly) {
      var parent = new Map([[start, null]]), queue = [start], next = 0;
      while (next < queue.length) {
        var current = queue[next++];
        if (current.kind === 'row') {
          for (var pool of current.edges) {
            if (cartOnly && !pool.existing) continue;
            if (parent.has(pool) || current.requested <= (current.flow.get(pool) || 0)) continue;
            parent.set(pool, current);
            if (pool.used < pool.capacity) return { end: pool, parent: parent };
            queue.push(pool);
          }
        } else {
          for (var owner of current.owners.keys()) {
            if (!parent.has(owner) && current.owners.get(owner) > 0) { parent.set(owner, current); queue.push(owner); }
          }
        }
      }
      return null;
    }
    function changeFlow(state, pool, amount) {
      var n = (state.flow.get(pool) || 0) + amount;
      if (n) { state.flow.set(pool, n); pool.owners.set(state, n); }
      else { state.flow.delete(pool); pool.owners.delete(state); }
      pool.used += amount;
    }
    // First maximize already-owned cart coverage, then fill from free inventory.
    [true, false].forEach(function (cartOnly) {
      states.forEach(function (start) {
      while (start.assigned < start.requested) {
        var path = pathFrom(start, cartOnly); if (!path) break;
        var amount = Math.min(start.requested - start.assigned, path.end.capacity - path.end.used);
        var current = path.end, previous;
        while ((previous = path.parent.get(current))) {
          amount = Math.min(amount, previous.kind === 'row'
            ? previous.requested - (previous.flow.get(current) || 0)
            : current.flow.get(previous) || 0);
          current = previous;
        }
        if (amount <= 0) break;
        current = path.end;
        while ((previous = path.parent.get(current))) {
          if (previous.kind === 'row') changeFlow(previous, current, amount);
          else changeFlow(current, previous, -amount);
          current = previous;
        }
        start.assigned += amount;
      }
      });
    });
    states.forEach(function (state) {
      var p = result.get(state.row.id);
      state.offers.forEach(function (o) {
        var id = String(o.variantId), pair = pools.get(id);
        if (!pair) return;
        p.inCart += state.flow.get(pair.cart) || 0;
        var n = state.flow.get(pair.free) || 0; if (!n) return;
        p.quantity += n; p.offers.push(Object.assign({}, o, { quantity: n }));
        var line = lines.get(id) || { id: id, quantity: 0, price: o.price };
        line.quantity += n; lines.set(id, line);
      });
    });
    var entries = Array.from(lines.values());
    return { rows: result, lines: entries, quantity: entries.reduce(function (n, l) { return n + l.quantity; }, 0),
      total: entries.reduce(function (n, l) { return n + Math.round(l.price * 100) * l.quantity; }, 0) / 100,
      requested: rows.reduce(function (n, r) { return n + quantity(r.quantity); }, 0),
      inCart: Array.from(result.values()).reduce(function (n, r) { return n + r.inCart; }, 0) };
  }
  function fingerprint(plan) {
    return JSON.stringify(plan.lines.map(function (l) { return [String(l.id), l.quantity, Math.round(l.price * 100)]; }).sort(function (a, b) { return a[0].localeCompare(b[0]); }));
  }
  function cartDiff(before, after, lines) {
    var counts = function (cart) { var m = new Map(); (cart.items || []).forEach(function (i) { var id = String(i.variant_id || i.id); m.set(id, (m.get(id) || 0) + i.quantity); }); return m; };
    var a = counts(before), b = counts(after);
    return lines.reduce(function (sum, line) { return sum + Math.min(line.quantity, Math.max(0, (b.get(String(line.id)) || 0) - (a.get(String(line.id)) || 0))); }, 0);
  }
  function uid() { return root.crypto?.randomUUID ? root.crypto.randomUUID() : Date.now().toString(36) + '-' + Math.random().toString(36).slice(2); }
  function safeUrl(value, image) {
    if (typeof value !== 'string' || !value.trim()) return '';
    try { var u = new URL(value, root.location.origin); return (image ? u.protocol === 'https:' : u.origin === root.location.origin) ? u.href : ''; } catch (_) { return ''; }
  }
  function node(tag, cls, text) { var el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; }
  var games = { magic: 'Magic', pokemon: 'Pokémon', 'one-piece': 'One Piece', yugioh: 'Yu-Gi-Oh!' };
  var copy = {
    it: { list: 'La mia wishlist', loading: 'Controllo disponibilità…', searching: 'Cerco le carte…', noResults: 'Nessuna carta trovata. Prova un nome più preciso.', searchError: 'Ricerca non disponibile. Riprova tra poco.', edit: 'Modifica', remove: 'Rimuovi', exact: 'Versione esatta', choose: 'Conferma questa carta', alternative: 'Consenti questa alternativa', pending: 'Carta da identificare', unavailable: 'Nessuna variante compatibile disponibile', offers: 'Versioni disponibili', selected: 'Selezionate', stock: 'disponibili', quantity: 'Quantità', import: 'Anteprima importazione', importEmpty: 'Nessuna riga importabile.', imported: 'Lista importata. Le righe da verificare restano visibili.', large: 'Il file supera 2 MB.', storage: 'Salvataggio sul dispositivo non disponibile: esporta la lista per conservarla.', corrupt: 'Il salvataggio precedente non è leggibile. Non verrà sovrascritto; puoi usare ed esportare una nuova lista.', empty: 'La tua prossima carta ti aspetta.', emptyBody: 'Cerca una carta oppure importa una wishlist. Puoi mescolare tutti i tuoi giochi.', available: 'Da aggiungere', cards: 'carte', already: 'già nel carrello', missing: 'non coperte', checking: 'Verifica finale di prezzi e disponibilità…', changed: 'Disponibilità o prezzi sono cambiati. Controlla le nuove selezioni e premi di nuovo per aggiungerle.', cartError: 'Non è stato possibile aggiornare il carrello. Nessun nuovo tentativo automatico: controlla il carrello prima di riprovare.', cartReadError: 'Impossibile leggere il carrello: riprova prima di aggiungere le carte.', added: 'carte aggiunte al carrello.', currency: 'Questa wishlist usa prezzi in EUR. Seleziona il mercato in euro prima di aggiungere.', partial: 'Aggiunta parziale: verifica il carrello e le quantità ancora disponibili.', review: 'Da verificare', saved: 'Preferenze salvate.', importLimit: 'Massimo 1.000 righe per lista.', truncation: 'Risultati parziali: restringi la ricerca per vedere altre stampe.', noGame: 'Seleziona il gioco in Modifica.', unknown: 'Variabili aggiuntive da verificare', euro: 'Totale stimato', busy: 'Attendi la verifica in corso.', importRows: 'righe', refresh: 'Ricontrolla disponibilità', fresh: 'Disponibilità aggiornata.', match: 'Seleziona la stampa corretta per questa riga.', filename: 'wishlist', error: 'Verifica non disponibile. Riprova.', noItems: 'Non ci sono altre carte compatibili da aggiungere.', readFile: 'Impossibile leggere il file.', verify: 'Verifica carta', invalid: 'Correggi i campi segnalati prima di aggiungere al carrello.' },
    en: { list: 'My wishlist', loading: 'Checking availability…', searching: 'Searching cards…', noResults: 'No cards found. Try a more precise name.', searchError: 'Search is unavailable. Please try again.', edit: 'Edit', remove: 'Remove', exact: 'Exact version', choose: 'Confirm this card', alternative: 'Allow this alternative', pending: 'Identify this card', unavailable: 'No matching variant available', offers: 'Available versions', selected: 'Selected', stock: 'available', quantity: 'Quantity', import: 'Import preview', importEmpty: 'No rows to import.', imported: 'List imported. Rows requiring review remain visible.', large: 'The file exceeds 2 MB.', storage: 'Device storage is unavailable. Export your list to keep it.', corrupt: 'The previous save cannot be read and will not be overwritten. You can use and export a new list.', empty: 'Your next card is waiting.', emptyBody: 'Search for a card or import a wishlist. Mix all your games.', available: 'To add', cards: 'cards', already: 'already in cart', missing: 'unfilled', checking: 'Checking current prices and availability…', changed: 'Prices or availability changed. Review the new selection and click again to add it.', cartError: 'The cart could not be updated. No automatic retry: check your cart before trying again.', cartReadError: 'Cannot read the cart. Please try again before adding cards.', added: 'cards added to cart.', currency: 'This wishlist uses EUR prices. Select a euro market before adding cards.', partial: 'Partially added: check the cart and remaining availability.', review: 'Needs review', saved: 'Preferences saved.', importLimit: 'Maximum 1,000 rows per list.', truncation: 'Partial results: narrow your search to see more printings.', noGame: 'Select the game using Edit.', unknown: 'Additional fields need review', euro: 'Estimated total', busy: 'Please wait for the current check.', importRows: 'rows', refresh: 'Refresh availability', fresh: 'Availability updated.', match: 'Select the correct printing for this row.', filename: 'wishlist', error: 'Check unavailable. Please try again.', noItems: 'No more matching cards to add.', readFile: 'Cannot read this file.', verify: 'Identify card', invalid: 'Correct the flagged fields before adding to cart.' }
  };

  function mount() {
    if (!root.document || !root.NlaWishlistCore || !root.NlaWishlistData) return;
    document.querySelectorAll('nla-wishlist:not([data-ready])').forEach(function (el) { el.dataset.ready = 'true'; new Workspace(el); });
  }
  function Workspace(el) {
    this.el = el; this.core = root.NlaWishlistCore; this.t = copy[el.dataset.locale === 'en' ? 'en' : 'it'];
    this.rootUrl = root.Shopify?.routes?.root || '/';
    this.client = root.NlaWishlistData.createClient({ endpoint: el.dataset.endpoint, rootUrl: this.rootUrl });
    this.results = new Map(); this.scanLimits = new Map(); this.cart = { items: [], currency: 'EUR' }; this.cartKnown = false; this.epoch = 0; this.busy = false; this.searchSeq = 0;
    this.storageKey = 'nla:wishlists:v1:' + root.location.hostname; this.canSave = true;
    this.state = { version: 1, selected: '', lists: [] };
    try {
      var saved = root.localStorage.getItem(this.storageKey);
      if (saved) {
        var parsed = JSON.parse(saved);
        if (parsed.version !== 1 || !Array.isArray(parsed.lists) || parsed.lists.length > 100 || !parsed.lists.every(function (l) { return typeof l.id === 'string' && typeof l.name === 'string' && Array.isArray(l.rows) && l.rows.length <= 1000; })) throw new Error('save');
        parsed.lists.forEach(function (l) { l.rows = l.rows.map(function (r) { return this.core.normalizeRow(r, { id: r?.id || uid() }); }, this); }, this);
        this.state = parsed;
      }
    } catch (_) { this.canSave = false; this.status(this.t.corrupt, true); }
    if (!this.state.lists.length) this.state.lists.push({ id: uid(), name: this.t.list, rows: [] });
    if (!this.state.lists.some(function (l) { return l.id === this.state.selected; }, this)) this.state.selected = this.state.lists[0].id;
    this.bind(); this.renderLists(); this.refresh();
  }
  Workspace.prototype.q = function (name) { return this.el.querySelector('[data-wl="' + name + '"]'); };
  Workspace.prototype.list = function () { return this.state.lists.find(function (l) { return l.id === this.state.selected; }, this); };
  Workspace.prototype.status = function (message, error) { var el = this.q('status'); el.textContent = message; el.dataset.state = error ? 'error' : 'info'; };
  Workspace.prototype.save = function () {
    if (!this.canSave) return;
    try { root.localStorage.setItem(this.storageKey, JSON.stringify(this.state)); } catch (_) { this.status(this.t.storage, true); }
  };
  Workspace.prototype.money = function (n) { return new Intl.NumberFormat(this.el.dataset.locale || 'it', { style: 'currency', currency: 'EUR' }).format(n); };
  Workspace.prototype.warning = function (code) {
    var it = { game_required: 'Seleziona il gioco in Modifica.', catalog_unavailable: 'Catalogo temporaneamente non disponibile.', fresh_data_unavailable: 'Non è stato possibile verificare alcune stampe su Shopify.', identity_required: 'Conferma la carta corretta tra i risultati.', identity_mismatch: 'Gli identificatori importati non corrispondono: verifica la stampa.', unknown_attributes: 'Alcune varianti non dichiarano tutte le caratteristiche richieste e sono escluse.', currency_unsupported: 'Sono supportati prezzi in EUR.', alternatives_require_confirmation: 'Altre stampe richiedono la tua conferma.', results_truncated: 'Risultati parziali: specifica meglio la carta o la stampa.', identity_lookup_unavailable: 'Identificatore Cardmarket non verificabile al momento.' };
    var en = { game_required: 'Choose a game using Edit.', catalog_unavailable: 'Catalog temporarily unavailable.', fresh_data_unavailable: 'Some Shopify printings could not be checked.', identity_required: 'Confirm the correct card from the results.', identity_mismatch: 'Imported identifiers do not match. Check the printing.', unknown_attributes: 'Variants with unknown requested attributes are excluded.', currency_unsupported: 'EUR prices are supported.', alternatives_require_confirmation: 'Other printings require confirmation.', results_truncated: 'Partial results: specify the card or printing more precisely.', identity_lookup_unavailable: 'Cannot verify this Cardmarket ID right now.' };
    return (this.el.dataset.locale === 'en' ? en : it)[code] || code;
  };
  Workspace.prototype.button = function (label, action) { var b = node('button', 'wl-button wl-button--quiet', label); b.type = 'button'; b.addEventListener('click', action); return b; };
  Workspace.prototype.renderLists = function () {
    var select = this.q('list-select'); select.replaceChildren();
    this.state.lists.forEach(function (l) { var option = node('option', '', l.name); option.value = l.id; select.append(option); });
    select.value = this.state.selected; this.q('list-name').value = this.list().name;
  };
  Workspace.prototype.bind = function () {
    var self = this;
    this.q('list-select').addEventListener('change', function () { if (self.busy) { this.value = self.state.selected; return; } self.state.selected = this.value; self.results.clear(); self.renderLists(); self.save(); self.refresh(); });
    this.q('list-name').addEventListener('change', function () { self.list().name = this.value.trim().slice(0, 80) || self.t.list; self.save(); self.renderLists(); });
    this.q('list-name').addEventListener('input', function () { self.list().name = this.value.trim().slice(0, 80) || self.t.list; var option = self.q('list-select').selectedOptions?.[0]; if (option) option.textContent = self.list().name; self.save(); });
    this.q('new-list').addEventListener('click', function () { if (self.busy || self.state.lists.length >= 100) return; var l = { id: uid(), name: self.t.list + ' ' + (self.state.lists.length + 1), rows: [] }; self.state.lists.push(l); self.state.selected = l.id; self.results.clear(); self.save(); self.renderLists(); self.refresh(); });
    this.q('search').addEventListener('input', function () { clearTimeout(self.searchTimer); self.searchAbort?.abort(); self.searchSeq = (self.searchSeq || 0) + 1; var seq = self.searchSeq; self.searchTimer = setTimeout(function () { self.search(seq); }, 300); });
    this.q('game').addEventListener('change', function () { self.search(++self.searchSeq); });
    this.q('search').addEventListener('keydown', function (e) {
      if (e.key === 'Escape') self.closeSearch();
      if (e.key === 'ArrowDown') { var b = self.q('search-results').querySelector('button'); if (b) { e.preventDefault(); b.focus(); } }
    });
    this.q('search-results').addEventListener('keydown', function (e) { var bs = Array.from(this.querySelectorAll('button')), i = bs.indexOf(document.activeElement); if (e.key === 'Escape') { self.closeSearch(); self.q('search').focus(); } if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); bs[(i + (e.key === 'ArrowDown' ? 1 : -1) + bs.length) % bs.length]?.focus(); } });
    this.q('import').addEventListener('click', function () { self.q('file').click(); });
    this.q('file').addEventListener('change', async function () {
      var file = this.files[0]; this.value = ''; if (!file) return;
      if (file.size > 2097152) { self.status(self.t.large, true); return; }
      try { self.previewImport(self.core.parseFile(await file.text(), file.name, { defaultGame: self.q('paste-game').value || self.q('game').value })); } catch (_) { self.status(self.t.readFile, true); }
    });
    this.q('paste-import').addEventListener('click', function () { self.previewImport(self.core.parseText(self.q('paste-text').value, { defaultGame: self.q('paste-game').value })); });
    this.q('import-cancel').addEventListener('click', function () { self.pendingImport = null; self.q('import-preview').hidden = true; });
    this.q('import-confirm').addEventListener('click', function () {
      if (self.busy || !self.pendingImport) return;
      if (self.list().rows.length + self.pendingImport.rows.length > 1000) { self.status(self.t.importLimit, true); return; }
      self.pendingImport.rows.forEach(function (r) { r.id = uid(); self.list().rows.push(r); });
      self.pendingImport = null; self.q('import-preview').hidden = true; self.save(); self.status(self.t.imported); self.refresh();
    });
    this.q('export').addEventListener('click', function () { var url = URL.createObjectURL(new Blob([self.core.exportCSV(self.list().rows)], { type: 'text/csv;charset=utf-8' })); var a = node('a'); a.href = url; a.download = self.t.filename + '.csv'; document.body.append(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 1000); });
    this.q('exact').addEventListener('change', function () { if (self.busy) return; self.list().rows.forEach(function (r) { r.exact = this.checked; }, this); self.save(); self.refresh(); });
    this.el.querySelectorAll('[data-wl="editor-cancel"]').forEach(function (b) { b.addEventListener('click', function () { self.q('editor').close(); }); });
    this.q('editor-form').addEventListener('submit', function (e) { e.preventDefault(); self.saveEditor(); });
    this.q('editor-form').addEventListener('input', function (e) { if (e.target.name) self.editedFields?.add(e.target.name); });
    this.q('editor-form').addEventListener('change', function (e) { if (e.target.name) self.editedFields?.add(e.target.name); });
    this.q('add-all').addEventListener('click', function () { self.addAll(); });
    var refresh = this.button(this.t.refresh, function () { self.refresh(true); }); refresh.dataset.wl = 'refresh'; this.q('summary').after(refresh);
    root.addEventListener('pageshow', function (e) { if (e.persisted) self.refresh(true); });
  };
  Workspace.prototype.closeSearch = function () { this.q('search-results').hidden = true; this.q('search').setAttribute('aria-expanded', 'false'); };
  Workspace.prototype.search = async function (seq) {
    var q = this.q('search').value.trim(), box = this.q('search-results');
    if (q.length < 2) { this.closeSearch(); return; }
    this.searchAbort?.abort(); this.searchAbort = new AbortController(); box.replaceChildren(node('li', 'wl-help', this.t.searching)); box.hidden = false; this.q('search').setAttribute('aria-expanded', 'true');
    try {
      var res = await this.client.search(q, this.q('game').value, { signal: this.searchAbort.signal });
      if (seq !== this.searchSeq) return;
      box.replaceChildren();
      res.items.forEach(function (product) { var li = node('li'); li.append(this.productButton(product, function () { this.addProduct(product); this.closeSearch(); this.q('search').value = ''; this.q('search').focus(); }.bind(this))); box.append(li); }, this);
      if (!res.items.length) box.append(node('li', 'wl-help', this.t.noResults));
      if (res.truncated) box.append(node('li', 'wl-help', this.t.truncation));
    } catch (e) { if (e.name !== 'AbortError' && seq === this.searchSeq) box.replaceChildren(node('li', 'wl-help', this.t.searchError)); }
  };
  Workspace.prototype.productButton = function (p, action, label) {
    var b = this.button('', action), text = node('span', '', p.canonicalCardName || p.commercialTitle || p.handle);
    text.append(node('small', '', [games[p.game], p.cardMetadata?.expansionName || p.cardMetadata?.expansionCode, p.cardMetadata?.collectorNumber].filter(Boolean).join(' · ')));
    if (label) text.append(node('small', '', label)); b.append(text); return b;
  };
  Workspace.prototype.bindProduct = function (r, p) {
    r.productId = p.productGid; r.handle = p.handle; r.name = p.canonicalCardName || p.commercialTitle; r.canonicalName = p.canonicalCardName; r.game = p.game;
    r.set = p.cardMetadata?.expansionCode || p.cardMetadata?.expansionName || ''; r.collectorNumber = p.cardMetadata?.collectorNumber || '';
    r.metaProductId = null; r.cardmarketId = null; r.confirmedProductIds = [];
    return this.core.normalizeRow(r, { id: r.id, editedFields: ['productId', 'cardmarketId', 'metaProductId', 'game', 'name', 'handle', 'canonicalName', 'confirmedProductIds', 'set', 'collectorNumber'] });
  };
  Workspace.prototype.addProduct = function (p) {
    if (this.busy) return;
    if (this.list().rows.length >= 1000) { this.status(this.t.importLimit, true); return; }
    var r = this.bindProduct({ id: uid(), quantity: 1, exact: this.q('exact').checked }, p); this.list().rows.push(r); this.save(); this.refresh();
  };
  Workspace.prototype.previewImport = function (parsed) {
    this.pendingImport = parsed;
    var content = this.q('import-preview-content'); content.replaceChildren(node('p', '', this.t.import + ': ' + parsed.rows.length + ' ' + this.t.importRows));
    (parsed.errors || []).concat(parsed.warnings || []).forEach(function (s) { content.append(node('p', 'wl-pill wl-pill--warning', typeof s === 'string' ? s : JSON.stringify(s))); });
    parsed.rows.forEach(function (r) {
      content.append(node('p', '', [r.quantity || '?', r.name || r.cardmarketId || r.metaProductId || '?', games[r.game] || '?', r.set, r.collectorNumber, r.languages.join('/'), r.minCondition].filter(Boolean).join(' · ')));
      var preferences = ['foil', 'signed', 'altered', 'firstEdition'].filter(function (k) { return r[k] !== null; }).map(function (k) { return k + ': ' + String(r[k]); });
      if (r.maxPrice !== null) preferences.push('Max ' + this.money(r.maxPrice)); preferences.push(this.t.exact + ': ' + String(r.exact)); if (r.notes) preferences.push(r.notes);
      content.append(node('p', 'wl-help', preferences.join(' · ')));
      (r.errors || []).concat(r.warnings || []).forEach(function (s) { content.append(node('small', 'wl-pill wl-pill--warning', s)); });
      if (Object.keys(r.extras || {}).some(function (k) { return !k.startsWith('_'); })) { var extra = node('details', 'wl-extras'); extra.append(node('summary', '', this.t.unknown), node('pre', '', JSON.stringify(r.extras, null, 2))); content.append(extra); }
    }, this);
    this.q('import-preview').hidden = false; this.q('import-confirm').disabled = !parsed.rows.length; this.q('import-preview').scrollIntoView({ block: 'nearest', behavior: 'auto' });
  };
  Workspace.prototype.readCart = async function () {
    var response = await fetch(this.rootUrl + 'cart.js', { credentials: 'same-origin', cache: 'no-store', headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error(this.t.cartReadError);
    var cart = await response.json(); if (!Array.isArray(cart.items)) throw new Error(this.t.cartReadError); return cart;
  };
  Workspace.prototype.refresh = async function (fresh) {
    if (this.busy) return;
    var epoch = ++this.epoch, rows = this.list().rows.slice(); this.pending = true; this.q('add-all').disabled = true; this.render();
    if (rows.length) this.status(this.t.loading);
    try { var cart = await this.readCart(); if (epoch !== this.epoch) return; this.cart = cart; this.cartKnown = true; } catch (_) { if (epoch === this.epoch) { this.cartKnown = false; this.status(this.t.cartReadError, true); } }
    var index = 0, self = this;
    async function worker() {
      while (index < rows.length && epoch === self.epoch) {
        var row = rows[index++];
        try { var result = await self.client.resolve(row, { fresh: !!fresh, scanLimit: self.scanLimits.get(row.id) || 24 }); if (epoch === self.epoch) self.results.set(row.id, result); }
        catch (_) { if (epoch === self.epoch) self.results.set(row.id, { offers: [], candidates: [], warnings: [self.t.error], resolved: false }); }
        if (epoch === self.epoch && rows.length > 1) self.status(self.t.loading + ' ' + Math.min(index, rows.length) + ' / ' + rows.length);
      }
    }
    await Promise.all([worker(), worker()]);
    if (epoch !== this.epoch) return;
    this.pending = false; this.render(); if (this.cartKnown) this.status(fresh ? this.t.fresh : '');
  };
  Workspace.prototype.render = function () {
    var self = this, rows = this.list().rows, box = this.q('rows'), opened = new Map();
    box.querySelectorAll('[data-row-id]').forEach(function (r) { opened.set(r.dataset.rowId, Array.from(r.querySelectorAll('details')).map(function (d) { return d.open; })); });
    var focused = document.activeElement, focusRow = focused?.closest?.('[data-row-id]'), focusValue = focusRow && focused.classList.contains('wl-quantity') ? focused.value : null;
    this.plan = allocate(rows, this.results, this.cart); box.replaceChildren();
    if (!rows.length) { var empty = node('div', 'wl-empty'); empty.append(node('h3', '', this.t.empty), node('p', '', this.t.emptyBody)); box.append(empty); }
    rows.forEach(function (r) {
      var res = self.results.get(r.id), p = self.plan.rows.get(r.id), row = node('article', 'wl-row'); row.dataset.rowId = r.id; row.setAttribute('aria-busy', String(!!self.pending));
      var first = res?.offers?.[0], image = node('img', 'wl-row__image'); image.alt = ''; image.loading = 'lazy'; image.width = 56; image.height = 78;
      var imageUrl = safeUrl(first?.image || '', true); if (imageUrl) { image.src = imageUrl; row.append(image); } else { var placeholder = node('span', 'wl-row__image', '✦'); placeholder.setAttribute('aria-hidden', 'true'); row.append(placeholder); }
      var content = node('div', 'wl-row__content'), title = node('h3', 'wl-row__title', r.name || ('ID ' + (r.cardmarketId || r.metaProductId || r.productId || '?')));
      content.append(title, node('p', 'wl-row__meta', [games[r.game] || self.t.noGame, r.set, r.collectorNumber, r.languages.join('/'), r.minCondition].filter(Boolean).join(' · ')));
      var flags = node('div', 'wl-row__flags'); flags.append(node('span', 'wl-pill' + (p.quantity + p.inCart >= p.requested && p.requested ? ' wl-pill--success' : ' wl-pill--warning'), (p.quantity + p.inCart) + ' / ' + p.requested + ' ' + self.t.cards));
      if (p.inCart) flags.append(node('span', 'wl-pill', p.inCart + ' ' + self.t.already));
      var physicalLabels = self.el.dataset.locale === 'en' ? { foil: ['Foil', 'Non foil'], signed: ['Signed', 'Unsigned'], altered: ['Altered', 'Unaltered'], firstEdition: ['First edition', 'Not first edition'] } : { foil: ['Foil', 'Non foil'], signed: ['Firmata', 'Non firmata'], altered: ['Alterata', 'Non alterata'], firstEdition: ['Prima edizione', 'Non prima edizione'] };
      ['foil', 'signed', 'altered', 'firstEdition'].forEach(function (k) { if (r[k] !== null && r[k] !== undefined) flags.append(node('span', 'wl-pill', physicalLabels[k][r[k] ? 0 : 1])); });
      if (r.maxPrice !== null) flags.append(node('span', 'wl-pill', 'Max ' + self.money(r.maxPrice)));
      content.append(flags); if (r.notes) content.append(node('p', 'wl-help', r.notes));
      var errors = (r.errors || []).concat(r.warnings || [], (res?.warnings || []).map(function (w) { return self.warning(w); }));
      errors.forEach(function (e) { content.append(node('p', 'wl-help wl-warning', e)); });
      if (!res) content.append(node('p', 'wl-help', self.t.loading));
      else if (!res.offers?.length) content.append(node('p', 'wl-help', res.resolved ? self.t.unavailable : self.t.pending));
      if (res?.truncated) content.append(node('p', 'wl-help', self.t.truncation));
      row.append(content);
      var actions = node('div', 'wl-row__actions'), qty = node('input', 'wl-quantity'); qty.type = 'number'; qty.min = '1'; qty.max = '999'; qty.step = '1'; qty.value = r.quantity || ''; qty.setAttribute('aria-label', self.t.quantity + ': ' + r.name); qty.disabled = self.busy;
      qty.addEventListener('change', function () { if (!/^[1-9]\d{0,2}$/.test(qty.value)) { qty.value = r.quantity || ''; return; } r.quantity = Number(qty.value); self.save(); self.render(); });
      var edit = self.button(self.t.edit, function () { self.edit(r.id); }), remove = self.button(self.t.remove, function () { self.list().rows = self.list().rows.filter(function (v) { return v.id !== r.id; }); self.save(); self.refresh(); }); edit.disabled = remove.disabled = self.busy;
      actions.append(qty, edit, remove);
      var exactLabel = node('label', 'wl-exact'), check = node('input'); check.type = 'checkbox'; check.checked = r.exact; check.disabled = self.busy; check.addEventListener('change', function () { r.exact = check.checked; self.save(); self.refresh(); }); exactLabel.append(check, node('span', '', self.t.exact)); actions.append(exactLabel); row.append(actions);
      var detail = node('div', 'wl-row__offers');
      if (res?.offers?.length) {
        p.offers.forEach(function (o) { detail.append(self.offerNode(o, self.t.selected + ': ' + o.quantity)); });
        var details = node('details'), summary = node('summary', '', self.t.offers + ' (' + res.offers.length + ')'); details.append(summary);
        res.offers.forEach(function (o) { details.append(self.offerNode(o, o.stock + ' ' + self.t.stock)); }); detail.append(details);
      }
      var choices = (res?.candidates || []).filter(function (candidate) { return candidate.productGid !== r.productId && !(r.confirmedProductIds || []).includes(candidate.productGid) && !(res.offers || []).some(function (o) { return o.productId === candidate.productGid; }); });
      if (choices.length && (!res.resolved || !r.exact)) {
        var candidates = node('details', 'wl-candidates'), cs = node('summary', '', self.t.verify + ' (' + choices.length + ')'); candidates.append(cs, node('p', 'wl-help', self.t.match));
        choices.forEach(function (candidate) { var b = self.productButton(candidate, function () {
          if (self.busy) return;
          if (r.productId && !r.exact) { r.confirmedProductIds = Array.from(new Set((r.confirmedProductIds || []).concat(candidate.productGid))); }
          else { var normalized = self.bindProduct(r, candidate); Object.assign(r, normalized); }
          self.save(); self.refresh();
        }, r.productId && !r.exact ? self.t.alternative : self.t.choose); b.disabled = self.busy; candidates.append(b); }); detail.append(candidates);
      }
      if (res?.truncated && (self.scanLimits.get(r.id) || 24) < 2000) {
        var more = self.button(self.el.dataset.locale === 'en' ? 'Show more printings' : 'Mostra altre stampe', function () { self.scanLimits.set(r.id, Math.min(2000, (self.scanLimits.get(r.id) || 24) + 24)); self.refresh(true); });
        more.disabled = self.busy || self.pending; detail.append(more);
      }
      if (detail.childNodes.length) row.append(detail); box.append(row);
      var previous = opened.get(r.id); if (previous) row.querySelectorAll('details').forEach(function (d, i) { d.open = !!previous[i]; });
      if (focusValue !== null && focusRow.dataset.rowId === r.id && !self.busy) { qty.value = focusValue; qty.focus({ preventScroll: true }); }
    });
    var exact = this.q('exact'); exact.checked = !rows.some(function (r) { return !r.exact; }); exact.indeterminate = rows.some(function (r) { return r.exact; }) && rows.some(function (r) { return !r.exact; }); exact.disabled = this.busy;
    var summary = this.q('summary'); summary.replaceChildren(node('span', '', this.t.available), node('strong', '', this.plan.quantity + ' / ' + this.plan.requested + ' ' + this.t.cards), node('p', '', this.t.euro + ': ' + this.money(this.plan.total)));
    if (this.plan.inCart) summary.append(node('p', 'wl-help', this.plan.inCart + ' ' + this.t.already));
    var missing = this.plan.requested - this.plan.quantity - this.plan.inCart; if (missing) summary.append(node('p', 'wl-help', missing + ' ' + this.t.missing));
    this.q('add-all').disabled = this.pending || this.busy || !this.cartKnown || this.cart.currency !== 'EUR' || !this.plan.quantity;
    if (this.cartKnown && this.cart.currency !== 'EUR') this.status(this.t.currency, true);
    ['new-list', 'list-select', 'import-confirm', 'refresh'].forEach(function (key) { var control = self.q(key); if (control) control.disabled = self.busy || (key === 'import-confirm' && !self.pendingImport?.rows?.length); });
  };
  Workspace.prototype.offerNode = function (o, label) {
    var box = node('div', 'wl-offer'), text = node('span', '', [o.set, o.collectorNumber, o.language, o.condition, o.foil === true ? 'Foil' : o.foil === false ? 'Non foil' : ''].filter(Boolean).join(' · '));
    var url = safeUrl(o.url || '', false); if (url) { var a = node('a', '', o.name || 'Carta'); a.href = url; text.prepend(a, document.createTextNode(' · ')); }
    box.append(text, node('span', 'wl-pill' + (!o.exact ? ' wl-pill--warning' : ''), label + (!o.exact ? ' · alternativa' : '')), node('strong', '', this.money(o.price))); return box;
  };
  Workspace.prototype.edit = function (id) {
    if (this.busy) return; var r = this.list().rows.find(function (v) { return v.id === id; }); if (!r) return;
    this.editing = id; this.editedFields = new Set(); var form = this.q('editor-form');
    form.querySelector('[data-wl="editor-errors"]')?.remove();
    if (r.errors?.length) { var error = node('p', 'wl-warning'); error.dataset.wl = 'editor-errors'; error.textContent = r.errors.join(' ') + ' ' + this.t.invalid; form.querySelector('.wl-editor__grid').prepend(error); }
    ['name', 'game', 'quantity', 'set', 'collectorNumber', 'minCondition', 'maxPrice', 'notes'].forEach(function (key) { form.elements[key].value = r.extras?._invalidFields?.[key] ?? r[key] ?? ''; });
    form.elements.languages.value = r.extras?._invalidFields?.languages ?? r.languages.join(', ');
    ['foil', 'signed', 'altered', 'firstEdition'].forEach(function (key) { form.elements[key].value = r[key] === null ? 'any' : r[key] ? 'yes' : 'no'; });
    form.elements.exact.checked = r.exact; this.q('editor').showModal(); form.elements.name.focus();
  };
  Workspace.prototype.saveEditor = function () {
    if (this.busy) return;
    var r = this.list().rows.find(function (v) { return v.id === this.editing; }, this); if (!r) return;
    var form = this.q('editor-form'), input = Object.assign({}, r), changed = false;
    ['name', 'game', 'quantity', 'set', 'collectorNumber', 'languages', 'minCondition', 'foil', 'signed', 'altered', 'firstEdition', 'maxPrice', 'notes'].forEach(function (key) { input[key] = form.elements[key].value; if (['name', 'game', 'set', 'collectorNumber'].includes(key) && String(r[key] || '') !== input[key]) changed = true; });
    input.exact = form.elements.exact.checked; input.extras = Object.assign({}, r.extras);
    // Browser number/select controls may display an invalid imported value as blank.
    // Keep the original blocking preference unless that control was explicitly edited.
    Object.keys(r.extras?._invalidFields || {}).forEach(function (key) { if (!this.editedFields.has(key)) input[key] = r.extras._invalidFields[key]; }, this);
    if (changed) { input.productId = null; input.cardmarketId = null; input.metaProductId = null; input.handle = ''; input.canonicalName = ''; input.confirmedProductIds = []; }
    var normalized = this.core.normalizeRow(input, { id: r.id, editedFields: Array.from(this.editedFields) }); Object.assign(r, normalized); this.save(); this.q('editor').close(); this.status(normalized.needsReview ? this.t.invalid : this.t.saved, normalized.needsReview); this.refresh(true);
  };
  Workspace.prototype.addAll = async function () {
    if (this.busy || this.pending || !this.cartKnown || !this.plan.quantity) return;
    var shown = fingerprint(this.plan), rows = this.list().rows.slice(); this.busy = true; ++this.epoch; this.render(); this.status(this.t.checking);
    var before, attempted = false, lines = [], confirmed = 0;
    try {
      before = await this.readCart(); this.cart = before;
      if (before.currency !== 'EUR') throw new Error(this.t.currency);
      for (var row of rows) this.results.set(row.id, await this.client.resolve(row, { fresh: true, scanLimit: this.scanLimits.get(row.id) || 24 }));
      before = await this.readCart(); this.cart = before;
      if (before.currency !== 'EUR') throw new Error(this.t.currency);
      this.plan = allocate(rows, this.results, before);
      if (fingerprint(this.plan) !== shown) { this.status(this.t.changed); return; }
      if (!this.plan.quantity) { this.status(this.t.noItems); return; }
      lines = this.plan.lines; attempted = true;
      var response = await fetch(this.rootUrl + 'cart/add.js', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' }, body: JSON.stringify({ items: lines.map(function (l) { return { id: l.id, quantity: l.quantity }; }) }) });
      // Reconcile even on 422 or an interrupted response; never retry an uncertain POST.
      var after = await this.readCart(); this.cart = after; this.cartKnown = true; confirmed = cartDiff(before, after, lines);
      this.status(confirmed === this.plan.quantity && response.ok ? confirmed + ' ' + this.t.added : confirmed + ' ' + this.t.added + ' ' + this.t.partial, confirmed !== this.plan.quantity);
      document.dispatchEvent(new CustomEvent('nla:wishlist-cart-updated', { detail: { cart: after } }));
      var count = document.querySelector('#cart-icon-bubble .cart-count-bubble'); if (count) count.querySelectorAll('span').forEach(function (span) { span.textContent = String(after.item_count); });
    } catch (e) {
      if (attempted) {
        try { var recovered = await this.readCart(); this.cart = recovered; confirmed = cartDiff(before, recovered, lines); this.cartKnown = true; this.status(confirmed + ' ' + this.t.added + ' ' + this.t.cartError, true); }
        catch (_) { this.cartKnown = false; this.status(this.t.cartError, true); }
      } else { this.status(e.message || this.t.cartReadError, true); }
    } finally { this.busy = false; this.render(); }
  };
  return { mount: mount, allocate: allocate, fingerprint: fingerprint, cartDiff: cartDiff };
}));
