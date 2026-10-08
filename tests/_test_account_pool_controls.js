/* Account realm switches, scoped bulk actions and all-account balances. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const html = require('./dashboard_source').htmlSource();
const accountPage = html.slice(html.indexOf('id="pageAccounts"'), html.indexOf('id="pageTasks"'));
for (const id of ['accountRealmIntl', 'accountRealmCn', 'btnQueryBalances']) {
  assert.ok(accountPage.includes(`id="${id}"`), `${id} must be reachable on the account page`);
}
const elements = new Map();
function element() {
  const classes = new Set();
  return {innerHTML: '', textContent: '', className: '', value: '', style: {},
    attrs: {}, classList: {add(x){classes.add(x);}, remove(x){classes.delete(x);}, contains(x){return classes.has(x);}},
    addEventListener(){}, querySelector(){return null;}, querySelectorAll(){return [];},
    appendChild(){}, focus(){}, setAttribute(k,v){this.attrs[k]=v;}, getAttribute(k){return this.attrs[k] || '';}};
}
const el = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
global.document = {getElementById: el, querySelector:()=>null, querySelectorAll:()=>[],
  addEventListener(){}, createElement:element, body:element(), head:element(), documentElement:element()};
global.window = {addEventListener(){}, location:{href:'http://localhost/?tab=accounts', search:''},
  matchMedia:()=>({matches:false,addEventListener(){}})};
global.location = window.location;
const stored = {};
global.localStorage = {getItem:k=>stored[k]||null, setItem:(k,v)=>stored[k]=v, removeItem:k=>delete stored[k]};
global.sessionStorage = localStorage;
global.navigator = {userAgent:'node'};
global.history = {replaceState(_a,_b,url){window.location.href=url;}};
global.setTimeout = () => 0;
global.setInterval = () => 0;
global.alert = () => {};
global.confirm = () => false;
const posts = [], downloadedQueries = [];
const balance = {total_remain:30.3,known_count:2,account_count:3,unknown_count:1,
  refreshed:true,refresh_failed:1,complete:false,
  by_realm:{cn:{total_remain:10.1,known_count:1,account_count:1},intl:{total_remain:20.2,known_count:1,account_count:2}}};
const script = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map(m=>m[1]).join('\n');
const api = new Function(script + `
  window.updateUI = updateUI;
  loadAccounts = async () => { renderAccounts(); updateUI(); };
  loadModels = loadGrowthTasks = loadSchedulerStatus = loadAnalytics = refresh = async () => {};
  postJSON = async (url, payload) => { posts.push({url,payload}); return balance; };
  downloadExport = async query => { downloadedQueries.push(query); return {count:1,name:'synthetic.json'}; };
  return {switchViewRealm,renderAccounts,setAll,queryBalances,autoAssignSlots,exportAccounts,
    renderAccountBalance, handlers:ACTION_HANDLERS};
`)( );
// These fixtures are data, never real credentials.
global.posts = posts; global.downloadedQueries = downloadedQueries; global.balance = balance;
window.ACCOUNTS = [
  {uid:'cn-synthetic',nickname:'DOMESTIC',realm:'cn',enabled:true,credits:{remain:10.1}},
  {uid:'intl-synthetic',nickname:'GLOBAL',realm:'intl',enabled:true,credits:{remain:20.2}},
  {uid:'legacy-synthetic',nickname:'LEGACY',enabled:false,credits:{remain:0}},
];

(async () => {
  window.ACTIVE_GATEWAY_REALM = 'intl';
  await api.switchViewRealm('cn');
  assert.ok(el('accounts').innerHTML.includes('DOMESTIC'));
  assert.ok(!el('accounts').innerHTML.includes('GLOBAL'));
  assert.ok(!el('accounts').innerHTML.includes('LEGACY'));
  assert.equal(el('accountRealmCn').attrs['aria-pressed'], 'true');
  assert.equal(el('accountRealmIntl').attrs['aria-pressed'], 'false');
  assert.equal(window.ACTIVE_GATEWAY_REALM, 'intl');
  assert.equal(new URL(window.location.href).searchParams.get('view'), 'cn');
  await api.handlers.setAll(element(), null, '0');
  assert.deepStrictEqual(posts.pop(), {url:'/accounts/set-all',payload:{enabled:false,realm:'cn'}});
  await api.exportAccounts(element());
  assert.equal(downloadedQueries.pop(), '?realm=cn');
  await api.switchViewRealm('intl');
  assert.ok(el('accounts').innerHTML.includes('GLOBAL'));
  assert.ok(el('accounts').innerHTML.includes('LEGACY'));
  assert.ok(!el('accounts').innerHTML.includes('DOMESTIC'));
  const button = element();
  await api.handlers.queryBalances(button);
  assert.deepStrictEqual(posts.pop(), {url:'/accounts/balance',payload:{}});
  assert.equal(button.disabled, false);
  assert.equal(el('accountBalanceTotal').textContent, '30.3');
  assert.equal(el('accountBalanceCn').textContent, '10.1');
  assert.equal(el('accountBalanceIntl').textContent, '20.2');
  assert.ok(el('accountBalanceStatus').textContent.includes('余额未知'));
  assert.ok(el('accountBalanceStatus').textContent.includes('查询失败'));
  await api.switchViewRealm('invalid');
  assert.equal(window.VIEW_REALM, 'intl');
  console.log('account realm, scoped actions and partial balance assertions passed');
})().catch(error=>{console.error(error);process.exit(1);});
