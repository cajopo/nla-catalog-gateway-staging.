'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const core = require('../theme/assets/nla-wishlist-core.js');

test('CSV preserves quoted names, escaped quotes, multiline cells, BOM and decimal comma', () => {
  const data = '\uFEFFgame;ProductName;Quantity;Language;MinCondition;IsFoil;MaxPrice_EUR;notes\r\n' +
    'Magic;"Jace, the \"\"Mind\"\" Sculptor";2;"English;Italian";EX;no;"12,50";"first line\nsecond line"\r\n';
  const result = core.parseFile(data, 'cards.csv');
  assert.deepEqual(result.errors, []);
  const row = result.rows[0];
  assert.equal(row.name, 'Jace, the "Mind" Sculptor');
  assert.equal(row.quantity, 2);
  assert.deepEqual(row.languages, ['en', 'it']);
  assert.equal(row.minCondition, 'EX');
  assert.equal(row.foil, false);
  assert.equal(row.maxPrice, 12.5);
  assert.equal(row.notes, 'first line\nsecond line');
});

test('mixed games remain per row, missing game stays unresolved', () => {
  const result = core.parseFile('name,game,count\nA,Magic,1\nB,Pokémon,2\nC,One Piece,3\nD,Yu-Gi-Oh!,4\nE,,1', 'mixed.csv');
  assert.deepEqual(result.rows.map(r => r.game), ['magic', 'pokemon', 'one-piece', 'yugioh', '']);
  assert.equal(result.rows[4].needsReview, true);
  assert.equal(new Set(result.rows.map(r => r.id)).size, 5);
  assert.equal(core.parseFile('name\nA', 'single.csv', {defaultGame: 'magic'}).rows[0].game, 'magic');
  const invalid = core.parseFile('name,game\nA,unknown', 'single.csv', {defaultGame: 'magic'}).rows[0];
  assert.equal(invalid.game, '');
  assert.equal(invalid.needsReview, true);
});

test('tab-separated fields and comma CSV retain physical card IDs separately', () => {
  const row = core.parseFile('name\tgame\tidProduct\tproductId\tidMetaproduct\nBolt\tmtg\t123\tgid://shopify/Product/456\t789', 'cards.tsv').rows[0];
  assert.equal(row.cardmarketId, '123');
  assert.equal(row.productId, 'gid://shopify/Product/456');
  assert.equal(row.metaProductId, '789');
  assert.equal(row.needsReview, false);
  assert.equal(core.normalizeRow({name:'Bolt', game:'magic'}).cardmarketId, null);
});

test('MKM JSON wrappers inherit game and preserve nested product identity', () => {
  const input = {response:{wantslist:[{name:'First',game:{idGame:1,name:'Magic the Gathering'},item:[{
    idWant:'opaque', type:'product', idProduct:123, count:4, wishPrice:1.25,
    minCondition:'NM', idLanguage:[1,5], isFoil:null, isSigned:false,
    product:{enName:'Lightning Bolt',expansionName:'Alpha',nr:'161'}
  }]},{name:'Second',game:{name:'Pokémon'},items:[{name:'Pikachu',count:1,idMetaproduct:99}]}]}};
  const result = core.parseFile(JSON.stringify(input), 'mkm.json');
  assert.deepEqual(result.errors, []);
  assert.equal(result.rows.length, 2);
  assert.equal(result.rows[0].game, 'magic');
  assert.equal(result.rows[0].set, 'Alpha');
  assert.equal(result.rows[0].collectorNumber, '161');
  assert.equal(result.rows[0].cardmarketId, '123');
  assert.deepEqual(result.rows[0].languages, ['en','it']);
  assert.equal(result.rows[0].extras.idWant, 'opaque');
  assert.equal(result.rows[1].game, 'pokemon');
  assert.equal(result.rows[1].metaProductId, '99');
});

test('JSON row arrays and single-row objects are supported', () => {
  for (const value of [{name:'Bolt',game:'magic'},[{name:'Bolt',game:'magic'}]]) {
    const result=core.parseFile(JSON.stringify(value),'list.json');
    assert.equal(result.rows.length,1);
    assert.deepEqual(result.errors,[]);
  }
});

test('tri-state flags distinguish false, true, and indifferent', () => {
  const row=core.normalizeRow({name:'Bolt',game:'magic',foil:'Y',signed:'N',altered:'any',firstEdition:null,exact:'false'});
  assert.equal(row.foil,true); assert.equal(row.signed,false);
  assert.equal(row.altered,null); assert.equal(row.firstEdition,null); assert.equal(row.exact,false);
  const unknown=core.normalizeRow({name:'Bolt',game:'magic',foil:'etched',signed:'foil',exact:'normal'});
  assert.equal(unknown.needsReview,true);
  assert.equal(unknown.foil,null); assert.equal(unknown.signed,null); assert.equal(unknown.exact,true);
  assert.equal(unknown.extras._invalidFields.foil,'etched');
});

