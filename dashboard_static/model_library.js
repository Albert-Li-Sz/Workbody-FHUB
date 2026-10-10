/* Extend the model library while keeping WorkBuddy's catalogue and renderer. */
const MODEL_LIBRARY_SOURCES = {cline:'Cline',opencode_zen:'OpenCode',commandcode:'Command Code'};
const MODEL_LIBRARY_STATES = new Map();
const MODEL_LIBRARY_PAGE_SIZE = 50;
const workbuddyModelLoad = loadModels;
const workbuddyModelRender = renderAvailableModels;
const workbuddyModelSelect = selectModelsChannel;
let modelLibraryLoading = false;
Object.assign(MODEL_CHANNEL_LABELS, MODEL_LIBRARY_SOURCES);
try {
  const saved = localStorage.getItem('wb_model_channel');
  if(Object.prototype.hasOwnProperty.call(MODEL_CHANNEL_LABELS, saved)) window.MODEL_CHANNEL = saved;
} catch(e){}

function modelLibraryState(channel=selectedModelsChannel()){
  if(!MODEL_LIBRARY_STATES.has(channel)) MODEL_LIBRARY_STATES.set(channel,{query:'',group:'all',page:1});
  return MODEL_LIBRARY_STATES.get(channel);
}

function syncModelLibrary(channel){
  const external = !!MODEL_LIBRARY_SOURCES[channel];
  const state = modelLibraryState(channel);
  const page = document.getElementById('pageModels');
  if(page) page.dataset.source = external ? channel : 'workbuddy';
  document.getElementById('modelBillingHeader').textContent = external ? '价格 / 权益' : '消费倍率';
  document.getElementById('modelLibrarySearch').value = state.query;
  document.getElementById('modelLibraryGroup').value = state.group;
  const subscription = document.getElementById('modelLibrarySubscription');
  subscription.hidden = !external;
  subscription.textContent = {cline:'ClinePass 订阅',opencode_zen:'OpenCode Go 订阅',commandcode:'Command Code 订阅'}[channel] || '订阅模型';
}

selectModelsChannel = async function(channel){
  if(!Object.prototype.hasOwnProperty.call(MODEL_CHANNEL_LABELS,channel)) return;
  return workbuddyModelSelect(channel);
};

loadModels = async function(){
  const channel = selectedModelsChannel();
  syncModelLibrary(channel);
  modelLibraryLoading = true;
  const status = document.getElementById('modelChannelStatus');
  status.dataset.tone = 'info';
  if(!MODEL_LIBRARY_SOURCES[channel]){
    const generation = MODEL_LOAD_GENERATION + 1;
    await workbuddyModelLoad();
    if(generation !== MODEL_LOAD_GENERATION) return;
    modelLibraryLoading = false;
    status.dataset.tone = status.textContent.startsWith('读取模型目录失败') ? 'bad' : 'info';
    renderAvailableModels();
    return;
  }
  const generation = ++MODEL_LOAD_GENERATION;
  document.getElementById('modelChannelSelect').value = channel;
  document.getElementById('modelChannelTitle').textContent = MODEL_LIBRARY_SOURCES[channel] + ' 模型';
  status.textContent = '正在加载模型目录…';
  MODELS_DATA = [];
  renderAvailableModels();
  try {
    const result = await getJSON(SOURCE_ROOT + '/models?upstream=' + encodeURIComponent(channel));
    if(generation !== MODEL_LOAD_GENERATION) return;
    MODELS_DATA = result.models || [];
    modelLibraryLoading = false;
    renderAvailableModels();
    const catalogue = (result.catalogues || {})[channel] || {};
    const notes = ['仅显示已启用账号允许调用的模型'];
    if(channel === 'opencode_zen') notes.push('opencode/go/ 使用 Go 订阅，其余使用 Zen');
    if(channel === 'cline') notes.push('ClinePass 价格为订阅配额参考价');
    if(channel === 'commandcode') notes.push('订阅价格为参考价，实际额度见账号池');
    if(catalogue.refreshing) notes.push('正在同步最新目录…');
    else if(!MODELS_DATA.length) notes.push('请在账号池添加并启用账号，确认模型权限后刷新');
    if(catalogue.error) notes.push('同步失败：' + catalogue.error);
    if(catalogue.stale && catalogue.updated_at) notes.push('当前为过期缓存');
    if(catalogue.metadata_stale) notes.push('价格与能力元数据暂未同步');
    status.textContent = notes.join(' · ') + '。';
    status.dataset.tone = catalogue.error ? 'bad' : catalogue.stale && catalogue.updated_at || catalogue.metadata_stale ? 'warn' : 'info';
  } catch(error){
    if(generation !== MODEL_LOAD_GENERATION) return;
    MODELS_DATA = [];
    modelLibraryLoading = false;
    renderAvailableModels();
    status.textContent = '读取模型目录失败：' + error.message;
    status.dataset.tone = 'bad';
  }
};

