const ADVANCED_SETTING_GROUPS = [
  {
    id: 'pool', title: '账号池与流量治理',
    desc: '公平调度、并发上限、限流恢复与会话绑定。',
    fields: [
      {key:'weighted_pick', label:'加权选号', type:'bool', hint:'同优先级付费账号先比较当日积分消耗与在途预估；并列时加权，关闭后并列轮询。'},
      {key:'free_fair_pick', label:'免费模型 Token 公平调度', type:'bool', hint:'国内、国际分别比较当日免费 Token 与在途预估；同一会话在切换窗口内优先沿用账号。'},
      {key:'free_switch_window_tokens', label:'免费会话换号窗口（Token）', type:'int', min:0, hint:'默认 262144（256K）。绑定账号比同优先级最低用量账号多出该值后才重新选号；0 = 每次比较最低用量。'},
      {key:'soft_rate', label:'软冷却基数（秒）', type:'number', min:0, step:'any', hint:'遇到上游软限流后的基础冷却秒数。'},
      {key:'soft_rate_max', label:'软冷却上限（秒）', type:'number', min:0, step:'any', hint:'指数退避的封顶秒数。'},
      {key:'breaker_threshold', label:'熔断阈值', type:'int', min:1, hint:'连续失败达到此数后进入熔断。'},
      {key:'breaker_cooldown', label:'熔断基础（秒）', type:'number', min:0, step:'any', hint:'首次熔断时长。'},
      {key:'breaker_cooldown_max', label:'熔断上限（秒）', type:'number', min:0, step:'any', hint:'熔断指数退避封顶。'},
      {key:'degrade_threshold', label:'降权阈值', type:'int', min:1, hint:'连续未知错误达到此数后临时出池。'},
      {key:'degrade_cooldown', label:'降权基础（秒）', type:'number', min:0, step:'any', hint:'首次降权时长。'},
      {key:'degrade_cooldown_max', label:'降权上限（秒）', type:'number', min:0, step:'any', hint:'降权指数退避封顶。'},
      {key:'idle_weight_per_hour', label:'闲置补偿 / 小时', type:'number', min:0, step:'any', hint:'账号闲置越久权重越高。'},
      {key:'idle_weight_max', label:'闲置补偿上限', type:'number', min:0, step:'any', hint:'闲置补偿最大点数。'},
      {key:'max_in_flight', label:'单账号最大在途', type:'int', min:0, hint:'0 = 不限制；每账号同时处理的请求数。'},
      {key:'max_in_flight_global', label:'国际版账号在途上限', type:'int', min:0, hint:'每个国际版账号的在途上限；0 = 使用单账号通用上限。'},
      {key:'top_n', label:'候选短名单 Top N', type:'int', min:1, hint:'加权随机前先取前 N 名。'},
      {key:'cost_ledger_ttl', label:'成本账本 TTL（秒）', type:'int', min:60, hint:'实测成本层的有效秒数。'},
      {key:'cost_explore_interval', label:'成本探索窗口（秒）', type:'number', min:0, step:'any', hint:'免费层垄断时，每隔多久搭车探索未知号；0 = 关闭。'},
      {key:'credit_floor', label:'积分保底', type:'int', min:0, hint:'只挡 tier2 付费模型；0 = 关闭。'},
      {key:'min_pick_gap', label:'最小重复间隔（秒）', type:'number', min:0, step:'any', hint:'短名单内尽量避免刚用过同一账号。'},
      {key:'affinity_ttl', label:'会话粘性 TTL（秒）', type:'int', min:60, hint:'同一会话固定账号的缓存窗口。'},
      {key:'affinity_max_entries', label:'会话粘性容量', type:'int', min:100, hint:'内存中最多保存的会话路由数。'},
      {key:'session_dead_threshold', label:'Session-dead 阈值', type:'int', min:1, hint:'12153/session not found 连续出现多少次才停用账号。'},
    ]
  },
  {
    id: 'schedule', title: '后台排程',
    desc: '签到、旅行、保活、夜猫、每日活跃与成长队列的时点、开关和余额巡检。',
    fields: [
      {key:'checkin_hours', label:'签到时点（小时）', type:'hours', placeholder:'9, 21', hint:'逗号分隔，0-23；空 = 不跑。'},
      {key:'travel_hours', label:'猫猫旅行时点（小时）', type:'hours', placeholder:'9, 21', hint:'逗号分隔，0-23。'},
      {key:'keepalive_hours', label:'Token 保活时点（小时）', type:'hours', placeholder:'22', hint:'逗号分隔，0-23。'},
      {key:'cat_hours', label:'夜猫窗口时点（小时）', type:'hours', placeholder:'1, 23', hint:'逗号分隔，0-23。'},
      {key:'daily_chat_hours', label:'国际活跃时点（小时）', type:'hours', placeholder:'9, 21', hint:'逗号分隔，0-23。'},
      {key:'growth_hours', label:'成长队列时点（小时）', type:'hours', placeholder:'1', hint:'逗号分隔，0-23。'},
      {key:'checkin_enabled', label:'启用签到', type:'bool', hint:'国内版签到。'},
      {key:'travel_enabled', label:'启用猫猫旅行', type:'bool', hint:'派出与领奖闭环。'},
      {key:'keepalive_enabled', label:'启用 Token 保活', type:'bool', hint:'集中刷新凭证。'},
      {key:'cat_enabled', label:'启用夜猫', type:'bool', hint:'23:00-08:00 窗口任务。'},
      {key:'daily_chat_enabled', label:'启用国际活跃', type:'bool', hint:'每日活跃对话打卡。'},
      {key:'growth_enabled', label:'启用成长队列', type:'bool', hint:'每日自动扫描并执行成长任务。'},
      {key:'include_disabled_in_tasks', label:'保号任务覆盖已禁用账号', type:'bool', hint:'禁用号不参与选号，但仍可签到/保活。'},
      {key:'balance_refresh_enabled', label:'后台刷新余额', type:'bool', hint:'定时刷新积分并解锁余额恢复账号。'},
      {key:'balance_refresh_minutes', label:'余额刷新间隔（分钟）', type:'int', min:1, hint:'仅在上方开关开启时生效。'},
    ]
  },
  {
    id: 'redis', title: 'Upstash Redis 镜像',
    desc: '可选会话绑定镜像。单实例已有 SQLite 持久化，无需启用。',
    fields: [
      {key:'url', label:'Upstash REST URL', type:'text', placeholder:'https://...upstash.io', hint:'留空即关闭镜像。'},
      {key:'token', label:'Upstash Token', type:'secret', placeholder:'token', hint:'保存在本地 SQLite 与设置导出文件，不回显明文。'},
      {key:'affinity_mirror', label:'启用粘性镜像', type:'bool', hint:'额外镜像会话绑定；不提供多副本公平调度。'},
      {key:'ttl_seconds', label:'镜像 TTL（秒）', type:'int', min:60, hint:'默认 604800 = 7 天。'},
    ]
  },
  {
    id: 'upstream', title: '上游与设备令牌',
    desc: 'SSE 首字节/流中空闲超时，以及可选的 X-Device-Token 文件兜底。',
    fields: [
      {key:'header_timeout_seconds', label:'首字节超时（秒）', type:'int', min:1, hint:'聊天 header 阶段超时。'},
      {key:'idle_timeout_seconds', label:'流中空闲超时（秒）', type:'int', min:1, hint:'活跃流会续命；静默到期释放租约。'},
      {key:'device_token', label:'X-Device-Token 值', type:'secret', placeholder:'留空 = 不注入', hint:'直接注入请求头的值。'},
      {key:'device_token_file', label:'X-Device-Token 文件', type:'text', placeholder:'C:/path/to/token', hint:'5 分钟热读；>1KB 忽略。'},
    ]
  },
  {
    id: 'prompt', title: '系统提示词',
    desc: '选择透传、替换或追加系统提示词。',
    fields: [
      {key:'mode', label:'提示词模式', type:'select', options:['passthrough','custom','append'], default:'passthrough', hint:'passthrough = 透传；custom = 网关自有；append = 客户端后追加。'},
      {key:'retry_on_content_rejection', label:'内容审核失败时重试当前请求', type:'bool', hint:'默认关闭。仅明确审核码 11140 时替换当前请求提示词并重试一次，不影响其他会话。'},
      {key:'file', label:'提示词文件路径', type:'text', placeholder:'留空 = 内置默认', hint:'custom/append 模式才读取。'},
    ]
  },
  {
    id: 'logging', title: '日志归档',
    desc: '来源记录是个人数据，默认关闭；轮转窗口与大小上限在这里配置。',
    fields: [
      {key:'record_client_info', label:'记录调用来源（IP/UA）', type:'bool', hint:'默认关闭。'},
      {key:'retention_days', label:'JSONL 导出保留天数', type:'int', min:1, hint:'默认 7 天；SQLite 历史保留由部署配置单独控制。'},
      {key:'archive_max_mb', label:'归档大小上限（MB）', type:'int', min:1, hint:'默认 100MB。'},
    ]
  }
];
let ADVANCED_SETTINGS_DATA = {};

