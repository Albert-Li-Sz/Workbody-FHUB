async function refresh(){
  // SSE 和页面切换可能同时请求更新；把重叠刷新合并为一次补跑。
  REFRESH_GEN++;
  if(REFRESH_RUNNING){ REFRESH_QUEUED = true; return; }
  REFRESH_RUNNING = true;
  const gen = REFRESH_GEN;
  try { await refreshInner(gen); }
  finally {
    REFRESH_RUNNING = false;
    if(REFRESH_QUEUED){ REFRESH_QUEUED = false; refresh(); }
  }
}
// 展示货币切换后，把带费用的视图就地重画：各接口有服务端 TTL 缓存，
// 重新拉取的代价很小，不必为每处维护一份数据副本。
function refreshAllCostViews(){
  refresh();
  if(currentMainTab === 'analytics'){
    loadAnalytics();
    loadAnalyticsMatrix();
  }
}
async function refreshInner(gen){
  let usage, recent, perf;
  try{
    [usage, recent, perf] = await Promise.all([
      getJSON('/usage?realm=' + encodeURIComponent(window.VIEW_REALM)),
      getJSON('/usage/recent?limit=' + RECENT_LIMIT + '&page=' + RECENT_PAGE + '&realm=' + encodeURIComponent(window.VIEW_REALM)),
      getJSON('/usage/perf?realm=' + encodeURIComponent(window.VIEW_REALM)),
    ]);
    // 取数期间又发起了更新的一轮（例如刚切了区域），这批结果已经过期，
    // 直接扔掉，交给排队的那一轮渲染，免得把旧区域的数字画上去。
    if(gen !== REFRESH_GEN) return;
    document.getElementById('statusDot').className = 'dot';
  }catch(e){
    if(gen === REFRESH_GEN){
      document.getElementById('statusDot').className = 'dot err';
      if(String(e.message) !== 'unauthorized'){
        document.getElementById('meta').innerHTML = '<b>无法连接反代</b>';
      }
    }
    return;
  }

  const t = usage;
  const metaEl = document.getElementById('meta');
  if(metaEl) metaEl.innerHTML = '';
  document.getElementById('logfile').textContent = t.log_file || '';
  const rEl = document.getElementById('realm'); if(rEl) rEl.textContent = t.realm ? ' · ' + t.realm : '';

  // Sum credits across accounts
  let totRemain = 0, totSize = 0, hasCreds = false;
  window.ACCOUNTS.filter(a => (a.realm || 'intl') === window.VIEW_REALM).forEach(a => {
    if(a.credits){
      totRemain += (a.credits.remain || 0);
      totSize += (a.credits.size || 0);
      hasCreds = true;
    }
  });

  // An account parked by the low-credit guard is enabled but not serving, so
  // the pool card must not count it as "正常". The same goes for an account
  // capped by the daily credit guard: it still serves free models, but a
  // paid request will rotate away from it.
  const accts = (window.ACCOUNTS || []).filter(a => (a.realm || 'intl') === window.VIEW_REALM);
  const activeAccts = accts.filter(a => a.enabled && !a.reserveBlocked && !a.dailyLimitBlocked && !a.creditLimitReached).length;
  const totalAccts = accts.length;
  const parkedAccts = accts.filter(a => a.enabled && a.reserveBlocked).length;
  const disabledAccts = accts.filter(a => !a.enabled).length;
  const dailyAccts = accts.filter(a => a.enabled && a.dailyLimitBlocked).length;
  const creditAccts = accts.filter(a => a.enabled && a.creditLimitReached && !a.dailyLimitBlocked).length;
  const poolNotes = [];
  if(parkedAccts) poolNotes.push(parkedAccts + ' 个保留积分');
  if(dailyAccts) poolNotes.push(dailyAccts + ' 个达日限额');
  if(creditAccts) poolNotes.push(creditAccts + ' 个达积分限额');
  if(disabledAccts) poolNotes.push(disabledAccts + ' 个停用');
  const poolSub = poolNotes.length ? poolNotes.join(' · ') : '全部启用 · 状态健康';
  const pctRemain = totSize > 0 ? ((totRemain / totSize) * 100).toFixed(1) + '%' : '';
  const subCredit = totSize > 0 ? ('总积分 ' + fmt(totSize) + ' · 剩余 ' + pctRemain) : '已查询账号余额';
  const succStr = perf.success_rate_pct != null ? pct(perf.success_rate_pct) : '100.0%';
  const errSub = (perf.errors || 0) + ' 次失败 · ' + (perf.client_aborted || 0) + ' 次取消';
  // 等价花费的汇率随 /usage 载荷更新（后端定价快照里的值）。
  if(t.usd_cny) costUsdRate = Number(t.usd_cny) || costUsdRate;

  document.getElementById('cards').innerHTML =
    card('可用账号池', activeAccts + ' <span style="font-size:13px;font-weight:400;color:var(--dim)">/ ' + totalAccts + ' 正常</span>', poolSub, 'accent') +
    card('本出口积分余额', hasCreds ? (fmt(totRemain) + ' <span style="font-size:13px;font-weight:400;color:var(--dim)">积分</span>') : '正常可用', subCredit, 'accent2') +
    card('网关调用量', fmt(t.requests) + ' <span style="font-size:13px;font-weight:400;color:var(--dim)">次</span>', '本出口累计消耗 ' + fmtTokens(t.total_tokens) + ' Token · ' + Number(t.credit || 0).toFixed(2) + ' 积分', '') +
    card('OpenRouter 价估算', fmtCost(t.cost_cny), '按 OpenRouter 模型价折算的等价 token 花费' + costToggleHtml(), 'warn') +
    card('请求成功率', succStr, errSub, perf.errors ? 'warn' : 'accent2');

  const total = recent.total || 0;
  RECENT_PAGE = recent.page || 1;
  RECENT_TOTAL_PAGES = recent.total_pages || Math.max(1, Math.ceil(total / RECENT_LIMIT));

  const pageInfo = document.getElementById('recentPageInfo');
  if(pageInfo){
    pageInfo.textContent = '第 ' + RECENT_PAGE + ' / ' + RECENT_TOTAL_PAGES + ' 页 · 共 ' + fmt(total) + ' 条记录';
  }
  const btnPrev = document.getElementById('btnRecentPrev');
  if(btnPrev) btnPrev.disabled = (RECENT_PAGE <= 1);
  const btnNext = document.getElementById('btnRecentNext');
  if(btnNext) btnNext.disabled = (RECENT_PAGE >= RECENT_TOTAL_PAGES);
  const btnBox = document.getElementById('recentPageButtons');
  if(btnBox){
    const pages = generatePageList(RECENT_PAGE, RECENT_TOTAL_PAGES);
    btnBox.innerHTML = pages.map(p => {
      if(p === '...'){
        return '<span style="color:var(--dim);padding:0 3px">…</span>';
      }
      const active = (p === RECENT_PAGE);
      return '<button class="range-btn' + (active ? ' active' : '') + '" style="min-width:26px;padding:3px 6px;font-size:11px"  data-action="gotoRecentPage" data-on="click" data-arg="' + p + '">' + p + '</button>';
    }).join('');
  }

  const rows = recent.rows || [];
  // Terminal state of a request. Rows written before the outcome field only
  // carry error/status, so fall back to that; a client cancellation is shown
  // apart from a real failure because the gateway did nothing wrong.
  const outcomeBadge = r => {
    const o = r.outcome || (r.error ? 'failed' : 'completed');
    if(o === 'completed') return '<span class="badge ok">完成</span>';
    if(o === 'client_aborted') return '<span class="badge off">客户端取消</span>';
    if(o === 'upstream_aborted') return '<span class="badge warn">上游中断</span>';
    return '<span class="badge bad">失败</span>';
  };
  const countEl = document.getElementById('recentCount');
  if(countEl) countEl.textContent = '(第 ' + RECENT_PAGE + ' 页 / 共 ' + fmt(total) + ' 条)';
  // 推理强度：这次请求实际跑在哪个档位（网关写入 usage 行时的 reasoning_effort）。
  // 只有该字段存在才显示——老行与没有档位的模型都没有它。挂在"模型"格里复用
  // 模型库的 .badge-effort 样式，不新增第 15 列（表格已经 14 列了）。
  const effortChip = r => r.reasoning_effort
    ? ' <span class="badge-effort" title="本次请求实际使用的推理强度">' + esc(r.reasoning_effort) + '</span>'
    : '';
  // 账号列显示昵称：uid -> 昵称取自 /usage 的 accounts_map（当前账号池）。
  // 已删除/不存在的账号回退到 uid 前 8 位，避免留空。
  const acctName = (uid) => {
    if(!uid) return '—';
    const m = (t.accounts_map && t.accounts_map[uid]);
    return (m && m.nickname) ? m.nickname : String(uid).slice(0,8);
  };
  COST_TIP_ROWS.clear();
  document.getElementById('recent').innerHTML = rows.length ?
    '<table class="data-cards"><thead><tr><th>时间</th><th>模型</th><th>账号</th><th>模式</th><th>结果</th><th>耗时</th><th>首字</th><th>速度</th><th>输入</th><th>输出</th><th>思考</th><th>缓存</th><th>总 token</th><th>积分</th><th style="color:var(--warn)">OpenRouter 价估算</th></tr></thead><tbody>'
    + rows.map((r, i) => {
        const costKey = costRowKey(r, i);
        COST_TIP_ROWS.set(costKey, r);
        return '<tr>'
        + '<td class="mono" data-label="时间">' + esc((r.iso||'').replace('T',' ').slice(5)) + '</td>'
        + '<td class="mono" data-label="模型">' + esc(r.model) + effortChip(r) + '</td>'
        + '<td class="mono" style="font-size:11px;color:var(--dim)" data-label="账号" title="' + esc(r.account||'') + '">' + esc(acctName(r.account)) + '</td>'
        + '<td data-label="模式"><span class="badge ' + (r.stream?'s':'') + '">' + (r.stream?'流式':'非流式') + '</span></td>'
        + '<td data-label="结果">' + outcomeBadge(r) + '</td>'
        + '<td data-label="耗时">' + (r.elapsed_ms!=null ? fmt(r.elapsed_ms)+' ms' : '—') + '</td>'
        + '<td data-label="首字" title="' + esc(requestTimingHint(r)) + '">' + (r.first_text_ms!=null ? fmt(r.first_text_ms)+' ms' : r.ttft_ms!=null ? fmt(r.ttft_ms)+' ms' : '—') + '</td>'
        + '<td data-label="速度">' + fmtTokenRate(r.tokens_per_sec) + '</td>'
        + '<td data-label="输入">' + fmtTokens(r.prompt_tokens) + '</td>'
        + '<td data-label="输出">' + fmtTokens(r.completion_tokens) + '</td>'
        + '<td style="color:var(--think)" data-label="思考">' + fmtTokens(r.reasoning_tokens) + '</td>'
        + '<td data-label="缓存">' + fmtTokens(r.cached_tokens || 0)
        + ' <span style="color:var(--dim)">(' + (r.cache_hit_pct!=null ? r.cache_hit_pct+'%' : '—') + ')</span></td>'
        + '<td data-label="总 token"><b>' + fmtTokens(r.total_tokens) + '</b></td>'
        + '<td data-label="积分" style="color:var(--accent2)">' + (r.credit != null ? Number(r.credit).toFixed(2) : '—') + '</td>'
        + '<td data-label="OpenRouter 价估算" class="cost-cell" style="color:var(--warn)" data-cost-key="' + esc(costKey) + '">'
        +   fmtCost(r.cost_cny)
        +   (r.cost_backfilled ? '<span style="color:var(--dim)">*</span>' : '')
        + '</td>'
      + '</tr>';
      }).join('') + '</tbody></table>'
    : '<div class="empty">还没有请求记录</div>';
  reanchorCostTip();
}

