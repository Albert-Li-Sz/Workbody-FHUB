/* Test the shipped channel picker, including stale-response races. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'dashboard.html'), 'utf8');
const source = html.slice(html.indexOf('const MODEL_CHANNEL_LABELS'), html.indexOf('let CURRENT_GROWTH_UID'));
assert.ok(source.includes('async function selectModelsChannel'));
const options = /id="modelChannelSelect"[\s\S]*?<\/select>/.exec(html)[0];
assert.deepStrictEqual([...options.matchAll(/<option value="([^"]+)"/g)].map(m => m[1]),
                       ['workbuddy-cn', 'workbuddy-intl']);
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
  work = api.selectModelsChannel('workbuddy-cn');
  const latestReply = pending.shift();
  assert.ok(!tbody.innerHTML.includes('domestic'), 'old rows disappear while loading');
  latestReply.resolve({source:'workbuddy',data:[{id:'latest-domestic',channel:'workbuddy-cn',
                        credits:'x0.50',max_output_tokens:32000,output_clamp:16000}]});
  await work;
  slowReply.resolve({data:[{id:'stale-workbuddy',credits:'x0.00'}]});
  await slow;
  assert.ok(!tbody.innerHTML.includes('stale-workbuddy'));
  assert.ok(tbody.innerHTML.includes('latest-domestic'));
  assert.ok(tbody.innerHTML.includes('0.50x'));
  assert.ok(tbody.innerHTML.includes('钳制'));
  assert.equal(el('modelChannelSelect').value,'workbuddy-cn');

  // Changing an unrelated view must not override the explicit model channel.
  window.VIEW_REALM='intl';
  work=api.loadModels();
  assert.equal(pending[0].url,'/v1/models?channel=workbuddy-cn');
  pending.shift().resolve({source:'workbuddy',data:[]});
  await work;
  assert.ok(el('modelChannelStatus').textContent.includes('WorkBuddy 国内'));

  work=api.selectModelsChannel('workbuddy-cn');
  pending.shift().reject(new Error('offline'));
  await work;
  assert.ok(el('modelChannelStatus').textContent.includes('offline'));
  assert.ok(!tbody.innerHTML.includes('latest-domestic'));
  const before=pending.length;
  await api.selectModelsChannel('invalid');
  await api.selectModelsChannel('opencode');
  assert.equal(pending.length,before);
  window.MODEL_CHANNEL='opencode';
  work=api.loadModels();
  assert.equal(pending[0].url,'/v1/models?channel=workbuddy-intl');
  pending.shift().resolve({data:[]});
  await work;
  console.log('WorkBuddy channel isolation, retired selection and request race assertions passed');
})().catch(error=>{console.error(error);process.exit(1);});