test('invalid constraints remain visible and blocking instead of widening silently', () => {
  const row=core.normalizeRow({name:'Card',game:'magic',quantity:0,minCondition:'MP',languages:'English,Elvish',foil:'maybe',maxPrice:'1,234.56 USD'});
  assert.equal(row.quantity,null); assert.equal(row.minCondition,null); assert.equal(row.maxPrice,null);
  assert.equal(row.needsReview,true);
  assert.equal(row.extras._invalidFields.quantity,0);
  assert.equal(row.extras._invalidFields.minCondition,'MP');
  assert.equal(row.extras._invalidFields.languages,'English,Elvish');
  assert.ok(row.errors.length>=5);
});

test('minimum condition and zero price remain semantically distinct from no constraint', () => {
  const row=core.normalizeRow({name:'Card',game:'magic',minCondition:'Mint',maxPrice:0});
  assert.equal(row.minCondition,'MT'); assert.equal(row.maxPrice,0);
  assert.equal(core.normalizeRow({name:'Card',game:'magic',minCondition:'EX'}).minCondition,'EX');
  assert.equal(core.normalizeRow({name:'Card',game:'magic'}).maxPrice,null);
});

test('unmapped variables are retained with warning and review, not discarded', () => {
  const row=core.parseFile('name,game,isReverseHolo,custom\nPikachu,pokemon,true,keep me','p.csv').rows[0];
  assert.equal(row.extras.isReverseHolo,'true'); assert.equal(row.extras.custom,'keep me');
  assert.equal(row.needsReview,true); assert.equal(row.warnings.length,2);
});

test('CatID is informational and never a Cardmarket or Shopify identifier', () => {
  const row=core.normalizeRow({Name:'Flooded Strand',game:'magic',Quantity:'1',CatID:'54194',Sideboard:'false',Annotation:'deck'});
  assert.equal(row.cardmarketId,null); assert.equal(row.productId,null);
  assert.equal(row.extras.CatID,'54194'); assert.equal(row.extras.Sideboard,'false');
  assert.equal(row.notes,'deck'); assert.ok(row.warnings.length>=2);
});

test('simple decklists accept quantities, set, game prefix and retain unknown versions', () => {
  const result=core.parseText('[Magic] 4x High Tide (V.1) (Fallen Empires)\n[Pokemon] 2 Pikachu\nSol Ring',{defaultGame:'magic'});
  assert.equal(result.rows[0].quantity,4); assert.equal(result.rows[0].set,'Fallen Empires');
  assert.equal(result.rows[0].name,'High Tide'); assert.equal(result.rows[0].extras.version,'V.1');
  assert.equal(result.rows[0].needsReview,true);
  assert.equal(result.rows[1].game,'pokemon'); assert.equal(result.rows[2].quantity,1);
  assert.equal(core.parseText('1.5 Sol Ring',{defaultGame:'magic'}).rows[0].quantity,null);
});

test('CSV malformed quotes, duplicate headers and row length mismatch reject whole import', () => {
  for (const text of ['name,game\n"Bolt,magic','name,name\nA,B','name,game\nA,magic,extra','name,game\n"A"oops,magic']) {
    const result=core.parseFile(text,'bad.csv');
    assert.equal(result.rows.length,0,text); assert.ok(result.errors.length,text);
  }
});

test('conflicting aliases cannot silently override constraints', () => {
  const row=core.parseFile('name,game,quantity,count\nBolt,magic,1,8','conflict.csv').rows[0];
  assert.equal(row.needsReview,true);
  assert.deepEqual(row.extras._invalidFields.quantity,['1','8']);
});

test('unknown numerical games do not receive an invented mapping', () => {
  const row=core.normalizeRow({name:'Card',idGame:999});
  assert.equal(row.game,''); assert.equal(row.needsReview,true);
  assert.equal(row.extras._invalidFields.game,999);
});

test('numeric language IDs, multiple languages and conflicting wildcards', () => {
  const row=core.normalizeRow({name:'Card',game:'magic',idLanguage:[{idLanguage:6},{idLanguage:11},7,5]});
  assert.deepEqual(row.languages,['zh-CN','zh-TW','ja','it']);
  assert.equal(row.needsReview,false);
  assert.equal(core.normalizeRow({name:'Card',game:'magic',languages:'any,en'}).needsReview,true);
});

