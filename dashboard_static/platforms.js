let PLATFORM_DATA = null;
let PLATFORM_LOGIN_TIMER = null;
let PLATFORM_LOADING = null;
const PLATFORM_PRIORITY_DRAFTS = new Map();
let PLATFORM_EDIT_UID = null;
let PLATFORM_MODEL_PAGE = 1;
const PLATFORM_LABELS = {workbuddy:'WorkBuddy',cline:'Cline',opencode_zen:'OpenCode Zen'};

async function loadPlatforms(){
  if(PLATFORM_LOADING) return PLATFORM_LOADING;
  PLATFORM_LOADING=renderPlatforms();
  try { return await PLATFORM_LOADING; } finally { PLATFORM_LOADING=null; }
}

async function renderPlatforms(){
  try {
    const data = await getJSON('/platforms?models=0');
    if(PLATFORM_DATA && PLATFORM_DATA.models_revision===data.models_revision){data.models=PLATFORM_DATA.models;}
    else {data.models=(await getJSON('/platforms/models')).models;}
    PLATFORM_DATA = data;
    const selected = document.getElementById('platformFilter').value;
    const accounts = data.accounts.filter(a => !selected || a.upstream === selected);
    const proxySelect=document.getElementById('platformProxySlot');
    const proxyValue=proxySelect.value;
    proxySelect.innerHTML='<option value="">直接连接</option>'+(data.proxy_slots || []).map(s=>'<option value="'+esc(s.id)+'">'+esc(s.label || s.id)+'</option>').join('');
    proxySelect.value=proxyValue;
    document.getElementById('platformStatus').innerHTML = Object.entries(data.catalogues).map(([name,c]) =>
      '<div class="infrastructure-item"><div class="k">'+esc(PLATFORM_LABELS[name])+'</div><div class="v">'+fmt(c.count)+' 个模型</div><div class="s">'+esc(c.error || (c.updated_at ? (c.stale ? '目录已过期，保留缓存' : '目录已同步') : '等待同步'))+'</div></div>').join('');
    const accountBox=document.getElementById('platformAccounts');
    const editing=accountBox.contains(document.activeElement);
    if(!editing) accountBox.innerHTML = accounts.length ? '<table class="data-cards"><thead><tr><th>平台 / 账号</th><th>状态</th><th>优先级</th><th>余额</th><th>今日用量</th><th>操作</th></tr></thead><tbody>'+accounts.map(a =>
      '<tr><td data-label="账号">'+esc(PLATFORM_LABELS[a.upstream])+'<br><b>'+esc(a.nickname)+'</b><div class="hint">'+esc(a.uid)+'</div></td>'+
      '<td data-label="状态">'+(a.enabled?'启用':'停用')+' · 在途 '+fmt(a.in_flight)+'<div class="hint">'+(a.verified_at?'真实调用已验证':'真实调用未验证')+'</div><div class="hint">'+esc(a.last_error || '')+'</div></td>'+
      '<td data-label="优先级"><input aria-label="调度优先级" id="platformPriority_'+esc(a.uid)+'" data-action="editPlatformPriority" data-on="input" data-uid="'+esc(a.uid)+'" type="number" min="0" max="2147483647" value="'+esc(PLATFORM_PRIORITY_DRAFTS.has(a.uid)?PLATFORM_PRIORITY_DRAFTS.get(a.uid):a.priority)+'" style="width:95px"><button class="sec mini" data-action="savePlatformPriority" data-on="click" data-uid="'+esc(a.uid)+'">保存优先级</button></td>'+
      '<td data-label="余额">'+(a.balance && a.balance.remain != null ? fmt(a.balance.remain)+' '+esc(a.balance.unit) : '未知')+'</td>'+
      '<td data-label="今日用量">'+fmtTokens(a.today.tokens || 0)+' Token<div class="hint">免费 '+fmtTokens(a.today.free_tokens || 0)+' · 消费 '+fmt(a.today.paid_cost || 0)+' '+(a.upstream==='cline'?'积分':'USD')+'</div></td>'+
      '<td data-label="操作"><button class="sec mini" data-action="editPlatformAccount" data-on="click" data-uid="'+esc(a.uid)+'">编辑</button> <button class="sec mini" data-action="togglePlatformAccount" data-on="click" data-uid="'+esc(a.uid)+'">'+(a.enabled?'停用':'启用')+'</button> <button class="sec mini" data-action="deletePlatformAccount" data-on="click" data-uid="'+esc(a.uid)+'">删除</button></td></tr>').join('')+'</tbody></table>' : '<div class="hint">还没有配置此平台账号。Cline 可使用设备登录，Zen 填写官方 API Key。</div>';
    renderPlatformModels();
    const storage = data.responses || {};
    document.getElementById('responseStorageSummary').textContent = fmt(storage.count || 0)+' 条响应 · '+((storage.bytes || 0)/1048576).toFixed(2)+' / '+storage.max_mb+' MiB';
    // Preserve edits while SSE refreshes the tables.
    for(const name of ['enabled','retention_days','max_mb']){
      const el = document.getElementById('responseStorage_'+name);
      if(!el.dataset.initialized){ if(name==='enabled') el.checked=storage[name]; else el.value=storage[name]; el.dataset.initialized='1'; }
    }
    document.getElementById('responseConversations').innerHTML = (storage.conversations || []).map(c => '<div class="toolbar"><code>'+esc(c.id)+'</code><span>'+esc(c.model)+' · '+fmt(c.responses)+' 条</span><button class="sec mini" data-action="deleteResponseConversation" data-on="click" data-arg="'+esc(c.id)+'">删除整个会话</button></div>').join('') || '<div class="hint">暂无已保存会话</div>';
    const usage = await getJSON('/platforms/usage'+(selected?'?upstream='+encodeURIComponent(selected):''));
    document.getElementById('platformUsage').innerHTML = '<table class="data-cards"><thead><tr><th>平台 / 模型</th><th>成功 / 错误</th><th>今日 Token</th></tr></thead><tbody>'+usage.totals.map(row => '<tr><td data-label="模型">'+esc(PLATFORM_LABELS[row.upstream])+' · '+esc(row.model)+'</td><td data-label="请求">'+fmt(row.requests)+' / '+fmt(row.errors)+'</td><td data-label="Token">'+fmtTokens(row.total_tokens)+'</td></tr>').join('')+'</tbody></table>';
    document.getElementById('platformRecent').innerHTML = '<table class="data-cards"><thead><tr><th>时间 / 平台</th><th>模型 / 账号</th><th>结果</th><th>Token</th></tr></thead><tbody>'+usage.recent.map(row => '<tr><td data-label="时间">'+esc(row.iso)+'<br>'+esc(PLATFORM_LABELS[row.upstream || 'workbuddy'])+'</td><td data-label="模型">'+esc(row.model)+'<div class="hint">'+esc(row.account || '—')+'</div></td><td data-label="结果">'+esc(row.outcome || '')+'<div class="hint">'+esc(row.message || '')+'</div></td><td data-label="Token">'+fmtTokens(row.total_tokens || 0)+'</td></tr>').join('')+'</tbody></table>';
  } catch(e){ toast('平台加载失败：'+e.message, 'bad'); }
}

