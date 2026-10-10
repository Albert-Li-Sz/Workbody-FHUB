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
  const pending = [],posts = [],copies = [],toasts = [];
  const navigator = {clipboard:{writeText:async value=>{copies.push(value);}}};
  const toast = (...values)=>toasts.push(values);
  const getJSON = url => new Promise((resolve,reject) => pending.push({url,resolve,reject}));
  const postJSON = (url,body) => new Promise((resolve,reject) => posts.push({url,body,resolve,reject}));
  const localStorage = {getItem:key=>stored[key],setItem:(key,value)=>{stored[key]=value;}};
  const esc = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const document = {getElementById:element,querySelector:()=>element('tbody')};
  const api = new Function('window','document','localStorage','getJSON','postJSON','esc','navigator','toast','setTimeout',
    "let MODELS_DATA=[]; const SOURCE_ROOT='/accounts/upstreams';\n"+formatting+core+prices+extension+
    '\nreturn {loadModels,selectModelsChannel,selectedModelsChannel,filterModelLibrary,pageModelLibrary,refreshModelLibrary,modelLibraryRow,modelLibraryEffortHtml,modelLibraryCapabilityHtml,copyModelId,editModelAlias,saveModelAlias,saveModelPolicy,selectAll:typeof selectAllModelLibrary=== "function"?selectAllModelLibrary:null,toggleSelection:typeof toggleModelSelection=== "function"?toggleModelSelection:null,batchEnabled:typeof setSelectedModelsEnabled=== "function"?setSelectedModelsEnabled:null,clearSelection:typeof clearModelSelection=== "function"?clearModelSelection:null,get data(){return MODELS_DATA;}};')
    (window,document,localStorage,getJSON,postJSON,esc,navigator,toast,callback=>setImmediate(callback));
  return {api,element,window,stored,pending,posts,copies,toasts};
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
  assert.equal(pending[0].url,'/settings/models?channel=opencode_zen');
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
  assert.equal(pending[0].url,'/settings/models?channel=cline');
  const many=Array.from({length:61},(_,index)=>({id:'cline-pass/model-'+String(index).padStart(2,'0'),upstream:'cline',billing_mode:'paid'}));
  pending.shift().resolve({models:many,catalogues:{cline:{updated_at:1,stale:true,metadata_stale:true}}});await work;
  assert.equal(element('pageModels').dataset.source,'cline');
  assert.equal(h.stored.wb_model_channel,'cline');
  assert.equal((element('tbody').innerHTML.match(/<tr>/g)||[]).length,50);
  assert.equal(element('modelChannelStatus').dataset.tone,'warn');
  assert(element('modelLibrarySelectionCount').textContent.includes('已选 0'), 'model library must expose batch selection');
  api.selectAll({checked:true});
  assert(element('modelLibrarySelectionCount').textContent.includes('已选 61'), 'all filtered pages are selected');
  assert(element('modelLibrarySelectAll').checked);
  api.toggleSelection({dataset:{model:many[0].id},checked:false});
  assert(element('modelLibrarySelectAll').indeterminate);
  assert(element('modelLibrarySelectionCount').textContent.includes('已选 60'));
  work=api.batchEnabled(false);
  await api.batchEnabled(true);
  assert.equal(posts.length,1,'a pending batch cannot issue another write');
  assert.equal(posts[0].body.model_ids.length,60);
  assert(!posts[0].body.model_ids.includes(many[0].id));
  posts.shift().resolve({channel:'cline',model_ids:many.slice(1).map(item=>item.id),enabled:false,count:60});await work;
  assert(api.data[0].enabled!==false);
  assert(api.data.slice(1).every(item=>item.enabled===false));
  assert(!element('modelLibraryBatchEnable').disabled);
  work=api.batchEnabled(true);posts.shift().reject(new Error('batch offline'));await work;
  assert(api.data.slice(1).every(item=>item.enabled===false),'failed batch retains all model switches');
  assert(h.toasts.at(-1)[0].includes('batch offline'));
  api.clearSelection();
  element('modelLibrarySearch').value='model-0';api.filterModelLibrary();
  api.selectAll({checked:true});
  assert(element('modelLibrarySelectionCount').textContent.includes('已选 10'));
  element('modelLibrarySearch').value='';api.filterModelLibrary();
  assert(element('modelLibrarySelectionCount').textContent.includes('已选 10'), 'selection persists while filtering');
  api.selectAll({checked:true});
  element('modelLibrarySearch').value='model-0';api.filterModelLibrary();
  api.selectAll({checked:false});
  assert(element('modelLibrarySelectionCount').textContent.includes('已选 51'));
  assert(!element('modelLibrarySelectAll').checked && !element('modelLibrarySelectAll').indeterminate, 'unselect affects only the current filter');
  element('modelLibrarySearch').value='';api.filterModelLibrary();
  api.clearSelection();
  api.pageModelLibrary(1);
  assert.equal((element('tbody').innerHTML.match(/<tr>/g)||[]).length,11);
  assert(element('modelLibraryNext').disabled);
  const beforeBackground=element('tbody').innerHTML;
  work=api.loadModels({background:true});
  assert.equal(element('tbody').innerHTML,beforeBackground,'background refresh must retain the table height while the request is in flight');
  pending.shift().resolve({models:many});await work;
  const savedRows=element('tbody').innerHTML;
  work=api.loadModels();pending.shift().reject(new Error('refresh offline'));await work;
  assert.equal(element('tbody').innerHTML,savedRows,'a failed reload retains the previous table');
  assert(element('modelLibraryPager').textContent.startsWith('2 / 2'),'SSE refresh preserves the current page');

  const edited={dataset:{model:many[50].id},value:'my-alias',disabled:false};
  api.editModelAlias(edited);
  work=api.saveModelAlias(edited);
  assert.deepEqual(posts[0].body,{channel:'cline',model_id:many[50].id,alias:'my-alias'});
  posts.shift().resolve({alias:'my-alias',enabled:false});await work;
  assert(element('tbody').innerHTML.includes('my-alias'));
  assert(api.data.find(item=>item.id===many[50].id).enabled===false);

  api.toggleSelection({dataset:{model:many[50].id},checked:true});
  const oldBatch=api.batchEnabled(true),batchReply=posts.shift();
  assert(element('modelLibraryBatchEnable').disabled);

  // The shared generation prevents races across the old and new API paths.
  const old=api.selectModelsChannel('workbuddy-cn'),oldReply=pending.shift();
  work=api.selectModelsChannel('commandcode');
  pending.shift().resolve({models:[{id:'commandcode/only',upstream:'commandcode',native_protocol:'chat'}]});await work;
  oldReply.resolve({data:[{id:'old-workbuddy',credits:'x0.5'}]});await old;
  batchReply.resolve({model_ids:[many[50].id],enabled:true,count:1});await oldBatch;
  assert.equal(api.data[0].enabled,undefined, 'a late batch reply cannot update another channel');
  assert(element('modelLibrarySelectionCount').textContent.includes('已选 0'), 'selections are isolated by channel');
  assert(element('tbody').innerHTML.includes('commandcode/only'));
  assert(!element('tbody').innerHTML.includes('old-workbuddy'));
  const stale=api.selectModelsChannel('cline'),staleReply=pending.shift();
  work=api.selectModelsChannel('workbuddy-cn');
  assert.equal(pending[0].url,'/settings/models?channel=workbuddy-cn');
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
  pending.shift().resolve({models:[go],catalogues:{opencode_zen:{refreshing:true}}});
  await new Promise(resolve=>setImmediate(resolve));
  assert(element('modelRefreshButton').disabled,'manual refresh waits for the background job');
  assert(element('modelChannelStatus').textContent.includes('正在同步'));
  await new Promise(resolve=>setImmediate(resolve));
  pending.shift().resolve({models:[go],catalogues:{opencode_zen:{refreshing:false}}});await work;
  assert(!element('modelRefreshButton').disabled);
  work=api.selectModelsChannel('workbuddy-intl');pending.shift().resolve({data:[]});await work;
  work=api.refreshModelLibrary();
  assert.equal(pending[0].url,'/settings/models?channel=workbuddy-intl');
  pending.shift().resolve({data:[]});await work;
  assert.equal(posts.length,0,'WorkBuddy catalogue needs no external platform refresh');
  await api.copyModelId('cline-pass/copy-this');
  assert.deepEqual(h.copies,['cline-pass/copy-this']);
  assert.equal(h.toasts.at(-1)[1],'ok');
  await api.selectModelsChannel('invalid');await api.selectModelsChannel('toString');
  assert.equal(pending.length,0);
  const changed = harness('cline');
  work=changed.api.loadModels();changed.pending.shift().resolve({data:many.slice(0,3)});await work;
  changed.api.selectAll({checked:true});
  work=changed.api.loadModels();changed.pending.shift().resolve({data:many.slice(0,2)});await work;
  assert(changed.element('modelLibrarySelectionCount').textContent.includes('已选 2'), 'refresh drops selected IDs removed from the catalogue');
  const reload=changed.api.loadModels(),beforeWrite=changed.pending.shift();
  work=changed.api.batchEnabled(false);
  changed.posts.shift().resolve({model_ids:many.slice(0,2).map(m=>m.id),enabled:false,count:2});await work;
  beforeWrite.resolve({data:many.slice(0,2).map(m=>({...m,enabled:true}))});
  await new Promise(resolve=>setImmediate(resolve));
  assert(changed.api.data.every(m=>m.enabled===false), 'a refresh started before saving cannot overwrite the batch result');
  changed.pending.shift().resolve({data:many.slice(0,2).map(m=>({...m,enabled:false}))});await reload;
  console.log('five model channels: capabilities, prices, tiers, scope, filters, paging, persistence, refresh and races passed');
})().catch(error=>{console.error(error);process.exit(1);});
