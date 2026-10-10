/* Exercise the actual WorkBuddy renderer plus the shipped platform extension. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const html = require('./dashboard_source').htmlSource();
const core = html.slice(html.indexOf('const MODEL_CHANNEL_LABELS'),html.indexOf('let CURRENT_GROWTH_UID'));
const formatting = html.slice(html.indexOf('const fmt ='),html.indexOf('const esc ='));
const prices = html.slice(html.indexOf('function sourcePriceNumber'),html.indexOf('function renderSourceModels'));
const extension = fs.readFileSync(path.join(__dirname,'../dashboard_static/model_library.js'),'utf8');
assert(html.indexOf(extension) > html.indexOf('function sourceModelPrice'));
assert(html.indexOf(extension) < html.indexOf('const ACTION_HANDLERS'));

function harness(savedChannel=''){
  const elements = {};
  const element = id => elements[id] || (elements[id]={value:'',textContent:'',innerHTML:'',dataset:{},hidden:false,disabled:false});
  const window = {MODEL_CHANNEL:'',VIEW_REALM:'intl',ACTIVE_GATEWAY_REALM:'intl'};
  const stored = {wb_model_channel:savedChannel};
  const pending = [],posts = [];
  const getJSON = url => new Promise((resolve,reject) => pending.push({url,resolve,reject}));
  const postJSON = (url,body) => new Promise((resolve,reject) => posts.push({url,body,resolve,reject}));
  const localStorage = {getItem:key=>stored[key],setItem:(key,value)=>{stored[key]=value;}};
  const esc = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const document = {getElementById:element,querySelector:()=>element('tbody')};
  const api = new Function('window','document','localStorage','getJSON','postJSON','esc',
    "let MODELS_DATA=[]; const SOURCE_ROOT='/accounts/upstreams';\n"+formatting+core+prices+extension+
    '\nreturn {loadModels,selectModelsChannel,selectedModelsChannel,filterModelLibrary,pageModelLibrary,refreshModelLibrary,modelLibraryRow,modelLibraryEffortHtml,modelLibraryCapabilityHtml,get data(){return MODELS_DATA;}};')
    (window,document,localStorage,getJSON,postJSON,esc);
  return {api,element,window,stored,pending,posts};
}

const go = {id:'opencode/go/fixture',upstream:'opencode_zen',name:'Go Reasoner',entitlement:'subscription',billing_mode:'paid',
  native_protocol:'responses',reasoning:true,reasoning_efforts:['low','high'],tool_call:true,modalities:{input:['text','image']},
  context_length:1000000,max_output_tokens:64000,reference_pricing:{input:0.3,output:1.2,cache_read:0.006,unit:'USD/1M tokens'}};
const free = {id:'opencode/free',upstream:'opencode_zen',billing_mode:'free',native_protocol:'chat',reasoning:false,
  pricing:{input:0,output:0,unit:'USD/1M tokens'}};
const paid = {id:'opencode/paid',upstream:'opencode_zen',billing_mode:'paid',native_protocol:'messages',reasoning:true};

(async()=>{
  const h = harness('opencode_zen');
  const {api,element,pending,posts} = h;
  assert.equal(api.selectedModelsChannel(),'opencode_zen','new channels survive a reload');
  let work = api.loadModels();
  assert.equal(pending[0].url,'/accounts/upstreams/models?upstream=opencode_zen');
  assert(element('tbody').innerHTML.includes('正在加载'));
  pending.shift().resolve({models:[paid,free,go],catalogues:{opencode_zen:{updated_at:Date.now()/1000}}});
  await work;
  let rows = element('tbody').innerHTML;
  for(const text of ['OpenCode Go 订阅','订阅配额参考价','$0.006','1M','64K','low','high','视觉','工具','Responses']) assert(rows.includes(text),text);
  assert(rows.indexOf(go.id)<rows.indexOf(free.id));
  assert(rows.indexOf(free.id)<rows.indexOf(paid.id));
  assert(element('modelChannelStatus').textContent.includes('其余使用 Zen'));
  assert.equal(element('pageModels').dataset.source,'opencode_zen');
  assert.equal(element('modelBillingHeader').textContent,'价格 / 权益');
  assert.equal(h.window.VIEW_REALM,'intl');
  assert.equal(h.window.ACTIVE_GATEWAY_REALM,'intl');

  element('modelLibraryGroup').value='subscription';api.filterModelLibrary();
  assert(element('tbody').innerHTML.includes(go.id));
  assert(!element('tbody').innerHTML.includes(free.id));
  element('modelLibraryGroup').value='all';element('modelLibrarySearch').value='GO REASONER';api.filterModelLibrary();
  assert(element('tbody').innerHTML.includes(go.id));
  assert(!element('tbody').innerHTML.includes(paid.id));
  assert.equal(pending.length,0,'search does not trigger upstream requests');
  element('modelLibrarySearch').value='absent';api.filterModelLibrary();
  assert(element('tbody').innerHTML.includes('没有匹配'));
  element('modelLibrarySearch').value='';api.filterModelLibrary();

  assert(api.modelLibraryEffortHtml(paid).includes('上游未公布档位'));
  assert(!api.modelLibraryEffortHtml(paid).includes('high'),'reasoning alone must not invent tiers');
  assert(api.modelLibraryEffortHtml(free).includes('不支持推理'));
  assert(api.modelLibraryEffortHtml({id:'deepseek-pro'}).includes('上游未提供'));
  assert(api.modelLibraryEffortHtml({reasoning_options:{efforts:['minimal','medium']}}).includes('minimal'));
  const nativeOptions={reasoning_options:[{type:'toggle'},{type:'effort',values:['low','medium','high','xhigh','max']}]};
  for(const value of ['low','medium','high','xhigh','max','开启／关闭']) assert(api.modelLibraryEffortHtml(nativeOptions).includes(value));
  assert(api.modelLibraryEffortHtml({reasoning_options:[{type:'effort',values:['none','high']}]}).includes('none'));
  assert(api.modelLibraryEffortHtml({reasoning_options:[{type:'toggle'}]}).includes('推理开关'));
  assert(api.modelLibraryCapabilityHtml({reasoning_options:[{type:'toggle'}]}).includes('推理'));
  assert(api.modelLibraryEffortHtml({reasoning_fixed_effort:'high'}).includes('固定档位'));
  assert(api.modelLibraryRow({id:'commandcode/test',upstream:'commandcode',entitlement:'subscription'}).includes('Command Code 订阅'));
  assert(!api.modelLibraryRow({id:'commandcode/test',upstream:'commandcode',entitlement:'subscription'}).includes('ClinePass'));
  rows=api.modelLibraryRow({id:'cline/<script>',name:'<img>',upstream:'cline',reference_pricing:{prompt:'0.0000003',completion:'0.0000012',unit:'USD/token'},reasoning_efforts:['<iframe>']});
  assert(rows.includes('$0.3') && rows.includes('$1.2'));
  assert(!rows.includes('<script>') && !rows.includes('<img>') && !rows.includes('<iframe>'));
  assert(api.modelLibraryCapabilityHtml({modalities:{input:{}},supported_parameters:{}}).includes('文本'));
  assert(api.modelLibraryRow({id:'missing',max_output_tokens:-10,context_length:Infinity}).includes('上游未提供'));

  work=api.selectModelsChannel('cline');
  assert.equal(pending[0].url,'/accounts/upstreams/models?upstream=cline');
  const many=Array.from({length:61},(_,index)=>({id:'cline/model-'+String(index).padStart(2,'0'),upstream:'cline',billing_mode:'paid'}));
  pending.shift().resolve({models:many,catalogues:{cline:{updated_at:1,stale:true,metadata_stale:true}}});await work;
  assert.equal(element('pageModels').dataset.source,'cline');
  assert.equal(h.stored.wb_model_channel,'cline');
  assert.equal((element('tbody').innerHTML.match(/<tr>/g)||[]).length,50);
  assert.equal(element('modelChannelStatus').dataset.tone,'warn');
  api.pageModelLibrary(1);
  assert.equal((element('tbody').innerHTML.match(/<tr>/g)||[]).length,11);
  assert(element('modelLibraryNext').disabled);
  work=api.loadModels();pending.shift().resolve({models:many});await work;
  assert(element('modelLibraryPager').textContent.startsWith('2 / 2'),'SSE refresh preserves the current page');

  // The shared generation prevents races across the old and new API paths.
  const old=api.selectModelsChannel('workbuddy-cn'),oldReply=pending.shift();
  work=api.selectModelsChannel('commandcode');
  pending.shift().resolve({models:[{id:'commandcode/only',upstream:'commandcode',native_protocol:'chat'}]});await work;
  oldReply.resolve({data:[{id:'old-workbuddy',credits:'x0.5'}]});await old;
  assert(element('tbody').innerHTML.includes('commandcode/only'));
  assert(!element('tbody').innerHTML.includes('old-workbuddy'));
  const stale=api.selectModelsChannel('cline'),staleReply=pending.shift();
  work=api.selectModelsChannel('workbuddy-cn');
  assert.equal(pending[0].url,'/v1/models?channel=workbuddy-cn');
  pending.shift().resolve({data:[{id:'domestic',credits:'x0.50',channel:'workbuddy-cn',output_clamp:16000,max_output_tokens:32000,reasoning_efforts:['low','high']}]});await work;
  staleReply.resolve({models:many});await stale;
  rows=element('tbody').innerHTML;
  assert(rows.includes('domestic') && rows.includes('0.50x') && rows.includes('钳制') && rows.includes('high'));
  assert.equal(api.data.length,1,'pagination leaves the original dataset intact');
  assert.equal(element('modelBillingHeader').textContent,'消费倍率');
  assert(element('modelLibrarySubscription').hidden);
  assert.equal(h.window.ACTIVE_GATEWAY_REALM,'intl','view selection never changes the gateway');
  element('modelLibraryGroup').value='free';api.filterModelLibrary();
  assert(element('tbody').innerHTML.includes('没有匹配'));
  element('modelLibraryGroup').value='all';api.filterModelLibrary();

  work=api.selectModelsChannel('opencode_zen');
  pending.shift().reject(new Error('offline'));await work;
  assert(!element('tbody').innerHTML.includes('domestic'));
  assert.equal(element('modelChannelStatus').dataset.tone,'bad');
  assert(element('modelChannelStatus').textContent.includes('offline'));
  work=api.refreshModelLibrary();
  assert(element('modelRefreshButton').disabled);
  assert.deepEqual(posts[0].body,{upstream:'opencode_zen'});
  assert.equal(posts[0].url,'/accounts/upstreams/refresh');
  posts.shift().resolve({refreshing:true});await Promise.resolve();
  pending.shift().resolve({models:[go],catalogues:{opencode_zen:{refreshing:true}}});await work;
  assert(element('modelChannelStatus').textContent.includes('正在同步'));
  assert(!element('modelRefreshButton').disabled);
  work=api.selectModelsChannel('workbuddy-intl');pending.shift().resolve({data:[]});await work;
  work=api.refreshModelLibrary();
  assert.equal(pending[0].url,'/v1/models?channel=workbuddy-intl');
  pending.shift().resolve({data:[]});await work;
  assert.equal(posts.length,0,'WorkBuddy refresh retains its original API');
  await api.selectModelsChannel('invalid');await api.selectModelsChannel('toString');
  assert.equal(pending.length,0);
  console.log('five model channels: capabilities, prices, tiers, scope, filters, paging, persistence, refresh and races passed');
})().catch(error=>{console.error(error);process.exit(1);});