function renderPlatformModels(){
  if(!PLATFORM_DATA) return;
  const selected=document.getElementById('platformFilter').value;
  const query=document.getElementById('platformModelFilter').value.toLowerCase();
  const models=PLATFORM_DATA.models.filter(m=>(!selected || m.upstream===selected) && (m.id+' '+(m.name || '')).toLowerCase().includes(query));
  const pages=Math.max(1,Math.ceil(models.length/50));PLATFORM_MODEL_PAGE=Math.min(PLATFORM_MODEL_PAGE,pages);
  const visible=models.slice((PLATFORM_MODEL_PAGE-1)*50,PLATFORM_MODEL_PAGE*50);
  document.getElementById('platformModels').innerHTML='<table class="data-cards"><thead><tr><th>模型 ID</th><th>协议</th><th>计费 / 权益</th><th>上下文</th></tr></thead><tbody>'+visible.map(m=>'<tr><td data-label="模型 ID"><code>'+esc(m.id)+'</code></td><td data-label="协议">'+esc(m.native_protocol)+'</td><td data-label="计费">'+esc(m.entitlement || m.billing_mode || '未知')+'</td><td data-label="上下文">'+(m.context_length ? fmtTokens(m.context_length) : '上游未提供')+'</td></tr>').join('')+'</tbody></table>';
  document.getElementById('platformModelsPager').textContent=PLATFORM_MODEL_PAGE+' / '+pages+' 页 · '+models.length+' 个模型';
}
function filterPlatformModels(){PLATFORM_MODEL_PAGE=1;renderPlatformModels();}
function changePlatformModelsPage(step){PLATFORM_MODEL_PAGE=Math.max(1,PLATFORM_MODEL_PAGE+Number(step));renderPlatformModels();}