(async function initDashboard(){
  await bootPanel();
})();

let RECENT_LIMIT = parseInt(localStorage.getItem('WB_RECENT_LIMIT') || '20', 10);
if(![10, 20, 50, 100].includes(RECENT_LIMIT)) RECENT_LIMIT = 20;
let RECENT_PAGE = 1;
let RECENT_TOTAL_PAGES = 1;

function updateRecentLimitButtons(){
  [10, 20, 50, 100].forEach(n => {
    const btn = document.getElementById('btnRecentLimit' + n);
    if(btn) btn.classList.toggle('active', RECENT_LIMIT === n);
  });
}

function setRecentLimit(n){
  RECENT_LIMIT = n;
  RECENT_PAGE = 1;
  try { localStorage.setItem('WB_RECENT_LIMIT', String(n)); } catch(e){}
  updateRecentLimitButtons();
  refresh();
}

async function changeRecentPage(delta){
  const next = RECENT_PAGE + delta;
  if(next < 1 || next > RECENT_TOTAL_PAGES) return;
  RECENT_PAGE = next;
  await refresh();
}

async function gotoRecentPage(p){
  if(p < 1 || p > RECENT_TOTAL_PAGES || p === RECENT_PAGE) return;
  RECENT_PAGE = p;
  await refresh();
}

