(() => {
  'use strict';

  const selectors = {
    form: '[data-nla-search-form]', game: '[data-nla-game]', query: '[data-nla-query]',
    suggestions: '[data-nla-suggestions]', grid: '[data-nla-grid]', status: '[data-nla-status]',
    loadMore: '[data-nla-load-more]', set: '[data-nla-set]', language: '[data-nla-language]',
    rarity: '[data-nla-rarity]', availability: '[data-nla-availability]', clear: '[data-nla-clear]'
  };

  class NlaCatalog {
    constructor(root) {
      this.root = root;
      this.apiBase = (root.dataset.apiBase || '/apps/nla-catalog').replace(/\/$/, '');
      this.pageSize = Math.max(12, Math.min(Number(root.dataset.pageSize || 24), 60));
      this.el = Object.fromEntries(Object.entries(selectors).map(([key, selector]) => [key, root.querySelector(selector)]));
      this.state = this.readState();
      this.datasetVersion = null;
      this.loadedCount = 0;
      this.loading = false;
      this.listAbort = null;
      this.suggestAbort = null;
      this.suggestTimer = null;
    }

    init() {
      this.applyState();
      this.bind();
      this.refresh(false);
    }

    readState() {
      const params = new URLSearchParams(window.location.search);
      return {
        game: params.get('game') || this.root.dataset.defaultGame || 'magic',
        q: params.get('q') || '', set: params.get('set') || '',
        language: params.get('language') || '', rarity: params.get('rarity') || '',
        availability: params.get('availability') || '', cursor: null
      };
    }

    applyState() {
      this.el.game.value = this.state.game;
      this.el.query.value = this.state.q;
      this.el.availability.value = this.state.availability;
    }

    bind() {
      this.el.form.addEventListener('submit', (event) => {
        event.preventDefault();
        this.state.q = this.el.query.value.trim();
        this.reset();
        this.closeSuggestions();
        this.refresh(true);
      });
      this.el.game.addEventListener('change', () => {
        this.state.game = this.el.game.value;
        this.state.set = '';
        this.state.language = '';
        this.state.rarity = '';
        this.reset();
        this.refresh(true);
      });
      this.el.query.addEventListener('input', () => {
        window.clearTimeout(this.suggestTimer);
        const value = this.el.query.value.trim();
        if (value.length < 2) return this.closeSuggestions();
        this.suggestTimer = window.setTimeout(() => this.loadSuggestions(value), 220);
      });
      this.el.query.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') this.closeSuggestions();
      });
      document.addEventListener('click', (event) => {
        if (!this.root.contains(event.target)) this.closeSuggestions();
      });
      this.el.loadMore.addEventListener('click', () => this.loadItems(true));
      for (const key of ['set', 'language', 'rarity', 'availability']) {
        this.el[key].addEventListener('change', () => {
          this.state[key] = this.el[key].value;
          this.reset();
          this.updateHistory(true);
          this.loadItems(false);
        });
      }
      this.el.clear.addEventListener('click', () => {
        for (const key of ['set', 'language', 'rarity', 'availability']) {
          this.state[key] = '';
          this.el[key].value = '';
        }
        this.reset();
        this.updateHistory(true);
        this.loadItems(false);
      });
      window.addEventListener('popstate', () => {
        this.state = this.readState();
        this.applyState();
        this.reset();
        this.refresh(false);
      });
    }

    reset() {
      this.state.cursor = null;
      this.loadedCount = 0;
      this.datasetVersion = null;
    }

    async refresh(pushHistory) {
      this.updateHistory(pushHistory);
      await Promise.all([this.loadItems(false), this.loadFacets()]);
    }

    updateHistory(push) {
      const url = new URL(window.location.href);
      for (const key of ['game', 'q', 'set', 'language', 'rarity', 'availability']) {
        const value = this.state[key];
        if (value) url.searchParams.set(key, value);
        else url.searchParams.delete(key);
      }
      url.searchParams.delete('cursor');
      window.history[push ? 'pushState' : 'replaceState']({}, '', url);
    }

    endpoint(path, params = {}) {
      const base = /^https?:\/\//i.test(this.apiBase) ? this.apiBase : `${window.location.origin}${this.apiBase}`;
      const url = new URL(`${base}/${path}`);
      for (const [key, value] of Object.entries(params)) {
        if (value !== null && value !== undefined && value !== '') url.searchParams.set(key, String(value));
      }
      return url;
    }

    async fetchJson(path, params, signal) {
      const response = await fetch(this.endpoint(path, params), {
        method: 'GET', credentials: 'same-origin', headers: { Accept: 'application/json' }, signal
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `Errore catalogo (${response.status})`);
      }
      return response.json();
    }

    params(includeCursor) {
      return {
        game: this.state.game, q: this.state.q || null, limit: this.pageSize,
        cursor: includeCursor ? this.state.cursor : null, set: this.state.set || null,
        language: this.state.language || null, rarity: this.state.rarity || null,
        availability: this.state.availability || null
      };
    }

    async loadItems(append) {
      if (this.loading || (append && !this.state.cursor)) return;
      this.loading = true;
      this.setBusy(true);
      if (!append && this.listAbort) this.listAbort.abort();
      this.listAbort = new AbortController();
      const mode = this.state.q.length >= 2 ? 'search' : 'browse';
      const params = this.params(append);
      if (mode === 'browse') delete params.q;
      try {
        const payload = await this.fetchJson(mode, params, this.listAbort.signal);
        this.assertPayload(payload);
        if (append && this.datasetVersion && payload.datasetVersion !== this.datasetVersion) {
          this.reset();
          return this.loadItems(false);
        }
        this.datasetVersion = payload.datasetVersion;
        this.state.cursor = payload.pageInfo?.endCursor || null;
        if (!append) {
          this.el.grid.replaceChildren();
          this.loadedCount = 0;
        }
        this.renderItems(payload.items || []);
        this.loadedCount += (payload.items || []).length;
        this.el.loadMore.hidden = !payload.pageInfo?.hasNextPage;
        const exact = mode === 'search' ? ` · ${payload.exactCount || 0} corrispondenze esatte` : '';
        this.el.status.textContent = `${this.loadedCount} stampe caricate${exact}`;
        this.el.status.classList.remove('nla-catalog__error');
      } catch (error) {
        if (error.name !== 'AbortError') this.renderError(error.message);
      } finally {
        this.loading = false;
        this.setBusy(false);
      }
    }

    assertPayload(payload) {
      if (!payload || !Array.isArray(payload.items)) throw new Error('Risposta catalogo non valida');
      if (payload.items.some((item) => item.game !== this.state.game)) {
        throw new Error('Risposta bloccata: prodotto appartenente a un altro gioco');
      }
    }

    renderItems(items) {
      if (!items.length && this.loadedCount === 0) {
        const empty = document.createElement('p');
        empty.className = 'nla-catalog__empty';
        empty.textContent = 'Nessuna stampa trovata con i criteri selezionati.';
        this.el.grid.append(empty);
        return;
      }
      const fragment = document.createDocumentFragment();
      for (const item of items) fragment.append(this.card(item));
      this.el.grid.append(fragment);
    }

    card(item) {
      const card = document.createElement('article');
      card.className = 'nla-catalog-card';
      const media = document.createElement('div');
      media.className = 'nla-catalog-card__media';
      if (item.imageUrl) {
        const image = document.createElement('img');
        image.src = item.imageUrl;
        image.alt = `${item.canonicalName}${item.setName ? ` — ${item.setName}` : ''}`;
        image.loading = 'lazy';
        image.decoding = 'async';
        media.append(image);
      }
      const badge = document.createElement('span');
      badge.className = 'nla-catalog-card__badge';
      badge.textContent = item.availabilityLabel;
      media.append(badge);
      const body = document.createElement('div');
      body.className = 'nla-catalog-card__body';
      const title = document.createElement('h2');
      title.className = 'nla-catalog-card__title';
      title.textContent = item.canonicalName;
      body.append(title);
      if (item.setName) {
        const set = document.createElement('p');
        set.className = 'nla-catalog-card__set';
        set.textContent = item.setName;
        body.append(set);
      }
      const details = [item.setCode, item.collectorNumber, item.rarity, item.language].filter(Boolean).join(' · ');
      if (details) {
        const meta = document.createElement('p');
        meta.className = 'nla-catalog-card__meta';
        meta.textContent = details;
        body.append(meta);
      }
      if (item.displayPrice) {
        const price = document.createElement('p');
        price.className = 'nla-catalog-card__price';
        price.textContent = item.displayPrice;
        body.append(price);
      }
      const link = document.createElement('a');
      link.className = `button ${item.available ? '' : 'button--secondary'} nla-catalog-card__link`;
      link.href = item.url;
      link.textContent = item.available ? 'Acquista' : 'Visualizza stampa';
      body.append(link);
      card.append(media, body);
      return card;
    }

    renderError(message) {
      this.el.loadMore.hidden = true;
      this.el.status.textContent = `Catalogo temporaneamente non disponibile: ${message}`;
      this.el.status.classList.add('nla-catalog__error');
      if (!this.loadedCount) this.el.grid.replaceChildren();
    }

    setBusy(value) {
      this.el.grid.setAttribute('aria-busy', String(value));
      this.el.loadMore.disabled = value;
    }

    async loadSuggestions(query) {
      if (this.suggestAbort) this.suggestAbort.abort();
      this.suggestAbort = new AbortController();
      try {
        const payload = await this.fetchJson('suggest', { game: this.el.game.value, q: query, limit: 8 }, this.suggestAbort.signal);
        if (this.el.query.value.trim() !== query) return;
        this.renderSuggestions(payload.items || []);
      } catch (error) {
        if (error.name !== 'AbortError') this.closeSuggestions();
      }
    }

    renderSuggestions(items) {
      this.el.suggestions.replaceChildren();
      if (!items.length) return this.closeSuggestions();
      const fragment = document.createDocumentFragment();
      for (const item of items) {
        if (item.game !== this.el.game.value) continue;
        const row = document.createElement('li');
        row.setAttribute('role', 'option');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'nla-catalog__suggestion-button';
        if (item.imageUrl) {
          const image = document.createElement('img');
          image.src = item.imageUrl;
          image.alt = '';
          image.loading = 'lazy';
          button.append(image);
        } else button.append(document.createElement('span'));
        const text = document.createElement('span');
        const name = document.createElement('strong');
        name.textContent = item.canonicalName;
        const meta = document.createElement('span');
        meta.className = 'nla-catalog__suggestion-meta';
        meta.textContent = `${item.printCount} stampe · ${item.availablePrintCount} disponibili`;
        text.append(name, meta);
        button.append(text);
        button.addEventListener('click', () => {
          this.el.query.value = item.canonicalName;
          this.state.q = item.canonicalName;
          this.reset();
          this.closeSuggestions();
          this.refresh(true);
        });
        row.append(button);
        fragment.append(row);
      }
      this.el.suggestions.append(fragment);
      this.el.suggestions.hidden = false;
    }

    closeSuggestions() {
      if (this.suggestAbort) this.suggestAbort.abort();
      this.el.suggestions.hidden = true;
      this.el.suggestions.replaceChildren();
    }

    async loadFacets() {
      try {
        const payload = await this.fetchJson('facets', { game: this.state.game, q: this.state.q || null });
        if (payload.game !== this.state.game) return;
        this.fillSelect(this.el.set, payload.sets || [], 'Tutte le espansioni', this.state.set, 'set');
        this.fillSelect(this.el.language, payload.languages || [], 'Tutte le lingue', this.state.language, 'language');
        this.fillSelect(this.el.rarity, payload.rarities || [], 'Tutte le rarità', this.state.rarity, 'rarity');
      } catch (_) { /* Search remains usable if facets fail. */ }
    }

    fillSelect(select, values, firstLabel, selected, key) {
      const first = document.createElement('option');
      first.value = '';
      first.textContent = firstLabel;
      const options = [first];
      for (const item of values) {
        const option = document.createElement('option');
        option.value = item.value;
        option.textContent = `${item.value} (${item.count})`;
        options.push(option);
      }
      select.replaceChildren(...options);
      select.value = selected;
      if (select.value !== selected) {
        select.value = '';
        this.state[key] = '';
      }
    }
  }

  const start = () => {
    document.querySelectorAll('[data-nla-catalog]').forEach((root) => {
      if (root.dataset.nlaInitialized === 'true') return;
      root.dataset.nlaInitialized = 'true';
      new NlaCatalog(root).init();
    });
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
  document.addEventListener('shopify:section:load', start);
})();
