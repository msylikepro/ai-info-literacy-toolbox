const {test}=require('node:test');
const assert=require('node:assert/strict');
const {csvCell}=require('../server.cjs');

test('导出的引号换行可正确转义，公式前缀不作为Excel公式执行',()=>{
  assert.equal(csvCell('网页"标题\n第二行'),'"网页""标题\n第二行"');
  assert.equal(csvCell('=1+1'),'"\'=1+1"');
  assert.equal(csvCell('https://example.com/?a=1'),'"https://example.com/?a=1"');
});