function advancedFieldId(group, key){ return 'adv_' + group + '_' + key; }
function advancedFieldValue(cfg, key, type){
  const value = cfg ? cfg[key] : undefined;
  if(type === 'hours') return Array.isArray(value) ? value.join(', ') : '';
  if(value === undefined || value === null) return '';
  return String(value);
}
function renderAdvancedSettings(data){
  ADVANCED_SETTINGS_DATA = data || {};
  const box = document.getElementById('advancedSettingsCards');
  if(!box) return;
  const openGroups = new Set(Array.from(box.querySelectorAll('details[data-adv-group]')).filter(function(el){ return el.open; }).map(function(el){ return el.dataset.advGroup; }));
  box.innerHTML = ADVANCED_SETTING_GROUPS.map(function(group){
    const cfg = (data && data[group.id]) || {};
    const fields = group.fields.map(function(field){
      const common = 'id="' + advancedFieldId(group.id, field.key) + '" data-adv-group="' + group.id + '" data-adv-key="' + field.key + '" data-adv-type="' + field.type + '"';
      const label = '<div style="font-size:12px;color:var(--dim);margin-bottom:4px">' + field.label + '</div>';
      const hint = field.hint ? '<div style="font-size:11px;color:var(--dim);line-height:1.35">' + field.hint + '</div>' : '';
      const value = advancedFieldValue(cfg, field.key, field.type);
      let control = '';
      if(field.type === 'bool'){
        control = '<label style="display:flex;align-items:center;gap:8px;min-height:40px;font-size:13px;color:var(--fg)"><input type="checkbox" ' + common + (cfg[field.key] ? ' checked' : '') + ' style="width:16px;height:16px"><span>' + field.label + '</span></label>';
        return '<div style="min-width:190px">' + control + (field.hint ? '<div style="font-size:11px;color:var(--dim);line-height:1.35;margin-left:24px">' + field.hint + '</div>' : '') + '</div>';
      }
      if(field.type === 'select'){
        const options = (field.options || []).map(function(option){
          return '<option value="' + option + '"' + (String(value || field.default || '') === option ? ' selected' : '') + '>' + option + '</option>';
        }).join('');
        control = '<select class="slot-select" style="width:100%;max-width:none" ' + common + '>' + options + '</select>';
      } else if(field.type === 'hours' || field.type === 'text' || field.type === 'secret'){
        const inputType = field.type === 'secret' ? 'password' : 'text';
        control = '<input type="' + inputType + '" class="slot-input" ' + common + ' value="' + esc(value) + '" placeholder="' + esc(field.placeholder || '') + '">';
      } else {
        const min = field.min == null ? 0 : field.min;
        const step = field.type === 'int' ? '1' : (field.step || 'any');
        control = '<input type="number" class="slot-input" ' + common + ' min="' + min + '" step="' + step + '" value="' + esc(value) + '">';
      }
      return '<div style="min-width:190px">' + label + control + hint + '</div>';
    }).join('');
    return '<details class="advanced-setting" data-adv-group="' + group.id + '"' + (openGroups.has(group.id) ? ' open' : '') + '><summary><div><h3>' + group.title + '</h3><div class="advanced-setting-desc">' + group.desc + '</div></div></summary><div class="advanced-setting-controls">' + fields + '</div><div style="margin-top:16px"><button data-action="saveAdvancedSettings" data-on="click" data-arg="' + group.id + '">保存此分类</button></div></details>';
  }).join('');
}
function readAdvancedSettingsGroup(groupId){
  const group = ADVANCED_SETTING_GROUPS.find(function(item){ return item.id === groupId; });
  if(!group) throw new Error('未知的设置组');
  const out = {};
  group.fields.forEach(function(field){
    const el = document.getElementById(advancedFieldId(groupId, field.key));
    if(!el) throw new Error(field.label + ' 控件不存在');
    if(field.type === 'bool'){ out[field.key] = !!el.checked; return; }
    const raw = String(el.value == null ? '' : el.value).trim();
    if(field.type === 'int' || field.type === 'number'){
      const number = Number(raw);
      const minimum = field.min == null ? 0 : field.min;
      if(!Number.isFinite(number) || number < minimum){
        throw new Error(field.label + ' 必须是不小于 ' + minimum + ' 的数字');
      }
      if(field.type === 'int' && !Number.isInteger(number)){
        throw new Error(field.label + ' 必须是整数');
      }
      out[field.key] = number;
    } else if(field.type === 'hours'){
      const parts = raw ? raw.split(',').map(function(part){ return part.trim(); }).filter(Boolean) : [];
      const hours = parts.map(function(part){ return Number(part); });
      if(hours.some(function(hour){ return !Number.isInteger(hour) || hour < 0 || hour > 23; })){
        throw new Error(field.label + ' 必须是 0-23，逗号分隔');
      }
      out[field.key] = hours;
    } else {
      out[field.key] = raw;
    }
  });
  return out;
}
async function saveAdvancedSettings(btn, ev, groupId){
  const group = ADVANCED_SETTING_GROUPS.find(function(item){ return item.id === groupId; });
  if(!group) return;
  if(btn) btn.disabled = true;
  try{
    const payload = {};
    payload[group.id] = readAdvancedSettingsGroup(group.id);
    if(group.id === 'schedule') payload.restart_scheduler = true;
    await postJSON('/settings/save', payload);
    toast(group.title + '已保存', 'ok');
    await loadSettings();
  }catch(e){
    toast('保存失败: ' + e.message, 'bad');
  }finally{
    if(btn) btn.disabled = false;
  }
}