function generatePageList(current, total){
  if(total <= 7){
    return Array.from({length: total}, (_, i) => i + 1);
  }
  const pages = [1];
  let start = Math.max(2, current - 2);
  let end = Math.min(total - 1, current + 2);
  if(current <= 4){
    end = 5;
  }
  if(current >= total - 3){
    start = total - 4;
  }
  if(start > 2) pages.push('...');
  for(let i = start; i <= end; i++){
    pages.push(i);
  }
  if(end < total - 1) pages.push('...');
  pages.push(total);
  return pages;
}

// Tab ids in nav order. One list so the restore path and the nav cannot
// drift apart.
const MAIN_TABS = ['gateway', 'accounts', 'tasks', 'analytics', 'models', 'keys', 'proxies', 'behavior', 'logs', 'settings'];
const MAIN_TAB_STORE = 'wb-proxy-main-tab';
let currentMainTab = 'gateway';
let analyticsRange = 'today';
let cachedMatrixData = null;
let matrixAcctFilter = '';
let matrixModelFilter = '';
// Model allowlist for the combined matrix; filled by loadAnalyticsMatrix().
let MATRIX_MODELS = new Set();


/* ---- panel password gate ---- */
function isAuthError(err){
  // Every 401/403 from the JSON helpers carries this message; the gate is
  // the single place that explains it, so callers stay quiet instead of
  // stacking an identical toast on top of it.
  return !!err && String(err.message) === 'unauthorized';
}

