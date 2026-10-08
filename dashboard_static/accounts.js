function accountRow(a){
  const realmBadge = a.realm === 'cn'
    ? '<span class="realm-badge-cn">国内版</span>'
    : '<span class="realm-badge-intl">国际版</span>';
  // Inline handlers embed these in an HTML attribute, so they must survive
  // both the attribute and the quoted JS string. uid comes from an upstream
  // JWT; treat it as untrusted and keep it to a safe charset.
  const uidAttr = esc(String(a.uid || '').replace(/[^\w.@-]/g, ''));
  const nameAttr = esc(String(a.nickname || '').replace(/["'\\<>]/g, ''));
  const usage = USAGE_BY_ACCOUNT[a.uid] || {};
  const priority = a.priority ?? 100;
  const draft = ACCOUNT_PRIORITY_DRAFTS.has(a.uid) ? ACCOUNT_PRIORITY_DRAFTS.get(a.uid) : String(priority);
  const priorityValid = String(draft).trim() !== '' && Number.isInteger(Number(draft))
    && Number(draft) >= 0 && Number(draft) <= 2147483647;
  const priorityDirty = !priorityValid || Number(draft) !== priority;
  const prioritySaving = ACCOUNT_PRIORITY_SAVING.has(a.uid);
  const state = !a.enabled
              ? (a.sessionDeadFails > 0
                  ? '<span class="badge bad" title="Session 连续失效达到阈值后自动停用">Session失效 ' + a.sessionDeadFails + '/' + (a.sessionDeadThreshold || 3) + '</span>'
                  : '<span class="badge off">已停用</span>')
              : a.balanceCooledFor > 0 ? '<span class="badge bad" title="上游余额不足，等待签到/余额刷新恢复">402冷却 ' + a.balanceCooledFor + 's</span>'
              : a.breakerFor > 0 ? '<span class="badge bad">熔断 ' + a.breakerFor + 's</span>'
              : a.degradeFor > 0 ? '<span class="badge warn">降权 ' + a.degradeFor + 's</span>'
              : a.reserveBlocked ? '<span class="badge warn">保留积分</span>'
              : a.dailyLimitBlocked ? '<span class="badge warn" title="今日已用 ' + fmtTokens(a.dailyTokensToday || 0) + ' / ' + fmtTokens(a.dailyTokenLimit || 0) + ' token，暂停接单（本地 0 点恢复）">日限额</span>'
              : a.creditLimitReached ? '<span class="badge warn" title="今日已消费 ' + Number(a.dailyCreditsToday || 0).toFixed(2) + ' / ' + (a.dailyCreditLimit || 0) + ' 积分，仅免费模型可用（本地 0 点恢复）">积分限额</span>'
              : a.inCooldown ? '<span class="badge warn">冷却 ' + (a.cooldownFor||0) + 's</span>'
              : a.expiresIn === 'expired' ? '<span class="badge bad">已过期</span>'
              : '<span class="badge ok">可用</span>';
  const flight = (a.inFlight || a.maxInFlight)
              ? '<div style="margin-top:3px"><span class="badge ' + (a.maxInFlight && a.inFlight >= a.maxInFlight ? 'warn' : 's') + ' mini">在途 ' + (a.inFlight || 0) + '/' + (a.maxInFlight || 0) + '</span></div>'
              : '';
  const pending = (a.pendingFreeTokens || a.pendingCredits) ? '<div class="hint" title="在途消耗预估，仅用于公平调度，完成后按上游实际用量结算">预估在途 ' + fmtTokens(a.pendingFreeTokens || 0) + ' Token · ' + Number(a.pendingCredits || 0).toLocaleString('zh-CN', {maximumFractionDigits:2}) + ' 积分</div>' : '';
  const pills = coolPills(a);
  const limitPills = modelLimitPills(a);
  const err = a.lastError && !(pills && a.lastError === 'HTTP 429 (model throttled)')
    ? '<div class="hint" style="color:var(--warn);margin:2px 0 0">' + esc(a.lastError) + '</div>' : '';
  const cred = a.credits;
  let expBadge = '';
  if(cred && cred.earliest_expiring && cred.earliest_expiring.days_left !== undefined && cred.earliest_expiring.days_left !== null){
    const d = Number(cred.earliest_expiring.days_left);
    if(d <= 3 && d >= 0){
      expBadge = '<span class="badge mini bad" style="font-size:10px;padding:1px 4px" title="最近套餐包将于 ' + esc(cred.earliest_expiring.cycle_end_time.slice(5,10)) + ' 到期 (剩' + d.toFixed(1) + '天)">临期</span>';
    } else if(d <= 7 && d >= 0){
      expBadge = '<span class="badge mini warn" style="font-size:10px;padding:1px 4px" title="最近套餐包将于 ' + esc(cred.earliest_expiring.cycle_end_time.slice(5,10)) + ' 到期 (剩' + Math.ceil(d) + '天)">7天内到期</span>';
    }
  }
  const credText = cred
    ? ('<div style="display:inline-flex;align-items:center;gap:6px">'
       + '<b style="color:var(--accent2)">' + fmt(cred.remain) + '</b>'
       + '<span style="color:var(--dim)">/ ' + fmt(cred.size) + '</span>'
       + expBadge
       + '<span class="badge mini" style="font-size:10px;padding:1px 5px;cursor:pointer" data-action="openCreditsDetail" data-on="click" data-uid="' + uidAttr + '" title="点击查看积分与套餐明细">明细</span>'
       + '</div>')
    : ('<div style="display:inline-flex;align-items:center;gap:6px">'
       + '<span style="color:var(--dim)">未查询</span>'
       + '<span class="badge mini" style="font-size:10px;padding:1px 5px;cursor:pointer" data-action="openCreditsDetail" data-on="click" data-uid="' + uidAttr + '" title="点击查询积分明细">查询</span>'
       + '</div>');
  const todayCredit = a.dailyCreditsToday == null ? ''
    : '<div class="hint" title="付费模型优先选择同优先级内当日积分消耗少的账号">今日消费 '
      + Number(a.dailyCreditsToday).toLocaleString('zh-CN', {maximumFractionDigits:2}) + ' 积分</div>';
  const freeTokenText = a.freeTokensToday == null ? ''
    : '<div class="hint" title="免费模型按账号当天全部免费模型的 Token 总量均衡，国内与国际分别计算">今日免费 '
      + fmtTokens(a.freeTokensToday) + '</div>';
  return '<tr data-account-uid="' + esc(a.uid) + '">'
    + '<td style="text-align:center;white-space:nowrap" data-label="版本">' + realmBadge + '</td>'
    + '<td style="text-align:left" data-label="账号">'
    +   '<div style="font-weight:600;font-size:13px;color:var(--fg)">' + esc(a.nickname)
    + ' <span class="badge mini" title="已保存的账号调度优先级，数字越小越早调用">优先级 ' + priority + '</span></div>'
    + '<div class="mono" style="color:var(--dim);font-size:11px">' + esc(a.uid.slice(0,8)) + ' · ' + esc(a.source) + ' · 到期 ' + esc(a.expiresIn || '?') + '</div>'
    + (a.machineId ? ('<div class="mono" style="color:var(--dim);font-size:10px;margin-top:2px" title="由账号UID稳定派生的专属设备码，防多号关联风控">设备码: ' + esc(a.machineId.slice(0,14)) + '...</div>') : '')
    + err + pills + limitPills + '</td>'
    + '<td style="text-align:center" data-label="状态">' + state + flight + pending + '</td>'
    + '<td style="text-align:center" data-label="出口">' + slotSelectHtml(a) + '</td>'
    + '<td style="text-align:center" data-label="优先级">'
    + '<div class="account-priority" style="display:flex;flex-wrap:wrap;gap:5px;align-items:center;justify-content:center">'
    + '<input type="number" min="0" max="2147483647" step="1" value="' + esc(draft)
    + '" aria-label="账号调度优先级" title="数字越小越早调用；点击保存优先级后生效" style="width:76px"'
    + (prioritySaving ? ' disabled' : '')
    + ' data-action="editAccountPriority" data-on="input" data-uid="' + uidAttr + '">'
    + '<button class="sec mini" data-action="setAccountPriority" data-on="click" data-uid="' + uidAttr + '"'
    + (prioritySaving || !priorityValid || !priorityDirty ? ' disabled' : '') + '>保存优先级</button>'
    + '<span class="priority-status" role="status" style="font-size:11px;color:var(--dim);width:100%">'
    + (prioritySaving ? '保存中…' : !priorityValid ? '请填写非负整数' : priorityDirty ? '未保存' : '已保存 · 重启保留') + '</span></div></td>'
    + '<td style="text-align:left;white-space:nowrap" data-label="积分">' + credText + todayCredit + '</td>'
    + '<td style="text-align:right" data-label="请求">' + fmt(usage.requests) + '</td>'
    + '<td style="text-align:right" data-label="总 token">' + fmtTokens(usage.total_tokens) + freeTokenText + '</td>'
    + '<td style="text-align:right" data-label="缓存">' + fmtTokens(usage.cached_tokens) + '</td>'
    + '<td class="acct-actions" style="text-align:center;white-space:nowrap;vertical-align:middle">'
    + '<div class="acct-actions-col">'
    +   '<div class="acct-actions-row">'
    +     '<button class="sec mini"  data-action="toggleAccount" data-on="click" data-uid="' + uidAttr + '" data-arg="' + (!a.enabled ? '1' : '0') + '">' + (a.enabled ? '停用' : '启用') + '</button>'
    +     '<button class="sec mini"  data-action="testAccount" data-on="click" data-uid="' + uidAttr + '">测试</button>'
    +     '<button class="sec mini"  data-action="refreshOne" data-on="click" data-uid="' + uidAttr + '">刷新凭证</button>'
    +     '<button class="sec mini"  data-action="syncProfile" data-on="click" data-uid="' + uidAttr + '" title="从 Web 控制台同步最新昵称（改名后免重登）">同步昵称</button>'
    +     (a.realm === 'intl' ? ('<button class="sec mini"  data-action="activateGlobal" data-on="click" data-uid="' + uidAttr + '" title="补注册地区并激活国际版账号（幂等）">激活</button>'
    +       '<button class="sec mini"  data-action="claimTrial" data-on="click" data-uid="' + uidAttr + '" title="领取一次性 trial 加油包（幂等）">Trial</button>') : '')
    +   '</div>'
    +   '<div class="acct-actions-row">'
    +     '<div class="id-btn-group" title="出站身分：默认 WorkBuddy 桌面端 (WB) / 官方 VSCode 插件 (VSC) / 官方 CodeBuddy CLI (CLI)">'
    +       '<button class="id-btn' + ((!a.product || a.product === 'workbuddy') ? ' active' : '') + '"  data-action="setAccountProduct" data-on="click" data-uid="' + uidAttr + '" data-arg="workbuddy">WB</button>'
    +       '<button class="id-btn' + (a.product === 'vscode' ? ' active' : '') + '"  data-action="setAccountProduct" data-on="click" data-uid="' + uidAttr + '" data-arg="vscode">VSC</button>'
    +       '<button class="id-btn' + (a.product === 'cli' ? ' active' : '') + '"  data-action="setAccountProduct" data-on="click" data-uid="' + uidAttr + '" data-arg="cli">CLI</button>'
    +     '</div>'
    +     '<button class="sec mini"  data-action="exportOne" data-on="click" data-uid="' + uidAttr + '">导出</button>'
    +     '<button class="danger mini"  data-action="deleteAccount" data-on="click" data-uid="' + uidAttr + '" data-name="' + nameAttr + '">删除</button>'
    +   '</div>'
    + '</div>'
    + '</td></tr>';
}

function renderAccounts(){
  const box = document.getElementById('accounts');
  const active = document.activeElement;
  if(active && typeof box.contains === 'function' && box.contains(active)
      && ['INPUT','SELECT','TEXTAREA'].includes(active.tagName)){
    ACCOUNT_RENDER_DEFERRED = true;
    return;
  }
  ACCOUNT_RENDER_DEFERRED = false;
  const currentView = (window.VIEW_REALM || "intl");
  let list = (window.ACCOUNTS || []).filter(a => (a.realm || 'intl') === currentView);
  // Enabled accounts first, then scheduling priority; ties retain server order.
  list = list.map((a, i) => [a, i])
    .sort((x, y) => (x[0].enabled === y[0].enabled)
      ? ((x[0].priority ?? 100) - (y[0].priority ?? 100) || x[1] - y[1])
      : (x[0].enabled ? -1 : 1))
    .map(pair => pair[0]);
  const usable = list.filter(a => a.enabled).length;
  const viewName = currentView === 'cn' ? '国内版' : '国际版';
  document.getElementById('acctCount').textContent =
    list.length ? ('（' + viewName + '共 ' + list.length + ' 个，启用 ' + usable + ' 个）') : '';
  if(!list.length){
    box.innerHTML =
      '<div style="text-align:center;padding:30px 16px">'
      + '<div style="font-size:15px;margin-bottom:8px">当前' + viewName + '还没有账号</div>'
      + '<div style="color:var(--dim);font-size:13px;margin-bottom:18px">'
      +   '请先登录或导入一个 ' + viewName + ' 账号，之后相关请求都会走该账号'
      + '</div>'
      + '<button  data-action="openLoginModal" data-on="click" style="font-size:14px;padding:10px 22px">'
      +   '登录新账号 (OAuth)'
      + '</button>'
      + '</div>';
    return;
  }
  const pages = Math.max(1, Math.ceil(list.length / ACCOUNT_PAGE_SIZE));
  const page = Math.min(pages, ACCOUNT_PAGES.get(currentView) || 1);
  ACCOUNT_PAGES.set(currentView, page);
  const visible = list.slice((page - 1) * ACCOUNT_PAGE_SIZE, page * ACCOUNT_PAGE_SIZE);
  const markup = visible.map(accountRow);
  const body = typeof box.querySelector === 'function' && box.querySelector('tbody');
  if(body && ACCOUNT_PAGE_LAYOUT === currentView + ':' + page + ':' + list.length
      && body.children.length === visible.length
      && visible.every((a,i) => body.children[i].getAttribute('data-account-uid') === a.uid)){
    visible.forEach((a,i) => {
      if(ACCOUNT_ROW_HTML.get(a.uid) === markup[i]) return;
      const staging = document.createElement('tbody');
      staging.innerHTML = markup[i];
      body.children[i].replaceWith(staging.firstElementChild);
      ACCOUNT_ROW_HTML.set(a.uid, markup[i]);
    });
    return;
  }
  const wrap = typeof box.querySelector === 'function' && box.querySelector('.table-wrap');
  const scrollLeft = wrap ? wrap.scrollLeft : 0;
  box.innerHTML = '<div class="table-wrap"><table class="data-cards account-cards"><thead><tr>'
    + '<th style="text-align:center;width:76px">版本</th>'
    + '<th style="text-align:left">账号</th>'
    + '<th style="text-align:center;width:84px">状态</th>'
    + '<th style="text-align:center;width:150px">出口</th>'
    + '<th style="text-align:center;width:174px">调度优先级</th>'
    + '<th style="text-align:left;width:120px">积分</th>'
    + '<th style="text-align:right;width:70px">请求</th>'
    + '<th style="text-align:right;width:88px">总 token</th>'
    + '<th style="text-align:right;width:80px">缓存</th>'
    + '<th style="text-align:center;width:232px">操作</th>'
    + '</tr></thead><tbody>' + markup.join('') + '</tbody></table></div>'
    + (pages > 1 ? '<div class="legend"><button class="sec mini" data-action="accountPage" data-on="click" data-arg="' + (page-1) + '"' + (page === 1 ? ' disabled' : '') + '>上一页</button> <span>第 ' + page + ' / ' + pages + ' 页 · 每页 ' + ACCOUNT_PAGE_SIZE + ' 个账号</span> <button class="sec mini" data-action="accountPage" data-on="click" data-arg="' + (page+1) + '"' + (page === pages ? ' disabled' : '') + '>下一页</button></div>' : '')
    + '<div class="legend"><span>出站身份：WB = WorkBuddy 独立桌面客户端（默认），VSC = 官方 VSCode 插件，CLI = 官方 CodeBuddy CLI；三者对应不同的出站指纹与配额渠道。</span></div>'
    + '<div class="legend"><span>优先级默认 100，数字越小越早调用，点击“保存优先级”后写入 SQLite 并导出账号文件，重启保留；当前优先级没有可用账号时切到下一优先级。同一优先级内，免费模型比较今日免费 Token 加在途预估，付费模型比较今日积分消耗加在途预估；国内、国际分别均衡。</span></div>';
  ACCOUNT_PAGE_LAYOUT = currentView + ':' + page + ':' + list.length;
  ACCOUNT_ROW_HTML.clear();
  visible.forEach((a,i) => ACCOUNT_ROW_HTML.set(a.uid, markup[i]));
  const nextWrap = typeof box.querySelector === 'function' && box.querySelector('.table-wrap');
  if(nextWrap) nextWrap.scrollLeft = scrollLeft;
}

async function loadAccounts(){
  try{
    const [acct, byAcct] = await Promise.all([getJSON('/accounts?realm=all'), getJSON('/usage/by-account')]);
    window.ACCOUNTS = acct.accounts || [];
    if(acct.balance) renderAccountBalance(acct.balance);
    USAGE_BY_ACCOUNT = {};
    (byAcct.accounts || []).forEach(a => { USAGE_BY_ACCOUNT[a.account] = a; });
    if(!PROXY_SLOTS.length || Date.now() - PROXY_SLOTS_LOADED_AT > 60000) await loadProxySlots();
    renderAccounts();
    updateUI();
    // Auto-fetch credits once if not present
    if(window.ACCOUNTS.length && window.ACCOUNTS.some(a => !a.credits)
        && !ACCOUNT_CREDITS_FETCHING && Date.now() - ACCOUNT_CREDITS_FETCH_AT > 60000){
      ACCOUNT_CREDITS_FETCHING = true;
      ACCOUNT_CREDITS_FETCH_AT = Date.now();
      postJSON('/accounts/credits', {}).then(r => {
        window.ACCOUNTS = r.accounts || ACCOUNTS;
        renderAccounts();
      }).catch(()=>{}).finally(() => { ACCOUNT_CREDITS_FETCHING = false; });
    }
  }catch(e){ toast('账号加载失败: ' + e.message); }
}

function renderAccountBalance(balance){
  if(!balance) return;
  const number = value => Number(value).toLocaleString('zh-CN', {maximumFractionDigits:2});
  for(const [id, value, known, count] of [
    ['accountBalanceTotal', balance.total_remain, balance.known_count, balance.account_count],
    ['accountBalanceIntl', (balance.by_realm.intl || {}).total_remain, (balance.by_realm.intl || {}).known_count, (balance.by_realm.intl || {}).account_count],
    ['accountBalanceCn', (balance.by_realm.cn || {}).total_remain, (balance.by_realm.cn || {}).known_count, (balance.by_realm.cn || {}).account_count],
  ]){
    const el = document.getElementById(id);
    if(el) el.textContent = known || count === 0 ? number(value || 0) : '—';
  }
  const status = document.getElementById('accountBalanceStatus');
  if(status){
    const parts = [(balance.refreshed ? '已查询' : '已缓存') + ' ' + balance.known_count + '/' + balance.account_count + ' 个账号（含停用账号）'];
    if(balance.unknown_count) parts.push(balance.unknown_count + ' 个余额未知，合计仅含已知余额');
    if(balance.refresh_failed) parts.push(balance.refresh_failed + ' 个查询失败，保留其已有缓存余额');
    status.textContent = parts.join(' · ');
  }
}

async function queryBalances(btn){
  if(btn){ btn.disabled = true; btn.textContent = '查询中...'; }
  try{
    const balance = await postJSON('/accounts/balance', {});
    await loadAccounts();
    renderAccountBalance(balance);
    toast(balance.complete ? '全部账号余额查询完成' : '余额查询完成，部分账号余额未知或查询失败', balance.complete ? 'ok' : 'warn');
  }catch(e){ toast('余额查询失败: ' + e.message, 'bad'); }
  finally{ if(btn){ btn.disabled = false; btn.textContent = '查询全部余额'; } }
}

async function fetchCredits(btn){
  if(btn){ btn.disabled = true; btn.textContent = '刷新中...'; }
  const currentView = (window.VIEW_REALM || "intl");
  const viewName = currentView === 'cn' ? '国内版' : '国际版';
  try{
    const r = await postJSON('/accounts/credits', {realm: currentView});
    await loadAccounts();
    refresh();
    const count = (r.results || []).length;
    toast('已成功刷新当前' + viewName + ' ' + count + ' 个账号的积分', 'ok');
  }catch(e){
    toast('刷新积分失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '刷新积分'; }
  }
}
const queryCredits = fetchCredits;

async function toggleAccount(uid, enable, btn){
  if(btn) btn.disabled = true;
  try{
    await postJSON('/accounts/set', {uid: uid, enabled: enable});
    await loadAccounts();
    toast(enable ? '账号已成功启用' : '账号已停用', 'ok');
  }catch(e){
    toast('操作失败: ' + e.message, 'bad');
  }finally{
    if(btn) btn.disabled = false;
  }
}
document.addEventListener('focusout', event => {
  if(['INPUT','SELECT','TEXTAREA'].includes(event.target.tagName)){
    setTimeout(() => { if(ACCOUNT_RENDER_DEFERRED) renderAccounts(); }, 0);
  }
});
function editAccountPriority(uid, el){
  ACCOUNT_PRIORITY_DRAFTS.set(uid, el.value);
  const account = (window.ACCOUNTS || []).find(a => a.uid === uid);
  const previous = account ? (account.priority ?? 100) : 100;
  const value = Number(el.value);
  const valid = el.value.trim() && Number.isInteger(value) && value >= 0 && value <= 2147483647;
  const box = el.closest('.account-priority');
  const button = box.querySelector('button');
  button.disabled = !valid || value === previous || ACCOUNT_PRIORITY_SAVING.has(uid);
  box.querySelector('.priority-status').textContent = !valid ? '请填写非负整数' : value === previous ? '已保存 · 重启保留' : '未保存';
}
async function setAccountPriority(uid, el){
  const box = el.closest('.account-priority');
  const input = box.querySelector('input');
  const account = (window.ACCOUNTS || []).find(a => a.uid === uid);
  const previous = account ? (account.priority ?? 100) : 100;
  const value = Number(input.value);
  if(!input.value.trim() || !Number.isInteger(value) || value < 0 || value > 2147483647){
    toast('优先级须为 0 至 2147483647 的整数', 'warn');
    return;
  }
  if(ACCOUNT_PRIORITY_SAVING.has(uid) || value === previous) return;
  ACCOUNT_PRIORITY_SAVING.add(uid);
  input.disabled = true;
  el.disabled = true;
  box.querySelector('.priority-status').textContent = '保存中…';
  try{
    const result = await postJSON('/accounts/set', {uid: uid, priority: value});
    window.ACCOUNTS = (window.ACCOUNTS || []).map(a => a.uid === uid ? {...a, ...result.account} : a);
    ACCOUNT_PRIORITY_DRAFTS.delete(uid);
    toast('账号优先级 ' + value + ' 已保存，重启保留', 'ok');
  }catch(e){
    toast('优先级保存失败: ' + e.message, 'bad');
  }finally{
    ACCOUNT_PRIORITY_SAVING.delete(uid);
    input.disabled = false;
    renderAccounts();
  }
}
async function setAccountProduct(uid, prod, btn){
  const names = {
    'workbuddy': 'WorkBuddy 独立桌面客户端 (WB)',
    'vscode': '官方 VSCode 插件 (VSC)',
    'cli': '官方 CodeBuddy CLI (CLI)'
  };
  const label = names[prod] || prod;
  if(!confirm('将该账号的出站身份切换为 ' + label + '？\n\n不同身分对应不同的出站指纹、端点和配额渠道。')) return;
  if(btn){ btn.disabled = true; }
  try {
    const r = await postJSON('/accounts/product', {uid: uid, product: prod});
    toast('已切换为 ' + label, 'ok');
    await loadAccounts();
  } catch(e) {
    toast('切换失败: ' + e.message, 'bad');
  } finally {
    if(btn){ btn.disabled = false; }
  }
}
async function switchProduct(uid, btn){ return setAccountProduct(uid, 'workbuddy', btn); }

async function refreshOne(uid, btn){
  if(btn){ btn.disabled = true; btn.textContent = '刷新中...'; }
  try{
    const r = await postJSON('/accounts/refresh', {uid: uid});
    const ok = (r.results||[])[0];
    toast(ok && ok.ok ? '账号凭证刷新成功' : ('刷新失败: ' + (ok && ok.error || '未知错误')), ok && ok.ok ? 'ok' : 'bad');
    await loadAccounts();
  }catch(e){
    toast('刷新失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '刷新凭证'; }
  }
}
async function activateGlobal(uid, btn){
  if(btn){ btn.disabled = true; btn.textContent = '激活中...'; }
  try{
    const r = await postJSON('/accounts/global-register', {uid: uid});
    if(r.ok) toast('国际版账号已激活: ' + (r.detail || ''), 'ok');
    else toast('激活失败: ' + (r.error || '未知错误'), 'bad');
    await loadAccounts();
  }catch(e){
    toast('激活请求失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '激活'; }
  }
}
async function claimTrial(uid, btn){
  if(btn){ btn.disabled = true; btn.textContent = '领取中...'; }
  try{
    const r = await postJSON('/accounts/trial', {uid: uid});
    if(!r.ok) toast('Trial 领取失败: ' + (r.error || '未知错误'), 'bad');
    else toast(r.claimed ? 'Trial 加油包已领取' : 'Trial 已领过（幂等）', r.claimed ? 'ok' : 'warn');
    await loadAccounts();
  }catch(e){
    toast('Trial 请求失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = 'Trial'; }
  }
}
async function syncProfile(uid, btn){
  if(btn){ btn.disabled = true; btn.textContent = '同步中...'; }
  try{
    const r = await postJSON('/accounts/sync-profile', {uid: uid});
    const item = (r.updated || [])[0];
    const bad = (r.failed || [])[0];
    if(item && item.nickname) toast('昵称已同步: ' + item.nickname, 'ok');
    else if(bad) toast('同步失败: ' + bad.error, 'bad');
    else toast('同步完成（上游未返回昵称）', 'warn');
    await loadAccounts();
  }catch(e){
    toast('同步失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '同步昵称'; }
  }
}
async function testAccount(uid, btn){
  if(btn){ btn.disabled = true; btn.textContent = '测试中...'; }
  try{
    const r = await postJSON('/accounts/test', {uid: uid});
    if(r.ok){
      toast('测试通过 (' + r.elapsed_ms + 'ms) [' + r.model + ']: ' + (r.reply || '正常'), 'ok');
    } else {
      toast('测试失败: ' + (r.error || r.status || '异常'), 'bad');
    }
    await loadAccounts();
  }catch(e){
    toast('测试请求失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '测试'; }
  }
}
async function refreshAccounts(){
  try{ const r = await postJSON('/accounts/refresh', {});
       const okc = (r.results||[]).filter(x=>x.ok).length;
       toast('刷新完成: ' + okc + '/' + (r.results||[]).length);
       await loadAccounts(); }
  catch(e){ toast(e.message); }
}
async function setAll(enable, btn){
  if(btn) btn.disabled = true;
  const realm = window.VIEW_REALM || 'intl';
  try{
    await postJSON('/accounts/set-all', {enabled: enable, realm: realm});
    await loadAccounts();
    toast('已' + (enable ? '启用' : '停用') + (realm === 'cn' ? '国内版' : '国际版') + '全部账号', 'ok');
  }catch(e){
    toast('批量操作失败: ' + e.message, 'bad');
  }finally{
    if(btn) btn.disabled = false;
  }
}
async function deleteAccount(uid, name, btn){
  if(!confirm("确定删除账号 " + name + "？")) return;
  if(btn) btn.disabled = true;
  try{
    const res = await postJSON('/accounts/delete', {uid: uid});
    if(res.deleted === false) throw new Error('account not found');
    await loadAccounts();
    toast('已成功删除账号 ' + name, 'ok');
  }catch(e){
    toast('删除失败: ' + e.message, 'bad');
  }finally{
    if(btn) btn.disabled = false;
  }
}

/* ---- 账号导出 / 导入 ---- */
async function downloadExport(query, fallbackLabel){
  // Fetch through the authorised JSON API and save the blob client-side.
  // A plain <a href> would not carry the X-Panel-Token header, so a
  // password-only session would be rejected.
  const r = await fetch('/accounts/export' + (query || ''), {cache:'no-store', headers: authHeaders()});
  if(r.status === 401 || r.status === 403){ panelSessionLost(); throw new Error('unauthorized'); }
  if(r.status === 404){
    let msg = '账号不存在';
    try{ const e = await r.json(); msg = (e.error && e.error.message) || msg; }catch(_){}
    throw new Error(msg);
  }
  if(!r.ok) throw new Error('HTTP ' + r.status);
  const text = await r.text();
  let doc;
  try{ doc = JSON.parse(text); }catch(e){ throw new Error('返回内容不是 JSON'); }
  const stamp = new Date().toISOString().slice(0,19).replace(/[-:T]/g,'');
  const name = 'workbuddy-accounts-' + (fallbackLabel || '') + stamp + '.json';
  const blob = new Blob([text], {type:'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return {count: doc.count || 0, name: name};
}

async function exportAccounts(btn){
  if(btn){ btn.disabled = true; btn.textContent = '导出中...'; }
  try{
    const r = await downloadExport('?realm=' + encodeURIComponent(window.VIEW_REALM || 'intl'), '');
    toast('已导出 ' + r.count + ' 个账号 → ' + r.name);
  }catch(e){
    toast('导出失败: ' + e.message, 'err');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '导出账号'; }
  }
}

async function exportOne(uid){
  // Same document format as the bulk export, just narrowed to one account, so
  // the file can be re-imported on another instance without editing.
  try{
    const r = await downloadExport('?uid=' + encodeURIComponent(uid), uid.slice(0,8) + '-');
    toast('已导出 1 个账号 → ' + r.name);
  }catch(e){
    toast('导出失败: ' + e.message, 'err');
  }
}

let importRows = null;   // 已解析、待导入的账号行

function openImport(){
  importRows = null;
  const m = document.getElementById('importModal');
  const body = document.getElementById('importBody');
  const ow = document.getElementById('importOverwrite');
  if(ow) ow.checked = false;
  if(body) body.innerHTML = '<p class="hint">正在打开文件…</p>';
  if(m) m.classList.add('show');
  // The picker is created per call so choosing the same file twice still fires.
  const picker = document.createElement('input');
  picker.type = 'file';
  picker.accept = '.json,application/json';
  picker.onchange = () => {
    const f = picker.files && picker.files[0];
    if(!f){ closeImport(); return; }
    readImportFile(f);
  };
  picker.click();
}

function closeImport(){
  const m = document.getElementById('importModal');
  if(m) m.classList.remove('show');
  importRows = null;
  const btn = document.getElementById('btnImportCommit');
  if(btn) btn.disabled = true;
}

async function readImportFile(file){
  const body = document.getElementById('importBody');
  try{
    const text = await file.text();
    let doc;
    try{ doc = JSON.parse(text); }
    catch(e){ throw new Error('文件不是合法 JSON'); }

    // Accept the export document, a bare array, or a single account object.
    let rows;
    if(Array.isArray(doc)) rows = doc;
    else if(doc && Array.isArray(doc.accounts)) rows = doc.accounts;
    else if(doc && (doc.accessToken || doc.auth)) rows = [doc];
    else throw new Error('文件里没有找到账号（既没有 accounts 数组，也不是单个账号）');

    if(!rows.length) throw new Error('账号列表是空的');
    importRows = rows;

    // Dry-run first so the user sees exactly what will happen.
    const r = await postJSON('/accounts/import', {data: doc, dryRun: true});
    renderImportPreview(file.name, r.result || {}, rows.length);
  }catch(e){
    importRows = null;
    const btn = document.getElementById('btnImportCommit');
    if(btn) btn.disabled = true;
    if(body) body.innerHTML = '<p class="hint" style="color:var(--warn)">读取失败: ' + esc(e.message) + '</p>';
  }
}

function renderImportPreview(filename, res, total){
  const body = document.getElementById('importBody');
  const btn = document.getElementById('btnImportCommit');
  const added = res.added || [], updated = res.updated || [];
  const skipped = res.skipped || [], invalid = res.invalid || [];

  const rowsHtml = list => list.map(x => {
    const uid = (typeof x === 'string' ? x : x.uid) || '?';
    const reason = (typeof x === 'object' && x.reason) ? ' — ' + esc(x.reason) : '';
    return '<li><code>' + esc(String(uid).slice(0,8)) + '</code>' + reason + '</li>';
  }).join('');

  let html = '<p class="hint" style="margin-top:0">文件：<b>' + esc(filename) + '</b>'
    + ' · 共 ' + total + ' 条</p>';
  html += '<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:10px">'
    + '<span>新增 <b style="color:var(--accent2)">' + added.length + '</b></span>'
    + '<span>覆盖 <b>' + updated.length + '</b></span>'
    + '<span>跳过 <b>' + skipped.length + '</b></span>'
    + '<span>无效 <b style="color:var(--warn)">' + invalid.length + '</b></span>'
    + '</div>';

  if(added.length)   html += '<div style="margin-bottom:8px"><b>将新增</b><ul class="hint" style="margin:4px 0 0 18px;padding:0">' + rowsHtml(added) + '</ul></div>';
  if(updated.length) html += '<div style="margin-bottom:8px"><b>将覆盖</b><ul class="hint" style="margin:4px 0 0 18px;padding:0">' + rowsHtml(updated) + '</ul></div>';
  if(skipped.length) html += '<div style="margin-bottom:8px"><b>将跳过</b><ul class="hint" style="margin:4px 0 0 18px;padding:0">' + rowsHtml(skipped) + '</ul></div>';
  if(invalid.length) html += '<div style="margin-bottom:8px"><b>无法解析</b><ul class="hint" style="margin:4px 0 0 18px;padding:0">' + rowsHtml(invalid) + '</ul></div>';

  if(!added.length && !updated.length){
    html += '<p class="hint" style="color:var(--warn)">没有可导入的账号。'
      + (skipped.length ? '若要覆盖已存在的账号，请勾选下方「覆盖同 UID 账号」。' : '') + '</p>';
  }
  if(body) body.innerHTML = html;

  const canCommit = (added.length + updated.length) > 0;
  if(btn){
    btn.disabled = !canCommit;
    btn.textContent = '确认导入 ' + (added.length + updated.length) + ' 个';
  }
}

async function commitImport(btn){
  if(!importRows) return;
  const ow = document.getElementById('importOverwrite');
  const overwrite = !!(ow && ow.checked);
  if(overwrite && !confirm('将覆盖同 UID 的现有账号（含其凭证），确定继续？')) return;

  if(btn){ btn.disabled = true; btn.textContent = '导入中...'; }
  try{
    const r = await postJSON('/accounts/import', {data: importRows, overwrite: overwrite});
    const res = r.result || {};
    const n = (res.added || []).length + (res.updated || []).length;
    toast('导入完成：新增 ' + (res.added || []).length
          + '，覆盖 ' + (res.updated || []).length
          + '，跳过 ' + (res.skipped || []).length
          + '，无效 ' + (res.invalid || []).length);
    if(n > 0){ closeImport(); await loadAccounts(); }
    else { renderImportPreview('（已导入）', res, importRows.length); }
  }catch(e){
    toast('导入失败: ' + e.message, 'err');
    if(btn){ btn.disabled = false; btn.textContent = '确认导入'; }
  }
}

/* 桌面客户端账号：两步确认（先扫描展示弹窗，再逐条导入） */
async function scanDesktop(btn){
  if(btn){ btn.disabled = true; btn.textContent = '扫描中...'; }
  openDesktopScan();
  try{
    const acct = await getJSON('/accounts?realm=all').catch(() => ({accounts: []}));
    window.SCAN_POOL = new Set((acct.accounts || []).map(a => a.uid));
    const r = await postJSON('/accounts/import/desktop', {});
    renderDesktopScan(r.detected || [], r.atrest || null);
  }catch(e){
    const body = document.getElementById('desktopScanBody');
    if(body) body.innerHTML = '<p class="hint" style="color:var(--warn)">扫描失败: ' + esc(e.message) + '</p>';
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '扫描桌面客户端账号'; }
  }
}

/* --------------------------- credits detail modal --------------------------- */
let CURRENT_CREDIT_DETAIL_UID = null;
let CURRENT_CREDITS_DATA = null;
let CURRENT_PKG_FILTER = 'all';
let CURRENT_PKG_SEARCH = '';
let CURRENT_PKG_SORT = 'expiry_asc';

async function openCreditsDetail(uid, forceRefresh = false){
  CURRENT_CREDIT_DETAIL_UID = uid;
  CURRENT_PKG_FILTER = 'all';
  CURRENT_PKG_SEARCH = '';
  CURRENT_PKG_SORT = 'expiry_asc';

  const m = document.getElementById("creditsDetailModal");
  if(m) m.classList.add("show");

  const searchInput = document.getElementById("cmPkgSearch");
  if(searchInput) searchInput.value = "";
  const sortSelect = document.getElementById("cmPkgSort");
  if(sortSelect) sortSelect.value = "expiry_asc";

  // 重置过滤器按钮高亮
  const filterBtns = document.querySelectorAll(".realm-filter button[data-filter]");
  filterBtns.forEach(b => {
    if(b.getAttribute("data-filter") === "all") b.classList.add("active");
    else b.classList.remove("active");
  });

  const acct = (window.ACCOUNTS || []).find(a => a.uid === uid);
  const titleEl = document.getElementById("creditsModalTitle");
  const realmEl = document.getElementById("creditsModalRealm");
  const tierEl = document.getElementById("creditsModalTier");
  if(titleEl) titleEl.textContent = (acct ? (acct.nickname || acct.uid.slice(0,8)) : uid.slice(0,8)) + " · 积分明细";
  if(realmEl && acct){
    realmEl.className = acct.realm === 'cn' ? 'realm-badge-cn' : 'realm-badge-intl';
    realmEl.textContent = acct.realm === 'cn' ? '国内版' : '国际版';
  }
  if(tierEl){
    if(acct && acct.credits && acct.credits.is_paid_user !== undefined){
      tierEl.style.display = "inline-block";
      tierEl.className = acct.credits.is_paid_user ? "badge mini ok" : "badge mini";
      tierEl.textContent = acct.credits.is_paid_user ? "付费用户" : "普通用户";
    } else {
      tierEl.style.display = "none";
    }
  }

  // 检查已缓存的数据是否包含有效期字段，若包含且无需强制刷新，先秒开渲染本地已缓存数据
  const cachedPkgs = (acct && acct.credits && Array.isArray(acct.credits.packages)) ? acct.credits.packages : [];
  const hasExpiryData = cachedPkgs.length > 0 && cachedPkgs.some(p => p.cycle_end_time || p.cycleEndTime || p.CycleEndTime || p.expired_time || p.ExpiredTime);
  if(!forceRefresh && hasExpiryData){
    CURRENT_CREDITS_DATA = acct.credits;
    renderCreditsDetail(acct.credits, acct);
    return;
  }

  await reloadCreditsDetail();
}

async function reloadCreditsDetail(btn){
  if(!CURRENT_CREDIT_DETAIL_UID) return;
  const btnEl = btn || document.getElementById("btnRefreshCreditsDetail");
  if(btnEl){ btnEl.disabled = true; btnEl.textContent = "刷新中..."; }
  const loadingEl = document.getElementById("creditsModalLoading");
  const contentEl = document.getElementById("creditsModalContent");
  if(loadingEl && (!contentEl || contentEl.style.display === 'none')) loadingEl.style.display = "block";

  try {
    const res = await postJSON("/accounts/credits/detail", { uid: CURRENT_CREDIT_DETAIL_UID, refresh: true });
    if(res && res.ok && res.credits){
      CURRENT_CREDITS_DATA = res.credits;
      // 同步更新全局 window.ACCOUNTS 中的 credits
      const acct = (window.ACCOUNTS || []).find(a => a.uid === CURRENT_CREDIT_DETAIL_UID);
      if(acct){
        acct.credits = res.credits;
        renderAccounts();
      }
      renderCreditsDetail(res.credits, acct);
    } else {
      toast("拉取积分明细失败: " + ((res && res.error) || "请确认后端代理服务已重启以加载新代码"));
    }
  } catch(e) {
    toast("网络异常: " + e.message);
  } finally {
    if(loadingEl) loadingEl.style.display = "none";
    if(contentEl) contentEl.style.display = "block";
    if(btnEl){ btnEl.disabled = false; btnEl.textContent = "刷新明细"; }
  }
}

function filterCreditsPackages(filterType, btn){
  CURRENT_PKG_FILTER = filterType;
  const parent = btn && btn.parentNode;
  if(parent){
    parent.querySelectorAll("button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  }
  renderCreditsPackagesTable();
}

function onCreditsSearchInput(val){
  CURRENT_PKG_SEARCH = (val || "").trim().toLowerCase();
  renderCreditsPackagesTable();
}

function onCreditsSortChange(val){
  CURRENT_PKG_SORT = val || "expiry_asc";
  renderCreditsPackagesTable();
}

function renderCreditsDetail(credits, acct){
  if(!credits) return;
  CURRENT_CREDITS_DATA = credits;
  const remain = Number(credits.remain) || 0;
  const used = Number(credits.used) || 0;
  const size = Number(credits.size) || (remain + used);
  const usedPct = credits.used_percent || (size > 0 ? (used / size * 100).toFixed(1) + '%' : '0.0%');

  const elRemain = document.getElementById("cmMetricRemain");
  const elUsed = document.getElementById("cmMetricUsed");
  const elTotal = document.getElementById("cmMetricTotal");
  const elUsedPct = document.getElementById("cmUsedPercent");
  const elBar = document.getElementById("cmProgressBar");
  const elUpdated = document.getElementById("cmUpdatedText");

  if(elRemain) elRemain.textContent = fmt(remain);
  if(elUsed) elUsed.textContent = fmt(used);
  if(elTotal) elTotal.textContent = fmt(size);
  if(elUsedPct) elUsedPct.textContent = usedPct;
  if(elBar){
    const frac = size > 0 ? Math.min(100, Math.max(0, (used / size) * 100)) : 0;
    elBar.style.width = frac.toFixed(1) + "%";
    elBar.style.background = frac >= 90 ? "var(--bad)" : frac >= 70 ? "var(--warn)" : "var(--accent)";
  }
  if(elUpdated) elUpdated.textContent = "更新时间: " + (credits.updated_iso || "刚刚");

  // 会员等级徽章
  const tierEl = document.getElementById("creditsModalTier");
  if(tierEl){
    if(credits.is_paid_user !== undefined){
      tierEl.style.display = "inline-block";
      tierEl.className = credits.is_paid_user ? "badge mini ok" : "badge mini";
      tierEl.textContent = credits.is_paid_user ? "付费用户" : "普通用户";
    } else {
      tierEl.style.display = "none";
    }
  }

  // 最近到期卡片（优先取后端计算的 earliest_expiring，缺失时前端自动推导）
  const elExpVal = document.getElementById("cmExpiryValue");
  const elExpSub = document.getElementById("cmExpirySub");
  if(elExpVal && elExpSub){
    let ep = credits.earliest_expiring;
    if(!ep && Array.isArray(credits.packages)){
      const candidates = [];
      credits.packages.forEach(p => {
        const rem = Number(p.remain ?? p.CycleCapacityRemain) || 0;
        const eStr = p.cycle_end_time || p.cycleEndTime || p.CycleEndTime || p.expired_time || p.ExpiredTime || '';
        if(rem > 0 && eStr && eStr !== '-'){
          try {
            const clean = eStr.replace(/-/g, '/').replace('T', ' ');
            const ts = new Date(clean).getTime();
            if(!isNaN(ts)){
              const d = Math.round((ts - Date.now()) / 86400000 * 10) / 10;
              candidates.push({ name: p.name || '套餐包', remain: rem, cycle_end_time: eStr, days_left: d });
            }
          } catch(e){}
        }
      });
      if(candidates.length){
        candidates.sort((a, b) => a.days_left - b.days_left);
        ep = candidates[0];
      }
    }

    if(ep && ep.days_left !== undefined && ep.days_left !== null){
      const days = Number(ep.days_left);
      const endStr = String(ep.cycle_end_time || '');
      if(days < 0){
        elExpVal.textContent = "已有包过期";
        elExpVal.style.color = "var(--bad)";
        elExpSub.textContent = esc(ep.name) + " · 周期已过";
      } else if(days <= 3){
        elExpVal.textContent = "剩 " + days.toFixed(1) + " 天";
        elExpVal.style.color = "var(--bad)";
        elExpSub.textContent = esc(endStr.slice(5, 16)) + " · " + fmt(ep.remain) + " 积分即将到期";
      } else if(days <= 7){
        elExpVal.textContent = "剩 " + Math.ceil(days) + " 天";
        elExpVal.style.color = "var(--warn)";
        elExpSub.textContent = esc(endStr.slice(5, 10)) + " 到期 · " + fmt(ep.remain) + " 积分";
      } else {
        elExpVal.textContent = "剩 " + Math.floor(days) + " 天";
        elExpVal.style.color = "var(--fg)";
        elExpSub.textContent = esc(endStr.slice(5, 10)) + " 到期 · " + fmt(ep.remain) + " 积分";
      }
      elExpSub.title = (ep.name || "") + " (" + endStr + ")";
    } else {
      elExpVal.textContent = "长期有效";
      elExpVal.style.color = "var(--accent2)";
      elExpSub.textContent = "暂无临期生效套餐包";
    }
  }

  // 扩展状态（签到与会员信息）
  const checkinCard = document.getElementById("cmCheckinCard");
  const checkinText = document.getElementById("cmCheckinText");
  if(checkinCard && checkinText){
    let items = [];
    if(credits.checkin){
      const c = credits.checkin;
      const st = c.today_checked_in
        ? '<span style="color:var(--accent2);font-weight:600">今日已签到</span>'
        : '<span style="color:var(--warn);font-weight:600">今日未签到</span>';
      items.push('每日签到: ' + st + ' (连续 ' + (c.streak_days || 0) + ' 天)');
      if(c.daily_credit) items.push('签到奖励: ' + c.daily_credit + ' 积分');
      if(c.today_credit) items.push('今日领取: ' + c.today_credit + ' 积分');
    }
    if(credits.is_paid_user !== undefined){
      items.push('会员类型: ' + (credits.is_paid_user ? '<span class="badge ok mini">付费用户</span>' : '<span class="badge mini">普通/体验用户</span>'));
    }
    if(items.length){
      checkinText.innerHTML = items.join(' · ');
      checkinCard.style.display = "block";
    } else {
      checkinCard.style.display = "none";
    }
  }

  // 渲染套餐权益包明细表格
  renderCreditsPackagesTable();
}

function renderCreditsPackagesTable(){
  const credits = CURRENT_CREDITS_DATA;
  if(!credits) return;
  const tbody = document.getElementById("cmPackagesBody");
  if(!tbody) return;

  const rawPkgs = Array.isArray(credits.packages) ? credits.packages : [];
  const countBadge = document.getElementById("cmPkgCountBadge");
  if(countBadge) countBadge.textContent = "共 " + rawPkgs.length + " 个";

  // 统一预处理各套餐包的有效期与数值
  const preparedPkgs = rawPkgs.map(p => {
    const pSize = Number(p.size ?? p.total ?? p.CycleCapacitySize) || 0;
    const pUsed = Number(p.used ?? p.CycleCapacityUsed) || 0;
    const pRemain = Number(p.remain ?? p.CycleCapacityRemain) || 0;
    const endTime = p.cycle_end_time || p.cycleEndTime || p.CycleEndTime || p.expired_time || p.ExpiredTime || '';
    const startTime = p.cycle_start_time || p.cycleStartTime || p.CycleStartTime || '';

    let days = (p.days_left !== undefined && p.days_left !== null) ? Number(p.days_left) : null;
    if(days === null && endTime && endTime !== '-'){
      try {
        const cleanStr = endTime.replace(/-/g, '/').replace('T', ' ');
        const endTs = new Date(cleanStr).getTime();
        if(!isNaN(endTs)){
          days = Math.round((endTs - Date.now()) / 86400000 * 10) / 10;
        }
      } catch(e){}
    }
    const isExpired = p.is_expired !== undefined ? !!p.is_expired : (days !== null && days < 0);
    return {
      raw: p,
      name: p.name || '套餐包',
      package_code: p.package_code || p.packageCode || p.PackageCode || '',
      resource_id: p.resource_id || p.resourceId || p.ResourceId || '',
      grant_reason: p.grant_reason || p.grantReason || '',
      sub_product_name: p.sub_product_name || p.subProductName || p.SubProductName || '',
      in_usage: p.in_usage ?? p.inUsage ?? p.InUsage,
      auto_renew: p.auto_renew ?? p.autoRenew ?? p.AutoRenewFlag,
      size: pSize,
      used: pUsed,
      remain: pRemain,
      cycle_start_time: startTime,
      cycle_end_time: endTime,
      days_left: days,
      is_expired: isExpired
    };
  });

  // 过滤
  let pkgs = preparedPkgs.filter(p => {
    const remain = p.remain;
    const isExpired = p.is_expired;
    const daysLeft = p.days_left;

    if(CURRENT_PKG_FILTER === 'active'){
      if(remain <= 0 || isExpired) return false;
    } else if(CURRENT_PKG_FILTER === 'expiring'){
      if(isExpired || remain <= 0) return false;
      if(daysLeft === null || daysLeft > 7) return false;
    } else if(CURRENT_PKG_FILTER === 'exhausted'){
      if(remain > 0 && !isExpired) return false;
    }

    if(CURRENT_PKG_SEARCH){
      const q = CURRENT_PKG_SEARCH;
      const match = (p.name && p.name.toLowerCase().includes(q))
        || (p.package_code && p.package_code.toLowerCase().includes(q))
        || (p.grant_reason && p.grant_reason.toLowerCase().includes(q))
        || (p.sub_product_name && p.sub_product_name.toLowerCase().includes(q))
        || (p.resource_id && p.resource_id.toLowerCase().includes(q));
      if(!match) return false;
    }
    return true;
  });

  // 排序
  pkgs.sort((a, b) => {
    if(CURRENT_PKG_SORT === 'expiry_asc'){
      const inUseA = a.in_usage ? 0 : 1;
      const inUseB = b.in_usage ? 0 : 1;
      if(inUseA !== inUseB) return inUseA - inUseB;
      const expA = a.is_expired ? 1 : 0;
      const expB = b.is_expired ? 1 : 0;
      if(expA !== expB) return expA - expB;
      const daysA = a.days_left !== null ? a.days_left : 99999;
      const daysB = b.days_left !== null ? b.days_left : 99999;
      if(daysA !== daysB) return daysA - daysB;
      return (b.remain || 0) - (a.remain || 0);
    } else if(CURRENT_PKG_SORT === 'remain_desc'){
      return (b.remain || 0) - (a.remain || 0);
    } else if(CURRENT_PKG_SORT === 'used_desc'){
      return (b.used || 0) - (a.used || 0);
    } else if(CURRENT_PKG_SORT === 'size_desc'){
      return (b.size || 0) - (a.size || 0);
    }
    return 0;
  });

  if(!pkgs.length){
    tbody.innerHTML = '<tr><td colspan="6" class="empty" style="text-align:center;padding:24px;color:var(--dim)">无符合条件的套餐权益包</td></tr>';
    return;
  }

  tbody.innerHTML = pkgs.map(p => {
    const pSize = p.size;
    const pUsed = p.used;
    const pRemain = p.remain;
    const pct = pSize > 0 ? Math.min(100, (pUsed / pSize) * 100) : 0;
    const days = p.days_left;

    // 到期倒计时与周期格式化
    let expiryBadge = '';
    if(p.is_expired || (days !== null && days < 0)){
      expiryBadge = '<span class="badge mini off">已过期</span>';
    } else if(days !== null){
      if(days <= 3){
        expiryBadge = '<span class="badge mini bad">剩 ' + days.toFixed(1) + ' 天 (即将到期)</span>';
      } else if(days <= 7){
        expiryBadge = '<span class="badge mini warn">剩 ' + Math.ceil(days) + ' 天</span>';
      } else if(days < 365){
        expiryBadge = '<span class="badge mini ok">剩 ' + Math.floor(days) + ' 天</span>';
      } else {
        expiryBadge = '<span class="badge mini">长期有效</span>';
      }
    } else if(p.cycle_end_time){
      expiryBadge = '<span class="badge mini">正常</span>';
    }

    const cycleEndTimeStr = p.cycle_end_time ? p.cycle_end_time.slice(0, 19) : '-';
    const cycleStartTimeStr = p.cycle_start_time ? p.cycle_start_time.slice(0, 19) : '';

    // 来源/原因/产品描述
    const reasonParts = [];
    if(p.grant_reason) reasonParts.push(esc(p.grant_reason));
    if(p.sub_product_name && p.sub_product_name !== p.name) reasonParts.push(esc(p.sub_product_name));
    const reasonLine = reasonParts.length ? ('<div style="font-size:11px;color:var(--dim);margin-top:2px">' + reasonParts.join(' · ') + '</div>') : '';

    // 标识行
    const idParts = [];
    if(p.package_code) idParts.push(esc(p.package_code));
    if(p.resource_id) idParts.push(esc(p.resource_id));
    const idLine = idParts.length ? ('<div class="mono" style="font-size:10px;color:var(--dim);margin-top:2px">' + idParts.join(' · ') + '</div>') : '';

    // 状态标签
    let statusTags = '';
    if(p.in_usage){
      statusTags += '<span class="badge mini s" style="margin-left:4px;font-size:10px">生效中</span>';
    }
    if(p.auto_renew){
      statusTags += '<span class="badge mini ok" style="margin-left:4px;font-size:10px">自动续费</span>';
    }

    const barColor = pct >= 90 ? "var(--bad)" : pct >= 70 ? "var(--warn)" : "var(--accent)";

    return '<tr>'
      + '<td style="text-align:left;padding:8px 10px">'
      +   '<div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px">'
      +     '<span style="font-weight:600;color:var(--fg)">' + esc(p.name) + '</span>'
      +     statusTags
      +   '</div>'
      +   reasonLine
      +   idLine
      + '</td>'
      + '<td style="text-align:center;padding:8px 10px">'
      +   (expiryBadge ? ('<div style="margin-bottom:3px">' + expiryBadge + '</div>') : '')
      +   '<div class="mono" style="font-size:11px;color:var(--fg)" title="到期时间">' + esc(cycleEndTimeStr) + '</div>'
      +   (cycleStartTimeStr ? ('<div class="mono" style="font-size:10px;color:var(--dim)" title="生效时间">自 ' + esc(cycleStartTimeStr.slice(0, 10)) + '</div>') : '')
      + '</td>'
      + '<td style="text-align:right;padding:8px 10px;font-weight:600">' + fmt(pSize) + '</td>'
      + '<td style="text-align:right;padding:8px 10px;color:var(--dim)">' + fmt(pUsed) + '</td>'
      + '<td style="text-align:right;padding:8px 10px;color:var(--accent2);font-weight:700;font-size:13px">' + fmt(pRemain) + '</td>'
      + '<td style="text-align:center;padding:8px 10px">'
      +   '<div style="display:flex;align-items:center;justify-content:center;gap:6px">'
      +     '<span style="font-size:11px;min-width:34px;text-align:right">' + pct.toFixed(1) + '%</span>'
      +     '<div style="width:46px;height:5px;background:var(--line);border-radius:3px;overflow:hidden">'
      +       '<div style="width:' + pct.toFixed(1) + '%;height:100%;background:' + barColor + '"></div>'
      +     '</div>'
      +   '</div>'
      + '</td>'
      + '</tr>';
  }).join('');
}

function closeCreditsDetail(){
  const m = document.getElementById("creditsDetailModal");
  if(m) m.classList.remove("show");
  CURRENT_CREDIT_DETAIL_UID = null;
}

function openDesktopScan(){
  const m = document.getElementById('desktopScanModal');
  const body = document.getElementById('desktopScanBody');
  if(body) body.innerHTML = '<p class="hint">正在检测本地桌面客户端账号…</p>';
  if(m) m.classList.add('show');
}

function closeDesktopScan(){
  const m = document.getElementById('desktopScanModal');
  if(m) m.classList.remove('show');
}

async function refreshDesktopScan(btn){
  if(btn){ btn.disabled = true; btn.textContent = '扫描中...'; }
  const body = document.getElementById('desktopScanBody');
  if(body) body.innerHTML = '<p class="hint">正在检测本地桌面客户端账号…</p>';
  try{
    const r = await postJSON('/accounts/import/desktop', {});
    renderDesktopScan(r.detected || [], r.atrest || null);
  }catch(e){
    if(body) body.innerHTML = '<p class="hint" style="color:var(--warn)">扫描失败: ' + esc(e.message) + '</p>';
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '重新扫描'; }
  }
}

/* at-rest 密钥：桌面端把 token 加密存了，得先从客户端进程内存里把静态密钥
   找回来才能解密导入。密钥只留在网关进程内存里，不落盘、不写日志。 */
async function recoverAtrestKey(btn){
  const idle = btn.textContent;
  btn.disabled = true;
  btn.textContent = '正在扫描 WorkBuddy.exe 内存…';
  try{
    const r = await postJSON('/accounts/import/desktop', {recoverKey: true});
    if(!r.ok){ throw new Error(r.msg || '回收失败'); }
    toast('密钥已回收，正在重新扫描');
    await refreshDesktopScan();
  }catch(e){
    toast('回收失败: ' + e.message, 'err');
    btn.disabled = false;
    btn.textContent = idle;
    const tip = document.getElementById('atrestTip');
    if(tip){
      tip.innerHTML = '回收失败：' + esc(e.message)
        + '<br><span style="color:var(--dim)">请确认 WorkBuddy 桌面客户端正在运行并已登录；'
        + '权限不足时可以管理员身份运行网关再试一次。</span>';
    }
  }
}

function renderAtrestBar(atrest, list){
  if(!atrest) return '';
  if(atrest.keyCached){
    return '<div class="hint" style="margin:0 0 12px;color:var(--accent2)">解码密钥已就绪（keyId '
      + esc(atrest.keyId || '-') + '），加密凭据可直接导入。</div>';
  }
  if(!list.some(d => d.needsKey)) return '';
  let html = '<div style="background:var(--panel2);border:1px solid var(--line);border-radius:10px;'
    + 'padding:12px 14px;margin-bottom:14px;font-size:13px">'
    + '<b>检测到加密凭据</b><div class="hint" style="margin:6px 0 8px" id="atrestTip">'
    + '桌面客户端把 token 加密存储了，需要从正在运行的 WorkBuddy.exe 进程内存里回收静态密钥'
    + '（只读，密钥只留在网关内存里）。通常几秒钟，内存大时要十几秒。</div>';
  if(atrest.huntSupported){
    html += '<button class="primary mini" data-action="recoverAtrestKey" data-on="click">回收密钥</button>';
  }else{
    html += '<div class="hint" style="color:var(--warn)">当前系统（' + esc(atrest.platform)
      + '）不支持进程内存回收，请改用「+ 添加账号 (OAuth)」。</div>';
  }
  return html + '</div>';
}

function renderDesktopScan(list, atrest){
  const body = document.getElementById('desktopScanBody');
  if(!body) return;
  const valid = list.filter(d => d.valid);
  const bad = list.filter(d => !d.valid);
  const needKey = bad.filter(d => d.needsKey);
  const broken = bad.filter(d => !d.needsKey);
  // Use every account across both realms: the visible list is filtered by the
  // current view, so an earlier import could otherwise look "not imported".
  const already = window.SCAN_POOL && window.SCAN_POOL.size
    ? window.SCAN_POOL
    : new Set((window.ACCOUNTS || []).map(a => a.uid));

  const section = (title, items, cls) => {
    let html = '<div style="margin:14px 0 6px;font-size:12px;font-weight:600" class="' + cls + '">'
      + title + ' <span style="color:var(--dim);font-weight:400">(' + items.length + ')</span></div>';
    if(!items.length){
      html += '<div class="hint" style="margin:4px 0 10px">未检测到该版本账号</div>';
      return html;
    }
    html += '<table><thead><tr><th>账号</th><th>域名</th><th>有效期</th><th></th></tr></thead><tbody>';
    items.forEach(d => {
      const dup = already.has(d.uid);
      // NOTE: never interpolate the path into an inline onclick - JSON.stringify
      // emits double quotes, which would terminate the HTML attribute and make
      // the button silently do nothing. Use a data attribute + delegation.
      const act = dup
        ? '<span class="badge off">已导入</span>'
        : '<button class="primary mini btn-import-desktop"'
          + ' data-path="' + esc(d.path) + '"'
          + ' data-realm="' + esc(d.realm) + '">导入</button>';
      html += '<tr>'
        + '<td><b>' + esc(d.nickname || (d.uid||'').slice(0,8)) + '</b>'
        + '<div class="mono" style="font-size:11px;color:var(--dim)">' + esc((d.uid||'').slice(0,8)) + ' · ' + esc(d.file) + '</div></td>'
        + '<td class="mono" style="font-size:11px">' + esc(d.domain || '-') + '</td>'
        + '<td>' + esc(d.expiresIn || '未知') + '</td>'
        + '<td style="text-align:right">' + act + '</td>'
        + '</tr>';
    });
    html += '</tbody></table>';
    return html;
  };

  let html = renderAtrestBar(atrest, list);
  if(!list.length && !html){
    body.innerHTML = '<p class="hint">未在本地检测到桌面客户端登录凭证。<br>'
      + '请确认已安装并登录 WorkBuddy 客户端后点「重新扫描」。</p>';
    return;
  }
  if(list.length){
    html += section('国际版 (Global) · www.workbuddy.ai',
                    valid.filter(d => d.realm !== 'cn'), '');
    html += section('国内版 (China) · copilot.tencent.com',
                    valid.filter(d => d.realm === 'cn'), '');
  }

  if(needKey.length){
    html += '<div style="margin:14px 0 6px;font-size:12px;font-weight:600;color:var(--warn)">'
      + '待解码的凭证（加密存储）</div>';
    html += '<table><tbody>';
    needKey.forEach(d => {
      html += '<tr><td class="mono" style="font-size:11px">' + esc(d.file) + '</td>'
        + '<td style="color:var(--dim);font-size:12px;text-align:right">需要先回收密钥</td></tr>';
    });
    html += '</tbody></table>';
  }
  if(broken.length){
    html += '<div style="margin:14px 0 6px;font-size:12px;font-weight:600;color:var(--warn)">无法读取的凭证</div>';
    html += '<table><tbody>';
    broken.forEach(d => {
      html += '<tr><td class="mono" style="font-size:11px">' + esc(d.file) + '</td>'
        + '<td style="color:var(--warn);font-size:12px;text-align:right">' + esc(d.error || '未知原因') + '</td></tr>';
    });
    html += '</tbody></table>';
  }
  if(!html){
    html = '<p class="hint">未在本地检测到桌面客户端登录凭证。<br>'
      + '请确认已安装并登录 WorkBuddy 客户端后点「重新扫描」。</p>';
  }
  body.innerHTML = html;
  // Wire the import buttons through event delegation (see renderDesktopScan).
  body.querySelectorAll('.btn-import-desktop').forEach(btn => {
    btn.addEventListener('click', () => {
      doImportDesktop(btn, btn.getAttribute('data-path'), btn.getAttribute('data-realm'));
    });
  });
}

async function doImportDesktop(btn, path, realm){
  btn.disabled = true;
  btn.textContent = '导入中...';
    try{
    const r = await postJSON('/accounts/import/desktop', {path: path, realm: realm});
    const a = (r.imported || [])[0] || {};
    toast('已导入 ' + (a.nickname || (a.uid||'').slice(0,8)) + ' 到 ' + (a.realm === 'cn' ? '国内版' : '国际版'));
    if(a.uid && window.SCAN_POOL) window.SCAN_POOL.add(a.uid);
    await loadAccounts();
    await refresh();
    try {
      const s = await postJSON('/accounts/import/desktop', {});
      if(s.pool_uids) window.SCAN_POOL = new Set(s.pool_uids);
      renderDesktopScan(s.detected || [], s.atrest || null);
    } catch(e2) { /* keep the refreshed toasts; list will refresh on next scan */ }
    // The scan list is filtered by the current view; tell the user where the
    // account actually landed so this never looks like a no-op.
    if(a.realm && a.realm !== window.VIEW_REALM){
      toast('该账号属于' + (a.realm === 'cn' ? '国内版' : '国际版')
            + '列表，点击上方选项卡即可查看', 'err');
    }
  }catch(e){
    toast('导入失败: ' + e.message, 'err');
    btn.disabled = false;
    btn.textContent = '导入';
  }
}

/* ------------------------------- dashboard ------------------------------ */
let REFRESH_RUNNING = false;
let REFRESH_QUEUED = false;
let REFRESH_GEN = 0;
