/* Additional account sources. WorkBuddy's account renderer and OAuth flow
 * stay in accounts.js/core.js with their original DOM and endpoints. */
const ACCOUNT_SOURCE_LABELS = {workbuddy:'WorkBuddy',cline:'Cline',opencode_zen:'OpenCode',commandcode:'Command Code'};
const ACCOUNT_SOURCE_TABS = {workbuddy:'sourceTabWorkbuddy',cline:'sourceTabCline',opencode_zen:'sourceTabOpencode',commandcode:'sourceTabCommandcode'};
const SOURCE_ROOT = '/accounts/upstreams';
let accountSource = 'workbuddy', sourceData = null, sourceLoading = null;
let sourceModelPage = 1, sourceEditUid = null, sourceTestUid = null, sourceRouteModel = null;
const SOURCE_PRIORITY_DRAFTS = new Map();
const SOURCE_ROUTING_DRAFTS = new Map();
const SOURCE_MODEL_GROUPS = new Map();
const sourceEl = id => document.getElementById(id);
const sourceList = () => ((sourceData || {}).accounts || []).filter(a => a.upstream === accountSource);

async function switchAccountSource(source){
  if(!ACCOUNT_SOURCE_LABELS[source]) return;
  accountSource = source;
  sourceModelPage = 1;
  sourceEl('workbuddyAccountsPanel').hidden = source !== 'workbuddy';
  sourceEl('sourceAccountsPanel').hidden = source === 'workbuddy';
  sourceEl('sourceAccountsPanel').dataset.source = source;
  for(const [kind,id] of Object.entries(ACCOUNT_SOURCE_TABS)){
    sourceEl(id).classList.toggle('active', kind === source);
    sourceEl(id).setAttribute('aria-pressed', String(kind === source));
  }
  if(source === 'workbuddy') return;
  sourceEl('sourceModelGroup').value = SOURCE_MODEL_GROUPS.get(source) || 'all';
  sourceEl('sourceSubscriptionOption').textContent = source === 'opencode_zen' ? 'OpenCode Go 订阅' : source === 'cline' ? 'ClinePass 订阅' : '订阅模型';
  sourceEl('sourceAccountsTitle').textContent = ACCOUNT_SOURCE_LABELS[source] + ' 账号';
  sourceEl('sourceLoginButton').hidden = source === 'commandcode';
  sourceEl('sourceCliImport').hidden = source !== 'commandcode';
  sourceEl('sourceAccountHint').textContent = source === 'cline'
    ? '使用浏览器 OAuth 登录，或导入 Cline API Key。ClinePass 可设置为仅调用订阅模型。'
    : source === 'opencode_zen'
    ? 'OAuth 登录并选择组织后，同步 Zen 与 Go 模型。opencode/go/ 开头的模型使用 Go 订阅额度；其余使用 Zen。也可导入 Zen API Key，或添加公开模型客户端。'
    : '导入官方 CLI 的 auth.json 或 user_* 凭据。显示订阅、积分与 5 小时／每周请求额度，额度用尽时自动切换。';
  renderSourceRouting(true);
  if(sourceData){ renderSourceAccounts(); renderSourceModels(); }
  sourceEl('sourceUsage').innerHTML='<div class="hint">正在加载此来源用量…</div>';
  sourceEl('sourceRecent').innerHTML='<div class="hint">正在加载此来源请求…</div>';
  // A switch can arrive while another source's usage request is in flight.
  // Render the selected source immediately, then load its own usage.
  if(sourceLoading) await sourceLoading;
  if(source!==accountSource) return;
  await loadSourceAccounts();
}

async function loadSourceAccounts(){
  if(accountSource === 'workbuddy') return;
  if(sourceLoading) return sourceLoading;
  sourceLoading = (async () => {
    try{
      const data = await getJSON(SOURCE_ROOT + '?models=0');
      data.models = sourceData && sourceData.models_revision === data.models_revision
        ? sourceData.models : (await getJSON(SOURCE_ROOT + '/models')).models || [];
      sourceData = data;
      renderSourceAccounts(); renderSourceRouting(); renderSourceModels();
      const source = accountSource;
      if(source === 'workbuddy') return;
      const usage = await getJSON(SOURCE_ROOT + '/usage?upstream=' + encodeURIComponent(source));
      if(source !== accountSource) return;
      sourceEl('sourceUsage').innerHTML = '<table class="data-cards"><thead><tr><th>模型</th><th>请求 / 错误</th><th>Token</th></tr></thead><tbody>' +
        (usage.totals || []).map(r => '<tr><td data-label="模型">'+esc(r.model)+'</td><td data-label="请求">'+fmt(r.requests)+' / '+fmt(r.errors)+'</td><td data-label="Token">'+fmtTokens(r.total_tokens)+'</td></tr>').join('') + '</tbody></table>';
      sourceEl('sourceRecent').innerHTML = '<table class="data-cards"><thead><tr><th>时间</th><th>模型 / 账号</th><th>结果 / 渠道</th><th>Token</th></tr></thead><tbody>' +
        (usage.recent || []).map(r => '<tr><td data-label="时间">'+esc(r.iso)+'</td><td data-label="模型">'+esc(r.model)+'<div class="hint">'+esc(r.account || '—')+'</div></td><td data-label="结果"><span class="badge '+(r.outcome==='completed'?'ok':r.outcome==='client_aborted'?'warn':'bad')+'">'+esc(r.outcome || '未知')+'</span><div class="hint">'+esc(r.actual_provider || r.message || '')+'</div></td><td data-label="Token">'+fmtTokens(r.total_tokens || 0)+'</td></tr>').join('') + '</tbody></table>';
    }catch(e){ if(!isAuthError(e)) toast('账号来源加载失败：'+e.message,'bad'); }
  })();
  try { await sourceLoading; } finally { sourceLoading = null; }
}