async function refreshModelLibrary(){
  const channel = selectedModelsChannel();
  if(!MODEL_LIBRARY_SOURCES[channel]) return loadModels();
  const button = document.getElementById('modelRefreshButton');
  button.disabled = true;
  try {
    await postJSON(SOURCE_ROOT + '/refresh',{upstream:channel});
    if(channel === selectedModelsChannel()) await loadModels();
  } catch(error){
    if(channel === selectedModelsChannel()){
      const status = document.getElementById('modelChannelStatus');
      status.textContent = '同步模型目录失败：' + error.message;
      status.dataset.tone = 'bad';
    }
  } finally { button.disabled = false; }
}

function filterModelLibrary(){
  const state = modelLibraryState();
  state.query = document.getElementById('modelLibrarySearch').value;
  state.group = document.getElementById('modelLibraryGroup').value;
  state.page = 1;
  renderAvailableModels();
}

function pageModelLibrary(step){
  const state = modelLibraryState();
  state.page = Math.max(1,state.page + Number(step));
  renderAvailableModels();
}

function modelLibraryBilling(model){
  if(model.entitlement === 'subscription') return 'subscription';
  if(model.upstream && model.upstream !== 'workbuddy') return model.billing_mode || 'unknown';
  const credits = model.credits == null ? '' : String(model.credits).trim().replace(/^x/i,'');
  return credits && Number.isFinite(Number(credits)) ? Number(credits) === 0 ? 'free' : 'paid' : 'unknown';
}

function modelLibraryEfforts(model){
  const options = model.reasoning_options || {};
  const candidates = [model.reasoning_efforts,options.efforts,options.reasoning_effort,options.effort,options.values,
    Array.isArray(options) ? options : null,
    ...modelLibraryOptions(model).filter(option => option.type === 'effort').map(option => option.values)];
  return [...new Set(candidates.flatMap(modelLibraryStrings).filter(value => value.trim()))];
}

function modelLibraryStrings(value){ return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []; }
function modelLibraryOptions(model){
  const options = model.reasoning_options;
  return (Array.isArray(options) ? options : [options]).filter(option => option && typeof option === 'object' && !Array.isArray(option));
}

function modelLibraryReasoning(model){
  return model.reasoning === true || model.supports_reasoning === true || model.supportsReasoning === true
    || !!model.reasoning_fixed_effort || modelLibraryEfforts(model).length > 0
    || modelLibraryStrings(model.supported_parameters).includes('reasoning')
    || modelLibraryOptions(model).some(option => option.type === 'toggle');
}

function modelLibraryCapabilityHtml(model){
  const inputs = modelLibraryStrings((model.modalities || {}).input || model.input_modalities || (model.architecture || {}).input_modalities);
  const vision = model.supports_vision || model.vision || model.multimodal || model.supportsImages || inputs.includes('image');
  const tools = model.supports_tool_calls || model.tool_call || (model.capabilities || {}).tool_calls
    || modelLibraryStrings(model.supported_parameters).includes('tools');
  return '<span class="badge '+(vision?'ok':'s')+'">'+(vision?'视觉':'文本')+'</span>'
    + (tools ? ' <span class="badge ok">工具</span>' : '')
    + (modelLibraryReasoning(model) ? ' <span class="badge-effort">推理</span>' : '');
}

function modelLibraryEffortHtml(model){
  const badge = effort => '<span class="badge-effort">'+esc(effort)+'</span>';
  if(model.reasoning_fixed_effort) return badge(model.reasoning_fixed_effort)+'<div class="hint">固定档位</div>';
  const efforts = modelLibraryEfforts(model);
  const toggle = modelLibraryOptions(model).some(option => option.type === 'toggle');
  if(efforts.length) return efforts.map(badge).join(' ')+(toggle ? '<div class="hint">支持开启／关闭推理</div>' : '');
  if(toggle) return badge('开启 / 关闭')+'<div class="hint">推理开关</div>';
  if(modelLibraryReasoning(model)) return badge('原生推理')+'<div class="hint">上游未公布档位</div>';
  return '<span class="hint">'+(model.reasoning === false || model.supports_reasoning === false ? '不支持推理' : '上游未提供')+'</span>';
}

