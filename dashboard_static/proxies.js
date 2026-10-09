let PROXY_SLOTS = [];
/* 编辑器里有未保存改动时为 true（issue #79）。
 *
 * 刷新槽位是「拉服务端列表 → 整体替换 → 重绘整张表」，而「+ 添加槽位」只是把
 * 一行 push 进本地列表、服务端并不知道它存在；loadAccounts() 每 15 秒会顺带
 * 刷新一次槽位，于是刚加的那行（以及改了一半的已有行）会被服务端的旧列表顶掉。
 * 置位期间跳过刷新，保存成功后清零。 */
let SLOTS_DIRTY = false;
let SLOT_DISCOVER = [];

function slotSelectHtml(a){
  const current = a.proxySlot || '';
  // A legacy per-account proxy URL still routes traffic while no slot is
  // bound. Surface it instead of pretending the account is direct.
  const legacy = (!current && a.proxy) ? String(a.proxy) : '';
  const legacyLabel = legacy.length > 28 ? legacy.slice(0, 25) + '...' : legacy;
  const opts = [];
  if(legacy){
    opts.push('<option value="__legacy__" selected>旧代理：' + esc(legacyLabel) + '</option>');
    opts.push('<option value="">直连（清除旧代理）</option>');
  } else {
    opts.push('<option value=""' + (current ? '' : ' selected') + '>直连</option>');
  }
  opts.push.apply(opts, PROXY_SLOTS.map(s =>
    '<option value="' + esc(s.id) + '"' + (s.id === current ? ' selected' : '') + '>'
    + esc(s.label || s.name || s.id) + (s.enabled === false ? '（停用）' : '') + '</option>'));
  const uidAttr = esc(String(a.uid || '').replace(/[^\w.@-]/g, ''));
  return '<select class="slot-select"  data-action="setAccountSlot" data-on="change" data-uid="' + uidAttr + '">'
    + opts.join('') + '</select>';
}

async function setAccountSlot(uid, slotId, el){
  if(slotId === '__legacy__') return;
  if(el) el.disabled = true;
  try{
    await postJSON('/accounts/set', {uid: uid, proxySlot: slotId});
    toast('出口已更新', 'ok');
    await loadAccounts();
    await loadProxySlots();
  }catch(e){
    toast('出口更新失败: ' + e.message, 'bad');
  }finally{
    if(el) el.disabled = false;
  }
}

let PROXY_SLOTS_LOADED_AT = 0;
async function loadProxySlots(force){
  // 编辑器有未保存改动时不动它：轮询与「切到设置页」都不该覆盖正在填的内容。
  if(SLOTS_DIRTY && !force) return;
  try{
    const r = await getJSON('/proxy/slots');
    PROXY_SLOTS = r.slots || [];
    PROXY_SLOTS_LOADED_AT = Date.now();
    renderProxySlots();
  }catch(e){
    // Panel not logged in yet; actions on the settings page surface errors.
  }
}

/* 标题旁的状态提示。单独抽出来，是因为标记「未保存」时只能更新这段文字，
 * 不能重绘表格——重绘会让正在输入的那个框失焦。 */
function renderSlotState(){
  const stateEl = document.getElementById('slotState');
  if(!stateEl) return;
  const parts = [];
  if(PROXY_SLOTS.length) parts.push(PROXY_SLOTS.length + ' 个');
  if(SLOTS_DIRTY) parts.push('未保存');
  stateEl.textContent = parts.length ? ('（' + parts.join(' · ') + '）') : '';
  stateEl.style.color = SLOTS_DIRTY ? 'var(--warn)' : '';
}

function markSlotsDirty(){
  if(SLOTS_DIRTY) return;
  SLOTS_DIRTY = true;
  renderSlotState();
}

/* 出口信息的展示口径，与服务端 wb_ipintel 保持一致：hosting 地址算机房，
   其余算住宅；国家名由查询服务直接给中文。 */
const IP_TYPE_LABELS = {residential: '住宅', datacenter: '机房'};

function ipTypeLabel(t){ return IP_TYPE_LABELS[t] || ''; }

/* 默认名称：国家 + 类型（如「美国 住宅」）。没有国家就不自动命名——只有
   「住宅」两个字区分不了不同槽位，此时回退显示槽位 id。 */
