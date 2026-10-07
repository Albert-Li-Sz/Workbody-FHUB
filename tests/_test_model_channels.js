/* Test the shipped channel picker, including stale-response races. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'dashboard.html'), 'utf8');
const source = html.slice(html.indexOf('const MODEL_CHANNEL_LABELS'), html.indexOf('let CURRENT_GROWTH_UID'));
assert.ok(source.includes('async function selectModelsChannel'));
const options = /id="modelChannelSelect"[\s\S]*?<\/select>/.exec(html)[0];
assert.deepStrictEqual([...options.matchAll(/<option value="([^"]+)"/g)].map(m => m[1]),
                       ['opencode', 'workbuddy-cn', 'workbuddy-intl']);
const elements = {};
const el = id => elements[id] || (elements[id] = {value:'',textContent:'',innerHTML:''});
const tbody = el('tbody');
const document = {getElementById: el, querySelector: () => tbody};
const window = {VIEW_REALM:'intl', ACTIVE_GATEWAY_REALM:'intl', MODEL_CHANNEL:''};
const saved = {};
const localStorage = {setItem:(key,value)=>{saved[key]=value;}};
const pending = [];
const getJSON = url => new Promise((resolve,reject)=>pending.push({url,resolve,reject}));
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
global.MODELS_DATA = [];
const api = new Function('window','document','localStorage','getJSON','esc',source +
  '\nreturn {loadModels,selectModelsChannel,renderAvailableModels};')(window,document,localStorage,getJSON,esc);

(async()=>{
  let work = api.selectModelsChannel('workbuddy-cn');
  assert.equal(pending[0].url,'/v1/models?channel=workbuddy-cn');
  pending.shift().resolve({data:[{id:'domestic',channel:'workbuddy-cn',credits:'x0.50'}]});
  await work;
  assert.ok(tbody.innerHTML.includes('domestic'));
  assert.equal(window.VIEW_REALM,'intl');
  assert.equal(window.ACTIVE_GATEWAY_REALM,'intl');
  assert.equal(saved.wb_model_channel,'workbuddy-cn');

  // A slow previous channel must not repaint the newly selected catalogue.
  const slow = api.selectModelsChannel('workbuddy-intl');
  const slowReply = pending.shift();
  work = api.selectModelsChannel('opencode');
  const latestReply = pending.shift();
  assert.ok(!tbody.innerHTML.includes('domestic'), 'old rows disappear while loading');
  latestReply.resolve({source:'models.dev',data:[{id:'example-free',channel:'opencode',
                        max_output_tokens:32000,output_clamp:16000,pricing:{input:0,output:0}},
                        {id:'paid',channel:'opencode',pricing:{input:2,output:8}}]});
  await work;
  slowReply.resolve({data:[{id:'stale-workbuddy',credits:'x0.00'}]});
  await slow;
  assert.ok(!tbody.innerHTML.includes('stale-workbuddy'));
  assert.ok(tbody.innerHTML.includes('example-free'));
  assert.ok(tbody.innerHTML.includes('免费（目录标价）'));
  assert.ok(tbody.innerHTML.includes('$2 / $8'));
  assert.ok(!tbody.innerHTML.includes('0.00x'), 'OpenCode pricing must not use WorkBuddy credits');
  assert.ok(!tbody.innerHTML.includes('钳制') && !tbody.innerHTML.includes('未探测'),
            'WorkBuddy output probes must not annotate another provider');
  assert.ok(!tbody.innerHTML.includes('>文本<'), 'missing OpenCode metadata must not invent a text capability');
  assert.ok(el('modelChannelStatus').textContent.includes('OpenCode 上游未配置'));
  assert.equal(el('modelChannelSelect').value,'opencode');

  // Changing an unrelated view must not override the explicit model channel.
  window.VIEW_REALM='cn';
  work=api.loadModels();
  assert.equal(pending[0].url,'/v1/models?channel=opencode');
  pending.shift().resolve({source:'models.dev',stale:true,data:[]});
  await work;
  assert.ok(el('modelChannelStatus').textContent.includes('缓存目录'));

  work=api.selectModelsChannel('workbuddy-cn');
  pending.shift().reject(new Error('offline'));
  await work;
  assert.ok(el('modelChannelStatus').textContent.includes('offline'));
  assert.ok(!tbody.innerHTML.includes('example-free'));
  const before=pending.length;
  await api.selectModelsChannel('invalid');
  assert.equal(pending.length,before);
  console.log('model channel isolation, pricing and request race assertions passed');
})().catch(error=>{console.error(error);process.exit(1);});