async function importPlatformAccount(){
  const kind = document.getElementById('platformKind').value;
  const body = {upstream:kind, name:document.getElementById('platformName').value, priority:Number(document.getElementById('platformPriority').value),
    models:document.getElementById('platformAllowModels').value.split(/[,\n]/).map(s=>s.trim()).filter(Boolean),
    proxy_slot:document.getElementById('platformProxySlot').value,
    access_token:document.getElementById('platformToken').value, refresh_token:document.getElementById('platformRefreshToken').value};
  if(!document.getElementById('platformPriority').value.trim() || !Number.isInteger(body.priority)){toast('请填写整数优先级','bad');return;}
  try {
    if(PLATFORM_EDIT_UID){body.uid=PLATFORM_EDIT_UID; if(!body.access_token) delete body.access_token; if(!body.refresh_token) delete body.refresh_token;}
    await postJSON(PLATFORM_EDIT_UID?'/platforms/accounts/update':'/platforms/accounts/import', body);
    resetPlatformForm(); toast('账号已保存','ok'); await loadPlatforms();
  }
  catch(e){ toast(e.message,'bad'); }
}
function editPlatformAccount(uid){
  const account=PLATFORM_DATA.accounts.find(a=>a.uid===uid);
  if(!account) return;
  PLATFORM_EDIT_UID=uid;
  const kind=document.getElementById('platformKind');kind.value=account.upstream;kind.disabled=true;
  document.getElementById('platformName').value=account.nickname;
  document.getElementById('platformPriority').value=account.priority;
  document.getElementById('platformAllowModels').value=account.models.join(', ');
  document.getElementById('platformProxySlot').value=account.proxy_slot;
  document.getElementById('platformToken').value='';document.getElementById('platformRefreshToken').value='';
  document.getElementById('platformFormTitle').textContent='编辑账号：'+account.nickname;
  document.getElementById('platformToken').placeholder='留空保留原凭据';
  document.getElementById('platformFormTitle').scrollIntoView({block:'start',behavior:'smooth'});
}
function resetPlatformForm(){
  PLATFORM_EDIT_UID=null;document.getElementById('platformKind').disabled=false;
  for(const id of ['platformToken','platformRefreshToken','platformName','platformAllowModels'])document.getElementById(id).value='';
  document.getElementById('platformPriority').value='100';document.getElementById('platformProxySlot').value='';
  document.getElementById('platformFormTitle').textContent='添加账号';
  document.getElementById('platformToken').placeholder='凭据仅保存到本机私有目录';
}
async function importPlatformFile(el){
  const file = el.files && el.files[0];
  if(!file) return;
  try { const body=JSON.parse(await file.text()); await postJSON('/platforms/accounts/import', body); toast('批量导入完成','ok'); await loadPlatforms(); }
  catch(e){ toast('导入失败：'+e.message,'bad'); }
  finally { el.value=''; }
}
async function startClineLogin(){
  try {
    const job=await postJSON('/platforms/login/start', {});
    const target=document.getElementById('platformLogin');
    target.innerHTML='<a target="_blank" rel="noopener noreferrer" href="'+esc(job.url)+'">打开 Cline 授权页面</a> · 设备码 <b>'+esc(job.code)+'</b>';
    if(PLATFORM_LOGIN_TIMER) clearInterval(PLATFORM_LOGIN_TIMER);
    PLATFORM_LOGIN_TIMER=setInterval(async()=>{
      try {
        const result=await getJSON('/platforms/login/poll?id='+encodeURIComponent(job.id));
        if(result.status!=='pending'){ clearInterval(PLATFORM_LOGIN_TIMER); PLATFORM_LOGIN_TIMER=null; target.textContent=result.status==='completed'?'授权完成，账号已保存':(result.error || '授权已过期'); await loadPlatforms(); }
      } catch(e){ clearInterval(PLATFORM_LOGIN_TIMER); PLATFORM_LOGIN_TIMER=null; target.textContent=e.message; }
    },5000);
  } catch(e){ toast(e.message,'bad'); }
}
async function savePlatformPriority(uid){
  const value=document.getElementById('platformPriority_'+uid).value;
  if(!value.trim() || !Number.isInteger(Number(value)) || Number(value)<0 || Number(value)>2147483647){ toast('优先级必须是 0–2147483647 的整数','bad'); return; }
  try { await postJSON('/platforms/accounts/update',{uid,priority:Number(value)}); PLATFORM_PRIORITY_DRAFTS.delete(uid); toast('优先级已持久化','ok'); await loadPlatforms(); }
  catch(e){ toast(e.message,'bad'); }
}
function editPlatformPriority(uid, el){
  if(el) PLATFORM_PRIORITY_DRAFTS.set(uid, el.value);
}
async function togglePlatformAccount(uid){
  const account=PLATFORM_DATA.accounts.find(a=>a.uid===uid);
  if(!account) return;
  try { await postJSON('/platforms/accounts/update',{uid,enabled:!account.enabled}); await loadPlatforms(); } catch(e){ toast(e.message,'bad'); }
}
async function deletePlatformAccount(uid){
  if(!confirm('删除这个平台账号？')) return;
  try { await postJSON('/platforms/accounts/update',{uid,delete:true}); await loadPlatforms(); } catch(e){ toast(e.message,'bad'); }
}
async function refreshPlatform(upstream){
  try { await postJSON('/platforms/refresh',{upstream}); toast('正在刷新目录和余额','ok'); } catch(e){ toast(e.message,'bad'); }
}
async function saveResponseStorage(){
  const body={enabled:document.getElementById('responseStorage_enabled').checked,retention_days:Number(document.getElementById('responseStorage_retention_days').value),max_mb:Number(document.getElementById('responseStorage_max_mb').value)};
  try { await postJSON('/platforms/responses/settings',body); toast('会话设置已保存','ok'); await loadPlatforms(); } catch(e){ toast(e.message,'bad'); }
}
async function deleteResponseConversation(conversation){
  if(!confirm('删除整个会话及所有分支？此操作无法撤销。')) return;
  try { await postJSON('/platforms/responses/delete',{conversation}); await loadPlatforms(); } catch(e){ toast(e.message,'bad'); }
}