function autoSlotName(c){
  const where = String((c && c.country) || '').trim();
  if(!where) return '';
  const kind = ipTypeLabel(c && c.ip_type);
  return kind ? (where + ' ' + kind) : where;
}

/* 保存时要把探测到的出口字段一起送回，否则一次保存就把它们抹掉了。 */
function slotPayload(){
  return PROXY_SLOTS.map(s => ({
    id: s.id || '', name: s.name || '', url: (s.url || '').trim(),
    username: s.username || '', password: s.password || '',
    enabled: s.enabled !== false,
    ip: s.ip || '', country: s.country || '', country_code: s.country_code || '',
    ip_type: s.ip_type || '', isp: s.isp || '', asn: s.asn || '',
    probed_at: s.probed_at || 0,
  }));
}

function slotExitHtml(s){
  if(!s.ip) return '<span style="color:var(--dim-light)">未探测</span>';
  const kind = ipTypeLabel(s.ip_type);
  const badge = kind
    ? '<span class="badge ' + (kind === '住宅' ? 's' : '') + '" style="font-size:11px">' + kind + '</span>'
    : '';
  const where = [s.country ? esc(s.country) : '', badge].filter(Boolean).join(' ');
  const tip = [s.isp, s.asn].filter(Boolean).join(' · ');
  return '<div class="mono" style="font-size:12px">' + esc(s.ip) + '</div>'
    + '<div style="font-size:12px;color:var(--dim);margin-top:2px"'
    + (tip ? ' title="' + esc(tip) + '"' : '') + '>'
    + (where || '<span style="color:var(--dim-light)">国家未知</span>') + '</div>';
}

function renderProxySlots(){
  const box = document.getElementById('slotList');
  if(!box) return;
  renderSlotState();
  if(!PROXY_SLOTS.length){
    box.innerHTML = '<div class="hint" style="color:var(--dim)">还没有代理槽。点击「自动发现 mihomo 端口」或「+ 添加槽位」。</div>';
    return;
  }
  box.innerHTML = '<div class="table-wrap"><table class="data-cards"><thead><tr>'
    + '<th style="width:150px">名称</th>'
    + '<th>代理地址</th>'
    + '<th style="width:150px">出口</th>'
    + '<th style="width:90px;text-align:center">启用</th>'
    + '<th style="width:90px;text-align:center">绑定账号</th>'
    + '<th style="width:190px;text-align:center">操作</th>'
    + '</tr></thead><tbody>'
    + PROXY_SLOTS.map((s, i) =>
        '<tr>'
        + '<td data-label="名称"><input value="' + esc(s.name || '') + '"  data-action="onProxySlotNameInput" data-on="input" data-arg="' + i + '" class="slot-input"></td>'
        + '<td data-label="代理地址"><input value="' + esc(s.url || '') + '" placeholder="http://host:port 或 socks5h://host:port" aria-label="代理地址" data-action="onProxySlotUrlInput" data-on="input" data-arg="' + i + '" class="slot-input mono">'
        + '<div style="display:flex;gap:6px;margin-top:6px;flex-wrap:wrap">'
        + '<input value="' + esc(s.username || '') + '" placeholder="用户名（可选）" aria-label="代理用户名" autocomplete="off" data-action="onProxySlotUsernameInput" data-on="input" data-arg="' + i + '" class="slot-input" style="flex:1;min-width:90px;width:90px">'
        + '<input type="password" value="' + esc(s.password || '') + '" placeholder="密码（可选）" aria-label="代理密码" autocomplete="new-password" data-action="onProxySlotPasswordInput" data-on="input" data-arg="' + i + '" class="slot-input" style="flex:1;min-width:90px;width:90px">'
        + '</div></td>'
        + '<td data-label="出口">' + slotExitHtml(s) + '</td>'
        + '<td style="text-align:center" data-label="启用"><input type="checkbox" ' + (s.enabled === false ? '' : 'checked')
        +   '  data-action="onProxySlotEnabledChange" data-on="change" data-arg="' + i + '"></td>'
        + '<td style="text-align:center" data-label="绑定账号">' + (s.bound || 0) + '</td>'
        + '<td style="text-align:center;white-space:nowrap" data-label="">'
        +   '<button class="sec mini"  data-action="testProxySlot" data-on="click" data-arg="' + i + '">测试</button> '
        +   '<button class="danger mini"  data-action="removeProxySlot" data-on="click" data-arg="' + i + '">删除</button>'
        + '</td></tr>'
      ).join('')
    + '</tbody></table></div>'
    + '<div class="legend"><span>「绑定账号」只统计已启用账号；停用账号会自动释放槽位，重新启用后需重新绑定。在网关页账号表的「出口」下拉中调整绑定。名称留空时按出口自动显示「国家 类型」，点「测试」会补全出口信息并据此命名。</span></div>';
}