function panelNeedsLogin(){
  const gate = document.getElementById('panelGate');
  if(gate) gate.style.display = 'flex';
  const input = document.getElementById('panelPwdInput');
  if(input){ input.focus(); }
}

function panelSessionLost(){
  // The session this tab holds is no longer valid - the gateway restarted,
  // or the token expired. Drop it and stop every poller: leaving them
  // running means each tick fails, re-opens the gate and logs another 401
  // server-side, which is how a stale tab ends up filling the log.
  PANEL_READY = false;
  stopPanelStream();
  PANEL_TIMERS.forEach(t => clearInterval(t));
  PANEL_TIMERS = [];
  if(typeof stopLogPolling === 'function') stopLogPolling();
  PANEL_TOKEN = '';
  try { sessionStorage.removeItem(PANEL_STORE); } catch(e) {}
  const msg = document.getElementById('panelLoginMsg');
  if(msg) msg.textContent = '会话已失效，请重新输入密码';
  panelNeedsLogin();
}

function panelHideGate(){
  const gate = document.getElementById('panelGate');
  if(gate) gate.style.display = 'none';
}

async function submitPanelLogin(){
  const input = document.getElementById('panelPwdInput');
  const msg = document.getElementById('panelLoginMsg');
  const password = (input && input.value) || '';
  if(!password){ if(msg) msg.textContent = '请输入面板密码'; return; }
  if(msg) msg.textContent = '';
  try {
    const r = await fetch('/panel/login', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: password})
    });
    const data = await r.json().catch(() => ({}));
    if(!r.ok){
      if(msg) msg.textContent = (data.error && data.error.message) || '密码错误';
      return;
    }
    PANEL_TOKEN = data.token || '';
    try { sessionStorage.setItem(PANEL_STORE, PANEL_TOKEN); } catch(e) {}
    if(input) input.value = '';
    panelHideGate();
    toast('已进入面板', 'ok');
    if(data.using_default_password){
      toast('面板密码尚未初始化，请检查服务启动日志', 'warn');
    }
    await startDashboard();
  } catch(e) {
    if(msg) msg.textContent = '登录失败: ' + e.message;
  }
}

