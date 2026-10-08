// Exercise the actual SSE parser and queue; no browser or live accounts.
const assert = require('assert');
const vm = require('vm');
const source = require('./dashboard_source').htmlSource();
const queue = source.slice(source.indexOf('function queuePanelRefresh('), source.indexOf('async function flushPanelRefresh('));
const accept = source.slice(source.indexOf('function acceptPanelFrame('), source.indexOf('async function connectPanelStream('));
const context = vm.createContext({
  window:{ACCOUNTS:[{uid:'a',inFlight:0}]}, USAGE_BY_ACCOUNT:{a:{requests:2,total_tokens:7}},
  PANEL_READY:true, document:{hidden:false}, PANEL_STREAM:{pending:new Set(),timer:null,flushing:false},
  setTimeout:()=>1, flushPanelRefresh:()=>{}, panelSessionLost:()=>{}, console
});
vm.runInContext(queue + '\n' + accept, context);
context.acceptPanelFrame('event: refresh\ndata: '+JSON.stringify({topics:[],changes:{accounts:{a:{inFlight:2}},usage:{a:{requests:1,total_tokens:5}}}}));
assert.strictEqual(context.window.ACCOUNTS[0].inFlight,2);
assert.strictEqual(context.USAGE_BY_ACCOUNT.a.total_tokens,12);
assert.strictEqual(context.USAGE_BY_ACCOUNT.a.requests,3);
assert.ok(context.PANEL_STREAM.pending.has('account_activity'),'numeric activity must reach the refresh queue');
assert.ok(!context.PANEL_STREAM.pending.has('accounts'),'known activity must avoid a full account reload');
context.acceptPanelFrame('event: refresh\ndata: '+JSON.stringify({topics:['accounts'],changes:{accounts:{unknown:{inFlight:1}}}}));
assert.ok(context.PANEL_STREAM.pending.has('accounts'),'unknown account needs canonical resync');
console.log('Dashboard activity delta parser and refresh queue passed.');