function addProxySlotRow(){
  SLOTS_DIRTY = true;
  // 名称留空：探测到出口后按「国家 类型」自动命名，填过就按填的显示。
  PROXY_SLOTS.push({id: '', name: '', url: '', enabled: true, bound: 0});
  renderProxySlots();
}

function removeProxySlot(index){
  const s = PROXY_SLOTS[index];
  if(!s) return;
  if((s.bound || 0) > 0 && !confirm('该槽位被 ' + s.bound + ' 个账号绑定，删除后它们将回退直连。继续？')) return;
  SLOTS_DIRTY = true;
  PROXY_SLOTS.splice(index, 1);
  renderProxySlots();
}

async function saveProxySlots(btn){
  if(btn) btn.disabled = true;
  try{
      const r = await postJSON('/proxy/slots/save', {slots: slotPayload()});
      PROXY_SLOTS = r.slots || [];
      SLOTS_DIRTY = false;
      renderProxySlots();
      await loadAccounts();
      toast('已保存 ' + PROXY_SLOTS.length + ' 个代理槽', 'ok');
  }catch(e){
    toast('保存失败: ' + e.message, 'bad');
  }finally{
    if(btn) btn.disabled = false;
  }
}

async function testProxySlot(index, btn){
  const s = PROXY_SLOTS[index];
  if(!s || !s.url){ toast('槽位还没有填写代理地址', 'warn'); return; }
  if(btn){ btn.disabled = true; btn.textContent = '测试中...'; }
  try{
    let id = s.id;
    if(!id){
      const r = await postJSON('/proxy/slots/save', {slots: slotPayload()});
      PROXY_SLOTS = r.slots || [];
      SLOTS_DIRTY = false;
      renderProxySlots();
      id = (PROXY_SLOTS[index] || {}).id;
    }
    const r = await postJSON('/proxy/slots/test', {id: id});
    if(r.ok){
      // 服务端已把出口信息写进槽位，这里只把这一行同步过来，不整表重载——
      // 其他行里还没保存的输入都还在 PROXY_SLOTS 里，重绘不会丢。
      const row = PROXY_SLOTS[index];
      if(row && r.slot){
        ['ip', 'country', 'country_code', 'ip_type', 'isp', 'asn', 'probed_at'].forEach(k => {
          if(r.slot[k] !== undefined) row[k] = r.slot[k];
        });
        if(r.slot.name) row.name = r.slot.name;
        row.label = row.name || autoSlotName(row) || row.id;
        renderProxySlots();
      }
      const where = [r.country, ipTypeLabel(r.ip_type)].filter(Boolean).join(' ');
      toast('出口 ' + r.exit_ip + (where ? ' · ' + where : '') + '（' + r.latency_ms + 'ms）', 'ok');
    }else{
      toast('测试失败: ' + (r.error || 'unknown'), 'bad');
    }
  }catch(e){
    toast('测试失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '测试'; }
  }
}

async function discoverProxySlots(btn){
  if(btn){ btn.disabled = true; btn.textContent = '探测中...'; }
  try{
    const r = await postJSON('/proxy/discover', {});
    SLOT_DISCOVER = r.candidates || [];
    renderDiscover();
    const ok = SLOT_DISCOVER.filter(c => c.reachable).length;
    toast('发现 ' + ok + ' 个可用出口', ok ? 'ok' : 'warn');
  }catch(e){
    toast('自动发现失败: ' + e.message, 'bad');
  }finally{
    if(btn){ btn.disabled = false; btn.textContent = '自动发现 mihomo 端口'; }
  }
}

function renderDiscover(){
  const box = document.getElementById('slotDiscover');
  if(!box) return;
  if(!SLOT_DISCOVER.length){ box.innerHTML = ''; return; }
  box.innerHTML = '<div style="margin-top:14px"><div style="font-size:12px;color:var(--dim);margin-bottom:8px">'
    + '勾选要导入为槽位的出口：</div>'
    + SLOT_DISCOVER.map((c, i) =>
        '<label style="display:flex;align-items:center;gap:8px;padding:6px 0;font-size:13px">'
        + '<input type="checkbox" ' + (c.reachable ? 'checked' : 'disabled') + ' data-idx="' + i + '">'
        + '<span class="mono">' + esc(c.url) + '</span>'
        + '<span style="color:' + (c.reachable ? 'var(--accent2)' : 'var(--bad)') + '">'
        + (c.reachable
            ? ('出口 ' + esc(c.exit_ip)
               + (autoSlotName(c) ? ' · ' + esc(autoSlotName(c)) : '')
               + ' · ' + c.latency_ms + 'ms')
            : '不可达') + '</span>'
        + '</label>').join('')
    + '<button class="sec"  data-action="importDiscovered" data-on="click" style="margin-top:8px">导入勾选的出口</button></div>';
}

function importDiscovered(){
  const box = document.getElementById('slotDiscover');
  if(!box) return;
  const picked = Array.from(box.querySelectorAll('input[type=checkbox]:checked')).map(el => SLOT_DISCOVER[+el.dataset.idx]);
  if(!picked.length){ toast('没有勾选任何出口', 'warn'); return; }
  picked.forEach(c => {
    if(PROXY_SLOTS.some(s => s.url === c.url)) return;
    // 导入时就把探测到的出口信息一起带上。名称留空：空名称 = 「按出口自动命名」，
    // 标签由 country/ip_type 每次现算，所以出口换了名字跟着换；写进 name 就成了
    // 用户名称，会被 slot_label() 永久优先，出口变了也还显示旧的国家。
    PROXY_SLOTS.push({
      id: '', name: '', url: c.url, enabled: true, bound: 0,
      ip: c.exit_ip || '', country: c.country || '', country_code: c.country_code || '',
      ip_type: c.ip_type || '', isp: c.isp || '', asn: c.asn || '',
      probed_at: Math.floor(Date.now() / 1000),
    });
  });
  renderProxySlots();
  toast('已加入 ' + picked.length + ' 个槽位，记得点「保存槽位」', 'ok');
}

async function autoAssignSlots(){
  // Only fills in accounts that have no exit yet: an account that is already
  // bound keeps its slot, so this is not a rebalancer.
  const realm = window.VIEW_REALM || 'intl';
  const unbound = (window.ACCOUNTS || []).filter(a => (a.realm || 'intl') === realm && a.enabled && !a.proxySlot);
  if(!unbound.length){ toast('所有已启用账号都已绑定代理出口', 'ok'); return; }
  const slots = PROXY_SLOTS.filter(s => s.enabled !== false);
  if(!slots.length){ toast('没有启用的代理槽，请先在「设置 → 代理槽」添加并保存', 'warn'); return; }
  let i = 0;
  for(const a of unbound){
    const slot = slots[i % slots.length];
    i++;
    try{ await postJSON('/accounts/set', {uid: a.uid, proxySlot: slot.id}); }catch(e){}
  }
  await loadAccounts();
  await loadProxySlots();
  toast('已为 ' + unbound.length + ' 个未绑定账号分配代理出口', 'ok');
}

function switchMainTab(tab){
  currentMainTab = tab;
  updateWorkspace(tab);
  closeSidebar();
  try {
    const url = new URL(window.location.href);
    url.searchParams.set('tab', tab);
    history.replaceState(null, '', url.toString());
  } catch(e){}
  try { localStorage.setItem(MAIN_TAB_STORE, tab); } catch(e){}
  const tabs = [
    ['gateway', 'btnNavGateway', 'pageGateway'],
    ['accounts', 'btnNavAccounts', 'pageAccounts'],
    ['tasks', 'btnNavTasks', 'pageTasks'],
    ['analytics', 'btnNavAnalytics', 'pageAnalytics'],
    ['models', 'btnNavModels', 'pageModels'],
    ['logs', 'btnNavLogs', 'pageLogs'],
    ['settings', 'btnNavSettings', 'pageSettings'],
    ['platforms', 'btnNavPlatforms', 'pagePlatforms']
  ];
  tabs.forEach(([name, btnId, pageId]) => {
    const btn = document.getElementById(btnId);
    const page = document.getElementById(pageId);
    if(!btn || !page) return;
    const on = (name === tab);
    btn.classList.toggle('active', on);
    if(on) btn.setAttribute('aria-current', 'page'); else btn.removeAttribute('aria-current');
    page.classList.toggle('active', on);
  });
  if(tab === 'platforms') loadPlatforms();
  if(tab === 'accounts'){ loadAccounts(); loadProxySlots(); }
  if(tab === 'tasks'){ loadGrowthTasks(); loadSchedulerStatus(); }
  if(tab === 'models'){ loadModels(); }
  if(tab === 'analytics'){ loadAnalytics(); loadAnalyticsMatrix(); }
  if(tab === 'settings'){ loadSettings(); loadProxySlots(); }
  if(tab === 'logs'){
    startLogPolling();
    fetchNewLogs(true);
    loadRequestArchive();
  } else {
    stopLogPolling();
  }
}

/* ---- 系统运行日志模块 ---- */
let logEntries = [];
let lastLogId = 0;
let logFilterLevel = '';
let logFilterTag = '';
let logSearchText = '';
let logAutoRefresh = true;
let logAutoScroll = true;
let logPollTimer = null;
let logFetching = false;
let logUserScrolledUp = false;

function startLogPolling(){
  stopLogPolling();
  if(logAutoRefresh && currentMainTab === 'logs') fetchNewLogs(false);
}

function stopLogPolling(){
  if(logPollTimer){
    clearInterval(logPollTimer);
    logPollTimer = null;
  }
}

async function fetchNewLogs(forceReset){
  if(logFetching) return;
  logFetching = true;
  const statusEl = document.getElementById('logTerminalStatus');
  if(statusEl && forceReset) statusEl.textContent = '正在拉取...';
  try {
    const since = forceReset ? 0 : lastLogId;
    const limit = forceReset ? 500 : 200;
    const data = await getJSON('/logs?since_id=' + since + '&limit=' + limit);
    if(data && data.logs){
      if(forceReset){
        logEntries = data.logs;
      } else if(data.logs.length > 0){
        const existingIds = new Set(logEntries.map(x => x.id));
        data.logs.forEach(item => {
          if(!existingIds.has(item.id)) logEntries.push(item);
        });
        if(logEntries.length > 2000){
          logEntries = logEntries.slice(-2000);
        }
      }
      if(data.max_id){
        lastLogId = Math.max(lastLogId, data.max_id);
      } else if(logEntries.length > 0){
        lastLogId = logEntries[logEntries.length - 1].id;
      }
      renderLogs();
      updateLogStats();
    }
    if(statusEl) statusEl.textContent = '就绪 · ' + new Date().toLocaleTimeString();
  } catch(e) {
    if(statusEl) statusEl.textContent = '连接中断: ' + e.message;
  } finally {
    logFetching = false;
  }
}

function updateLogStats(){
  const badge = document.getElementById('logStatsBadge');
  if(!badge) return;
  let errors = 0, warns = 0;
  logEntries.forEach(x => {
    if(x.level === 'ERROR') errors++;
    else if(x.level === 'WARN') warns++;
  });
  let txt = '共 ' + logEntries.length + ' 条';
  if(errors > 0) txt += ' · <span style="color:var(--bad)">' + errors + ' 错误</span>';
  if(warns > 0) txt += ' · <span style="color:var(--warn)">' + warns + ' 警告</span>';
  badge.innerHTML = txt;
}

function setLogFilterLevel(lvl){
  logFilterLevel = lvl;
  ['All', 'Info', 'Warn', 'Error'].forEach(name => {
    const btn = document.getElementById('btnLogLvl' + name);
    if(btn){
      const match = (lvl === '' && name === 'All') || (lvl.toUpperCase() === name.toUpperCase());
      btn.classList.toggle('active', match);
    }
  });
  renderLogs();
}

function setLogFilterTag(tag){
  logFilterTag = tag;
  const tagMap = {
    '': 'All',
    'chat': 'Chat',
    'tasks': 'Tasks',
    'scheduler': 'Sched',
    'accounts': 'Acct',
    'system': 'Sys',
    'catalog': 'Catalog',
    'auth': 'Auth',
    'settings': 'Settings'
  };
  Object.keys(tagMap).forEach(k => {
    const btn = document.getElementById('btnLogTag' + tagMap[k]);
    if(btn){
      btn.classList.toggle('active', logFilterTag === k);
    }
  });
  renderLogs();
}

let logSearchDebounce = null;
function onLogSearchInput(){
  clearTimeout(logSearchDebounce);
  logSearchDebounce = setTimeout(() => {
    const input = document.getElementById('logSearchInput');
    logSearchText = input ? input.value.trim().toLowerCase() : '';
    renderLogs();
  }, 200);
}

function toggleLogAuto(){
  logAutoRefresh = !logAutoRefresh;
  const btn = document.getElementById('btnToggleLogAuto');
  if(btn){
    if(logAutoRefresh){
      btn.textContent = '实时监听中';
      btn.style.color = 'var(--accent2)';
      startLogPolling();
    } else {
      btn.textContent = '已暂停监听';
      btn.style.color = 'var(--dim)';
      stopLogPolling();
    }
  }
}

function toggleLogScroll(){
  logAutoScroll = !logAutoScroll;
  const btn = document.getElementById('btnToggleLogScroll');
  if(btn){
    btn.textContent = logAutoScroll ? '自动滚屏: 开' : '自动滚屏: 关';
  }
  if(logAutoScroll){
    const body = document.getElementById('logTerminalBody');
    if(body) body.scrollTop = body.scrollHeight;
  }
}

function handleLogTerminalScroll(){
  const body = document.getElementById('logTerminalBody');
  if(!body) return;
  const atBottom = (body.scrollHeight - body.scrollTop - body.clientHeight) < 40;
  if(!atBottom && logAutoScroll){
    logUserScrolledUp = true;
  } else if(atBottom && logUserScrolledUp){
    logUserScrolledUp = false;
  }
}

function escapeHtml(s){
  return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function renderLogs(){
  const body = document.getElementById('logTerminalBody');
  if(!body) return;

  const filtered = logEntries.filter(item => {
    if(logFilterLevel && item.level !== logFilterLevel) return false;
    if(logFilterTag && item.tag !== logFilterTag) return false;
    if(logSearchText){
      const haystack = ((item.msg || '') + ' ' + (item.tag || '') + ' ' + (item.time || '')).toLowerCase();
      if(!haystack.includes(logSearchText)) return false;
    }
    return true;
  });

  if(filtered.length === 0){
    body.innerHTML = '<div class="log-empty">暂无匹配的日志记录</div>';
    return;
  }

  const htmlParts = [];
  filtered.forEach(item => {
    const lvlCls = 'lvl-' + (item.level || 'INFO');
    const tagCls = 'tag-' + (item.tag || 'system');
    htmlParts.push(
      '<div class="log-line">' +
        '<span class="log-ts">' + escapeHtml(item.time || '') + '</span>' +
        '<span class="log-lvl ' + lvlCls + '">' + escapeHtml(item.level || 'INFO') + '</span>' +
        '<span class="log-tag ' + tagCls + '">[' + escapeHtml(item.tag || 'system') + ']</span>' +
        '<span class="log-msg">' + escapeHtml(item.msg || '') + '</span>' +
      '</div>'
    );
  });
  body.innerHTML = htmlParts.join('');

  if(logAutoScroll && !logUserScrolledUp){
    body.scrollTop = body.scrollHeight;
  }
}

function copyFilteredLogs(){
  const filtered = logEntries.filter(item => {
    if(logFilterLevel && item.level !== logFilterLevel) return false;
    if(logFilterTag && item.tag !== logFilterTag) return false;
    if(logSearchText){
      const haystack = ((item.msg || '') + ' ' + (item.tag || '') + ' ' + (item.time || '')).toLowerCase();
      if(!haystack.includes(logSearchText)) return false;
    }
    return true;
  });
  const text = filtered.map(x => '[' + (x.ts || x.time) + '] [' + x.level + '] [' + x.tag + '] ' + x.msg).join('\n');
  navigator.clipboard.writeText(text).then(() => {
    toast('已复制 ' + filtered.length + ' 行日志', 'ok');
  }).catch(e => {
    toast('复制失败: ' + e.message, 'bad');
  });
}

async function exportLogsFile(){
  try {
    const data = await getJSON('/logs?limit=5000');
    if(!data || !data.logs || !data.logs.length){
      toast('暂无日志可导出', 'warn');
      return;
    }
    const lines = data.logs.map(x => '[' + (x.ts || x.time) + '] [' + x.level + '] [' + x.tag + '] ' + x.msg);
    const text = lines.join('\n');
    const blob = new Blob([text], {type: 'text/plain;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    a.download = 'wb-proxy-' + ts + '.log';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast('已导出 ' + data.logs.length + ' 行日志', 'ok');
  } catch(e) {
    toast('导出日志失败: ' + e.message, 'bad');
  }
}

async function clearServerLogs(){
  if(!confirm('确定要清空网关日志吗？此操作将清空内存中的全部日志缓冲。')) return;
  try {
    await postJSON('/logs/clear', {});
    logEntries = [];
    lastLogId = 0;
    renderLogs();
    updateLogStats();
    toast('网关日志已清空', 'ok');
  } catch(e) {
    toast('清空失败: ' + e.message, 'bad');
  }
}

/* 时间范围：每个窗口都是服务端的一段切片，切换即重新取数。
 *
 * 只有「今日 / 全部历史」时，一次 /usage/analytics 同时带回两个桶，切换按钮
 * 重渲染缓存就够了；窗口变多之后一个 payload 装不下所有窗口，继续重渲染缓存
 * 只会把上一个窗口的数字挂到新标签下面，所以一律重取。 */
function setAnalyticsRange(range){
  analyticsRange = range;
  const btns = {today:'btnRangeToday', week:'btnRangeWeek', month:'btnRangeMonth',
                all:'btnRangeAll', custom:'btnRangeCustom'};
  Object.keys(btns).forEach(k => {
    const b = document.getElementById(btns[k]);
    if(b) b.classList.toggle('active', k === range);
  });
  const box = document.getElementById('rangeCustomBox');
  if(box) box.style.display = (range === 'custom') ? 'inline-flex' : 'none';
  if(range === 'custom') prefillCustomRange();
  loadAnalytics();
  // The model matrix reads /usage and /usage/perf directly, so it has to be
  // refetched: without this the table kept showing all-time figures while the
  // page said "today", which is the inconsistency the range buttons were
  // meant to remove.
  loadAnalyticsMatrix();
}

/* 自定义区间的输入框初始为空，而空 = 不限，画面会和「全部历史」一模一样，看起来
 * 像按钮坏了。第一次点开时把起点填成今天零点：一个能看懂的默认窗口，操作者再自己
 * 放宽或收窄；终点留空表示「到现在」。 */
function prefillCustomRange(){
  const el = document.getElementById('rangeCustomSince');
  if(!el || el.value) return;
  const d = new Date();
  el.value = toLocalInputValue(new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() / 1000);
}

function pad2(n){ return String(n).padStart(2, '0'); }

/* datetime-local 与 epoch 互转：输入框里是操作者按日历读到的本地墙上时间，所以
 * 转换用浏览器自己的时区；服务端拿 epoch 与它自己的时钟比较。 */
function toLocalInputValue(epochSec){
  if(!epochSec) return '';
  const d = new Date(epochSec * 1000);
  if(isNaN(d.getTime())) return '';
  return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate())
    + 'T' + pad2(d.getHours()) + ':' + pad2(d.getMinutes());
}

function fromLocalInputValue(value){
  if(!value) return null;
  const t = new Date(value).getTime();
  return isNaN(t) ? null : Math.floor(t / 1000);
}

function onRangeCustomChange(){
  loadAnalytics();
  loadAnalyticsMatrix();
}

/* 三个取数端点共用同一个查询串，避免 /usage 与 /usage/perf 各拼一份而漏掉自定义
 * 区间——那正是「卡片与表格口径不一致」的复发路径。 */
function analyticsQuery(){
  let q = '?realm=all&range=' + encodeURIComponent(analyticsRange || 'today');
  if(analyticsRange === 'custom'){
    const sEl = document.getElementById('rangeCustomSince');
    const uEl = document.getElementById('rangeCustomUntil');
    const s = fromLocalInputValue(sEl ? sEl.value : '');
    const u = fromLocalInputValue(uEl ? uEl.value : '');
    if(s !== null) q += '&since=' + s;
    if(u !== null) q += '&until=' + u;
  }
  return q;
}

/* 模型性能指标与用量一览
 *
 * Reads the combined view on purpose. The table carries its own 区域
 * column, so scoping it to the gateway's current exit would hide exactly the
 * models this page exists to compare. */