async function panelLogout(){
  try { await postJSON('/panel/logout', {}); } catch(e) {}
  PANEL_READY = false;
  stopPanelStream();
  PANEL_TIMERS.forEach(t => clearInterval(t));
  PANEL_TIMERS = [];
  PANEL_TOKEN = '';
  try { sessionStorage.removeItem(PANEL_STORE); } catch(e) {}
  location.reload();
}

async function bootPanel(){
  // Passwords are never accepted from URLs. Clear legacy links before login.
  const params = new URLSearchParams(window.location.search);
  if(params.has('pwd') || params.has('password')){
    params.delete('pwd'); params.delete('password');
    const query = params.toString();
    history.replaceState(null, '', window.location.pathname + (query ? '?' + query : '') + (window.location.hash || ''));
  }
  try {
    const r = await fetch('/panel/status', {cache: 'no-store', headers: authHeaders()});
    PANEL_STATUS = await r.json().catch(() => ({}));
  } catch(e) { PANEL_STATUS = {}; }
  const hint = document.getElementById('panelDefaultHint');
  if(hint && PANEL_STATUS.panel_password_is_default) hint.style.display = 'block';
  if(PANEL_STATUS.authenticated){
    panelHideGate();
    await startDashboard();
  } else {
    panelNeedsLogin();
  }
}

let PANEL_READY = false;
let PANEL_TIMERS = [];

const PANEL_STREAM = {controller:null, generation:0, reconnect:null, connected:false,
  lastSeen:0, failures:0, pending:new Set(), timer:null, flushing:false};
