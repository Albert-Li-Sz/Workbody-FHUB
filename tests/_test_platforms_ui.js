'use strict';
const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const path=require('path');
const elements={};
for(const id of ['platformFilter','platformProxySlot','platformStatus','platformAccounts','platformModels','platformModelFilter','platformModelsPager','responseStorageSummary','responseConversations','platformUsage','platformRecent',
  'responseStorage_enabled','responseStorage_retention_days','responseStorage_max_mb','platformKind','platformName','platformPriority','platformAllowModels','platformToken','platformRefreshToken','platformFormTitle','platformLogin']){
  elements[id]={value:'',dataset:{},innerHTML:'',textContent:'',contains:()=>false,scrollIntoView:()=>{}};
}
elements.platformKind.value='cline';elements.platformPriority.value='100';
const account={uid:'cline-fixture',upstream:'cline',nickname:'fixture',enabled:true,priority:100,in_flight:0,models:[],today:{tokens:1000000},proxy_slot:''};
const data={accounts:[account],catalogues:{cline:{count:1}},models:[{upstream:'cline',id:'cline/test',native_protocol:'chat',context_length:1000000}],
  responses:{max_mb:1024,enabled:true,retention_days:7},proxy_slots:[]};
let gets=0;const posts=[];const notices=[];
const context=vm.createContext({console,document:{activeElement:null,getElementById:id=>elements[id]},
  esc:value=>String(value ?? '').replaceAll('<','&lt;'),fmt:String,fmtTokens:v=>String(v)+'K',
  getJSON:async url=>{gets++;return url.startsWith('/platforms/usage')?{totals:[],recent:[]}:url==='/platforms/models'?{models:data.models}:Object.assign({},data);},
  postJSON:async (url,body)=>{posts.push({url,body});return{};},toast:(...v)=>notices.push(v),confirm:()=>true});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../dashboard_static/platforms.js'),'utf8'),context);
(async()=>{
  await Promise.all([context.loadPlatforms(),context.loadPlatforms()]);
  assert.equal(gets,3,'SSE bursts coalesce status, catalogue and usage fetches');
  context.editPlatformPriority(account.uid,{value:'7'});
  await context.loadPlatforms();
  assert(elements.platformAccounts.innerHTML.includes('value="7"'));
  const old=elements.platformAccounts.innerHTML;
  elements.platformAccounts.contains=()=>true;
  await context.loadPlatforms();
  assert.equal(elements.platformAccounts.innerHTML,old,'keep the input focus');
  elements.platformAccounts.contains=()=>false;
  elements['platformPriority_'+account.uid]={value:''};
  await context.savePlatformPriority(account.uid);assert.equal(posts.length,0);
  elements['platformPriority_'+account.uid].value='3';
  await context.savePlatformPriority(account.uid);assert.equal(posts[0].body.priority,3);
  context.editPlatformAccount(account.uid);
  assert.equal(elements.platformKind.disabled,true);
  assert.equal(elements.platformToken.value,'');
  elements.platformPriority.value='5';
  await context.importPlatformAccount();
  assert.equal(posts.at(-1).url,'/platforms/accounts/update');
  assert.equal(posts.at(-1).body.uid,account.uid);
  assert(!('access_token' in posts.at(-1).body));
  assert.equal(elements.platformKind.disabled,false);
  assert.equal(elements.platformToken.value,'');
  console.log('platform UI: coalescing, persistent priority drafts, account editing and credential clearing passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