async function loadSettings(showToast){
  try {
    const data = await getJSON('/settings');
    renderInfrastructure(data);
    const passwordHint = document.getElementById('panelPasswordOverrideHint');
    if(passwordHint) passwordHint.style.display = data.panel_password_startup_override ? 'block' : 'none';
    const snapshotHint = document.getElementById('settingsSnapshotHint');
    if(snapshotHint) snapshotHint.style.display = data.settings_using_snapshot ? 'block' : 'none';
    const pwdState = document.getElementById('setPwdState');
    if(pwdState){
      pwdState.textContent = data.panel_password_is_default ? '(当前为默认密码)' : '(已自定义)';
      pwdState.style.color = data.panel_password_is_default ? 'var(--warn)' : 'var(--accent2)';
    }
    const keyState = document.getElementById('setKeyState');
    if(keyState){
      const count = (data.api_keys || []).filter(k => k.enabled).length;
      const required = data.auth_required === true;
      keyState.textContent = !required ? '(当前不校验)' : count ? ('(' + count + ' 个生效)')
        : (data.api_keys || []).length ? '(无启用 Key，API 请求将被拒绝)' : '(启动 Key 校验)';
      keyState.style.color = required ? 'var(--accent2)' : 'var(--dim)';
    }
    loadLimitInputs(data);
    const refreshHours = document.getElementById('setCreditsRefreshHours');
    if(refreshHours) refreshHours.value = String(data.credits_refresh_hours ?? 0.5);
    const previousPricing = window.PRICING_ENABLED !== false;
    window.PRICING_ENABLED = data.pricing_enabled !== false;
    const pricingEnabled = document.getElementById('setPricingEnabled');
    if(pricingEnabled) pricingEnabled.checked = window.PRICING_ENABLED;
    if(previousPricing !== window.PRICING_ENABLED && typeof refreshAllCostViews === 'function') refreshAllCostViews();
      const pricingMinutes = Number(data.pricing_refresh_minutes || 0);
      const pricingInput = document.getElementById('setPricingMinutes');
      if(pricingInput) pricingInput.value = String(pricingMinutes);
      const pricingState = document.getElementById('setPricingState');
      if(pricingState){
        pricingState.textContent = !window.PRICING_ENABLED ? '(已关闭)' : pricingMinutes > 0 ? ('(每 ' + pricingMinutes + ' 分钟)') : '(手动取价)';
        pricingState.style.color = window.PRICING_ENABLED && pricingMinutes > 0 ? 'var(--accent2)' : 'var(--dim)';
      }
      const variantOn = data.pricing_variant_inherit !== false;
      const variantInput = document.getElementById('setPricingVariant');
      if(variantInput) variantInput.checked = variantOn;
      loadPricingStatus();
      const autoSwitch = data.auto_switch_product === true;
      const autoSwitchInput = document.getElementById('setAutoSwitch');
      if(autoSwitchInput) autoSwitchInput.checked = autoSwitch;
      const autoSwitchState = document.getElementById('setAutoSwitchState');
      if(autoSwitchState){
        autoSwitchState.textContent = autoSwitch ? '(已启用)' : '(未启用)';
        autoSwitchState.style.color = autoSwitch ? 'var(--accent2)' : 'var(--dim)';
      }
      const dailyWeb = data.daily_chat_web !== false;
      const dailyWebInput = document.getElementById('setDailyChatWeb');
      if(dailyWebInput) dailyWebInput.checked = dailyWeb;
      const dailyWebState = document.getElementById('setDailyChatWebState');
      if(dailyWebState){
        dailyWebState.textContent = dailyWeb ? '(已启用)' : '(仅桌面端对话)';
        dailyWebState.style.color = dailyWeb ? 'var(--accent2)' : 'var(--dim)';
      }
      const localWeb = data.local_web_tools === true;
      const localWebInput = document.getElementById('setLocalWebTools');
      if(localWebInput) localWebInput.checked = localWeb;
      const localWebState = document.getElementById('setLocalWebToolsState');
      if(localWebState){
        localWebState.textContent = localWeb ? '(已启用)' : '(直通)';
        localWebState.style.color = localWeb ? 'var(--accent2)' : 'var(--dim)';
      }
    // Rebuild the editable rows, keeping stored values so an untouched field
    // is not accidentally blanked.
    API_KEY_ROWS = (data.api_keys || []).map(k => ({
      id: k.id || '',
      name: k.name || '',
      key: '',
      // The server keeps the stored value when a row comes back blank, so
      // leaving the field untouched will not wipe an existing key.
      stored_key: '',
      masked: k.masked || '',
      realm: k.realm || '',
      allowed_upstreams: k.allowed_upstreams || ['workbuddy'],
      models: Array.isArray(k.models) ? k.models.slice() : [],
      enabled: k.enabled !== false,
      created_at: k.created_at || '',
      _editing: false,
    }));
    window.API_KEY_ROWS = API_KEY_ROWS;
    DELETED_KEY_ROWS = (data.deleted_api_keys || []).map(k => ({
      id: k.id || '',
      name: k.name || '',
      realm: k.realm || '',
      created_at: k.created_at || '',
      deleted_at: k.deleted_at || '',
    }));
    renderKeyRows();
    renderAdvancedSettings(data);
    updateUI();
    const set = (id, value) => { const el = document.getElementById(id); if(el) el.textContent = value || '-'; };
    set('setVersion', data.version);
    set('setAccountsDir', data.accounts_dir);
    set('setUsageDir', data.usage_dir);
    set('setFile', data.settings_file);
    set('setSettingsFile', data.settings_file);
    set('setMaxConcurrent', data.max_concurrent_chat == null ? '-' : String(data.max_concurrent_chat));
    set('setChatSlotWait', data.chat_slot_wait_seconds == null ? '-' : String(data.chat_slot_wait_seconds) + 's');
    if(showToast) toast('设置已刷新', 'ok');
  } catch(e) {
    if(showToast) toast('读取设置失败: ' + e.message, 'bad');
  }
}

