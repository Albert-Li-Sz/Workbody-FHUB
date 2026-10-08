function renderInfrastructure(data){
  const target = document.getElementById('infrastructureStats');
  if(!target) return;
  const db = data.storage || {}, pool = data.transport || {};
  const rows = [
    ['本地存储', db.engine === 'sqlite' ? 'SQLite · WAL' : 'JSON', '账号与配置 ' + fmt(db.documents || 0) + ' · 请求流水 ' + fmt(db.usage_records || 0)],
    ['上游连接', fmt(pool.reused || 0) + ' 次复用', '空闲 ' + (pool.idle || 0) + ' · 使用中 ' + (pool.active || 0)],
    ['面板更新', 'SSE 实时推送', '心跳 ' + (data.sse_heartbeat_seconds || 15) + ' 秒 · 断线自动重连']
  ];
  target.innerHTML = rows.map(row => '<div class="infrastructure-item"><div class="k">' + esc(row[0]) + '</div><div class="v">' + esc(row[1]) + '</div><div class="s">' + esc(row[2]) + '</div></div>').join('');
}
updateWorkspace(window.__MAIN_TAB__ || 'gateway');

const ACTION_HANDLERS = {
  accountPage: (el, ev, arg) => accountPage(arg),
  switchMainTab: (el, ev, arg) => switchMainTab(arg),
  toggleSidebar: () => toggleSidebar(),
  closeSidebar: () => closeSidebar(),
  toggleLanguage: () => wbToggleLanguage(),
  submitPanelLoginOnEnter: (el, ev) => { if(ev.key === 'Enter') submitPanelLogin(); },
  submitPanelLogin: () => submitPanelLogin(),
  switchViewRealm: (el, ev, arg) => switchViewRealm(arg),
  selectModelsChannel: (el) => selectModelsChannel(el.value),
  loadModels: () => loadModels(),
  toggleActiveGatewayRealm: () => toggleActiveGatewayRealm(),
  triggerSchedulerNow: (el) => triggerSchedulerNow(el),
  toggleScheduler: (el) => toggleScheduler(el),
  openLoginModal: () => openLoginModal(),
  doCheckin: (el) => doCheckin(el),
  doDailyChat: (el) => doDailyChat(el),
  doDailyChatWeb: (el) => doDailyChatWeb(el),
  scanDesktop: (el) => scanDesktop(el),
  exportAccounts: (el) => exportAccounts(el),
  openImport: () => openImport(),
  fetchCredits: (el) => fetchCredits(el),
  queryBalances: (el) => queryBalances(el),
  autoAssignSlots: () => autoAssignSlots(),
  setAll: (el, ev, arg) => setAll(arg === '1', el),
  setRecentLimit: (el, ev, arg) => setRecentLimit(Number(arg)),
  changeRecentPage: (el, ev, arg) => changeRecentPage(Number(arg)),
  switchGrowthAccount: (el) => switchGrowthAccount(el.value),
  runGrowthTasks: (el) => runGrowthTasks(el),
  triggerCatTravel: (el) => triggerCatTravel(el),
  scanTaskQueue: (el) => scanTaskQueue(el),
  runTaskQueue: (el) => runTaskQueue(el),
  setAnalyticsRange: (el, ev, arg) => setAnalyticsRange(arg),
  onRangeCustomChange: () => onRangeCustomChange(),
  loadCreditHistory: (el) => loadCreditHistory(el),
  onMatrixAcctFilterChange: (el) => { matrixAcctFilter = el.value; if(cachedMatrixData) renderPerfMatrix(cachedMatrixData.usage, cachedMatrixData.perf); },
  onMatrixModelFilterChange: (el) => { matrixModelFilter = el.value; if(cachedMatrixData) renderPerfMatrix(cachedMatrixData.usage, cachedMatrixData.perf); },
  savePanelPassword: (el) => savePanelPassword(el),
  addApiKeyRow: () => addApiKeyRow(),
  discoverProxySlots: (el) => discoverProxySlots(el),
  addProxySlotRow: () => addProxySlotRow(),
  saveProxySlots: (el) => saveProxySlots(el),
  saveReserveCredits: (el) => saveReserveCredits(el),
  saveDailyTokenLimit: (el) => saveDailyTokenLimit(el),
  saveAutoSwitchProduct: (el) => saveAutoSwitchProduct(el),
  saveDailyChatWeb: (el) => saveDailyChatWeb(el),
  saveLocalWebTools: (el) => saveLocalWebTools(el),
  saveAdvancedSettings: (el, ev, arg) => saveAdvancedSettings(el, ev, arg),
  loadSettings: (el, ev, arg) => loadSettings(arg === '1'),
  panelLogout: () => panelLogout(),
  fetchNewLogs: (el, ev, arg) => fetchNewLogs(arg === '1'),
  toggleLogAuto: () => toggleLogAuto(),
  toggleLogScroll: () => toggleLogScroll(),
  copyFilteredLogs: () => copyFilteredLogs(),
  exportLogsFile: () => exportLogsFile(),
  clearServerLogs: () => clearServerLogs(),
  setLogFilterLevel: (el, ev, arg) => setLogFilterLevel(arg),
  setLogFilterTag: (el, ev, arg) => setLogFilterTag(arg),
  onLogSearchInput: () => onLogSearchInput(),
  loadRequestArchive: (el) => loadRequestArchive(el),
  closeLogin: () => closeLogin(),
  switchLoginRealm: (el) => switchLoginRealm(el.value),
  restartLogin: () => restartLogin(),
  closeDesktopScan: () => closeDesktopScan(),
  refreshDesktopScan: (el) => refreshDesktopScan(el),
  closeImport: () => closeImport(),
  commitImport: (el) => commitImport(el),
  handleLogTerminalScroll: () => handleLogTerminalScroll(),
  toggleAccount: (el, ev, arg) => toggleAccount(el.dataset.uid, arg === '1', el),
  setAccountPriority: (el) => setAccountPriority(el.dataset.uid, el),
  editAccountPriority: (el) => editAccountPriority(el.dataset.uid, el),
  testAccount: (el) => testAccount(el.dataset.uid, el),
  refreshOne: (el) => refreshOne(el.dataset.uid, el),
  syncProfile: (el) => syncProfile(el.dataset.uid, el),
  activateGlobal: (el) => activateGlobal(el.dataset.uid, el),
  claimTrial: (el) => claimTrial(el.dataset.uid, el),
  setAccountProduct: (el, ev, arg) => setAccountProduct(el.dataset.uid, arg, el),
  exportOne: (el) => exportOne(el.dataset.uid),
  deleteAccount: (el) => deleteAccount(el.dataset.uid, el.dataset.name, el),
  gotoRecentPage: (el, ev, arg) => gotoRecentPage(Number(arg)),
  generateKeyForEdit: (el, ev, arg) => generateKeyForEdit(Number(arg)),
  cancelEditKey: (el, ev, arg) => cancelEditKey(Number(arg)),
  saveSingleKey: (el, ev, arg) => saveSingleKey(Number(arg), el),
  copyKeyRow: (el, ev, arg) => copyKeyRow(Number(arg)),
  openEditKey: (el, ev, arg) => openEditKey(Number(arg)),
  toggleKeyRow: (el, ev, arg) => toggleKeyRow(Number(arg)),
  removeKeyRow: (el, ev, arg) => removeKeyRow(Number(arg)),
  setAccountSlot: (el) => setAccountSlot(el.dataset.uid, el.value, el),
  onProxySlotNameInput: (el, ev, arg) => { PROXY_SLOTS[Number(arg)].name = el.value; markSlotsDirty(); },
  onProxySlotUrlInput: (el, ev, arg) => { PROXY_SLOTS[Number(arg)].url = el.value; markSlotsDirty(); },
  onProxySlotUsernameInput: (el, ev, arg) => { PROXY_SLOTS[Number(arg)].username = el.value; markSlotsDirty(); },
  onProxySlotPasswordInput: (el, ev, arg) => { PROXY_SLOTS[Number(arg)].password = el.value; markSlotsDirty(); },
  onProxySlotEnabledChange: (el, ev, arg) => { PROXY_SLOTS[Number(arg)].enabled = el.checked; markSlotsDirty(); },
  testProxySlot: (el, ev, arg) => testProxySlot(Number(arg), el),
  removeProxySlot: (el, ev, arg) => removeProxySlot(Number(arg)),
  importDiscovered: () => importDiscovered(),
  toggleThemeMenu: (el, ev) => window.toggleThemeMenu(ev),
  selectTheme: (el, ev, arg) => window.selectTheme(arg, ev),
  saveDailyCreditLimit: (el) => saveDailyCreditLimit(el),
  saveModelDailyTokenLimit: (el) => saveModelDailyTokenLimit(el),
  savePricingMinutes: (el) => savePricingMinutes(el),
  refreshPricingNow: (el) => refreshPricingNow(el),
  savePricingVariant: (el) => savePricingVariant(el),
  closeCreditsDetailBackdrop: (el, ev) => { if(ev.target === el) closeCreditsDetail(); },
  closeCreditsDetail: () => closeCreditsDetail(),
  filterCreditsPackages: (el, ev, arg) => filterCreditsPackages(arg, el),
  onCreditsSearchInput: (el) => onCreditsSearchInput(el.value),
  onCreditsSortChange: (el) => onCreditsSortChange(el.value),
  reloadCreditsDetail: (el) => reloadCreditsDetail(el),
  openCreditsDetail: (el) => openCreditsDetail(el.dataset.uid),
  recoverAtrestKey: (el) => recoverAtrestKey(el),
  fillPricingMapping: (el) => fillPricingMapping(el),
  savePricingMapping: (el) => savePricingMapping(el),
  setCostCurrency: (el, ev, arg) => setCostCurrency(arg),
};

function runDashboardAction(el, ev, type){
  const name = el.dataset ? el.dataset.action : '';
  const fn = ACTION_HANDLERS[name];
  if(typeof fn !== 'function') return;
  try{
    fn(el, ev, el.dataset ? el.dataset.arg : undefined);
  }catch(err){
    console.error('dashboard action "' + name + '" failed:', err);
  }
}

function dashboardActionTarget(ev){
  const node = ev.target;
  if(!node || typeof node.closest !== 'function') return null;
  const el = node.closest('[data-action]');
  if(!el) return null;
  const type = (ev.type || '').toLowerCase();
  return (el.dataset && el.dataset.on === type) ? el : null;
}

['click', 'change', 'input', 'keydown'].forEach(type => {
  document.addEventListener(type, ev => {
    const el = dashboardActionTarget(ev);
    if(el && !el.disabled) runDashboardAction(el, ev, type);
  });
});
// Scroll does not bubble from inner scrollers; capture reaches the target.
document.addEventListener('scroll', ev => {
  const el = dashboardActionTarget(ev);
  if(el) runDashboardAction(el, ev, 'scroll');
}, true);