function renderSourceAccounts(){
  const list = sourceList().sort((a,b) => Number(b.enabled)-Number(a.enabled) || a.priority-b.priority);
  sourceEl('sourceAccountSummary').textContent = '共 '+list.length+' 个 · 启用 '+list.filter(a=>a.enabled).length+' 个';
  const target = sourceEl('sourceAccountsTable');
  if(target.contains(document.activeElement)) return;
  if(!list.length){ target.innerHTML = '<div class="empty">此来源还没有账号，请登录或导入。</div>'; return; }
  target.innerHTML = '<div class="table-wrap"><table class="data-cards source-account-cards"><thead><tr><th>账号</th><th>状态</th><th>出口</th><th>调度优先级</th><th>余额 / 额度</th><th>今日用量</th><th>操作</th></tr></thead><tbody>' + list.map(a => {
    const uid = esc(a.uid), today = a.today || {}, balance = a.balance || {};
    const slot = ((sourceData || {}).proxy_slots || []).find(s=>s.id===a.proxy_slot);
    const cooldown = Math.max(0, Number((a.cooldowns || {})['*']) || 0);
    const partialCooldown = Object.entries(a.cooldowns || {}).some(([model,seconds])=>model!=='*' && seconds>0);
    const state = !a.enabled ? '停用' : a.credit_exhausted ? '积分耗尽' : cooldown ? '冷却 '+fmt(cooldown)+' 秒' : a.credential_ready === false ? '等待组织配置' : partialCooldown ? '部分模型冷却' : '启用';
    const stateTone = !a.enabled ? 'off' : a.credit_exhausted ? 'bad' : cooldown || a.credential_ready===false || partialCooldown ? 'warn' : 'ok';
    const unit = a.upstream === 'opencode_zen' ? 'USD' : '积分';
    const windows = a.quota || {}, billingStatus=a.billing_status || {};
    const quota = Object.entries(windows).map(([key,value]) => {
      if(!value || typeof value!=='object') return '';
      const label={fiveHour:'5 小时',weekly:'每周',monthly:'每月'}[key] || key;
      const usage=value.percent_used != null ? '剩余 '+fmt(value.remaining_percent)+'%（已用 '+fmt(value.percent_used)+'%）'
        : value.cap != null ? fmt(value.used || 0)+' / '+fmt(value.cap)+' 条' : '未知';
      const reset=value.reset_at || value.resetAt;
      const tone = (billingStatus.quota || {}).stale ? 'warn' : value.remaining_percent!=null ? value.remaining_percent<=0?'bad':value.remaining_percent<=10?'warn':'ok' : 'info';
      return '<div class="hint source-quota" data-tone="'+tone+'">'+esc(label)+' '+esc(usage)+((billingStatus.quota || {}).stale?'（缓存）':'')+(reset?' · '+esc(new Date(reset).toLocaleString())+' 重置':'')+'</div>';
    }).join('');
    const subscription=a.subscription || {};
    const planPrice=subscription.price==null?'':'<div class="hint">订阅 $'+sourcePriceNumber(subscription.price)+(subscription.interval?' / '+esc({month:'月',monthly:'月',year:'年'}[subscription.interval] || subscription.interval):'')+'</div>';
    const billingErrors=[...new Set(Object.values(a.billing_errors || {}))].map(value=>'<div class="hint source-notice" data-tone="bad">'+esc(value)+'</div>').join('');
    const queriedAt=Math.max(0,...Object.values(billingStatus).map(value=>Number(value.updated_at) || 0),Number(balance.updated_at) || 0);
    const queried=queriedAt?'<div class="hint">更新于 '+esc(new Date(queriedAt*1000).toLocaleString())+'</div>':'';
    const action = (name,label) => '<button class="sec mini" data-action="'+name+'" data-on="click" data-uid="'+uid+'">'+label+'</button>';
    return '<tr data-source-uid="'+uid+'"><td data-label="账号"><b class="source-account-name" title="'+esc(a.nickname)+'">'+esc(a.nickname)+'</b><div class="hint">'+esc(a.public?'公开模型客户端':a.auth_type==='oauth'?'OAuth 登录':'API Key / CLI 凭据')+(a.plan?' · '+esc(a.plan):'')+'</div><div class="hint">'+esc(a.org_id || a.uid)+'</div></td>'+
      '<td data-label="状态"><span class="badge '+stateTone+'">'+esc(state)+'</span><div class="hint">在途 '+fmt(a.in_flight || 0)+'</div><div><span class="badge '+(a.verified_at?'ok':'off')+'">'+(a.verified_at?'调用已验证':'调用未验证')+'</span></div><div class="hint source-notice" data-tone="'+(a.console_config_error || a.last_error?'warn':'info')+'">'+esc(a.console_config_error || a.last_error || a.last_provider && a.last_provider.provider || '')+'</div></td>'+
      '<td data-label="出口">'+esc(slot && slot.label || a.proxy_slot || '直接连接')+'</td>'+
      '<td data-label="调度优先级"><input id="sourcePriority_'+uid+'" aria-label="'+esc(a.nickname)+' 调度优先级" type="number" min="0" max="2147483647" value="'+esc(SOURCE_PRIORITY_DRAFTS.has(a.uid)?SOURCE_PRIORITY_DRAFTS.get(a.uid):a.priority)+'" data-action="editSourcePriority" data-on="input" data-uid="'+uid+'" style="width:92px"> '+action('saveSourcePriority','保存优先级')+'</td>'+
      '<td data-label="余额 / 额度"><span class="source-balance-value">'+(balance.remain == null?'未知':fmt(balance.remain)+' '+esc(balance.unit==='credits'?'积分':balance.unit || unit))+((billingStatus.balance || {}).stale?'（缓存）':'')+'</span>'+(subscription.name?'<div><span class="badge subscription">'+esc(subscription.name)+'</span></div>':'')+planPrice+quota+queried+(balance.note?'<div class="hint">'+esc(balance.note)+'</div>':'')+billingErrors+'</td>'+
      '<td data-label="今日用量">'+fmtTokens(today.tokens || 0)+' Token<div class="hint">免费 '+fmtTokens(today.free_tokens || 0)+'</div><div class="hint">消费 '+fmt(today.paid_cost || 0)+' '+unit+'</div></td>'+
      '<td data-label="操作"><div class="source-account-actions">'+action('openSourceEditor','编辑')+action('toggleSourceAccount',a.enabled?'停用':'启用')+action('preferSourceAccount','优先使用')+action('refreshSourceBilling','查询余额／额度')+action('openSourceTest','测试调用')+action('exportSourceAccount','导出')+action('exportSourceAccountSecrets','导出含凭据')+action('deleteSourceAccount','删除')+'</div></td></tr>';
  }).join('') + '</tbody></table></div><p class="hint">优先级越小越早调用；保存后重启保留。同优先级下，免费模型均衡 Token，付费模型均衡实际消费，并计入在途请求。自动模式使用较大窗口保留会话账号。</p>';
}

