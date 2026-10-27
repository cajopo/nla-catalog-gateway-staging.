import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { createRequire } from 'node:module';

export async function arenaFixture(theme, runtime) {
  const require = createRequire(join(runtime, 'package.json'));
  const { Liquid } = require('liquidjs');
  const locale = JSON.parse((await readFile(join(theme, 'locales/it.json'), 'utf8')).replace(/^\s*\/\*[\s\S]*?\*\/\s*/, ''));
  const routes = { search_url: '/it/search', root_url: '/it/', cart_url: '/it/cart', account_url: '/it/account' };
  const engine = new Liquid({ root: join(theme, 'snippets'), extname: '.liquid', globals: { routes }, strictFilters: true });
  engine.registerFilter('t', key => {
    const value = key.split('.').reduce((current, part) => current?.[part], locale);
    assert.equal(typeof value, 'string', `Missing translation: ${key}`); return value;
  });
  engine.registerFilter('asset_url', name => '/assets/' + name);
  engine.registerFilter('stylesheet_tag', url => `<link rel='stylesheet' href='${url}'>`);
  engine.registerFilter('json', JSON.stringify);
  for (const name of ['doc', 'stylesheet', 'javascript', 'schema']) engine.registerTag(name, {
    parse(_token, tokens) { while (tokens.length && tokens.shift().name !== `end${name}`) {} },
    render() { return ''; },
  });
  const headerSource = await readFile(join(theme, 'sections/nla-header.liquid'), 'utf8');
  const catalogSource = await readFile(join(theme, 'snippets/nla-catalog-search.liquid'), 'utf8');
  const styleOf = source => source.match(/{% stylesheet %}([\s\S]*?){% endstylesheet %}/)[1];
  const script = catalogSource.match(/{% javascript %}([\s\S]*?){% endjavascript %}/)[1];
  const links = [['Magic', '/collections/singole-magic'], ['Pokémon', '/collections/singole-pokemon'],
    ['One Piece', '/collections/singole-one-piece'], ['Yu-Gi-Oh!', '/collections/yugioh'],
    ['Eventi', '/#eventi'], ['Vendi carte', '/#vendi'], ['Il negozio', '/#negozio']]
    .map(([title, url]) => ({ title, url, links: [] }));
  const context = { routes, shop: { name: 'Arena fixture', currency: 'EUR', customer_accounts_enabled: false },
    cart: { item_count: 0 }, request: { locale: { iso_code: 'it' } }, section: { id: 'fixture',
      settings: { menu: { links }, menu_label: 'Navigazione principale', cart_label: 'Carrello' } } };
  const header = await engine.parseAndRender(headerSource, context);
  const wishlist = await engine.renderFile('nla-wishlist', { ...context, instance_id: 'fixture' });
  return `<!doctype html><html lang='it'><head><meta name='viewport' content='width=device-width,initial-scale=1'>
    <style>:root{--font-body-family:Arial,sans-serif;--font-heading-family:Arial,sans-serif}html{font-size:62.5%}body{margin:0}*,*::before,*::after{box-sizing:border-box}${styleOf(headerSource)}${styleOf(catalogSource)}</style>
    <link rel='stylesheet' href='/assets/nla-arena.css'><link rel='stylesheet' href='/assets/nla-arena-native.css'></head>
    <body class='nla-arena'>${header}<main>${wishlist}</main><script>${script}</script></body></html>`;
}