test('injection values remain inert and prototype keys cannot become preferences', () => {
  const raw=JSON.parse('{"name":"<img src=x onerror=alert(1)>","game":"magic","__proto__":{"polluted":true},"languages":"constructor","minCondition":"constructor"}');
  const row=core.normalizeRow(raw);
  assert.equal({}.polluted,undefined);
  assert.equal(row.extras.__proto__.polluted,true);
  assert.equal(row.name,'<img src=x onerror=alert(1)>');
  assert.deepEqual(row.languages,[]); assert.equal(row.minCondition,null); assert.equal(row.needsReview,true);
});

test('export protects spreadsheet formulas and reimports losslessly', () => {
  const row=core.normalizeRow({name:'=HYPERLINK("https://example.invalid")',game:'magic',quantity:3,
    notes:'\n+SUM(1,2)',languages:['en','it'],foil:false,signed:true,altered:null,maxPrice:0,exact:false});
  const csv=core.exportCSV([row]);
  assert.match(csv,/'=HYPERLINK/); assert.match(csv,/'\n\+SUM/);
  const back=core.parseFile(csv,'roundtrip.csv');
  assert.deepEqual(back.errors,[]);
  for (const field of ['name','notes','languages','foil','signed','altered','maxPrice','quantity','exact']) assert.deepEqual(back.rows[0][field],row[field]);
});

test('invalid fields and unknown metadata survive export and reimport with review required', () => {
  const row=core.normalizeRow({name:'Card',game:'magic',quantity:'bad',minCondition:'HP',special:'unknown'});
  const back=core.parseFile(core.exportCSV([row]),'invalid.csv').rows[0];
  assert.equal(back.needsReview,true); assert.equal(back.quantity,null); assert.equal(back.minCondition,null);
  assert.equal(back.extras._invalidFields.quantity,'bad'); assert.equal(back.extras.special,'unknown');
});

test('unsafe numeric IDs and unsupported currencies are never guessed', () => {
  const row=core.normalizeRow({name:'Card',game:'magic',idProduct:9007199254740992,maxPrice:'$10.00'});
  assert.equal(row.cardmarketId,null); assert.equal(row.maxPrice,null); assert.equal(row.needsReview,true);
  assert.equal(core.normalizeRow({name:'A',game:'magic',maxPrice:'9999999999999999999'}).maxPrice,null);
  for (const price of ['1EUR2', 'EUR 1 €', '1.234,56', '1 000']) {
    const parsed=core.normalizeRow({name:'A',game:'magic',maxPrice:price});
    assert.equal(parsed.needsReview,true); assert.equal(parsed.maxPrice,null);
  }
  assert.equal(core.normalizeRow({name:'A',game:'magic',maxPrice:'€ 12,50'}).maxPrice,12.5);
  assert.equal(core.normalizeRow({name:'A',game:'magic',maxPrice:'12.50 EUR'}).maxPrice,12.5);
});

test('file, row, cell and nesting limits fail explicitly without partial application', () => {
  const cases=[['a'.repeat(core.limits.bytes+1),'a.txt'],['name,game\n'+Array(core.limits.rows+1).fill('A,magic').join('\n'),'a.csv'],
    ['name,game\n'+ 'A'.repeat(core.limits.cell+1)+',magic','a.csv'],['{"response":'.repeat(30)+'{}'+'}'.repeat(30),'a.json']];
  for(const [content,file] of cases){const result=core.parseFile(content,file);assert.equal(result.rows.length,0);assert.ok(result.errors.length);}
});

test('malformed JSON, binary data and XML external entity declarations are rejected', () => {
  for(const [content,file] of [['{oops','a.json'],['name\0foo','a.csv'],['<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><wantslist/>','a.xml'],['<Deck/>','a.dek']]) {
    const result=core.parseFile(content,file); assert.equal(result.rows.length,0); assert.ok(result.errors.length);
  }
});

test('normalization does not mutate caller input and browser UMD exports the same API', () => {
  const input={name:'Bolt',game:'magic',extras:{note:'x'}}; const before=JSON.stringify(input);
  core.normalizeRow(input); assert.equal(JSON.stringify(input),before);
  const sandbox={}; vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../theme/assets/nla-wishlist-core.js'),'utf8'),sandbox);
  assert.equal(typeof sandbox.NlaWishlistCore.parseFile,'function');
  assert.equal(sandbox.NlaWishlistCore.parseFile('name,game\nBolt,magic','a.csv').rows[0].game,'magic');
});