function renderSourceRouting(force){
  if(!sourceData) return;
  const mode = sourceEl('sourceRoutingMode'), preferred = sourceEl('sourcePreferredAccount');
  if(!force && (document.activeElement===mode || document.activeElement===preferred)) return;
  const routing = SOURCE_ROUTING_DRAFTS.get(accountSource) || (sourceData.routing || {})[accountSource] || {};
  mode.value = routing.mode || 'fair';
  preferred.innerHTML = sourceList().map(a=>'<option value="'+esc(a.uid)+'">'+esc(a.nickname)+'</option>').join('');
  preferred.value = routing.uid || (sourceList()[0] || {}).uid || '';
  sourceRoutingModeChanged();
}
function sourceRoutingModeChanged(editing=false){
  sourceEl('sourcePreferredLabel').hidden = sourceEl('sourceRoutingMode').value !== 'manual';
  if(editing) SOURCE_ROUTING_DRAFTS.set(accountSource,{mode:sourceEl('sourceRoutingMode').value,uid:sourceEl('sourcePreferredAccount').value});
}
async function saveSourceRouting(){
  const source=accountSource;
  try { await postJSON(SOURCE_ROOT+'/routing',{upstream:source,mode:sourceEl('sourceRoutingMode').value,uid:sourceEl('sourcePreferredAccount').value}); SOURCE_ROUTING_DRAFTS.delete(source); toast('调度方式已保存','ok'); await loadSourceAccounts(); if(source===accountSource) renderSourceRouting(true); }
  catch(e){ toast(e.message,'bad'); }
}
async function preferSourceAccount(uid){
  const source=accountSource;
  try { await postJSON(SOURCE_ROOT+'/routing',{upstream:source,mode:'manual',uid}); SOURCE_ROUTING_DRAFTS.delete(source); toast('优先账号已保存','ok'); await loadSourceAccounts(); if(source===accountSource) renderSourceRouting(true); }
  catch(e){ toast(e.message,'bad'); }
}
function editSourcePriority(uid,el){ SOURCE_PRIORITY_DRAFTS.set(uid,el.value); }
async function saveSourcePriority(uid){
  const value = sourceEl('sourcePriority_'+uid).value;
  if(!value.trim() || !Number.isInteger(Number(value)) || Number(value)<0 || Number(value)>2147483647){ toast('优先级必须是 0–2147483647 的整数','bad'); return; }
  try { await postJSON(SOURCE_ROOT+'/accounts/update',{uid,priority:Number(value)}); SOURCE_PRIORITY_DRAFTS.delete(uid); await loadSourceAccounts(); toast('优先级已持久化','ok'); }
  catch(e){ toast(e.message,'bad'); }
}
async function toggleSourceAccount(uid){
  const row = sourceList().find(a=>a.uid===uid); if(!row) return;
  try { await postJSON(SOURCE_ROOT+'/accounts/update',{uid,enabled:!row.enabled}); await loadSourceAccounts(); }
  catch(e){ toast(e.message,'bad'); }
}
async function deleteSourceAccount(uid){
  if(!confirm('删除此账号？已记录的用量仍保留。')) return;
  try { await postJSON(SOURCE_ROOT+'/accounts/update',{uid,delete:true}); await loadSourceAccounts(); }
  catch(e){ toast(e.message,'bad'); }
}
async function batchSourceAccounts(enabled){
  const uids = sourceList().map(a=>a.uid); if(!uids.length) return;
  try { for(let i=0;i<uids.length;i+=500) await postJSON(SOURCE_ROOT+'/accounts/batch',{uids:uids.slice(i,i+500),enabled}); await loadSourceAccounts(); }
  catch(e){ toast(e.message,'bad'); }
}
async function refreshAccountSource(){
  try { await postJSON(SOURCE_ROOT+'/refresh',{upstream:accountSource}); toast('正在刷新此来源的凭证、余额和模型','ok'); }
  catch(e){ toast(e.message,'bad'); }
}

