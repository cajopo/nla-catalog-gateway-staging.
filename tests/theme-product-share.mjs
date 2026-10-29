import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { cp, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const [baseline] = process.argv.slice(2);
assert(baseline, 'Usage: node tests/theme-product-share.mjs <private-clone-source>');
const root = fileURLToPath(new URL('../', import.meta.url));
const original = await readFile(join(baseline, 'layout/theme.liquid'));
assert.equal(createHash('sha256').update(original).digest('hex'),
  'c1022da9f9a646708c9261b778e5233a1aae14d94e289bd88177208b00df0064', 'Layout baseline drift');
const candidate = await mkdtemp(join(tmpdir(), 'nla-share-135-'));
await cp(baseline, candidate, { recursive: true });
const patch = join(candidate, 'share.patch');
await writeFile(patch, (await readFile(join(root, 'theme/patches/product-share-dependency-20261029.patch'), 'utf8')).replaceAll('\r\n', '\n'));
const apply = args => execFileSync('git', ['-c', 'core.autocrlf=false', 'apply', ...args, patch], { cwd: candidate, stdio: 'pipe' });
apply(['--check']); apply([]); apply(['--reverse', '--check']);
const layout = await readFile(join(candidate, 'layout/theme.liquid'), 'utf8');
const insertion = "    <script src=\"{{ 'details-disclosure.js' | asset_url }}\" defer=\"defer\"></script>\n";
assert.equal(layout.split(insertion).length, 2);
assert.equal(layout.replace(insertion, ''), original.toString('utf8'), 'Only the dependency script may change');
assert(layout.indexOf("'global.js'") < layout.indexOf("'details-disclosure.js'"));
assert(layout.indexOf("'details-disclosure.js'") < layout.indexOf('content_for_layout'));

const assets = {};
for (const name of ['details-disclosure.js', 'share.js']) assets[name] = await readFile(join(baseline, 'assets', name), 'utf8');
const snippet = await readFile(join(baseline, 'snippets/share-button.liquid'), 'utf8');
assert.match(snippet, /'share\.js' \| asset_url[^\n]+defer="defer"/);
function runtime(nativeShare = false) {
  const registry = new Map();
  const attrs = new Map([['open', '']]);
  const summary = { nextElementSibling: { getAnimations: () => [] }, setAttribute: (k, v) => attrs.set(k, v), focus() {} };
  const control = () => ({ classList: { add() {}, remove() {} }, addEventListener() {}, focus() {}, value: 'https://example.invalid/product' });
  const details = { querySelector: s => s === 'summary' ? summary : control(), addEventListener() {},
    removeAttribute: k => attrs.delete(k), setAttribute: (k, v) => attrs.set(k, v), hasAttribute: k => attrs.has(k) };
  class Element { querySelector(s) { return s === 'details' ? details : s === 'summary' ? summary : control(); } }
  const context = vm.createContext({ HTMLElement: Element, navigator: nativeShare ? { share() {} } : {},
    document: { location: { href: 'https://example.invalid/product' }, title: 'Fixture' },
    customElements: { get: k => registry.get(k), define(k, v) { assert(!registry.has(k)); registry.set(k, v); } } });
  return { context, registry, attrs };
}
// Reproduce the actual failure with the original loader, not a substituted class.
assert.throws(() => vm.runInContext(assets['share.js'], runtime().context), /DetailsDisclosure is not defined/);
for (const nativeShare of [false, true]) {
  const r = runtime(nativeShare);
  const html = layout.replace('{{ content_for_layout }}', snippet);
  for (const match of html.matchAll(/<script src="\{\{ '([^']+)' \| asset_url \}\}" defer="defer"><\/script>/g)) {
    if (assets[match[1]]) vm.runInContext(assets[match[1]], r.context, { filename: match[1] });
  }
  assert(r.registry.has('details-disclosure') && r.registry.has('header-menu') && r.registry.has('share-button'));
  const button = new (r.registry.get('share-button'))();
  assert(button instanceof r.registry.get('details-disclosure'));
  button.close();
  assert.equal(r.attrs.has('open'), false);
  assert.equal(r.attrs.get('aria-expanded'), false);
  button.updateUrl('https://example.invalid/updated');
  assert.equal(button.elements.urlInput.value, 'https://example.invalid/updated');
}
console.log(JSON.stringify({ status: 'passed', checks: 4, candidate, scenarios: ['exact reversible one-line patch', 'original ReferenceError reproduced', 'native sharing consumer', 'fallback sharing consumer'] }));