test('product bindings survive normalization and CSV without becoming verified identities', () => {
  const input={name:'Bolt',game:'magic',productId:'gid://shopify/Product/456',cardmarketId:'123',
    handle:'lightning-bolt-a',canonicalName:'Lightning Bolt',confirmedProductIds:['456','gid://shopify/Product/789']};
  const normalized=core.normalizeRow(input);
  assert.equal(normalized.needsReview,false);
  const back=core.parseFile(core.exportCSV([normalized]),'bindings.csv').rows[0];
  for(const field of ['productId','cardmarketId','handle','canonicalName','confirmedProductIds']) assert.deepEqual(back[field],input[field]);
  const invalid=core.normalizeRow({...input,handle:'https://example.invalid',confirmedProductIds:['not-an-id']});
  assert.equal(invalid.needsReview,true);
  assert.deepEqual(invalid.confirmedProductIds,[]);
});

test('stored invalid constraints cannot disappear merely by normalizing them again', () => {
  const first=core.normalizeRow({name:'Bolt',game:'magic',foil:'maybe',languages:'en,Elvish',exact:'maybe'});
  const again=core.normalizeRow(first);
  assert.equal(again.needsReview,true);
  assert.equal(again.extras._invalidFields.foil,'maybe');
  assert.equal(again.extras._invalidFields.languages,'en,Elvish');
  assert.equal(again.extras._invalidFields.exact,'maybe');
  const partial=core.normalizeRow({...again,foil:false});
  assert.equal(partial.foil,false); assert.equal(partial.needsReview,true);
  assert.equal(partial.extras._invalidFields.foil,undefined);
  const cleared=core.normalizeRow({...again,foil:null,languages:[],exact:true},{editedFields:['foil','languages','exact']});
  assert.equal(cleared.needsReview,false); assert.deepEqual(cleared.errors,[]);
  assert.equal(cleared.extras._invalidFields,undefined);
  assert.equal(cleared.extras._reviewValues,undefined);
});

test('disagreeing nested MKM product IDs require review', () => {
  const row=core.parseFile(JSON.stringify({name:'Bolt',game:'magic',idProduct:123,product:{idProduct:456,enName:'Bolt'}}),'conflict.json').rows[0];
  assert.equal(row.needsReview,true);
  assert.deepEqual(row.extras._invalidFields.cardmarketId,[123,456]);
});

test('CSV formula protection preserves original leading apostrophes literally', () => {
  for (const notes of ["'=SUM(1,2)", "'ordinary note", "''=1+1", "'", ' =SUM(1,2)', '\t@SUM(1,2)']) {
    const row=core.normalizeRow({name:'Bolt',game:'magic',notes});
    const back=core.parseFile(core.exportCSV([row]),'apostrophes.csv');
    assert.deepEqual(back.errors,[]);
    assert.equal(back.rows[0].notes,notes);
  }
});

test('nested MKM purchase preferences are applied or explicitly require review', () => {
  const row=core.normalizeRow({game:'magic',product:{enName:'Card',idProduct:'100',isFoil:true,isSigned:false}});
  assert.equal(row.foil,true); assert.equal(row.signed,false); assert.equal(row.needsReview,false);
  const invalid=core.normalizeRow({game:'magic',product:{enName:'Card',idProduct:'100',isFoil:'etched',isReverseHolo:true}});
  assert.equal(invalid.needsReview,true); assert.equal(invalid.extras._invalidFields.foil,'etched');
  assert.equal(invalid.extras['product.isReverseHolo'],true);
  const conflict=core.normalizeRow({game:'magic',foil:false,product:{enName:'Card',isFoil:true}});
  assert.equal(conflict.needsReview,true); assert.deepEqual(conflict.extras._invalidFields.foil,[false,true]);
});

test('nested product game cannot silently contradict the outer wishlist game', () => {
  const row=core.normalizeRow({game:'pokemon',product:{enName:'Card',gameName:'Magic'}});
  assert.equal(row.needsReview,true); assert.deepEqual(row.extras._invalidFields.game,['pokemon','Magic']);
  const same=core.normalizeRow({game:'magic',product:{enName:'Card',gameName:'Magic: The Gathering',idGame:1}});
  assert.equal(same.needsReview,false); assert.equal(same.game,'magic');
});

test('structured invalid values remain visible without throwing or becoming wildcard constraints', () => {
  const row=core.normalizeRow({name:{unrecognized:'Card'},game:'magic',notes:{text:'note'},languages:[{unknown:'en'}]});
  assert.equal(row.needsReview,true);
  assert.equal(row.extras._invalidFields.name.unrecognized,'Card');
  assert.equal(row.extras._invalidFields.languages[0].unknown,'en');
  assert.equal(row.extras._invalidFields.notes.text,'note');
});