function openSourceEditor(uid){
  const account = sourceList().find(a=>a.uid===uid);
  sourceEditUid = account && account.uid || null;
  sourceEl('sourceEditorTitle').textContent = (account?'编辑':'导入')+' '+ACCOUNT_SOURCE_LABELS[accountSource]+' 账号';
  sourceEl('sourceName').value = account && account.nickname || '';
  sourceEl('sourcePriority').value = account && account.priority != null ? account.priority : 100;
  sourceEl('sourceProxy').innerHTML = '<option value="">直接连接</option>'+((sourceData || {}).proxy_slots || []).map(s=>'<option value="'+esc(s.id)+'">'+esc(s.label || s.id)+'</option>').join('');
  sourceEl('sourceProxy').value = account && account.proxy_slot || '';
  sourceEl('sourceAuth').innerHTML = '<option value="api_key">API Key / CLI 凭据</option>' + (accountSource==='commandcode'?'':'<option value="oauth">OAuth 凭据（手动导入）</option>') + (accountSource==='opencode_zen' && (!account || account.public)?'<option value="public">公开免费模型（客户端模式）</option>':'');
  sourceEl('sourceAuth').value = account && account.public ? 'public' : account && account.auth_type || 'api_key';
  sourceEl('sourceAuthLabel').hidden = !!(account && account.public);
  sourceEl('sourceToken').value = ''; sourceEl('sourceRefresh').value = '';
  sourceEl('sourceToken').placeholder = account?'留空保留原凭据':'仅保存到私有账号目录';
  sourceEl('sourceScope').value = account && account.access_scope || 'all';
  sourceEl('sourceScopeLabel').hidden = accountSource !== 'cline';
  sourceEl('sourceModelsAllow').value = ((account || {}).models || []).join(', ');
  sourceEl('sourceAccountOrg').innerHTML = ((account || {}).orgs || []).map(o=>'<option value="'+esc(o.id)+'">'+esc(o.name || o.id)+'</option>').join('');
  sourceEl('sourceAccountOrg').value = account && account.org_id || '';
  sourceEl('sourceEditorHint').textContent = accountSource==='commandcode'?'使用官方 CLI auth.json 中的 user_* apiKey，也可从账号页导入文件。':accountSource==='opencode_zen'?'OAuth 首次登录请使用账号页的浏览器登录按钮。公开模式仅调用明确免费的模型，保留上游权限限制。':'OAuth 首次登录请使用账号页的浏览器登录按钮。API Key 使用原始凭据，OAuth 使用 WorkOS 凭据。';
  sourceEl('sourceEditorStatus').textContent = '';
  sourceAuthChanged(); sourceEl('sourceEditorModal').classList.add('show'); sourceEl('sourceName').focus();
}
function sourceAuthChanged(){
  const kind = sourceEl('sourceAuth').value;
  sourceEl('sourceTokenLabel').hidden = kind === 'public';
  sourceEl('sourceRefreshLabel').hidden = kind !== 'oauth';
  const account = sourceList().find(a=>a.uid===sourceEditUid);
  sourceEl('sourceOrgLabel').hidden = !(accountSource==='opencode_zen' && account && account.auth_type==='oauth' && (account.orgs || []).length);
}
function closeSourceEditor(){ sourceEl('sourceEditorModal').classList.remove('show'); sourceEl('sourceToken').value=''; sourceEl('sourceRefresh').value=''; sourceEditUid=null; }
async function saveSourceAccount(){
  const raw = sourceEl('sourcePriority').value, priority = Number(raw);
  if(!raw.trim() || !Number.isInteger(priority) || priority<0 || priority>2147483647){ sourceEl('sourceEditorStatus').textContent='优先级必须是 0–2147483647 的整数'; return; }
  const kind = sourceEl('sourceAuth').value;
  const body = {upstream:accountSource,name:sourceEl('sourceName').value,priority,proxy_slot:sourceEl('sourceProxy').value,
    models:sourceEl('sourceModelsAllow').value.split(/[,\n]/).map(s=>s.trim()).filter(Boolean),auth_type:kind==='public'?'api_key':kind};
  if(accountSource==='cline') body.access_scope=sourceEl('sourceScope').value;
  if(kind==='public'){ body.public=true; if(!sourceEditUid) body.enabled=true; }
  const token=sourceEl('sourceToken').value.trim(), refresh=sourceEl('sourceRefresh').value.trim();
  if(token) body[kind==='oauth'?'access_token':'api_key']=token;
  if(refresh) body.refresh_token=refresh;
  if(sourceEditUid) body.uid=sourceEditUid;
  try{
    await postJSON(SOURCE_ROOT+'/accounts/'+(sourceEditUid?'update':'import'),body);
    const original=sourceList().find(a=>a.uid===sourceEditUid), org=sourceEl('sourceAccountOrg').value;
    if(original && original.auth_type==='oauth' && accountSource==='opencode_zen' && org && org!==original.org_id)
      await postJSON(SOURCE_ROOT+'/accounts/org',{uid:sourceEditUid,org_id:org});
    closeSourceEditor(); await loadSourceAccounts(); toast('账号已保存','ok');
  }catch(e){ sourceEl('sourceEditorStatus').textContent='保存失败：'+e.message; }
}
function openSourceFile(){ sourceEl('sourceImportFile').click(); }
async function importSourceFile(el){
  const file=el.files && el.files[0]; if(!file) return;
  try{
    if(file.size>1024*1024) throw new Error('账号文件不能超过 1 MiB');
    const document=JSON.parse(await file.text());
    const rows=Array.isArray(document)?document:Array.isArray(document.accounts)?document.accounts:[document];
    const accounts=rows.map(row=>{ if(row.upstream && row.upstream!==accountSource) throw new Error('请选择文件对应的账号来源'); return {...row,upstream:accountSource}; });
    await postJSON(SOURCE_ROOT+'/accounts/import',accounts); await loadSourceAccounts(); toast('账号文件已导入','ok');
  }catch(e){ toast('导入失败：'+e.message,'bad'); } finally{ el.value=''; }
}
async function importCommandCli(){
  try { await postJSON(SOURCE_ROOT+'/accounts/cli-import',{}); await loadSourceAccounts(); toast('服务器 CLI 账号已导入','ok'); }
  catch(e){ toast('导入失败：'+e.message+'；也可上传客户端的 auth.json','bad'); }
}
async function exportSourceAccounts(uid,includeSecrets=false){
  if(includeSecrets && !confirm('导出文件将包含 API Key、访问令牌等明文凭据，可用于迁移或恢复账号。请妥善保管，确认继续导出？')) return;
  try{
    const data=await getJSON(SOURCE_ROOT+'/accounts/export?upstream='+encodeURIComponent(accountSource)+(uid?'&uid='+encodeURIComponent(uid):'')+'&includeSecrets='+(includeSecrets?'1':'0'));
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const link=document.createElement('a'); link.href=url; link.download='fhub-'+accountSource+'-accounts.json'; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000);
    toast(includeSecrets?'已导出（文件含明文凭据，请妥善保管）':'已导出账号信息（不含凭据）','ok');
  }catch(e){ toast('导出失败：'+e.message,'bad'); }
}

