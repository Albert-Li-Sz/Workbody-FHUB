/* Audit probe: no real browser, credentials, or network. Exit 1 = reproduced findings. */
'use strict';
const fs = require('fs');
const vm = require('vm');
const path = require('path');
const source = fs.readFileSync(path.join(__dirname, '..', 'dashboard.html'), 'utf8');
const post = source.slice(source.indexOf('async function postJSON('), source.indexOf('\nfunction toast(', source.indexOf('async function postJSON(')));
const boot = source.slice(source.indexOf('async function bootPanel('), source.indexOf('\nlet PANEL_READY', source.indexOf('async function bootPanel(')));
const result = {};
(async () => {
  let lost = 0;
  const postContext = vm.createContext({JSON,
    authHeaders: () => ({}),
    panelSessionLost: () => { lost++; },
    fetch: async () => ({status:401,ok:false,text:async () => JSON.stringify({error:{message:'current password is wrong',code:'current_password_invalid'}})})
  });
  vm.runInContext(post, postContext);
  try { await postContext.postJSON('/panel/password', {}); } catch (error) { result.client_error = error.message; }
  result.valid_session_cleared_on_wrong_current_password = lost === 1;
  postContext.fetch = async () => ({status:401,ok:false,text:async()=>JSON.stringify({error:{message:'panel password required',code:401}})});
  try { await postContext.postJSON('/settings/save', {}); } catch (error) {}
  result.invalid_session_cleared = lost === 1;

  const location = {search:'?pwd=AUDIT_URL_ONLY',pathname:'/'};
  let login = 0;
  let replaced = 0;
  const input = {value:''};
  const bootContext = vm.createContext({
    URLSearchParams, PANEL_STATUS:{}, window:{location},
    document:{getElementById: id => id === 'panelPwdInput' ? input : {style:{}}},
    history:{replaceState:() => { replaced++; location.search=''; }},
    authHeaders:() => ({}), panelNeedsLogin:()=>{}, panelHideGate:()=>{}, startDashboard:async()=>{},
    submitPanelLogin:async()=>{login++;},
    fetch:async()=>({json:async()=>({authenticated:false})})
  });
  vm.runInContext(boot, bootContext);
  await bootContext.bootPanel();
  result.url_password_login_triggered = login === 1;
  result.url_password_removed = replaced > 0 || !location.search.includes('pwd=');
  const findings = [];
  if(result.valid_session_cleared_on_wrong_current_password) findings.push('A10');
  if(result.url_password_login_triggered && !result.url_password_removed) findings.push('A04');
  console.log(JSON.stringify({scope:'actual dashboard functions in Node VM with mocked HTTP/DOM',observations:result,findings}, null, 2));
  process.exitCode = findings.length ? 1 : 0;
})().catch(error => { console.error(error.name); process.exitCode = 2; });