function panelStreamState(state, text){
  const indicator = document.getElementById('liveIndicator');
  const label = document.getElementById('liveStatusText');
  if(indicator) indicator.dataset.state = state;
  if(label) label.textContent = text;
}
function stopPanelStream(){
  PANEL_STREAM.generation++;
  if(PANEL_STREAM.controller) PANEL_STREAM.controller.abort();
  PANEL_STREAM.controller = null;
  PANEL_STREAM.connected = false;
  if(PANEL_STREAM.reconnect) clearTimeout(PANEL_STREAM.reconnect);
  if(PANEL_STREAM.timer) clearTimeout(PANEL_STREAM.timer);
  PANEL_STREAM.reconnect = PANEL_STREAM.timer = null;
  PANEL_STREAM.pending.clear();
  panelStreamState('waiting', document.hidden ? '已暂停' : '等待连接');
}
function startPanelStream(){
  stopPanelStream();
  if(!PANEL_READY || document.hidden) return;
  connectPanelStream(PANEL_STREAM.generation);
}
function queuePanelRefresh(topics){
  if(!PANEL_READY || document.hidden) return;
  for(const topic of topics || []){
    if(['usage','accounts','account_activity','tasks','scheduler','settings','logs','models','platforms'].includes(topic)) PANEL_STREAM.pending.add(topic);
  }
  if(!PANEL_STREAM.timer && !PANEL_STREAM.flushing){
    PANEL_STREAM.timer = setTimeout(flushPanelRefresh, 750);
  }
}
async function flushPanelRefresh(){
  PANEL_STREAM.timer = null;
  if(!PANEL_READY || document.hidden || PANEL_STREAM.flushing) return;
  const topics = new Set(PANEL_STREAM.pending);
  PANEL_STREAM.pending.clear();
  PANEL_STREAM.flushing = true;
  const jobs = [];
  if(topics.has('usage')){
    if(currentMainTab === 'gateway') jobs.push(refresh());
    if(currentMainTab === 'analytics') jobs.push(loadAnalytics(), loadAnalyticsMatrix());
    if(currentMainTab === 'logs') jobs.push(loadRequestArchive());
  }
  if(currentMainTab === 'accounts' && ['platforms','accounts','models','usage'].some(topic => topics.has(topic))) jobs.push(loadSourceAccounts());
  if(currentMainTab === 'settings' && topics.has('settings')) jobs.push(loadResponseStorage());
  if(topics.has('accounts') && ['gateway','accounts','tasks'].includes(currentMainTab)) jobs.push(loadAccounts());
  if(topics.has('tasks') && currentMainTab === 'tasks') jobs.push(loadGrowthTasks());
  if(topics.has('scheduler') && ['gateway','tasks'].includes(currentMainTab)) jobs.push(loadSchedulerStatus());
  if(topics.has('logs') && currentMainTab === 'logs' && logAutoRefresh) jobs.push(fetchNewLogs(false));
  // Model browsing is explicitly refreshed by navigation or the user.
  // Background catalogue events must not replace a table being read/edited.
  if(topics.has('account_activity')) renderAccounts();
  // Settings editors retain unsaved inputs. Their own save handlers reload
  // confirmed values; another admin's event must not erase a draft.
  try { await Promise.allSettled(jobs); }
  finally {
    PANEL_STREAM.flushing = false;
    if(PANEL_STREAM.pending.size) queuePanelRefresh([]);
  }
}
function acceptPanelFrame(frame){
  let event = 'message';
  const data = [];
  for(const line of frame.split('\n')){
    if(line.startsWith('event:')) event = line.slice(6).trim();
    else if(line.startsWith('data:')) data.push(line.slice(5).trimStart());
  }
  if(event === 'session_expired'){ panelSessionLost(); return; }
  if(event === 'refresh' && data.length){
    try {
      const update = JSON.parse(data.join('\n'));
      const topics = new Set(update.topics || []);
      const changes = update.changes || {};
      let unknown = false;
      for(const [uid, fields] of Object.entries(changes.accounts || {})){
        const account = (window.ACCOUNTS || []).find(a => a.uid === uid);
        if(!account){ unknown = true; continue; }
        for(const name of ['inFlight','pendingFreeTokens','pendingCredits']){
          if(Number.isFinite(fields[name])) account[name] = fields[name];
        }
        topics.add('account_activity');
      }
      for(const [uid, fields] of Object.entries(changes.usage || {})){
        if(!USAGE_BY_ACCOUNT[uid]){ unknown = true; continue; }
        const target = USAGE_BY_ACCOUNT[uid];
        for(const name of ['requests','errors','client_aborted','prompt_tokens','completion_tokens','reasoning_tokens','cached_tokens','total_tokens']){
          if(Number.isFinite(fields[name])) target[name] = (target[name] || 0) + fields[name];
        }
        topics.add('account_activity');
      }
      if(unknown) topics.add('accounts');
      queuePanelRefresh([...topics]);
    } catch(error){}
  }
}
async function connectPanelStream(generation){
  if(generation !== PANEL_STREAM.generation || !PANEL_READY || document.hidden) return;
  const controller = new AbortController();
  PANEL_STREAM.controller = controller;
  let reader = null;
  try {
    // fetch can carry X-Panel-Token. EventSource cannot set this header;
    // putting the token in a URL would expose it in history and access logs.
    const response = await fetch('/api/events?realm=all', {headers:authHeaders(), cache:'no-store', signal:controller.signal});
    if(response.status === 401 || response.status === 403){ panelSessionLost(); return; }
    if(!response.ok || !response.body) throw new Error('dashboard stream unavailable');
    if(generation !== PANEL_STREAM.generation) return;
    reader = response.body.getReader();
    PANEL_STREAM.connected = true;
    PANEL_STREAM.lastSeen = Date.now();
    panelStreamState('live','实时连接');
    const decoder = new TextDecoder();
    let buffer = '';
    while(generation === PANEL_STREAM.generation && PANEL_READY){
      const result = await reader.read();
      if(result.done) break;
      PANEL_STREAM.lastSeen = Date.now();
      PANEL_STREAM.failures = 0;
      buffer = (buffer + decoder.decode(result.value, {stream:true})).replace(/\r\n/g,'\n');
      if(buffer.length > 131072) throw new Error('dashboard stream frame too large');
      let boundary;
      while((boundary = buffer.indexOf('\n\n')) >= 0){
        acceptPanelFrame(buffer.slice(0,boundary));
        buffer = buffer.slice(boundary+2);
      }
    }
  } catch(error) {
    if(error.name === 'AbortError') return;
  } finally {
    if(reader){ try { await reader.cancel(); } catch(error){} }
    if(generation === PANEL_STREAM.generation){
      PANEL_STREAM.controller = null;
      PANEL_STREAM.connected = false;
      if(PANEL_READY && !document.hidden){
        panelStreamState('retry','正在重连');
        const delay = Math.min(30000, 3000 * Math.pow(2, Math.min(PANEL_STREAM.failures++, 4)));
        PANEL_STREAM.reconnect = setTimeout(() => connectPanelStream(generation), delay);
      }
    }
  }
}
document.addEventListener('visibilitychange', () => {
  if(document.hidden) stopPanelStream();
  else if(PANEL_READY){ startPanelStream(); queuePanelRefresh(['usage','accounts','tasks','scheduler','logs']); }
});
window.addEventListener('pagehide', stopPanelStream);