let sourceOAuth = null, sourceOAuthTimer = null, sourceOAuthGeneration = 0, sourceOAuthPolling = false;
function stopSourceOAuth(){
  if(sourceOAuthTimer) clearInterval(sourceOAuthTimer); sourceOAuthTimer=null;
  if(sourceOAuth && sourceOAuth.id) postJSON(SOURCE_ROOT+'/login/cancel',{id:sourceOAuth.id}).catch(()=>{});
  sourceOAuth=null; sourceOAuthPolling=false;
}
function closeSourceOAuth(){ ++sourceOAuthGeneration; stopSourceOAuth(); sourceEl('sourceOAuthModal').classList.remove('show'); }
function openSourceOAuth(){
  if(!['cline','opencode_zen'].includes(accountSource)) return;
  closeSourceEditor();
  sourceEl('sourceOAuthTitle').textContent='添加 '+ACCOUNT_SOURCE_LABELS[accountSource]+' 账号 (OAuth 授权)';
  sourceEl('sourceOAuthModal').classList.add('show');
  restartSourceOAuth();
}
async function restartSourceOAuth(){
  stopSourceOAuth(); const generation=++sourceOAuthGeneration, source=accountSource;
  sourceEl('sourceLoginLinkBox').innerHTML=''; sourceEl('sourceLoginStatus').textContent=''; sourceEl('sourceOrgChoice').hidden=true;
  sourceEl('sourceLoginStatus').dataset.tone='info';
  sourceEl('sourceStep1').className='step active'; sourceEl('sourceStep2').className='step'; sourceEl('sourceStep3').className='step';
  sourceEl('sourceStep1Text').textContent='正在申请 '+ACCOUNT_SOURCE_LABELS[source]+' 授权登录链接…';
  try{
    const job=await postJSON(SOURCE_ROOT+'/login/start',{upstream:source});
    if(generation!==sourceOAuthGeneration){ postJSON(SOURCE_ROOT+'/login/cancel',{id:job.id}).catch(()=>{}); return; }
    if(!job.url || !job.url.startsWith('https://')) throw new Error('上游没有返回有效的授权链接');
    sourceOAuth={...job,upstream:source};
    sourceEl('sourceStep1').className='step done'; sourceEl('sourceStep2').className='step active';
    sourceEl('sourceStep1Text').textContent=ACCOUNT_SOURCE_LABELS[source]+' 授权登录链接已生成';
    sourceEl('sourceLoginLinkBox').innerHTML='<a class="login-link" href="'+esc(job.url)+'" target="_blank" rel="noopener noreferrer">'+esc(job.url)+'</a>'+
      (job.code?'<div class="source-login-code">设备码 <b>'+esc(job.code)+'</b><button class="sec mini" data-action="copySourceLoginCode" data-on="click">复制设备码</button></div>':'')+
      '<div class="hint">点击上方链接打开授权页面。登录完成后本窗口自动检测并加入账号池。</div>';
    await pollSourceOAuth(generation);
    if(generation===sourceOAuthGeneration && sourceOAuth) sourceOAuthTimer=setInterval(()=>pollSourceOAuth(generation),2500);
  }catch(e){ if(generation===sourceOAuthGeneration){ sourceEl('sourceLoginStatus').textContent='发起失败：'+e.message; sourceEl('sourceLoginStatus').dataset.tone='bad'; } }
}
async function copySourceLoginCode(){
  try { if(sourceOAuth && sourceOAuth.code) await navigator.clipboard.writeText(sourceOAuth.code); toast('设备码已复制','ok'); }
  catch(e){ toast('复制失败，请选中设备码手动复制','warn'); }
}
async function pollSourceOAuth(generation=sourceOAuthGeneration){
  if(!sourceOAuth || sourceOAuthPolling || generation!==sourceOAuthGeneration) return;
  sourceOAuthPolling=true; const id=sourceOAuth.id;
  try{
    const job=await getJSON(SOURCE_ROOT+'/login/poll?id='+encodeURIComponent(id));
    if(generation!==sourceOAuthGeneration || !sourceOAuth || id!==sourceOAuth.id) return;
    sourceEl('sourceStep3').className='step active';
    sourceEl('sourceLoginStatus').dataset.tone=job.status==='completed'?'ok':['failed','denied'].includes(job.status)?'bad':['expired','cancelled'].includes(job.status)?'warn':'info';
    if(job.status==='select_org'){
      sourceEl('sourceOrgChoice').hidden=false;
      const org=sourceEl('sourceLoginOrg'), selected=org.value;
      org.innerHTML=(job.orgs || []).map(o=>'<option value="'+esc(o.id)+'">'+esc(o.name || o.id)+'</option>').join('');
      if((job.orgs || []).some(o=>o.id===selected)) org.value=selected;
      sourceEl('sourceLoginStatus').textContent='授权成功，请选择要接入的组织。';
    }else if(job.status==='completed'){
      sourceEl('sourceStep2').className='step done'; sourceEl('sourceStep3').className='step done';
      sourceEl('sourceOrgChoice').hidden=true; sourceEl('sourceLoginStatus').textContent='登录成功，账号已加入账号池。';
      if(sourceOAuthTimer) clearInterval(sourceOAuthTimer); sourceOAuthTimer=null; sourceOAuth=null; await loadSourceAccounts();
    }else if(['failed','expired','denied','cancelled'].includes(job.status)){
      if(sourceOAuthTimer) clearInterval(sourceOAuthTimer); sourceOAuthTimer=null; sourceOAuth=null;
      sourceEl('sourceLoginStatus').textContent=job.error || ({expired:'授权链接已过期，请重新生成。',denied:'授权已拒绝。',cancelled:'已取消授权。'}[job.status] || '授权失败。');
    }else sourceEl('sourceLoginStatus').textContent='等待浏览器授权…';
  }catch(e){ if(generation===sourceOAuthGeneration){ sourceEl('sourceLoginStatus').textContent='查询授权状态失败：'+e.message; sourceEl('sourceLoginStatus').dataset.tone='bad'; } }
  finally { if(generation===sourceOAuthGeneration) sourceOAuthPolling=false; }
}
async function completeSourceOAuth(){
  if(!sourceOAuth) return; const generation=sourceOAuthGeneration;
  try { await postJSON(SOURCE_ROOT+'/login/complete',{id:sourceOAuth.id,org_id:sourceEl('sourceLoginOrg').value}); await pollSourceOAuth(generation); }
  catch(e){ if(generation===sourceOAuthGeneration) sourceEl('sourceLoginStatus').textContent='接入组织失败：'+e.message; }
}

