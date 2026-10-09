'use strict';
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
const elements={},posts=[],timers=new Set();let status='pending',pendingStart=null,delayStart=false;
function element(id){return elements[id] || (elements[id]={value:'',innerHTML:'',textContent:'',hidden:false,dataset:{},className:'',classList:{add(){},remove(){},toggle(){},contains(){return false;}},setAttribute(){},contains(){return false;},focus(){}});}
const data={accounts:[],models:[],catalogues:{},models_revision:'1'};
const context=vm.createContext({console,window:{VIEW_REALM:'intl',addEventListener(){}},document:{activeElement:null,getElementById:element,addEventListener(){},querySelector(){return {value:'intl'};}},
 esc:v=>String(v??''),fmt:String,fmtTokens:String,isAuthError:()=>false,toast(){},setTimeout(){},clearInterval:id=>timers.delete(id),setInterval:fn=>{timers.add(fn);return fn;},
 getJSON:async url=>url.includes('/login/poll')?{status,orgs:[{id:'org-one',name:'One'},{id:'org-two',name:'Two'}]}:url.includes('/usage?')?{totals:[],recent:[]}:{...data},
 postJSON:async(url,body)=>{posts.push({url,body});if(url.endsWith('/login/start')){const value=url==='/accounts/login/start'?{state:'wb-state',authUrl:'https://www.workbuddy.ai/fixture-auth'}:{id:'source-job',url:'https://opencode.ai/console/auth/device?code=CODE',code:'CODE'};return delayStart?new Promise(resolve=>{pendingStart=()=>resolve(value);}):value;}if(url.endsWith('/login/complete'))status='completed';return{};}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../dashboard_static/account_sources.js'),'utf8'),context);
(async()=>{
 await context.switchAccountSource('opencode_zen');
 context.openSourceOAuth();await new Promise(setImmediate);await new Promise(setImmediate);
 assert(element('sourceLoginLinkBox').innerHTML.includes('href="https://opencode.ai/console/auth/device?code=CODE"'),'OAuth jump link must stay visible and clickable');
 assert(element('sourceLoginLinkBox').innerHTML.includes('target="_blank"'));
 assert(element('sourceStep1Text').textContent.includes('已生成'));
 status='select_org';await context.pollSourceOAuth();assert(!element('sourceOrgChoice').hidden);
 element('sourceLoginOrg').value='org-two';await context.completeSourceOAuth();assert.equal(posts.at(-1).body.org_id,'org-two');
 assert(element('sourceLoginStatus').textContent.includes('登录成功'));assert.equal(timers.size,0);
 status='pending';delayStart=true;context.openSourceOAuth();context.closeSourceOAuth();pendingStart();await new Promise(setImmediate);
 assert(posts.some(p=>p.url.endsWith('/login/cancel') && p.body.id==='source-job'),'late start is cancelled');
 assert(!element('sourceLoginLinkBox').innerHTML.includes('https://'),'closed modal cannot get a late link');
 delayStart=false;context.openSourceOAuth();await new Promise(setImmediate);status='expired';await context.pollSourceOAuth();
 assert(element('sourceLoginStatus').textContent.includes('过期'));assert.equal(timers.size,0);
 const core=fs.readFileSync(path.join(__dirname,'../dashboard_static/core.js'),'utf8');
 vm.runInContext('let loginState=null,loginTimer=null;'+core.slice(core.indexOf('function openLogin(){'),core.indexOf('window.ACTIVE_GATEWAY_REALM')),context);
 status='pending';context.openLoginModal();await new Promise(setImmediate);
 assert(element('loginLinkBox').innerHTML.includes('href="https://www.workbuddy.ai/fixture-auth"'),'original WorkBuddy OAuth jump link is unchanged');
 assert.equal(posts.filter(p=>p.url==='/accounts/login/start').at(-1).body.realm,'intl');
 context.closeLogin();assert(posts.some(p=>p.url==='/accounts/login/cancel' && p.body.state==='wb-state'));
 console.log('OAuth UI: visible links, WorkBuddy preservation, org choice, cancellation, late responses and expiry passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
