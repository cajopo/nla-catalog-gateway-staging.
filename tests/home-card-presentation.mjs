import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { createRequire } from 'node:module';

const [root, skillRoot] = process.argv.slice(2);
const require = createRequire(join(skillRoot, 'package.json'));
const { toLiquidHtmlAST, walk } = require('@shopify/liquid-html-parser');
const card = readFileSync(join(root, 'theme/snippets/nla-product-card.liquid'), 'utf8');
const home = readFileSync(join(root, 'theme/sections/nla-home.liquid'), 'utf8');
const backup = JSON.parse(readFileSync(join(root, 'backup-card-exact.json'), 'utf8')).data.theme;
assert.equal(backup.id, 'gid://shopify/OnlineStoreTheme/175195881740');
assert.equal(backup.role, 'UNPUBLISHED');
toLiquidHtmlAST(home);
let priceGuard;
const soldOutGuards = [];
walk(toLiquidHtmlAST(card), node => {
  if (node.type !== 'LiquidTag' || node.name !== 'if') return;
  const text = card.slice(node.position.start, node.position.end);
  if (text.includes('product.available == false')) soldOutGuards.push(node.markup);
  if (text.includes('product.price_min > 0')) priceGuard = node.markup;
});
function evaluate(node, values) {
  if (node.type === 'LogicalExpression') {
    assert.equal(node.relation, 'or');
    return evaluate(node.left, values) || evaluate(node.right, values);
  }
  if (node.type === 'Comparison') {
    const a = evaluate(node.left, values), b = evaluate(node.right, values);
    if (node.comparator === '>') return typeof a === 'number' && a > b;
    assert.equal(node.comparator, '==');
    return a === b;
  }
  if (node.type === 'VariableLookup') return node.lookups.reduce((v, k) => v?.[k.value], values[node.name]);
  if (node.type === 'Number') return Number(node.value);
  assert.equal(node.keyword, 'false');
  return false;
}
assert.equal(soldOutGuards.length, 2);
for (const catalog_only of [false, true]) for (const available of [false, true]) {
  for (const price_min of [null, 0, 60]) {
    const values = { catalog_only, product: { available, price_min } };
    for (const guard of soldOutGuards) assert.equal(evaluate(guard, values), catalog_only || !available);
    assert.equal(!catalog_only && evaluate(priceGuard, values), !catalog_only && price_min > 0);
  }
}
assert.match(card, /{% unless catalog_only %}\s*{% if product.price_min > 0 %}/);
assert.equal((card.match(/>SOLD OUT</g) || []).length, 2);
assert(!card.includes("'products.product.sold_out' | t"));
for (const selector of ['.nla-product-card__status', '.nla-product-card__body .nla-product-card__unavailable']) {
  const rule = home.slice(home.indexOf(selector + ' {')).split('}')[0];
  assert(rule.includes('color: #ff4d4f;'));
}
assert(card.includes('<a href="{{ product.url }}">'));
assert(card.includes("product.tags contains 'nla_catalog_only'"));
assert(card.includes('product.featured_image'));
assert.match(home, /\.nla-home h2,\s*\.nla-home h3\s*\{\s*color: var\(--nla-white, #ffffff\);\s*\}/);
console.log('PASS: two parses, clone guard, 12 availability/price cases, universal red SOLD OUT, positive price and catalog-only guard retained.');