function sourcePriceNumber(value){ return Number(value).toLocaleString('en-US',{maximumFractionDigits:8}); }
function sourceModelPrice(model){
  const price=model.pricing || model.reference_pricing;
  if(!price || price.input==null && price.prompt==null && price.output==null && price.completion==null) return '上游未提供';
  if(price.unit && !['USD/token','USD/1M tokens'].includes(price.unit)) return '价格单位：'+esc(price.unit);
  const multiplier=price.unit==='USD/token'?1000000:1;
  const rate=keys=>{ const key=keys.find(k=>price[k]!=null && typeof price[k]!=='boolean' && String(price[k]).trim() && Number.isFinite(Number(price[k])) && Number(price[k])>=0); return key?'$'+sourcePriceNumber(Number(price[key])*multiplier):'未知'; };
  return '输入 '+rate(['input','prompt'])+' · 输出 '+rate(['output','completion'])+'<div class="hint">缓存读 '+rate(['cache_read','input_cache_read'])+' · 写 '+rate(['cache_write','input_cache_write'])+'</div><div class="hint">USD / 1M Token'+(model.entitlement==='subscription'?' · 订阅配额参考价':model.reference_pricing && !model.pricing?' · 参考价':'')+(price.stale?' · 缓存价格':'')+'</div>';
}
function sourceModelEntitlement(model){
  if(model.entitlement==='subscription') return {opencode_zen:'OpenCode Go 订阅',cline:'ClinePass 订阅',commandcode:'Command Code 订阅'}[model.upstream] || '订阅模型';
  return {free:'免费',recommended:'积分模型',account:'积分模型',clineCloud:'Cline Cloud'}[model.entitlement]
    || model.min_plan || (model.billing_mode==='free'?'免费':'付费');
}
function renderSourceModels(){
  const query=sourceEl('sourceModelSearch').value.toLowerCase();
  const group=sourceEl('sourceModelGroup').value || 'all';
  const list=((sourceData || {}).models || []).filter(m=>m.upstream===accountSource && (m.id+' '+(m.name || '')).toLowerCase().includes(query)
    && (group==='all' || group==='subscription' && m.entitlement==='subscription' || group==='free' && m.billing_mode==='free'
      || group==='paid' && m.billing_mode!=='free' && m.entitlement!=='subscription'))
    .sort((a,b)=>(a.entitlement==='subscription'?0:a.billing_mode==='free'?1:2)-(b.entitlement==='subscription'?0:b.billing_mode==='free'?1:2) || a.id.localeCompare(b.id));
  const pages=Math.max(1,Math.ceil(list.length/50)); sourceModelPage=Math.min(sourceModelPage,pages);
  sourceEl('sourceModelsPager').textContent=sourceModelPage+' / '+pages+' 页 · '+list.length+' 个模型';
  const catalog=((sourceData || {}).catalogues || {})[accountSource] || {};
  const passCount=(catalog.groups || {}).subscription;
  sourceEl('sourceCatalogStatus').textContent=catalog.error || (catalog.refreshing?'正在同步模型…':catalog.updated_at?(catalog.stale?'模型缓存已过期，请刷新目录。':'目录已同步；仅显示已启用账号允许调用的模型。'):'等待模型同步；请先添加账号。');
  if(accountSource==='cline' && passCount!=null) sourceEl('sourceCatalogStatus').textContent+=' ClinePass 已采集 '+passCount+' 个模型。';
  if(catalog.metadata_stale) sourceEl('sourceCatalogStatus').textContent+=' 价格与客户端元数据暂未同步。';
  sourceEl('sourceCatalogStatus').dataset.tone=catalog.error?'bad':catalog.stale || catalog.metadata_stale?'warn':catalog.updated_at && !catalog.refreshing?'ok':'info';
  sourceEl('sourceModels').innerHTML='<table class="data-cards"><thead><tr><th>模型 ID</th><th>协议</th><th>计费 / 权益</th><th>价格</th><th>上下文</th>'+(accountSource==='cline'?'<th>上游渠道</th>':'')+'</tr></thead><tbody>'+list.slice((sourceModelPage-1)*50,sourceModelPage*50).map(m=>'<tr><td data-label="模型 ID"><code>'+esc(m.id)+'</code></td><td data-label="协议"><span class="badge s">'+esc(m.native_protocol)+'</span></td><td data-label="计费"><span class="badge '+(m.entitlement==='subscription'?'subscription':m.billing_mode==='free'?'ok':'paid')+'">'+esc(sourceModelEntitlement(m))+'</span></td><td data-label="价格">'+sourceModelPrice(m)+'</td><td data-label="上下文">'+(m.context_length?fmtTokens(m.context_length):'上游未提供')+'</td>'+(accountSource==='cline'?'<td data-label="上游渠道"><button class="sec mini" data-action="openSourceRoute" data-on="click" data-arg="'+esc(m.upstream_model || m.id.slice(6))+'">配置渠道</button></td>':'')+'</tr>').join('')+'</tbody></table>';
}
function filterSourceModels(){ SOURCE_MODEL_GROUPS.set(accountSource,sourceEl('sourceModelGroup').value || 'all'); sourceModelPage=1; renderSourceModels(); }
async function refreshSourceBilling(uid){
  try { await getJSON(SOURCE_ROOT+'/billing?uid='+encodeURIComponent(uid)+'&refresh=1'); toast('正在查询余额与订阅额度'); await loadSourceAccounts(); }
  catch(error){ toast('查询失败：'+error.message,'bad'); }
}
function pageSourceModels(step){ sourceModelPage=Math.max(1,sourceModelPage+Number(step)); renderSourceModels(); }
function openSourceTest(uid){
  sourceTestUid=uid; sourceEl('sourceTestTitle').textContent='测试 '+((sourceList().find(a=>a.uid===uid) || {}).nickname || '账号');
  sourceEl('sourceTestModel').innerHTML=((sourceData || {}).models || []).filter(m=>m.upstream===accountSource).map(m=>'<option value="'+esc(m.id)+'">'+esc(m.id)+'</option>').join('');
  sourceEl('sourceTestStatus').textContent=''; sourceEl('sourceTestModal').classList.add('show');
}
function closeSourceTest(){ sourceEl('sourceTestModal').classList.remove('show'); sourceTestUid=null; }
async function runSourceTest(){
  const uid=sourceTestUid, model=sourceEl('sourceTestModel').value; if(!uid || !model) return;
  sourceEl('sourceTestStatus').textContent='正在调用…';
  try { const r=await postJSON(SOURCE_ROOT+'/accounts/test',{uid,model}); if(uid===sourceTestUid) sourceEl('sourceTestStatus').textContent='调用成功 · '+fmtTokens((r.usage || {}).total_tokens || 0)+' Token'; await loadSourceAccounts(); }
  catch(e){ if(uid===sourceTestUid) sourceEl('sourceTestStatus').textContent='调用失败：'+e.message; }
}
function openSourceRoute(model){
  sourceRouteModel=model; const policy=((sourceData || {}).cline_routes || {})[model] || {};
  sourceEl('sourceRouteTitle').textContent='Cline 上游渠道 · '+model;
  for(const [id,value] of Object.entries({sourceRouteMode:policy.mode || 'auto',sourceRouteSort:policy.sort || '',sourceRouteProviders:(policy.providers || []).join(', '),sourceRouteIgnore:(policy.excluded || []).join(', '),sourceRouteKnown:(policy.known_providers || []).join(', ')})) sourceEl(id).value=value;
  sourceEl('sourceRouteStatus').textContent=''; sourceEl('sourceRouteModal').classList.add('show');
}
function closeSourceRoute(){ sourceEl('sourceRouteModal').classList.remove('show'); sourceRouteModel=null; }
async function saveSourceRoute(){
  const split=id=>sourceEl(id).value.split(',').map(s=>s.trim()).filter(Boolean);
  try { await postJSON(SOURCE_ROOT+'/cline-route',{model:sourceRouteModel,policy:{mode:sourceEl('sourceRouteMode').value,sort:sourceEl('sourceRouteSort').value,providers:split('sourceRouteProviders'),excluded:split('sourceRouteIgnore'),known_providers:split('sourceRouteKnown')}}); closeSourceRoute(); await loadSourceAccounts(); toast('上游渠道设置已保存','ok'); }
  catch(e){ sourceEl('sourceRouteStatus').textContent=e.message; }
}

