/* Test the shipped picker, badges and save payload; no browser secrets. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname,'..','dashboard.html'),'utf8');
const script = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
const elements = {};
const element = id => elements[id] || (elements[id] = {
  innerHTML:'',textContent:'',value:'',checked:false,style:{},disabled:false,
  classList:{add(){},remove(){},contains(){return false;}},
  addEventListener(){},querySelector(){return null;},querySelectorAll(){return [];},
  appendChild(){},focus(){},setAttribute(){},getAttribute(){return '';},
});
global.document = {getElementById:element,querySelector:()=>null,querySelectorAll:()=>[],
  addEventListener(){},createElement:element,body:element('body'),head:element('head'),documentElement:element('html')};
global.window = {addEventListener(){},location:{href:'',search:''},
  matchMedia:()=>({matches:false,addEventListener(){}})};
global.localStorage = {getItem(){return null;},setItem(){},removeItem(){}};
global.sessionStorage = global.localStorage;
global.navigator = {userAgent:'node'};
global.setInterval = ()=>0;
global.setTimeout = ()=>0;
global.location = {href:'',search:'',hash:''};
global.alert = ()=>{};
global.confirm = ()=>false;
const posts = [];
global.fetch = async (url,options) => {
  if(options?.body) posts.push({url,payload:JSON.parse(options.body)});
  const response = {api_keys:[],opencode:{mode:'zen',api_key_set:true,configured:true},data:[],
    slots:[{id:'saved-proxy',name:'Saved proxy',enabled:true}]};
  return {status:200,ok:true,json:async()=>response,text:async()=>JSON.stringify(response)};
};
const api = new Function(script+`
  window.updateUI = updateUI;
  return {choices:REALM_CHOICES,renderKeyRows,keyRealmCell,renderOpenCodeSettings,
          onOpenCodeModeChange,saveOpenCodeSettings,saveApiKeys,loadProxySlots,
          setRows:rows=>{API_KEY_ROWS=rows;},setDeleted:rows=>{DELETED_KEY_ROWS=rows;}};`)();

(async()=>{
  assert.deepStrictEqual(api.choices.map(([value])=>value),['','intl','cn','opencode']);
  api.setRows([{id:'oc',name:'OpenCode',realm:'opencode',enabled:true,masked:'synt******test',models:[],_editing:true}]);
  api.renderKeyRows();
  assert.ok(element('keyList').innerHTML.includes('<option value="opencode" selected>固定 OpenCode 出口</option>'));
  api.setRows([{id:'oc',name:'OpenCode',realm:'opencode',enabled:true,masked:'synt******test',models:[]}]);
  api.setDeleted([{id:'old',name:'Old OpenCode',realm:'opencode'}]);
  api.renderKeyRows();
  assert.ok(element('keyList').innerHTML.includes('固定 OpenCode 出口'));
  assert.ok(element('deletedKeySection').innerHTML.includes('固定 OpenCode 出口'));
  assert.ok(api.keyRealmCell({realm:'opencode'}).includes('OpenCode'));
  await api.saveApiKeys();
  assert.equal(posts[0].payload.api_keys[0].realm,'opencode');
  assert.equal(posts[0].payload.api_keys[0].key,'');

  api.renderOpenCodeSettings({enabled:true,mode:'go',api_key_set:true,configured:true,timeout_seconds:90});
  assert.equal(element('setOpenCodeMode').value,'go');
  assert.equal(element('setOpenCodeBaseUrl').value,'https://opencode.ai/zen/go/v1');
  assert.equal(element('setOpenCodeBaseUrl').readOnly,true);
  assert.equal(element('setOpenCodeKey').value,'');
  assert.equal(element('setOpenCodeState').textContent,'(已配置)');
  await api.saveOpenCodeSettings({disabled:false});
  const config = posts.find(p=>p.payload.opencode).payload.opencode;
  assert.equal(config.mode,'go');
  assert.equal(config.api_key,'');
  assert.equal(config.clear_api_key,false);
  assert.equal(config.enabled,true);
  element('setOpenCodeMode').value='custom';
  api.onOpenCodeModeChange();
  assert.equal(element('setOpenCodeBaseUrl').readOnly,false);
  api.renderOpenCodeSettings({mode:'custom',proxy_slot:'saved-proxy',timeout_seconds:90});
  element('setOpenCodeKey').value='unsaved-synthetic-draft';
  element('setOpenCodeTimeout').value='75';
  await api.loadProxySlots();
  assert.equal(element('setOpenCodeProxySlot').value,'saved-proxy');
  assert.ok(element('setOpenCodeProxySlot').innerHTML.includes('Saved proxy'));
  assert.equal(element('setOpenCodeKey').value,'unsaved-synthetic-draft');
  assert.equal(element('setOpenCodeTimeout').value,'75');
  console.log('OpenCode fixed key picker, history, save and upstream credential isolation passed');
})().catch(error=>{console.error(error);process.exit(1);});