async function savePanelPassword(btn){
  const cur = (document.getElementById('setPwdCurrent') || {}).value || '';
  const nw = (document.getElementById('setPwdNew') || {}).value || '';
  if(!cur || !nw){ toast('请填写当前密码和新密码', 'warn'); return; }
  btn.disabled = true;
  try {
    const data = await postJSON('/panel/password', {current: cur, new: nw});
    if(data.token){
      PANEL_TOKEN = data.token;
      try { sessionStorage.setItem(PANEL_STORE, PANEL_TOKEN); } catch(e) {}
    }
    document.getElementById('setPwdCurrent').value = '';
    document.getElementById('setPwdNew').value = '';
    toast('面板密码已更新', 'ok');
    loadSettings();
  } catch(e) {
    toast('修改失败: ' + e.message, 'bad');
  } finally {
    btn.disabled = false;
  }
}

const LIMIT_INPUTS = {
  reserve_credits: ['setReserveCredits', 'setReserveState'],
  daily_token_limit: ['setDailyTokenLimit', 'setDailyTokenState'],
  daily_credit_limit: ['setDailyCreditLimit', 'setDailyCreditState'],
  model_daily_token_limit: ['setModelDailyTokenLimit', 'setModelDailyTokenState'],
  expiring_window_days: ['setExpiringWindow', 'setExpiringState']
};
function loadLimitInputs(data){
  Object.entries(LIMIT_INPUTS).forEach(([key, [id, stateId]]) => {
    const row = (data.limits || {})[key] || {global: data[key] || 0, intl: null, cn: null};
    const globalValue = Number(row.global || 0);
    [['', 'global'], ['Intl', 'intl'], ['Cn', 'cn']].forEach(([suffix, scope]) => {
      const input = document.getElementById(id + suffix);
      if(input){
        input.value = row[scope] == null ? '' : String(row[scope]);
        if(suffix) input.placeholder = '继承 ' + globalValue;
      }
    });
    const state = document.getElementById(stateId);
    if(state){
      const summary = value => value > 0 ? (/token/.test(key) ? fmtTokens(value) : String(value)) : '关闭';
      state.textContent = '全局 ' + summary(globalValue) + ' · 国际 ' + summary(row.intl ?? globalValue) + ' · 国内 ' + summary(row.cn ?? globalValue);
    }
  });
}
async function saveLimitRow(key, btn){
  const ids = LIMIT_INPUTS[key];
  if(!ids) return;
  const row = {};
  for(const [suffix, scope] of [['', 'global'], ['Intl', 'intl'], ['Cn', 'cn']]){
    const input = document.getElementById(ids[0] + suffix);
    const raw = input ? input.value.trim() : '';
    const value = suffix && raw === '' ? null : Number(raw || 0);
    if(value !== null && (!Number.isSafeInteger(value) || value < 0 || (key === 'expiring_window_days' && value > 3650))){
      toast('请填写非负整数，渠道留空表示继承；临期窗口最多 3650 天', 'warn'); return;
    }
    row[scope] = value;
  }
  if(btn) btn.disabled = true;
  try{
    await postJSON('/settings/save', {limits: {[key]: row}});
    toast('渠道设置已保存', 'ok');
    await loadSettings();
  }catch(e){ toast('保存失败: ' + e.message, 'bad'); }
  finally{ if(btn) btn.disabled = false; }
}
async function saveReserveCredits(btn){ return saveLimitRow('reserve_credits', btn); }
async function saveDailyTokenLimit(btn){ return saveLimitRow('daily_token_limit', btn); }
async function saveDailyCreditLimit(btn){ return saveLimitRow('daily_credit_limit', btn); }
async function saveExpiringWindow(btn){ return saveLimitRow('expiring_window_days', btn); }
async function saveCreditsRefreshHours(btn){
  const input = document.getElementById('setCreditsRefreshHours');
  const value = Number(input ? input.value : 0.5);
  if(!Number.isFinite(value) || value < 0 || value > 72){ toast('刷新间隔需在 0–72 小时之间', 'warn'); return; }
  if(btn) btn.disabled = true;
  try{ await postJSON('/settings/save', {credits_refresh_hours: value}); toast('刷新间隔已保存', 'ok'); await loadSettings(); }
  catch(e){ toast('保存失败: ' + e.message, 'bad'); }
  finally{ if(btn) btn.disabled = false; }
}
async function savePricingEnabled(btn){
  const enabled = !!(document.getElementById('setPricingEnabled') || {}).checked;
  if(btn) btn.disabled = true;
  try{ await postJSON('/settings/save', {pricing_enabled: enabled}); await loadSettings(); toast(enabled ? '已开启费用估算' : '已关闭费用估算', 'ok'); }
  catch(e){ toast('保存失败: ' + e.message, 'bad'); }
  finally{ if(btn) btn.disabled = false; }
}

