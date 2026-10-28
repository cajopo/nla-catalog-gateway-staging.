import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';

const [baseline, runtime] = process.argv.slice(2);
assert(baseline && runtime, 'Usage: node tests/theme-footer-games.mjs <private-clone-source> <liquidjs-runtime>');
const root = fileURLToPath(new URL('../', import.meta.url));
const original = await readFile(join(baseline, 'sections/nla-footer.liquid'));
assert.equal(createHash('sha256').update(original).digest('hex'),
  '3384fbd9c2cc8be5802f9fc8cdee270d77a7d70ba0f65a82a0bcfc87c8c9d2a0', 'Footer baseline drift');
const candidate = await mkdtemp(join(tmpdir(), 'nla-footer-135-'));
await cp(baseline, candidate, { recursive: true });
const patch = join(candidate, 'footer.patch');
await writeFile(patch, (await readFile(join(root, 'theme/patches/footer-six-games-20261028.patch'), 'utf8')).replaceAll('\r\n', '\n'));
const apply = args => execFileSync('git', ['-c', 'core.autocrlf=false', 'apply', ...args, patch], { cwd: candidate, stdio: 'pipe' });
apply(['--check']); apply([]); apply(['--reverse', '--check']);
const source = await readFile(join(candidate, 'sections/nla-footer.liquid'), 'utf8');
const insertion = "        {% render 'nla-new-game-footer-links', menu: section.settings.menu %}\n";
assert.equal(source.split(insertion).length, 2);
assert.equal(source.replace(insertion, ''), original.toString('utf8'), 'Only the render call may change the footer');
await mkdir(join(candidate, 'snippets'), { recursive: true });
await writeFile(join(candidate, 'snippets/nla-new-game-footer-links.liquid'),
  (await readFile(join(root, 'theme/snippets/nla-new-game-footer-links.liquid'), 'utf8')).replaceAll('\r\n', '\n'));
const { Liquid } = createRequire(join(runtime, 'package.json'))('liquidjs');
const baseLinks = [['Magic', '/collections/singole-magic'], ['Pokémon', '/collections/singole-pokemon'],
  ['One Piece', '/collections/singole-one-piece'], ['Yu-Gi-Oh!', '/collections/yugioh'],
  ['Eventi', '/#eventi'], ['Vendi carte', '/#vendi'], ['Il negozio', '/#negozio']]
  .map(([title, url]) => ({ title, url }));
const decode = value => value.replaceAll('&quot;', '"').replaceAll('&lt;', '<').replaceAll('&gt;', '>').replace(/&#(\d+);/g, (_, number) => String.fromCodePoint(Number(number))).replaceAll('&amp;', '&');
function linksOf(html) {
  const nav = html.match(/<nav\b[^>]*>([\s\S]*?)<\/nav>/)[1];
  return [...nav.matchAll(/<a href="([^"]*)">([^<]*)<\/a>/g)].map(([, url, title]) => ({ title: decode(title), url: decode(url) }));
}
let passed = 1;
const scenarios = [
  { name: 'four games', extra: [], expected: ['riftbound', 'lorcana'] },
  { name: 'existing Riftbound collection', extra: [{ title: 'Riftbound', url: '/collections/riftbound' }], expected: ['lorcana'] },
  { name: 'existing branded Lorcana collection', extra: [{ title: 'Disney Lorcana', url: '/collections/lorcana' }], expected: ['riftbound'] },
  { name: 'existing unbranded Lorcana collection', extra: [{ title: 'Lorcana', url: '/collections/lorcana' }], expected: ['riftbound'] },
  { name: 'case and outer whitespace', extra: [{ title: '  DISNEY LORCANA  ', url: '/collections/disney' }, { title: 'RIFTBOUND', url: '/collections/rift' }], expected: [] },
  { name: 'both existing with localized labels and query order', extra: [
    { title: 'Il Rift', url: '/it/search?game=riftbound&view=nla-catalog&family=all' },
    { title: 'Carte Disney', url: '/it/search?view=nla-catalog&family=single&game=lorcana#cards' }], expected: [] },
  { name: 'query substrings are different games', extra: [
    { title: 'Other', url: '/search?game=lorcana-other&othergame=riftbound' }], expected: ['riftbound', 'lorcana'] },
  { name: 'game word in search query is not a game selector', extra: [
    { title: 'Other', url: '/search?q=game%3Dlorcana&game=magic' }], expected: ['riftbound', 'lorcana'] },
  { name: 'existing labels remain escaped', extra: [{ title: '<script>alert("menu")</script>', url: '/pages/example' }], expected: ['riftbound', 'lorcana'] },
];
for (const language of ['it', 'en']) {
  const routes = { search_url: language === 'it' ? '/it/search' : '/search' };
  const locale = JSON.parse(await readFile(join(root, 'theme/locales', language === 'it' ? 'it.json' : 'en.default.json'), 'utf8'));
  const engine = new Liquid({ root: join(candidate, 'snippets'), extname: '.liquid', globals: { routes }, strictFilters: true });
  engine.registerFilter('t', key => { const value = key.split('.').reduce((v, part) => v?.[part], locale); assert.equal(typeof value, 'string'); return value; });
  for (const name of ['doc', 'stylesheet', 'schema']) engine.registerTag(name, {
    parse(_token, tokens) { while (tokens.length && tokens.shift().name !== `end${name}`) {} }, render() { return ''; },
  });
  async function render(links) {
    return engine.parseAndRender(source, { shop: { name: 'Arena fixture' }, routes,
      section: { settings: { tagline: 'Carte e community', menu_label: 'Navigazione', search_label: 'Cerca', menu: { links } } } });
  }
  for (const scenario of scenarios) {
    const existing = [...baseLinks, ...scenario.extra], html = await render(existing);
    const links = linksOf(html);
    assert.deepEqual(links.slice(0, existing.length), existing, `${language}: existing links preserved`);
    assert.deepEqual(links.slice(existing.length), scenario.expected.map(game => ({ title: locale.nla_catalog[game],
      url: `${routes.search_url}?view=nla-catalog&game=${game}&family=all` })), `${language}: ${scenario.name}`);
    assert(!html.includes('<script>'));
    passed++; console.log(`PASS ${language}: ${scenario.name}`);
  }
  const empty = linksOf(await render([]));
  assert.equal(empty.length, 2); passed++;
  const html = await render(baseLinks), styles = source.match(/{% stylesheet %}([\s\S]*?){% endstylesheet %}/)[1];
  await writeFile(join(candidate, `footer-${language}.html`), `<!doctype html><html lang="${language}"><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>:root{--nla-white:#fff;--nla-silver:#aaa;--nla-gradient:linear-gradient(90deg,#6a5aff,#dd5cff)}html{font-size:62.5%}body{margin:0;font:16px Arial;background:#090a0d}*,*::before,*::after{box-sizing:border-box}${styles}</style></head><body>${html}</body></html>`);
}
console.log(`PASS ${passed}/21 guarded footer patch and Liquid consumer cases`);
console.log(`CANDIDATE=${candidate}`);