async function loadResponseStorage(){
  try{
    const data=await getJSON('/settings/responses'), storage=data.responses || {};
    sourceEl('responseStorageSummary').textContent=fmt(storage.count || 0)+' 条响应 · '+((storage.bytes || 0)/1048576).toFixed(2)+' / '+storage.max_mb+' MiB';
    for(const name of ['enabled','retention_days','max_mb']){ const el=sourceEl('responseStorage_'+name); if(!el.dataset.initialized){ if(name==='enabled') el.checked=storage[name]; else el.value=storage[name]; el.dataset.initialized='1'; } }
    sourceEl('responseConversations').innerHTML=(storage.conversations || []).map(c=>'<div class="toolbar"><code>'+esc(c.id)+'</code><span>'+esc(c.model)+' · '+fmt(c.responses)+' 条</span><button class="sec mini" data-action="deleteResponseConversation" data-on="click" data-arg="'+esc(c.id)+'">删除整个会话</button></div>').join('') || '<div class="hint">暂无已保存会话</div>';
  }catch(e){ if(!isAuthError(e)) toast('会话设置读取失败：'+e.message,'bad'); }
}
async function saveResponseStorage(){
  try { await postJSON('/settings/responses',{enabled:sourceEl('responseStorage_enabled').checked,retention_days:Number(sourceEl('responseStorage_retention_days').value),max_mb:Number(sourceEl('responseStorage_max_mb').value)}); await loadResponseStorage(); toast('会话设置已保存','ok'); }
  catch(e){ toast(e.message,'bad'); }
}
async function deleteResponseConversation(conversation){
  if(!confirm('删除整个会话及所有分支？此操作无法撤销。')) return;
  try { await postJSON('/settings/responses/delete',{conversation}); await loadResponseStorage(); }
  catch(e){ toast(e.message,'bad'); }
}
document.addEventListener('keydown',event=>{
  if(event.key!=='Escape') return;
  for(const [id,close] of [['sourceOAuthModal',closeSourceOAuth],['sourceEditorModal',closeSourceEditor],['sourceTestModal',closeSourceTest],['sourceRouteModal',closeSourceRoute]]) if(sourceEl(id).classList.contains('show')) close();
});
window.addEventListener('pagehide',()=>{ ++sourceOAuthGeneration; stopSourceOAuth(); });
