'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const dom = require('./_dom_stub.js');
const {htmlSource} = require('./dashboard_source');
const html = htmlSource();
const settings = fs.readFileSync(path.join(__dirname, '../dashboard_static/settings.js'), 'utf8');
const accounts = fs.readFileSync(path.join(__dirname, '../dashboard_static/accounts.js'), 'utf8');
const analytics = fs.readFileSync(path.join(__dirname, '../dashboard_static/analytics.js'), 'utf8');
const core = fs.readFileSync(path.join(__dirname, '../dashboard_static/core.js'), 'utf8');
const environment = dom.installDom();
const esc = s => String(s ?? '').replace(/[&<>\"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));
const toasts = [];
const toast = (message, kind) => toasts.push({message, kind});
const writes = [];
const post = async (url, payload) => { writes.push({url, payload: JSON.parse(JSON.stringify(payload))}); return {}; };
const limitsSource = settings.slice(settings.indexOf('const LIMIT_INPUTS'), settings.indexOf('async function savePricingMinutes'));
const limitAPI = new Function('document', 'postJSON', 'loadSettings', 'toast', 'fmtTokens', limitsSource +
  ';return {LIMIT_INPUTS, loadLimitInputs, saveLimitRow, saveCreditsRefreshHours, savePricingEnabled};')(
  environment.document, post, async () => {}, toast, n => (n / 1000) + 'K');

(async () => {
  const limits = {daily_token_limit: {global: 1000, intl: 0, cn: null}};
  limitAPI.loadLimitInputs({limits});
  for(const [id] of Object.values(limitAPI.LIMIT_INPUTS)){
    for(const suffix of ['', 'Intl', 'Cn']) assert.ok(html.includes('id="' + id + suffix + '"'));
  }
  assert.strictEqual(dom.byId('setDailyTokenLimit').value, '1000');
  assert.strictEqual(dom.byId('setDailyTokenLimitIntl').value, '0');
  assert.strictEqual(dom.byId('setDailyTokenLimitCn').value, '');
  assert.strictEqual(dom.byId('setDailyTokenLimitCn').placeholder, '继承 1000');
  assert.ok(dom.byId('setDailyTokenState').textContent.includes('1K'));
  const button = dom.makeElement('button');
  await limitAPI.saveLimitRow('daily_token_limit', button);
  assert.deepStrictEqual(writes.pop().payload, {limits: {daily_token_limit: {global: 1000, intl: 0, cn: null}}});
  assert.strictEqual(button.disabled, false);
  dom.byId('setDailyTokenLimitCn').value = '1.2';
  const count = writes.length;
  await limitAPI.saveLimitRow('daily_token_limit', button);
  assert.strictEqual(writes.length, count, 'fractional quota must not be silently rounded');
  assert.strictEqual(toasts.pop().kind, 'warn');
  environment.document.getElementById('setCreditsRefreshHours').value = '0';
  await limitAPI.saveCreditsRefreshHours(button);
  assert.deepStrictEqual(writes.pop().payload, {credits_refresh_hours: 0});
  environment.document.getElementById('setPricingEnabled').checked = false;
  await limitAPI.savePricingEnabled(button);
  assert.deepStrictEqual(writes.pop().payload, {pricing_enabled: false});

  // Explicit deletion and post-save reload complete before the caller proceeds.
  const keySource = settings.slice(settings.indexOf('const REALM_CHOICES'), settings.indexOf('let PROXY_SLOTS'));
  const rows = [{id:'k1', name:'one', key:'', masked:'masked', enabled:true, realm:'cn', models:['deepseek*']},
                {id:'k2', name:'two', key:'', masked:'masked', enabled:true, realm:'intl', models:[]}];
  let reloaded = 0;
  const keyAPI = new Function('document','API_KEY_ROWS','DELETED_KEY_ROWS','DELETED_KEY_IDS','esc','postJSON','loadSettings','toast','confirm',keySource +
    ';return {saveApiKeys, removeKeyRow};')(environment.document, rows, [], [], esc, post,
      async () => { await Promise.resolve(); reloaded++; }, toast, () => true);
  await keyAPI.removeKeyRow(1);
  const keyWrite = writes.pop();
  assert.deepStrictEqual(keyWrite.payload.deleted_api_key_ids, ['k2']);
  assert.strictEqual(keyWrite.payload.api_keys[0].id, 'k1');
  assert.deepStrictEqual(keyWrite.payload.api_keys[0].models, ['deepseek*']);
  assert.strictEqual(reloaded, 1);

  const tbody = dom.makeElement('tbody');
  const historySource = analytics.slice(analytics.indexOf('let CREDIT_HISTORY_ROWS'), analytics.indexOf('/* 第一列'));
  const history = new Function('document','window','postJSON','toast','esc','fmt','fmtTokens',historySource +
    ';return {loadCreditHistory, renderCreditHistory};')({querySelector: () => tbody}, environment.window,
    async () => ({rows: [{account:'abcdefgh-more', iso:'now', model:'deepseek', credit:2, total_tokens:1000000}]}),
    toast, esc, String, () => '1M');
  environment.window.ACCOUNTS = [];
  await history.loadCreditHistory();
  assert.ok(tbody.innerHTML.includes('abcdefgh</td>'));
  environment.window.ACCOUNTS = [{uid:'abcdefgh-more', nickname:'<昵称>'}];
  history.renderCreditHistory();
  assert.ok(tbody.innerHTML.includes('&lt;昵称&gt;'));
  assert.ok(tbody.innerHTML.includes('title="abcdefgh-more"'));
  assert.ok(tbody.innerHTML.includes('1M'));
  assert.ok(/#creditHistoryTable th\{position:sticky;top:0/.test(html));
  assert.ok(/credit-history-scroll\{overflow:auto;max-height:260px/.test(html));
  assert.ok(accounts.includes("typeof renderCreditHistory === 'function'"));
  assert.ok(core.includes('window.PRICING_ENABLED === false || cny == null'));

  const expirySource = accounts.slice(0, accounts.indexOf('function accountRow'));
  const expiry = new Function(expirySource + ';return {creditExpiryInfo, earliestCreditPackage};')();
  const now = Date.now()/1000;
  const pkg = {remain:100, expire_at:now+3*86400, expire_time:'actual deadline', cycle_end_time:'month end'};
  assert.ok(Math.abs(expiry.creditExpiryInfo(pkg).days - 3) < 0.01);
  assert.strictEqual(expiry.creditExpiryInfo(pkg).end, 'actual deadline');
  assert.strictEqual(expiry.creditExpiryInfo({...pkg,no_expiry:true}).days, null);
  assert.strictEqual(expiry.earliestCreditPackage({packages:[{...pkg,package_code:'enterprise'}]}), null);
  assert.strictEqual(expiry.earliestCreditPackage({packages:[{...pkg,expire_at:now-86400}]}), null);
  assert.strictEqual(expiry.earliestCreditPackage({packages:[{...pkg,remain:0}]}), null);

  const refreshSource = accounts.slice(accounts.indexOf('let CREDENTIAL_REFRESHING'), accounts.indexOf('async function setAll'));
  let loaded = 0, polled = 0;
  const refresh = new Function('document','postJSON','getJSON','loadAccounts','toast','setTimeout',refreshSource +
    ';return refreshAccounts;')(environment.document,
    async (url, payload) => { assert.strictEqual(url, '/accounts/refresh'); assert.deepStrictEqual(payload, {async:true}); return {id:'job', total:2, completed:0, running:true}; },
    async url => { assert.ok(url.endsWith('?id=job')); polled++; return {id:'job', total:2, completed:2, running:false, results:[{uid:'a',ok:true},{uid:'b',ok:false,error:'HTTP 401'}]}; },
    async () => { loaded++; }, toast, fn => fn());
  button.textContent = '刷新全部凭证';
  const running = refresh(button);
  assert.strictEqual(button.disabled, true);
  await refresh(button); // coalesces duplicate clicks
  await running;
  assert.strictEqual(polled, 1);
  assert.strictEqual(loaded, 1);
  assert.strictEqual(button.disabled, false);
  assert.strictEqual(button.textContent, '刷新全部凭证');
  assert.ok(toasts.some(x => x.kind === 'bad' && x.message.includes('HTTP 401')));
  assert.ok(html.includes('data-action="refreshAccounts"'));
  console.log('upstream UI contracts passed: regional limits, keys, credit history, pricing and bounded refresh');
})().catch(error => { console.error(error); process.exit(1); });