async function startDashboard(){
  if(PANEL_READY) return;
  PANEL_READY = true;
  // 前两步决定下面各自查什么（VIEW_REALM / 面板可见性），必须先行；之后就并行，
  // 别让国内版那条约 2 秒的成长任务接口把首屏的用量卡片拖在后面。
  await loadSettings();
  await initRealm();
  await Promise.all([loadAccounts(), loadGrowthTasks(),
                     loadSchedulerStatus(), refresh()]);
  updateRecentLimitButtons();
  // The head script already resolved this before first paint; re-apply it
  // here so the data loaders for the active page actually run.
  switchMainTab(MAIN_TABS.includes(window.__MAIN_TAB__) ? window.__MAIN_TAB__ : 'gateway');
  PANEL_TIMERS.forEach(t => clearInterval(t));
  startPanelStream();
  // Only disconnected or unsupported streams use the slow recovery poll.
  PANEL_TIMERS = [setInterval(() => {
    if(PANEL_READY && !document.hidden && (!PANEL_STREAM.connected || Date.now()-PANEL_STREAM.lastSeen > 45000)){
      queuePanelRefresh(['usage','accounts','tasks','scheduler','logs']);
    }
  }, 30000)];
}


/* ---- advanced settings (audit 2026-10-06) --------------------------------
 * The backend has validated these six groups since M1/M2. Keep the field
 * descriptions here rather than duplicating 49 static inputs in the markup;
 * renderAdvancedSettings() redraws the cards from GET /settings and each card
 * saves one deep-merge patch through /settings/save.
 */