function modelLibraryLimit(value){
  return typeof value !== 'boolean' && Number.isFinite(Number(value)) && Number(value) > 0
    ? '<b>'+fmtTokens(Number(value))+'</b>' : '<span class="hint">上游未提供</span>';
}

function modelLibraryRow(model){
  const billing = modelLibraryBilling(model);
  const entitlement = billing === 'unknown' ? '计费信息未提供' : sourceModelEntitlement(model);
  const protocol = {chat:'Chat',responses:'Responses',messages:'Messages'}[model.native_protocol];
  return '<tr><td class="mono" data-label="模型 ID"><b>'+esc(model.id)+'</b>'
    +(model.name ? '<div class="hint">'+esc(model.name)+'</div>' : '')
    +(protocol ? '<span class="badge s">'+protocol+'</span>' : '')
    +(model.stale || model.metadata_stale ? '<span class="badge warn">缓存元数据</span>' : '')+'</td>'
    +'<td data-label="价格 / 权益"><span class="badge '+(billing === 'subscription' ? 'subscription' : billing === 'free' ? 'ok' : 'paid')+'">'+esc(entitlement)+'</span><div class="model-library-price">'+sourceModelPrice(model)+'</div></td>'
    +'<td data-label="能力">'+modelLibraryCapabilityHtml(model)+'</td>'
    +'<td data-label="上下文">'+modelLibraryLimit(model.context_length || (model.limit || {}).context || model.contextWindow)+'</td>'
    +'<td data-label="最大输出">'+modelLibraryLimit(model.max_output_tokens || (model.limit || {}).output || model.maxTokens)+'</td>'
    +'<td data-label="思考档位">'+modelLibraryEffortHtml(model)+'</td></tr>';
}

renderAvailableModels = function(){
  const tbody = document.querySelector('#modelsTable tbody');
  if(!tbody) return;
  const channel = selectedModelsChannel();
  const state = modelLibraryState(channel);
  const external = !!MODEL_LIBRARY_SOURCES[channel];
  const all = MODELS_DATA;
  const query = state.query.trim().toLowerCase();
  const list = all.filter(model => (model.id+' '+(model.name || '')).toLowerCase().includes(query)
    && (state.group === 'all' || modelLibraryBilling(model) === state.group));
  if(external) list.sort((a,b) => {
    const order = model => ({subscription:0,free:1,paid:2}[modelLibraryBilling(model)] ?? 3);
    return order(a)-order(b) || a.id.localeCompare(b.id);
  });
  const pages = Math.max(1,Math.ceil(list.length / MODEL_LIBRARY_PAGE_SIZE));
  if(!modelLibraryLoading) state.page = Math.min(state.page,pages);
  const visible = list.slice((state.page-1)*MODEL_LIBRARY_PAGE_SIZE,state.page*MODEL_LIBRARY_PAGE_SIZE);
  if(modelLibraryLoading) tbody.innerHTML = '<tr><td colspan="6" class="empty">正在加载…</td></tr>';
  else if(!list.length) tbody.innerHTML = '<tr><td colspan="6" class="empty">'+(all.length ? '没有匹配的模型，请调整搜索或筛选。' : external ? '暂无可用模型，请先在账号池添加并启用此平台的账号。' : '暂无可用模型')+'</td></tr>';
  else if(external) tbody.innerHTML = visible.map(modelLibraryRow).join('');
  else {
    // The original renderer still owns WorkBuddy multipliers and output probes.
    MODELS_DATA = visible;
    try { workbuddyModelRender(); } finally { MODELS_DATA = all; }
  }
  document.getElementById('availModelCount').textContent = '(共 '+all.length+' 个)';
  document.getElementById('modelLibraryPager').textContent = modelLibraryLoading ? '正在加载目录…' : state.page+' / '+pages+' 页 · '+list.length+' 个模型';
  document.getElementById('modelLibraryPrevious').disabled = modelLibraryLoading || state.page <= 1;
  document.getElementById('modelLibraryNext').disabled = modelLibraryLoading || state.page >= pages;
};
