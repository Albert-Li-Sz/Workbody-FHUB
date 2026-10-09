'use strict';
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
const elements={};
function element(id){ return elements[id] || (elements[id]={value:'',dataset:{},innerHTML:'',textContent:'',hidden:false,classList:{add(){},remove(){},toggle(){},contains(){return false;}},contains:()=>false,setAttribute(){},focus(){},click(){}}); }
const account={uid:'cline-fixture',upstream:'cline',nickname:'fixture',enabled:true,priority:100,in_flight:0,models:[],today:{tokens:1000000},proxy_slot:''};
const data={accounts:[account,{...account,uid:'cc-fixture',upstream:'commandcode'},{...account,uid:'zen-fixture',upstream:'opencode_zen',public:true,enabled:false,auth_type:'api_key'}],catalogues:{cline:{count:1}},models:[{upstream:'cline',id:'cline/test',native_protocol:'chat',context_length:1000000}],routing:{},models_revision:'1',responses:{max_mb:1024,enabled:true,retention_days:7},proxy_slots:[]};
const posts=[],notices=[];let gets=0;
const context=vm.createContext({console,window:{addEventListener(){}},document:{activeElement:null,getElementById:element,addEventListener(){}},setTimeout,clearInterval,
 esc:v=>String(v??'').replaceAll('<','&lt;'),fmt:String,fmtTokens:v=>String(v)+'K',isAuthError:()=>false,
 getJSON:async url=>{gets++;return url.includes('/usage?')?{totals:[],recent:[]}:url.endsWith('/models')?{models:data.models}:{...data};},
 postJSON:async(url,body)=>{posts.push({url,body});return{};},toast:(...v)=>notices.push(v),confirm:()=>true});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../dashboard_static/account_sources.js'),'utf8'),context);
(async()=>{
 await context.switchAccountSource('cline'); assert.equal(gets,3);
 assert(element('workbuddyAccountsPanel').hidden); assert(!element('sourceAccountsPanel').hidden);
 assert(!element('sourceAccountsTable').innerHTML.includes('cc-fixture'));
 assert(element('sourceModels').innerHTML.includes('1000000K'));
 await Promise.all([context.loadSourceAccounts(),context.loadSourceAccounts()]);assert.equal(gets,5,'coalesce SSE bursts and retain model revision');
 element('sourceRoutingMode').value='manual';element('sourcePreferredAccount').value=account.uid;context.sourceRoutingModeChanged(true);
 await context.loadSourceAccounts();assert.equal(element('sourceRoutingMode').value,'manual','SSE preserves an unsaved routing draft after blur');
 assert.equal(element('sourcePreferredAccount').value,account.uid);
 context.editSourcePriority(account.uid,{value:'7'});await context.loadSourceAccounts();
 assert(element('sourceAccountsTable').innerHTML.includes('value="7"'));
 const old=element('sourceAccountsTable').innerHTML;element('sourceAccountsTable').contains=()=>true;
 await context.loadSourceAccounts();assert.equal(element('sourceAccountsTable').innerHTML,old);
 element('sourceAccountsTable').contains=()=>false;
 element('sourcePriority_'+account.uid).value='';await context.saveSourcePriority(account.uid);assert.equal(posts.length,0);
 element('sourcePriority_'+account.uid).value='3';await context.saveSourcePriority(account.uid);assert.equal(posts.at(-1).body.priority,3);
 context.openSourceEditor(account.uid);assert.equal(element('sourceToken').value,'');
 element('sourcePriority').value='5';await context.saveSourceAccount();
 assert.equal(posts.at(-1).url,'/accounts/upstreams/accounts/update');assert.equal(posts.at(-1).body.uid,account.uid);
 assert(!('api_key' in posts.at(-1).body));assert.equal(element('sourceToken').value,'');
 await context.preferSourceAccount(account.uid);assert.equal(posts.at(-1).body.mode,'manual');
 assert.equal(element('sourceRoutingMode').value,'fair','a saved selection clears its draft and reloads persisted routing');
 await context.batchSourceAccounts(false);assert.deepEqual(Array.from(posts.at(-1).body.uids),['cline-fixture']);
 context.openSourceRoute('test');element('sourceRouteMode').value='preferred';element('sourceRouteProviders').value='z-ai';
 element('sourceRouteIgnore').value='other';element('sourceRouteKnown').value='z-ai,other';element('sourceRouteSort').value='cost';
 await context.saveSourceRoute();assert.deepEqual(Array.from(posts.at(-1).body.policy.excluded),['other']);
 let completeOldUsage;
 const getJSON=context.getJSON;
 context.getJSON=async url=>url.includes('/usage?upstream=cline')?new Promise(resolve=>{completeOldUsage=resolve;}):url.includes('/usage?upstream=opencode_zen')?{totals:[{model:'opencode/new-usage',requests:1,errors:0,total_tokens:2}],recent:[]}:getJSON(url);
 const oldLoad=context.loadSourceAccounts();await new Promise(setImmediate);
 const switching=context.switchAccountSource('opencode_zen');
 assert(element('sourceAccountsTable').innerHTML.includes('zen-fixture'),'switch renders its own account rows before the old usage response arrives');
 assert(!element('sourceAccountsTable').innerHTML.includes('cline-fixture'));
 completeOldUsage({totals:[{model:'cline/old-usage'}],recent:[]});await Promise.all([oldLoad,switching]);
 assert(element('sourceUsage').innerHTML.includes('opencode/new-usage'));assert(!element('sourceUsage').innerHTML.includes('cline/old-usage'));
 context.openSourceEditor('zen-fixture');assert(element('sourceTokenLabel').hidden,'public account editing does not request a secret');
 element('sourcePriority').value='100';
 await context.saveSourceAccount();assert(!('enabled' in posts.at(-1).body),'editing a disabled public account cannot enable it implicitly');
 await context.switchAccountSource('workbuddy');assert(!element('workbuddyAccountsPanel').hidden);assert(element('sourceAccountsPanel').hidden);
 assert(posts.every(p=>!p.url.startsWith('/accounts/login')),'source actions never touch WorkBuddy login');
 console.log('additional account sources: isolation, drafts, editing, batch, routes and persistence passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