async function savePricingMinutes(btn){
  const el = document.getElementById('setPricingMinutes');
  const value = Number((el || {}).value || 0);
  if(!Number.isFinite(value) || value < 0){ toast('请填写 0 或正数（分钟）', 'warn'); return; }
  if(btn) btn.disabled = true;
  try {
    await postJSON('/settings/save', {pricing_refresh_minutes: value});
    toast(value > 0 ? ('已启用：每 ' + value + ' 分钟取一次价') : '已关闭自动取价（仍可手动取一次）', 'ok');
    loadSettings();
  } catch(e) {
    toast('保存失败: ' + e.message, 'bad');
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function saveModelDailyTokenLimit(btn){ return saveLimitRow('model_daily_token_limit', btn); }

async function loadPricingStatus(){
  const meta = document.getElementById('setPricingMeta');
  const box = document.getElementById('setPricingCurrent');
  if(!meta) return;
  try {
    const st = await getJSON('/pricing');
    const bits = [];
    if(st.master_enabled === false) bits.push('费用估算已关闭；Token 和实际积分继续记录');
    if(st.current_at_label) bits.push('当前生效 ' + st.current_at_label + ' 那一份（' + (st.models || 0) + ' 个模型）');
    else bits.push('还没取过价，暂用出厂快照');
    if(st.last_run_label) bits.push('上次取价 ' + st.last_run_label);
    if(st.enabled && st.next_run_label) bits.push('下次 ' + st.next_run_label);
    bits.push('策略表 ' + (st.policies || 0) + ' 条');
    if(st.last_error) bits.push('上次失败：' + st.last_error);
    meta.textContent = '　' + bits.join('；');
    meta.style.color = st.last_error ? 'var(--warn)' : 'var(--dim)';
    if(box){
      const cur = st.current || {};
      const models = Object.keys(cur);
      box.innerHTML = models.length
        ? '<details><summary style="cursor:pointer">展开查看每个模型当前生效的策略</summary>'
          + '<div style="margin-top:6px;max-height:260px;overflow:auto;font-family:monospace;line-height:1.7">'
          + models.map(m => esc(m) + ' → ' + esc(cur[m].id || '')
              + (cur[m].via === 'variant' ? '（继承自 ' + esc(cur[m].inherited_from || '?') + '）' : '')
              + (cur[m].label ? '　' + esc(cur[m].label) + ' 首次取到' : '')).join('<br>')
          + '</div></details>'
        : '';
    }
    renderPricingGaps(st);
  } catch(e) {
    meta.textContent = '';
    if(box) box.innerHTML = '';
  }
}

/* ---- unpriced models: what shows a dash, why, and a way to map it ---- */
const PRICING_GAP_LABELS = {
  or_missing: {text: 'OpenRouter 无对应', color: 'var(--warn)'},
  variant_unmatched: {text: '变体名未命中基准', color: 'var(--warn)'},
  alias: {text: '虚拟别名（非实体模型）', color: 'var(--dim)'},
};

function safeModelId(value){
  // Model ids and OpenRouter ids are [A-Za-z0-9._/:-]; anything else is
  // dropped before it reaches an attribute or an inline handler argument.
  return String(value == null ? '' : value).replace(/[^A-Za-z0-9._/:\-]/g, '');
}

function renderPricingGaps(st){
  const box = document.getElementById('setPricingGaps');
  if(!box) return;
  const gaps = Array.isArray(st.gaps) ? st.gaps : [];
  const sum = st.gap_summary || {};
  const head = '<div style="font-size:12px;color:var(--dim);margin-top:10px">'
    + '<b>未定价模型</b>：' + fmt(sum.total || 0) + ' 个需要人工关注'
    + (sum.or_missing ? '（无对应 ' + fmt(sum.or_missing) + '）' : '')
    + (sum.variant_unmatched ? '（变体未命中 ' + fmt(sum.variant_unmatched) + '）' : '')
    + (sum.aliases ? '；另有 ' + fmt(sum.aliases) + ' 个虚拟别名不参与统计' : '')
    + (sum.variants_enabled === false ? '；变体继承当前已关闭' : '')
    + '</div>';
  if(!gaps.length){
    box.innerHTML = head + '<div style="font-size:12px;color:var(--accent2);margin-top:4px">全部模型都有价。</div>';
    return;
  }
  const rows = gaps.map(g => {
    const model = safeModelId(g.model);
    const label = PRICING_GAP_LABELS[g.reason] || {text: g.reason || '未定价', color: 'var(--dim)'};
    const cands = (g.candidates || []).map(c =>
      '<a href="javascript:void(0)" data-or-id="' + safeModelId(c)
      + '" data-action="fillPricingMapping" data-on="click" style="color:var(--accent2)">' + esc(c) + '</a>'
    ).join('、');
    const editable = g.reason !== 'alias';
    const control = editable
      ? '<input placeholder="vendor/model" style="width:190px;background:var(--panel2);'
        + 'border:1px solid var(--line);border-radius:6px;padding:4px 8px;color:var(--fg);font:inherit;font-size:12px">'
        + '<button data-action="savePricingMapping" data-on="click" style="font-size:12px;padding:4px 10px">登记</button>'
      : '<span style="color:var(--dim);font-size:12px">无需登记</span>';
    return '<div data-model="' + model + '" style="display:flex;align-items:center;gap:8px;'
      + 'flex-wrap:wrap;padding:5px 0;border-top:1px solid var(--line)">'
      + '<span class="mono" style="font-size:12px;min-width:180px">' + esc(g.model) + '</span>'
      + '<span style="font-size:12px;color:' + label.color + '">' + esc(label.text) + '</span>'
      + '<span style="font-size:12px;color:var(--dim)">' + (cands ? '候选：' + cands : '') + '</span>'
      + control + '</div>';
  }).join('');
  box.innerHTML = head
    + '<details style="margin-top:4px"><summary style="cursor:pointer;font-size:12px">展开逐条查看 / 手填 OpenRouter id</summary>'
    + '<div style="margin-top:4px;max-height:320px;overflow:auto">' + rows + '</div>'
    + '<div style="font-size:11px;color:var(--dim);margin-top:6px">手填的映射存在数据目录的 pricing-overrides.json（不改源码），登记后立即触发一次取价；留空提交即删除该映射。候选只是字面相似度建议，不自动采用。</div>'
    + '</details>';
}

function fillPricingMapping(link){
  const row = link.closest('[data-model]');
  const input = row && row.querySelector('input');
  if(input) input.value = link.getAttribute('data-or-id') || '';
}

async function savePricingMapping(btn){
  const row = btn.closest('[data-model]');
  if(!row) return;
  const model = row.getAttribute('data-model');
  const input = row.querySelector('input');
  const orId = (input && input.value || '').trim();
  btn.disabled = true;
  try {
    const res = await postJSON('/pricing/mapping', {model: model, or_id: orId});
    toast(res.msg || '已记录', res.known || !orId ? 'ok' : 'warn');
    setTimeout(loadPricingStatus, 3000);
    setTimeout(loadPricingStatus, 12000);
  } catch(e) {
    toast('登记失败: ' + e.message, 'bad');
  } finally {
    btn.disabled = false;
  }
}

async function savePricingVariant(btn){
  const el = document.getElementById('setPricingVariant');
  const value = !!(el && el.checked);
  if(btn) btn.disabled = true;
  try {
    const res = await postJSON('/settings/save', {pricing_variant_inherit: value});
    toast(value
      ? '已开启：带渠道后缀的模型按基准模型继承定价（仅在唯一命中时）'
      : '已关闭变体继承：带后缀的名字不再自动取价', 'ok');
    if(res.pricing_refresh_started) setTimeout(loadPricingStatus, 4000);
    loadSettings();
  } catch(e) {
    toast('保存失败: ' + e.message, 'bad');
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function refreshPricingNow(btn){
  if(btn) btn.disabled = true;
  try {
    const st = await postJSON('/pricing/refresh', {});
    toast(st.msg || '已开始抓取', 'ok');
    // The fetch runs on the server's own thread, so come back for the result
    // instead of holding the button.
    setTimeout(loadPricingStatus, 4000);
    setTimeout(loadPricingStatus, 15000);
  } catch(e) {
    toast('触发失败: ' + e.message, 'bad');
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function saveAutoSwitchProduct(btn){
  const el = document.getElementById('setAutoSwitch');
  const value = !!(el && el.checked);
  if(btn) btn.disabled = true;
  try {
    await postJSON('/settings/save', {auto_switch_product: value});
    toast(value ? '已启用：429 时自动切换出站身份' : '已关闭自动切换出站身份', 'ok');
    loadSettings();
  } catch(e) {
    toast('保存失败: ' + e.message, 'bad');
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function saveDailyChatWeb(btn){
  const el = document.getElementById('setDailyChatWeb');
  const value = !!(el && el.checked);
  if(btn) btn.disabled = true;
  try {
    await postJSON('/settings/save', {daily_chat_web: value});
    toast(value ? '已启用：国际版打卡走网页渠道' : '已关闭：国际版打卡只发桌面端对话', 'ok');
    loadSettings();
  } catch(e) {
    toast('保存失败: ' + e.message, 'bad');
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function saveLocalWebTools(btn){
  const el = document.getElementById('setLocalWebTools');
  const value = !!(el && el.checked);
  if(btn) btn.disabled = true;
  try {
    await postJSON('/settings/save', {local_web_tools: value});
    toast(value ? '已启用：由网关代跑 web_search / web_fetch' : '已关闭：工具声明原样透传', 'ok');
    loadSettings();
  } catch(e) {
    toast('保存失败: ' + e.message, 'bad');
  } finally {
    if(btn) btn.disabled = false;
  }
}

/* ---- API key list: several keys, each bound to an upstream exit ---- */
let API_KEY_ROWS = [];
let DELETED_KEY_ROWS = [];
let DELETED_KEY_IDS = [];

function randomKeyValue(){
  const bytes = new Uint8Array(18);
  if(window.crypto && crypto.getRandomValues) crypto.getRandomValues(bytes);
  const raw = Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join('');
  // crypto.getRandomValues is present in every supported browser; the
  // timestamp fallback only exists so the field is never left empty.
  return raw || ('wb-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
}

const REALM_CHOICES = [
  ['', '跟随面板切换'],
  ['intl', '固定国际版出口'],
  ['cn', '固定国内版出口'],
];

/* Model allow-list per key. Patterns are matched case-insensitively with `*`
   wildcards ("deepseek*", "gpt-6-astra"). An empty list means no limit, which
   is how every key saved before this field existed comes back. */
function parseModelPatterns(text){
  const out = [];
  String(text || '').split(/[,;]/).forEach(part => {
    const pattern = part.trim().toLowerCase();
    if(pattern && out.indexOf(pattern) === -1) out.push(pattern);
  });
  return out;
}
function modelPatternsText(patterns){
  return Array.isArray(patterns) ? patterns.join(', ') : '';
}

/* 已删除的 Key 是只读历史：密钥已被抹掉，所以这里不提供复制，也不提供恢复。 */
function renderDeletedKeyRows(){
  const box = document.getElementById('deletedKeySection');
  if(!box) return;
  if(!DELETED_KEY_ROWS.length){ box.innerHTML = ''; return; }
  const rows = DELETED_KEY_ROWS.map(k => {
    const choice = REALM_CHOICES.find(([value]) => value === (k.realm || ''));
    const realmLbl = choice ? choice[1] : '出口已移除';
    return '<div style="font-size:12px;color:var(--dim);display:flex;gap:14px;flex-wrap:wrap;padding:7px 0;border-top:1px solid var(--line)">'
      + '<span style="color:var(--fg);font-weight:600">' + esc(k.name || '未命名') + '</span>'
      + '<span>' + esc(realmLbl) + '</span>'
      + (k.created_at ? '<span>创建 ' + esc(k.created_at) + '</span>' : '')
      + (k.deleted_at ? '<span>删除 ' + esc(k.deleted_at) + '</span>' : '')
      + '<span class="mono">' + esc(k.id) + '</span>'
      + '</div>';
  }).join('');
  box.innerHTML = '<details style="margin-top:14px">'
    + '<summary style="cursor:pointer;font-size:12px;color:var(--dim);font-weight:600">已删除的 API Key（'
    + DELETED_KEY_ROWS.length + '）· 只读</summary>'
    + '<div style="margin-top:4px">' + rows + '</div>'
    + '<div style="font-size:11px;color:var(--dim);margin-top:8px">'
    + '删除时密钥已被抹掉，无法恢复、也无法再用于请求。保留这条记录是为了让「按 API Key 的消耗归属」里这些 Key 的历史用量仍然显示名字。'
    + '</div></details>';
}

function renderKeyRows(){
  renderDeletedKeyRows();
  const box = document.getElementById('keyList');
  if(!box) return;
  if(!API_KEY_ROWS.length){
    box.innerHTML = '<div class="empty" style="padding:24px 0">还没有配置 API Key，点击右上角「+ 添加 API Key」创建。</div>';
    return;
  }
  box.innerHTML = API_KEY_ROWS.map((row, i) => {
    if(row._editing){
      const retired = row.realm && !REALM_CHOICES.some(([value]) => value === row.realm);
      const options = (retired ? '<option value="' + esc(row.realm) + '" selected disabled>出口已移除，请选择新出口</option>' : '') + REALM_CHOICES.map(([val, lbl]) =>
        '<option value="' + val + '"' + ((row.realm || '') === val ? ' selected' : '') + '>' + lbl + '</option>'
      ).join('');
      return '<div class="key-card" style="border-color:var(--accent);background:var(--panel);box-shadow:0 0 0 1px var(--accent), var(--shadow-md)">'
        + '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px">'
        +   '<div style="font-size:14px;font-weight:700;color:var(--fg)">' + (row.id ? '编辑 API Key' : '新建 API Key') + '</div>'
        +   '<span class="badge s mini">设置出口</span>'
        + '</div>'
        + '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:14px">'
        +   '<div>'
        +     '<div style="font-size:12px;color:var(--dim);margin-bottom:4px;font-weight:500">备注名称</div>'
        +     '<input type="text" id="editKeyName_' + i + '" value="' + esc(row.name || '') + '" placeholder="如: Cursor / DSH / 本地测试" '
        +       'style="width:100%;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit;color:var(--fg)">'
        +   '</div>'
        +   '<div>'
        +     '<div style="font-size:12px;color:var(--dim);margin-bottom:4px;font-weight:500">出口绑定</div>'
        +     '<select id="editKeyRealm_' + i + '" style="width:100%;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit;color:var(--fg)">'
        +       options
        +     '</select>'
        +   '</div>'
        +   '<div style="grid-column:1 / -1">'
        +     '<div style="font-size:12px;color:var(--dim);margin-bottom:4px;font-weight:500">模型限制 <span style="color:var(--dim-light)">(选填，留空 = 不限制)</span></div>'
        +     '<div style="margin-bottom:8px">允许平台：' + [['workbuddy','WorkBuddy'],['cline','Cline'],['opencode_zen','OpenCode Zen']].map(([name,label]) => '<label style="margin-right:12px"><input type="checkbox" id="editKeyUpstream_' + i + '_' + name + '"' + ((row.allowed_upstreams || ['workbuddy']).includes(name) ? ' checked' : '') + '> ' + label + '</label>').join('') + '</div>'
          +     '<input type="text" id="editKeyModels_' + i + '" value="' + esc(modelPatternsText(row.models)) + '" placeholder="如 deepseek* 或 gpt-6-astra；多个用逗号分隔，支持 * 通配" '
        +       'style="width:100%;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit;color:var(--fg)">'
        +   '</div>'
        +   '<div style="grid-column:1 / -1">'
        +     '<div style="font-size:12px;color:var(--dim);margin-bottom:4px;font-weight:500">API Key 内容 ' + (row.masked ? '<span style="color:var(--dim-light)">(已保存: ' + esc(row.masked) + '，留空表示不改)</span>' : '') + '</div>'
        +     '<div style="display:flex;gap:8px">'
        +       '<input type="text" id="editKeyValue_' + i + '" value="' + esc(row.key || '') + '" placeholder="' + (row.masked ? '留空表示保持原 Key 不变' : '输入自定义密钥，或点击右侧生成') + '" '
        +         'style="flex:1;background:var(--panel2);border:1px solid var(--line);border-radius:8px;padding:7px 10px;font:inherit;color:var(--fg)">'
        +       '<button class="sec mini" style="white-space:nowrap;border-radius:8px;padding:7px 14px"  data-action="generateKeyForEdit" data-on="click" data-arg="' + i + '">随机生成</button>'
        +     '</div>'
        +   '</div>'
        + '</div>'
        + '<div style="display:flex;gap:8px;justify-content:flex-end">'
        +   '<button class="sec mini" style="border-radius:8px;padding:6px 16px"  data-action="cancelEditKey" data-on="click" data-arg="' + i + '">取消</button>'
        +   '<button class="mini" style="border-radius:8px;padding:6px 18px"  data-action="saveSingleKey" data-on="click" data-arg="' + i + '">保存</button>'
        + '</div>'
        + '</div>';
    }

    const statusBadge = row.enabled
      ? '<span class="badge ok" style="font-size:11px;font-weight:600;padding:2px 10px">已启用</span>'
      : '<span class="badge off" style="font-size:11px;font-weight:600;padding:2px 10px">已禁用</span>';

    const realmBadge = (row.realm === 'intl')
      ? '<span class="realm-badge-intl" style="font-size:11px">固定国际版出口</span>'
      : (row.realm === 'cn')
      ? '<span class="realm-badge-cn" style="font-size:11px">固定国内版出口</span>'
      : (row.realm && !REALM_CHOICES.some(([value]) => value === row.realm))
      ? '<span class="badge off" style="font-size:11px">出口已移除，请编辑重新绑定</span>'
      : '<span class="badge s" style="font-size:11px">跟随面板切换</span>';

    const modelBadge = (Array.isArray(row.models) && row.models.length)
      ? '<span class="badge s" style="font-size:11px">限 ' + esc(modelPatternsText(row.models)) + '</span>'
      : '';

    const displayKey = row.masked || (row.key ? (row.key.slice(0, 4) + '******' + row.key.slice(-4)) : '未设置');
    const createdStr = row.created_at ? ('创建时间 ' + esc(row.created_at)) : '';

    return '<div class="key-card' + (row.enabled ? '' : ' disabled') + '">'
      + '<div class="key-card-main">'
      +   '<div>'
      +     '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">'
      +       '<span style="font-size:15px;font-weight:700;color:var(--fg)">' + esc(row.name || '未命名') + '</span>'
      +       statusBadge
      +       realmBadge
      +       '<span class="badge s">' + esc((row.allowed_upstreams || ['workbuddy']).map(name => ({workbuddy:'WorkBuddy',cline:'Cline',opencode_zen:'Zen'}[name] || name)).join(' · ')) + '</span>'
      +       modelBadge
      +     '</div>'
      +     '<div style="font-size:12px;color:var(--dim);display:flex;align-items:center;gap:16px;flex-wrap:wrap">'
      +       '<span>Key: <span class="mono" style="color:var(--fg);font-weight:500">' + esc(displayKey) + '</span></span>'
      +       (createdStr ? ('<span>' + createdStr + '</span>') : '')
      +     '</div>'
      +   '</div>'
      +   '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
      +     '<button class="key-action-btn" id="copyBtn' + i + '"  data-action="copyKeyRow" data-on="click" data-arg="' + i + '">复制</button>'
      +     '<button class="key-action-btn"  data-action="openEditKey" data-on="click" data-arg="' + i + '">编辑</button>'
      +     '<button class="key-action-btn"  data-action="toggleKeyRow" data-on="click" data-arg="' + i + '">' + (row.enabled ? '禁用' : '启用') + '</button>'
      +     '<button class="key-action-btn danger"  data-action="removeKeyRow" data-on="click" data-arg="' + i + '">删除</button>'
      +   '</div>'
      + '</div>'
      + '</div>';
  }).join('');
}

function openEditKey(index){
  if(!API_KEY_ROWS[index]) return;
  API_KEY_ROWS[index]._editing = true;
  renderKeyRows();
}

function cancelEditKey(index){
  if(!API_KEY_ROWS[index]) return;
  if(!API_KEY_ROWS[index].id && !API_KEY_ROWS[index].masked){
    API_KEY_ROWS.splice(index, 1);
  } else {
    API_KEY_ROWS[index]._editing = false;
  }
  renderKeyRows();
}

function generateKeyForEdit(index){
  const el = document.getElementById('editKeyValue_' + index);
  if(el){
    el.value = randomKeyValue();
  }
}

async function saveSingleKey(index, btn){
  const row = API_KEY_ROWS[index];
  if(!row) return;
  const nameInput = document.getElementById('editKeyName_' + index);
  const realmSelect = document.getElementById('editKeyRealm_' + index);
  const keyInput = document.getElementById('editKeyValue_' + index);
  const modelsInput = document.getElementById('editKeyModels_' + index);

  const name = nameInput ? nameInput.value.trim() : (row.name || '');
  const realm = realmSelect ? realmSelect.value : (row.realm || '');
  const keyVal = keyInput ? keyInput.value.trim() : (row.key || '');

  if(!keyVal && !row.masked){
    toast('API Key 不能为空', 'warn');
    return;
  }

  row.name = name || '未命名';
  row.realm = realm;
  const upstreamInputs = ['workbuddy','cline','opencode_zen'].map(name => [name, document.getElementById('editKeyUpstream_' + index + '_' + name)]);
  if(upstreamInputs.some(([name,el]) => el)){
    const allowed = upstreamInputs.filter(([name,el]) => el && el.checked).map(([name]) => name);
    if(!allowed.length){ toast('请选择至少一个平台', 'warn'); return; }
    row.allowed_upstreams = allowed;
  }
  row.models = parseModelPatterns(modelsInput ? modelsInput.value : modelPatternsText(row.models));
  if(keyVal) row.key = keyVal;
  row._editing = false;

  if(btn) btn.disabled = true;
  try {
    if(!await saveApiKeys()){ row._editing = true; return; }
    toast('API Key [' + row.name + '] 已保存', 'ok');
  } catch(e){
    toast('保存失败: ' + e.message, 'bad');
  } finally {
    if(btn) btn.disabled = false;
  }
}

async function toggleKeyRow(index){
  const row = API_KEY_ROWS[index];
  if(!row) return;
  if(!row.enabled && row.realm && !REALM_CHOICES.some(([value]) => value === row.realm)){
    toast('出口已移除，请先编辑并选择新出口', 'warn');
    return;
  }
  row.enabled = !row.enabled;
  try {
    if(!await saveApiKeys()){
      row.enabled = !row.enabled;
      renderKeyRows();
      return;
    }
    toast(row.enabled ? 'Key [' + row.name + '] 已启用' : 'Key [' + row.name + '] 已禁用', 'ok');
  } catch(e){
    row.enabled = !row.enabled;
    renderKeyRows();
    toast('操作失败: ' + e.message, 'bad');
  }
}

async function removeKeyRow(index){
  const row = API_KEY_ROWS[index];
  if(!row) return;
  if(!confirm('确定删除 API Key [' + (row.name || '未命名') + '] 吗？密钥会被抹掉且无法恢复；看板里它已经产生的历史用量仍会保留这个名字。')) return;
  if(row.id && !DELETED_KEY_IDS.includes(row.id)) DELETED_KEY_IDS.push(row.id);
  API_KEY_ROWS.splice(index, 1);
  try {
    if(!await saveApiKeys()){
      DELETED_KEY_IDS = DELETED_KEY_IDS.filter(id => id !== row.id);
      await loadSettings();
      return;
    }
    toast('已删除 API Key', 'ok');
  } catch(e){
    toast('删除失败: ' + e.message, 'bad');
  }
}

function addApiKeyRow(){
  API_KEY_ROWS.push({
    id: '',
    name: '',
    key: randomKeyValue(),
    realm: '',
    allowed_upstreams: ['workbuddy'],
    models: [],
    enabled: true,
    masked: '',
    _editing: true
  });
  renderKeyRows();
  setTimeout(() => {
    const el = document.getElementById('editKeyName_' + (API_KEY_ROWS.length - 1));
    if(el) el.focus();
  }, 50);
}
/* Copy the key in a row, fetching the stored value when the field is blank
   (the panel only ever displays a masked key). */
async function copyKeyRow(index){
  const row = API_KEY_ROWS[index];
  if(!row) return;
  const btn = document.getElementById('copyBtn' + index);
  let value = (row.key || '').trim();
  try {
    if(!value && row.id){
      const data = await getJSON('/settings/reveal?id=' + encodeURIComponent(row.id));
      value = data.key || '';
    }
    if(!value){
      toast('这一行还没有 Key，点「随机生成」或直接填写', 'warn');
      return;
    }
    await writeClipboard(value);
    if(btn){
      const old = btn.textContent;
      btn.textContent = '已复制';
      setTimeout(() => { btn.textContent = old; }, 1600);
    }
    toast('已复制到剪贴板', 'ok');
  } catch(e) {
    toast('复制失败: ' + e.message, 'bad');
  }
}

async function writeClipboard(text){
  // navigator.clipboard needs a secure context; plain http on a LAN address
  // does not qualify, so fall back to a temporary textarea.
  if(navigator.clipboard && window.isSecureContext){
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.cssText = 'position:fixed;top:-1000px;opacity:0';
  document.body.appendChild(area);
  area.select();
  area.setSelectionRange(0, area.value.length);
  const ok = document.execCommand('copy');
  document.body.removeChild(area);
  if(!ok) throw new Error('浏览器拒绝了复制操作');
}

async function saveApiKeys(btn){
  const deletedIds = DELETED_KEY_IDS.slice();
  const payload = API_KEY_ROWS.filter(row => !deletedIds.includes(row.id)).map(row => ({
    id: row.id || '',
    name: row.name || '',
    realm: row.realm || '',
    allowed_upstreams: row.allowed_upstreams || ['workbuddy'],
    models: row.models || [],
    enabled: row.enabled !== false,
    // Blank means "keep the stored key", which the server honours per row.
    key: (row.key || '').trim(),
  }));
  const newRow = API_KEY_ROWS.find(row => !row.masked && !row.id && !(row.key || '').trim());
  if(newRow){
    toast('新增的行还没有填写 Key', 'warn');
    return false;
  }
  // Several callers save without going through a button (saveSingleKey,
  // toggleKeyRow, removeKeyRow), so a missing button must not abort the save.
  if(btn) btn.disabled = true;
  try {
    await postJSON('/settings/save', {api_keys: payload, deleted_api_key_ids: deletedIds});
    DELETED_KEY_IDS = DELETED_KEY_IDS.filter(id => !deletedIds.includes(id));
    toast('已保存 ' + payload.length + ' 个 Key', 'ok');
    await loadSettings();
    return true;
  } catch(e) {
    toast('保存失败: ' + e.message, 'bad');
    return false;
  } finally {
    if(btn) btn.disabled = false;
  }
}
