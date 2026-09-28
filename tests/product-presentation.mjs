import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const [artifactRoot, skillRoot] = process.argv.slice(2);
assert(artifactRoot && skillRoot, 'Pass artifact directory and Shopify Liquid skill directory');
const require = createRequire(join(skillRoot, 'package.json'));
const { toLiquidHtmlAST, walk } = require('@shopify/liquid-html-parser');
const before = JSON.parse(readFileSync(join(artifactRoot, 'backup-exact.json'), 'utf8'));
assert.equal(before.themeId, 'gid://shopify/OnlineStoreTheme/175195881740');
assert.equal(before.role, 'UNPUBLISHED');
const files = Object.fromEntries(before.files.map(({ filename }) => [
  filename, readFileSync(join(artifactRoot, 'prepared', filename), 'utf8'),
]));
for (const source of Object.values(files)) toLiquidHtmlAST(source);
const price = files['snippets/price.liquid'];
let guard;
walk(toLiquidHtmlAST(price), node => {
  if (node.type === 'LiquidTag' && node.name === 'if'
      && price.slice(node.position.start, node.position.start + 60).includes('target.price > 0')) guard = node;
});
assert(guard);
const guarded = price.slice(guard.position.start, guard.position.end);
assert(guarded.includes('class="price__container"'));
assert(!guarded.includes('price__badge-sold-out'));
assert(price.indexOf('price__badge-sold-out') > guard.position.end);

const blank = Symbol('blank');
function evaluate(node, variables) {
  if (node.type === 'LogicalExpression') {
    assert.equal(node.relation, 'or');
    return evaluate(node.left, variables) || evaluate(node.right, variables);
  }
  if (node.type === 'Comparison') {
    const left = evaluate(node.left, variables), right = evaluate(node.right, variables);
    if (node.comparator === '>') return typeof left === 'number' && left > right;
    assert.equal(node.comparator, '==');
    return right === blank ? left == null : left === right;
  }
  if (node.type === 'VariableLookup') {
    return node.lookups.reduce((v, key) => v?.[key.value], variables[node.name]);
  }
  if (node.type === 'Number') return Number(node.value);
  assert.equal(node.keyword, 'blank');
  return blank;
}
for (const [value, visible] of [[0, false], [null, false], [undefined, false], [1, true], [1800, true]]) {
  assert.equal(evaluate(guard.markup, { target: { price: value }, product: {} }), visible);
}
assert.equal(evaluate(guard.markup, { target: {}, product: null }), true);
for (const source of Object.values(files)) assert(!source.includes("'products.product.sold_out' | t"));
assert.match(files['layout/theme.liquid'], /soldOut: `SOLD OUT`/);
assert.match(files['sections/main-product.liquid'], /\.product-form__submit:disabled\s*\{\s*color: #e00000;\s*border-color: #e00000;\s*opacity: 1;/);
const buyBefore = before.files.find(f => f.filename === 'snippets/buy-buttons.liquid').body.content;
assert.equal(files['snippets/buy-buttons.liquid'], buyBefore.replaceAll("{{ 'products.product.sold_out' | t }}", 'SOLD OUT'));
console.log('PASS: four Liquid/HTML parses; six price-guard cases; badge retained; universal initial/dynamic SOLD OUT; disabled/purchase logic unchanged. Not a storefront visual test.');
