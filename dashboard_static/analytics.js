async function loadAnalyticsMatrix(){
  try{
      const q = analyticsQuery();
    const [usage, perf, models] = await Promise.all([
      getJSON('/usage' + q),
      getJSON('/usage/perf' + q),
      // The catalog is only a display filter, so a failure here must not
      // blank the table; null keeps the previous allowlist.
      getJSON('/v1/models?realm=all').catch(() => null),
    ]);
    if(models && models.data) MATRIX_MODELS = new Set(models.data.map(m => m.id));
    cachedMatrixData = { usage: usage, perf: perf };
    fillMatrixFilters(usage);
    renderPerfMatrix(usage, perf);
  }catch(err){
    if(!isAuthError(err)) console.error('loadAnalyticsMatrix failed:', err);
  }
}

/* Rebuild the two matrix filter dropdowns from the payload just fetched.
 *
 * Options are derived from the data rather than from the account pool, so the
 * list only offers accounts and models that actually have rows - a filter that
 * can only ever yield an empty table is worse than no filter. A previously
 * chosen value is kept when it is still present, and cleared when it is not,
 * which is what happens when the range flips and an account drops out.
 */
function fillMatrixFilters(usage){
  const acctSel = document.getElementById('matrixAcctFilter');
  const modelSel = document.getElementById('matrixModelFilter');
  const names = (usage && usage.accounts_map) || {};
  const modelCount = {};
  Object.keys((usage && usage.by_model) || {}).forEach(id => {
    if(!id.endsWith('-model')) modelCount[id] = (usage.by_model[id] || {}).requests || 0;
  });
  if(acctSel){
    const seen = new Set();
    Object.values((usage && usage.by_model_acct) || {}).forEach(byRealm => {
      Object.values(byRealm || {}).forEach(byAcct => {
        Object.keys(byAcct || {}).forEach(uid => {
          if(uid && uid !== '(unattributed)') seen.add(uid);
        });
      });
    });
    const opts = Array.from(seen).sort((a, b) => {
      const na = (names[a] || {}).nickname || a;
      const nb = (names[b] || {}).nickname || b;
      return na.localeCompare(nb);
    });
    if(matrixAcctFilter && !seen.has(matrixAcctFilter)) matrixAcctFilter = '';
    acctSel.innerHTML = '<option value="">全部账号</option>' + opts.map(uid => {
      const info = names[uid] || {};
      const label = (info.nickname || uid.slice(0, 8)) + ' (' + uid.slice(0, 6) + ')';
      return '<option value="' + esc(uid) + '"' + (uid === matrixAcctFilter ? ' selected' : '') + '>' + esc(label) + '</option>';
    }).join('');
  }
  if(modelSel){
    const ids = Object.keys(modelCount).filter(id => modelCount[id] > 0).sort();
    if(matrixModelFilter && ids.indexOf(matrixModelFilter) === -1) matrixModelFilter = '';
    modelSel.innerHTML = '<option value="">全部模型</option>' + ids.map(id =>
      '<option value="' + esc(id) + '"' + (id === matrixModelFilter ? ' selected' : '') + '>' + esc(id) + '</option>'
    ).join('');
  }
}

function renderPerfMatrix(usage, perf){
  const matrixEl = document.getElementById("perfMatrix");
  if(!matrixEl) return;
  const bmPerf = (perf && perf.by_model) || {};
  const validModels = MATRIX_MODELS;
  const modelMap = {};
  Object.entries(usage.by_model || {}).forEach(([id, m]) => {
    if((!validModels.size || validModels.has(id)) && m.requests > 0 && !id.endsWith('-model')){
      modelMap[id] = Object.assign({id: id}, m);
    }
  });
  Object.entries(bmPerf).forEach(([id, p]) => {
    if((!validModels.size || validModels.has(id)) && p.requests > 0 && !id.endsWith('-model') && !modelMap[id]){
      modelMap[id] = {
        id: id,
        requests: p.requests || 0,
        prompt_tokens: 0,
        completion_tokens: 0,
        reasoning_tokens: 0,
        cached_tokens: 0,
        total_tokens: 0
      };
    }
  });
  // One row per (model, exit). A model served by both exits gets two rows,
  // each carrying its own tokens, latency and speed; the region column then
  // describes exactly the numbers next to it instead of collapsing both.
  const realmMap = (usage && usage.by_model_realm) || {};
  const acctMap = (usage && usage.by_model_acct) || {};
  const perfAcctMap = (perf && perf.by_model_acct) || {};
  const rowsData = [];
  Object.values(modelMap)
    .sort((a,b) => (b.total_tokens || b.requests) - (a.total_tokens || a.requests))
    .forEach(m => {
      if(matrixModelFilter && m.id !== matrixModelFilter) return;
      const per = realmMap[m.id];
      const realms = per ? Object.keys(per).filter(r => (per[r].requests || 0) > 0) : [];
      if(realms.length > 1){
        // Most-used exit first, so the ordering stays meaningful.
        realms.sort((x, y) => (per[y].total_tokens || 0) - (per[x].total_tokens || 0));
      }
      // Within an exit, one row per account: two accounts sharing an exit are
      // two different consumers, and merging them hid which one spent what.
      const parts = [];
      (realms.length ? realms : ['']).forEach(r => {
        const accts = ((acctMap[m.id] || {})[r]) || {};
        const perfAccts = ((perfAcctMap[m.id] || {})[r]) || {};
        // Union of both maps: a bucket holding only failures exists in perf
        // alone, and dropping it would hide failures the total counts.
        const keys = Array.from(new Set(
          Object.keys(accts).concat(Object.keys(perfAccts))
        )).filter(a => {
          const u = accts[a] || {};
          const p = perfAccts[a] || {};
          return (u.requests || 0) > 0 || (u.errors || 0) > 0 ||
                 (p.requests || 0) > 0 || (p.errors || 0) > 0 ||
                 (p.client_aborted || 0) > 0;
        });
        // The account filter narrows the rows themselves, not just their
        // visibility, so the summary below always matches what is shown.
        const shown = matrixAcctFilter ? keys.filter(a => a === matrixAcctFilter) : keys;
        if(shown.length){
          shown.sort((x, y) =>
            ((accts[y] || {}).total_tokens || 0) - ((accts[x] || {}).total_tokens || 0));
          shown.forEach(a => {
            // Tokens come from usage; a failure-only bucket has none.
            const u = accts[a] || {requests: 0, prompt_tokens: 0, completion_tokens: 0,
                                   reasoning_tokens: 0, cached_tokens: 0, total_tokens: 0};
            parts.push({ stat: u, realm: r, acct: a,
                         accts: { [a]: u.requests || 0 } });
          });
        } else if(!matrixAcctFilter){
          // No per-account data for this exit (an older log, say): fall back
          // to the exit totals rather than dropping the row.
          const fallback = per ? per[r] : m;
          parts.push({ stat: fallback, realm: r, acct: '',
                       accts: fallback.accounts || {} });
        }
      });
      parts.forEach((p, i) => {
        rowsData.push(Object.assign({}, p.stat, {
          id: m.id, realm: p.realm, acct: p.acct, accts: p.accts,
          split: parts.length > 1, first: i === 0,
        }));
      });
    });

  const countEm = document.getElementById("matrixModelCount");
  if(countEm){
    const nModels = new Set(rowsData.map(r => r.id)).size;
    const anyFilter = !!(matrixAcctFilter || matrixModelFilter);
    countEm.textContent = nModels ? ("(有调用的模型: " + nModels +
      " 个·共 " + rowsData.length + " 行明细" + (anyFilter ? " · 已筛选" : "") + ")") : "";
  }

  if(!rowsData.length){
    matrixEl.innerHTML = '<div class="empty">当前版本暂无模型请求或性能数据</div>';
  } else {
    const maxTok = Math.max(1, ...rowsData.map(m => m.total_tokens));
    /* Summary row (Total / All Models).
     *
     * With no filter this is the endpoint-wide figure, as before. With a
     * filter active it is recomputed from the visible rows instead, because a
     * total that ignores the filter contradicts the rows directly beneath it -
     * the exact confusion the filter is meant to remove. Latency, speed and
     * wall time are averages over the filtered rows' own sample counts, so a
     * barely-used row cannot outvote a heavily-used one.
     */
    const filtering = !!(matrixAcctFilter || matrixModelFilter);
    let sumReq, sumErr, sumTok, sumP, sumC, sumR, totTtft, totTps, totWall, totCache, sumCost;
    if(!filtering){
      sumReq = usage.requests; sumErr = perf.errors; sumTok = usage.total_tokens;
      sumP = usage.prompt_tokens; sumC = usage.completion_tokens; sumR = usage.reasoning_tokens;
      // OpenRouter 价估算的合计：未筛选时取出口级汇总（与上面的数字同源）。
      sumCost = usage.cost_cny || 0;
      totTtft = perf.ttft_ms ? (ms(perf.ttft_ms.avg) + " (P50 " + ms(perf.ttft_ms.p50) + ")") : "-";
      totTps = perf.tokens_per_sec ? (fmtTokenRate(perf.tokens_per_sec.avg) + " tok/s") : "-";
      totWall = perf.wall_ms ? ms(perf.wall_ms.avg) : "-";
      totCache = perf.cache_hit_pct ? (perf.cache_hit_pct.avg.toFixed(1) + "%") : "-";
    } else {
      sumReq = 0; sumErr = 0; sumTok = 0; sumP = 0; sumC = 0; sumR = 0; sumCost = 0;
      let ttftW = 0, ttftN = 0, tpsW = 0, tpsN = 0, wallW = 0, wallN = 0, cacheW = 0, cacheN = 0;
      rowsData.forEach(m => {
        sumReq += m.requests || 0;
        sumTok += m.total_tokens || 0;
        sumP += m.prompt_tokens || 0;
        sumC += m.completion_tokens || 0;
        sumR += m.reasoning_tokens || 0;
        sumCost += m.cost_cny || 0;
        const mp = ((perf && perf.by_model_realm) || {})[m.id] || {};
        const mpAcctAll = ((perf && perf.by_model_acct) || {})[m.id] || {};
        const mpRealm = m.realm ? (mp[m.realm] || null) : null;
        const mpAcct = (m.realm && m.acct && mpAcctAll[m.realm])
          ? (mpAcctAll[m.realm][m.acct] || null) : null;
        const e = mpAcct || mpRealm || bmPerf[m.id] || {};
        sumErr += e.errors || 0;
        if(e.ttft_ms && e.ttft_ms.samples){ ttftW += e.ttft_ms.avg * e.ttft_ms.samples; ttftN += e.ttft_ms.samples; }
        if(e.tokens_per_sec && e.tokens_per_sec.generation_ms_total){ tpsW += e.tokens_per_sec.output_tokens * 1000; tpsN += e.tokens_per_sec.generation_ms_total; }
        if(e.wall_ms && e.wall_ms.samples){ wallW += e.wall_ms.avg * e.wall_ms.samples; wallN += e.wall_ms.samples; }
        if(e.cache_hit_pct && e.cache_hit_pct.samples){ cacheW += e.cache_hit_pct.avg * e.cache_hit_pct.samples; cacheN += e.cache_hit_pct.samples; }
      });
      totTtft = ttftN ? ms(ttftW / ttftN) : "-";
      totTps = tpsN ? (fmtTokenRate(tpsW / tpsN) + " tok/s") : "-";
      totWall = wallN ? ms(wallW / wallN) : "-";
      totCache = cacheN ? ((cacheW / cacheN).toFixed(1) + "%") : "-";
    }
    const summaryRow = '<tr style="background:rgba(37,99,235,.06);font-weight:600">'
      + '<td style="text-align:left" data-label="模型"><b>' + (filtering ? '筛选结果合计 (Filtered)' : '全部模型合计 (Total)') + '</b></td>'
      + '<td style="text-align:center" data-label="区域"><span style="color:var(--dim)">—</span></td>'
      + '<td style="text-align:left" data-label="账号"><span style="color:var(--dim)">' + (filtering ? '已筛选' : '全部账号') + '</span></td>'
      + '<td data-label="请求数">' + fmt(sumReq) + '</td>'
      + '<td data-label="失败">' + (sumErr
          ? ('<span style="color:var(--bad)">' + fmt(sumErr) + '</span>')
          : '<span style="color:var(--dim)">0</span>') + '</td>'
      + '<td data-label="总 Token"><b style="color:var(--accent)">' + fmtTokens(sumTok) + '</b></td>'
      + '<td class="triple" data-label="输入 / 输出 / 思考">' + tripleTokens(sumP, sumC, sumR) + '</td>'
      + '<td data-label="首字延迟">' + totTtft + '</td>'
      + '<td data-label="生成速度"><b style="color:var(--accent2)">' + totTps + '</b></td>'
      + '<td data-label="端到端耗时">' + totWall + '</td>'
      + '<td data-label="缓存命中">' + totCache + '</td>'
      + '<td data-label="用量占比">100%</td>'
      + '<td data-label="OpenRouter 价估算" style="color:var(--warn)">' + fmtCost(sumCost) + '</td>'
      + '</tr>';

    const rows = rowsData.map(m => {
      // Latency/speed come from the matching (model, exit) bucket when the
      // backend supplied one; otherwise fall back to the model-wide figure.
      const mp = ((perf && perf.by_model_realm) || {})[m.id] || {};
      const mpAcctAll = ((perf && perf.by_model_acct) || {})[m.id] || {};
      const mpRealm = m.realm ? (mp[m.realm] || null) : null;
      // Most specific first: this account on this exit, then the exit, then
      // the model. A split row must not borrow another account's latency.
      const mpAcct = (m.realm && m.acct && mpAcctAll[m.realm])
        ? (mpAcctAll[m.realm][m.acct] || null) : null;
      const mpEff = mpAcct || mpRealm || bmPerf[m.id] || {};
      const m_ttft = mpEff.ttft_ms ? (ms(mpEff.ttft_ms.avg) + " <span style='color:var(--dim);font-size:11px'>(P50 " + ms(mpEff.ttft_ms.p50) + ")</span>") : "-";
      const m_tps = mpEff.tokens_per_sec ? ('<b style="color:var(--accent2)">' + fmtTokenRate(mpEff.tokens_per_sec.avg) + '</b> <span style="font-size:11px;color:var(--dim)">tok/s</span>') : "-";
      const m_wall = mpEff.wall_ms ? ms(mpEff.wall_ms.avg) : "-";
      const m_cache = (m.prompt_tokens > 0) ? pct(m.cached_tokens / m.prompt_tokens * 100) : (mpEff.cache_hit_pct ? mpEff.cache_hit_pct.avg.toFixed(1) + "%" : "-");
      const pctTok = Math.round(m.total_tokens / maxTok * 100);
      // 0 is a real result (the model ran and never failed), so it stays
      // visible as a muted zero rather than the dash used for no data.
      const errCell = mpEff.errors
        ? ('<span style="color:var(--bad)">' + fmt(mpEff.errors) + '</span>')
        : '<span style="color:var(--dim)">0</span>';
      const acctsMap = usage.accounts_map || {};
      // This row's own accounts, not every account that touched the model.
      const mAccts = m.accts || m.accounts || {};
      const acctEntries = Object.entries(mAccts);
      let realmCell = '<span style="color:var(--dim)">—</span>';
      let acctCell = '<span style="color:var(--dim)">—</span>';
      const realms = new Set();
      if(m.realm){
        realms.add(m.realm);
      } else {
        acctEntries.forEach(([uid]) => {
          const info = acctsMap[uid] || {};
          if(info.realm) realms.add(info.realm);
        });
      }
      if(realms.size === 1){
        const r = Array.from(realms)[0];
        realmCell = r === 'cn' ? '<span class="realm-badge-cn">国内版</span>' : '<span class="realm-badge-intl">国际版</span>';
      } else if(realms.size > 1){
        realmCell = '<span class="realm-badge-intl">国际版</span> <span class="realm-badge-cn">国内版</span>';
      } else {
        // No account attribution on these rows (a test call,
        // say). Decide from the model id itself: this table
        // spans both realms, so the gateway's current exit
        // would mislabel domestic-only models.
        const isIntlOnly = ['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4', 'gpt-5.3-codex', 'gemini-3.5-flash', 'grok-4.7'].includes(m.id);
        const isCnOnly = ['deepseek-v4-pro', 'glm-5.1', 'glm-5v-turbo', 'kimi-k3-1', 'kimi-k2.7', 'minimax-m3'].includes(m.id);
        realmCell = isIntlOnly ? '<span class="realm-badge-intl">国际版</span>'
          : (isCnOnly ? '<span class="realm-badge-cn">国内版</span>'
            : '<span style="color:var(--dim)">—</span>');
      }
      if(acctEntries.length === 1 && acctEntries[0][0] === '(unattributed)'){
        acctCell = '<span style="color:var(--dim)">—</span>';
      } else if(acctEntries.length === 1){
        const [uid, count] = acctEntries[0];
        const info = acctsMap[uid] || {};
        const name = esc(info.nickname || uid.slice(0, 8));
        acctCell = '<b>' + name + '</b>';
      } else if(acctEntries.length > 1){
        acctCell = acctEntries.map(([uid, count]) => {
          const info = acctsMap[uid] || {};
          const name = esc(info.nickname || uid.slice(0, 6));
          return '<span class="badge mini" style="margin:1px 2px">' + name + ' <span style="color:var(--dim)">(' + count + ')</span></span>';
        }).join('');
      }
      return '<tr>'
        + '<td style="text-align:left" class="mono" data-label="模型"><b>' + esc(m.id) + '</b></td>'
        + '<td style="text-align:center;white-space:nowrap" data-label="区域">' + realmCell + '</td>'
        + '<td style="text-align:left" data-label="账号">' + acctCell + '</td>'
        + '<td data-label="请求数">' + fmt(m.requests) + '</td>'
        + '<td data-label="失败">' + errCell + '</td>'
        + '<td data-label="总 Token"><b>' + fmtTokens(m.total_tokens) + '</b></td>'
        + '<td class="triple" data-label="输入 / 输出 / 思考">' + tripleTokens(m.prompt_tokens, m.completion_tokens, m.reasoning_tokens) + '</td>'
        + '<td data-label="首字延迟">' + m_ttft + '</td>'
        + '<td data-label="生成速度">' + m_tps + '</td>'
        + '<td data-label="端到端耗时">' + m_wall + '</td>'
        + '<td data-label="缓存命中">' + m_cache + '</td>'
        + '<td style="min-width:90px" data-label="用量占比"><span class="bar-fill" style="width:' + Math.max(3, pctTok) + '%"></span> <span style="font-size:11px;color:var(--dim)">' + pctTok + '%</span></td>'
        + '<td data-label="OpenRouter 价估算" style="color:var(--warn)" title="OpenRouter 价估算：按该行（模型·区域·账号）的 token 消耗折算；按条件定价的模型（输入长度阈值或时段）按每条请求取档；单条请求实际用的策略、三档单价与匹配来源见「最近请求」里那条的悬停提示">'
        +   ((m.cost_cny || 0) > 0 ? fmtCost(m.cost_cny) : '<span style="color:var(--dim)">—</span>')
        + '</td>'
        + '</tr>';
    }).join('');

    // 延迟 / 速度列取自日志末尾的采样，窗口比采样更宽时它们只覆盖最新的那一段。
    // 明说覆盖范围，比让局部数字冒充整个窗口要好。
    let coverageNote = '';
    if(perf && perf.sample_capped && perf.sample_from){
      coverageNote = '<div style="font-size:12px;color:var(--dim);margin-bottom:8px">'
        + '延迟 / 速度列只覆盖日志末尾的部分请求（自 '
        + esc(new Date(perf.sample_from * 1000).toLocaleString())
        + ' 起），更早的请求未纳入这三列。</div>';
    }
    matrixEl.innerHTML = coverageNote + '<table class="data-cards"><thead><tr>'
      + '<th style="text-align:left">模型名称</th>'
      + '<th style="text-align:center;width:76px">区域</th>'
      + '<th style="text-align:left">账号</th>'
      + '<th>请求数</th><th>失败</th><th>总 Token</th><th style="min-width:190px">输入 / 输出 / 思考</th>'
      + '<th>首字延迟 (TTFT)</th><th>生成速度</th><th>端到端耗时</th><th>缓存命中率</th><th>用量占比</th>'
      + '<th style="color:var(--warn)">OpenRouter 价估算</th>'
      + '</tr></thead><tbody>' + summaryRow + rows + '</tbody></table>';
  }

}

async function loadAnalytics(){
  try {
    // 载荷永远按当前选中的窗口取，它的 window 桶就是第一列要展示的数字。
    const data = await getJSON('/usage/analytics' + analyticsQuery());
    renderAnalytics(data);
    loadUsageSeries();
    loadCreditHistory();
  } catch(err) {
    console.error('loadAnalytics failed:', err);
  }
}

function loadUsageSeries(){
  getJSON('/usage/timeseries' + analyticsQuery()).then(renderUsageSeries).catch(() => {});
}

function renderUsageSeries(data){
  const canvas = document.getElementById('usageSeriesChart');
  if(!canvas) return;
  const series = (data && data.series) || [];
  const summary = document.getElementById('usageSeriesSummary');
  const totalTokens = series.reduce((sum, b) => sum + (b.total_tokens || 0), 0);
  const totalCredit = series.reduce((sum, b) => sum + (b.credit || 0), 0);
  if(summary) summary.textContent = '总 Token ' + fmtTokens(totalTokens) + ' · 扣减积分 ' + fmt(totalCredit)
    + ' · 桶 ' + (data ? data.bucket_seconds : '-') + 's';
  const ctx = canvas.getContext('2d');
  const ratio = window.devicePixelRatio || 1;
  const cssW = canvas.clientWidth || 800;
  const cssH = 220;
  canvas.width = cssW * ratio;
  canvas.height = cssH * ratio;
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  if(!series.length){
    ctx.fillStyle = '#64748b';
    ctx.font = '12px sans-serif';
    ctx.fillText('当前范围没有请求数据', 12, 24);
    return;
  }
  const pad = {l: 52, r: 16, t: 12, b: 26};
  const plotW = Math.max(10, cssW - pad.l - pad.r);
  const plotH = Math.max(10, cssH - pad.t - pad.b);
  const maxTokens = Math.max(1, ...series.map(b => b.total_tokens || 0));
  const maxReq = Math.max(1, ...series.map(b => b.requests || 0));
  const slot = plotW / series.length;
  const barW = Math.max(1, slot - 2);
  ctx.strokeStyle = '#1e293b';
  ctx.beginPath();
  ctx.moveTo(pad.l, pad.t);
  ctx.lineTo(pad.l, pad.t + plotH);
  ctx.lineTo(pad.l + plotW, pad.t + plotH);
  ctx.stroke();
  series.forEach((b, i) => {
    const h = plotH * (b.total_tokens || 0) / maxTokens;
    const x = pad.l + slot * i + 1;
    ctx.fillStyle = 'rgba(56,189,248,.55)';
    ctx.fillRect(x, pad.t + plotH - h, barW, h);
  });
  ctx.strokeStyle = '#a78bfa';
  ctx.beginPath();
  series.forEach((b, i) => {
    const x = pad.l + slot * (i + 0.5);
    const y = pad.t + plotH - plotH * (b.requests || 0) / maxReq;
    if(i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = '#64748b';
  ctx.font = '10px monospace';
  ctx.fillText(fmtTokens(maxTokens), 4, pad.t + 8);
  ctx.fillText('0', 4, pad.t + plotH);
  const tsLabel = t => new Date(t * 1000).toLocaleString();
  const firstLabel = tsLabel(series[0].at);
  const lastLabel = tsLabel(series[series.length - 1].at);
  ctx.fillText(firstLabel, pad.l, cssH - 6);
  ctx.fillText(lastLabel, Math.max(pad.l, cssW - pad.r - ctx.measureText(lastLabel).width), cssH - 6);
}

let CREDIT_HISTORY_ROWS = [];
function creditAccountLabel(uid){
  const account = (window.ACCOUNTS || []).find(a => String(a.uid) === String(uid));
  return account && account.nickname ? account.nickname : String(uid || '').slice(0, 8);
}
function renderCreditHistory(){
  const tbody = document.querySelector('#creditHistoryTable tbody');
  if(!tbody) return;
  tbody.innerHTML = CREDIT_HISTORY_ROWS.map(x => '<tr>'
    + '<td>' + esc(x.iso || '') + '</td>'
    + '<td>' + esc(x.model || '') + '</td>'
    + '<td title="' + esc(x.account || '') + '">' + esc(creditAccountLabel(x.account)) + '</td>'
    + '<td>' + fmt(x.credit) + '</td>'
    + '<td>' + fmtTokens(x.total_tokens || 0) + '</td>'
    + '</tr>').join('') || '<tr><td colspan="5" style="color:var(--dim)">没有积分扣减记录</td></tr>';
}
async function loadCreditHistory(btn){
  if(btn) btn.disabled = true;
  try{
    const r = await postJSON('/requests', {limit: 500});
    CREDIT_HISTORY_ROWS = (r.rows || []).filter(x => Number(x.credit || 0) > 0).slice(0, 50);
    renderCreditHistory();
    if(btn) toast('积分扣减历史已刷新', 'ok');
  }catch(e){ toast('读取积分扣减历史失败: ' + e.message, 'bad'); }
  finally{ if(btn) btn.disabled = false; }
}

/* 第一列的口径随范围切换，标签必须跟着走，否则「本周」的数字会被当成「今日」读。 */
const RANGE_LABELS = {today:'今日', week:'本周', month:'本月', custom:'自定义区间', all:'全部历史'};
function rangeLabel(){ return RANGE_LABELS[analyticsRange] || RANGE_LABELS.today; }

function renderAnalytics(data){
  if(!data || !data.summary) return;
  const sumWindow = data.summary.window || {};
  const sumAll = data.summary.all_time || {};
  const currentSum = sumWindow;

  // KPI 1: follows the range selector. It used to be hard-wired to the Today
  // bucket while the card next to it was hard-wired to All Time, so the range
  // buttons appeared to do nothing to the headline number.
  const elTodayTok = document.getElementById('kpiTodayTokens');
  const elTodayDetail = document.getElementById('kpiTodayTokensDetail');
  const elTodayTitle = document.getElementById('kpiRangeTokenTitle');
  if(elTodayTitle) elTodayTitle.textContent = rangeLabel() + '消耗 Token';
  if(elTodayTok) elTodayTok.textContent = fmtTokens(currentSum.total_tokens || 0);
  if(elTodayDetail) elTodayDetail.innerHTML =
    '<span style="color:var(--accent)">输入 ' + fmtTokens(currentSum.prompt_tokens || 0) + '</span>' +
    ' <span style="color:var(--dim-light)">/</span> ' + '<span style="color:var(--accent2)">输出 ' + fmtTokens(currentSum.completion_tokens || 0) + '</span>' +
    ' <span style="color:var(--dim-light)">/</span> ' + '<span style="color:var(--think)">思考 ' + fmtTokens(currentSum.reasoning_tokens || 0) + '</span>';

  // KPI 2: always the all-time figure, as the stable reference next to KPI 1.
  const elTotalTok = document.getElementById('kpiTotalTokens');
  const elTotalDetail = document.getElementById('kpiTotalTokensDetail');
  if(elTotalTok) elTotalTok.textContent = fmtTokens(sumAll.total_tokens || 0);
  if(elTotalDetail) elTotalDetail.innerHTML =
    '<span style="color:var(--accent)">输入 ' + fmtTokens(sumAll.prompt_tokens || 0) + '</span>' +
    ' <span style="color:var(--dim-light)">/</span> ' + '<span style="color:var(--accent2)">输出 ' + fmtTokens(sumAll.completion_tokens || 0) + '</span>' +
    ' <span style="color:var(--dim-light)">/</span> ' + '<span style="color:var(--think)">思考 ' + fmtTokens(sumAll.reasoning_tokens || 0) + '</span>' +
    // Two cards showing the same number reads as a broken counter rather than
    // as "there is nothing older to show", so say which case it is.
    ((analyticsRange === 'all' && (sumAll.total_tokens || 0) > 0)
      ? '<br><span style="color:var(--dim);font-size:11px">当前为「全部历史」视图，两张卡片口径相同</span>'
      : ((analyticsRange !== 'all' && (sumAll.total_tokens || 0) === (sumWindow.total_tokens || 0) && (sumAll.total_tokens || 0) > 0)
        ? '<br><span style="color:var(--dim);font-size:11px">与' + rangeLabel() + '相同：所选范围已覆盖日志中的全部请求</span>'
        : ''));

  // KPI 3: 网关平均生成速度
  const elAvgSpeed = document.getElementById('kpiAvgSpeed');
  const elAvgLatency = document.getElementById('kpiAvgLatency');
  if(elAvgSpeed){
    elAvgSpeed.innerHTML = fmtTokenRate(currentSum.speed_avg) + ' <span style="font-size:12px;font-weight:400;color:var(--dim)">tok/s</span>';
    elAvgSpeed.title = '有效请求的总输出 Token ÷ 总生成时间；生成时间从首个内容帧到末个内容帧，含思考和工具参数，排除失败、取消与无法测速的请求。样本数：' + (currentSum.speed_n || 0);
  }
  if(elAvgLatency) elAvgLatency.textContent = '平均首字延迟 ' + (currentSum.ttft_ms_avg ? fmt(currentSum.ttft_ms_avg) + ' ms' : '—') + ' · 耗时 ' + (currentSum.elapsed_ms_avg ? (currentSum.elapsed_ms_avg / 1000).toFixed(2) + ' s' : '—');

  // KPI 4: 缓存命中率
  const elCacheRate = document.getElementById('kpiCacheRate');
  if(elCacheRate) elCacheRate.textContent = (currentSum.cache_hit_pct != null ? currentSum.cache_hit_pct.toFixed(1) : '0.0') + '%';

  // KPI 5: 请求数与成功率
  const elReqTitle = document.getElementById('kpiReqTitle');
  const elReqCount = document.getElementById('kpiReqCount');
  const elReqSuccess = document.getElementById('kpiReqSuccess');
  if(elReqTitle) elReqTitle.textContent = (analyticsRange === 'all' ? '累计' : rangeLabel()) + '请求数 & 成功率';
  const totalReq = (currentSum.requests || 0) + (currentSum.errors || 0);
  const successPct = totalReq > 0 ? ((currentSum.requests / totalReq) * 100).toFixed(1) : '100.0';
  if(elReqCount) elReqCount.textContent = fmt(currentSum.requests || 0) + ' 次';
  if(elReqSuccess) elReqSuccess.textContent = '成功率 ' + successPct + '% · 失败 ' + (currentSum.errors || 0) + ' · 取消 ' + (currentSum.client_aborted || 0);

  // KPI 6: API 等价花费（跟随范围切换；货币切换按钮挂在这里）
  if(data.usd_cny) costUsdRate = Number(data.usd_cny) || costUsdRate;
  const elCostRange = document.getElementById('kpiCostRange');
  const elCostValue = document.getElementById('kpiCostValue');
  const elCostDetail = document.getElementById('kpiCostDetail');
  if(elCostRange) elCostRange.textContent = '(' + rangeLabel() + ')';
  if(elCostValue) elCostValue.innerHTML = fmtCost(currentSum.cost_cny != null ? currentSum.cost_cny : 0);
  if(elCostDetail) elCostDetail.innerHTML = '按 OpenRouter 模型价折算的等价 token 花费 ' + costToggleHtml();

  // Table 1: 账号透视表
  const acctTbody = document.getElementById('analyticsAccountTbody');
  const acctCountEm = document.getElementById('analyticsAcctCount');
  let accts = (data.accounts || []).filter(a => {
    if(a.uid === '(unattributed)' && !((a.window || {}).requests || a.all_time.requests)) return false;
    return true;
  });
  if(acctCountEm) acctCountEm.textContent = accts.length ? '(' + accts.length + ' 个账号)' : '';

  if(acctTbody){
    if(!accts.length){
      acctTbody.innerHTML = '<tr><td colspan="8" class="empty">暂无账号用量数据</td></tr>';
    } else {
      acctTbody.innerHTML = accts.map(a => {
        // window 桶就是当前选中的范围，也就是这张表要展示的口径。
        const st = a.window || {};
        const modelsMap = a.window_models || {};
        const entries = Object.entries(modelsMap || {}).sort((x, y) => (y[1].tokens || 0) - (x[1].tokens || 0));

        let pills = '<span style="color:var(--dim)">无调用</span>';
        if(entries.length){
          pills = entries.map(([mid, ms]) => {
            return '<span class="model-pill">'
              + '<b style="color:var(--fg)">' + esc(mid) + '</b>: '
              + ms.requests + '次 · <b style="color:var(--accent)">' + fmtTokens(ms.tokens) + '</b> tok'
              + '</span>';
          }).join('');
        }

        const realmBadge = a.realm === 'cn'
          ? '<span class="badge warn" style="font-size:10px">国内版</span>'
          : '<span class="badge s" style="font-size:10px">国际版</span>';

        let creditStr = '<span style="color:var(--dim)">—</span>';
        if(a.credits && a.credits.remain != null){
          if(a.credits.size){
            creditStr = '<b style="color:var(--accent2)">' + fmt(a.credits.remain) + '</b> <span style="color:var(--dim);font-size:11px">/ ' + fmt(a.credits.size) + ' 积分</span>';
          } else {
            creditStr = '<b style="color:var(--accent2)">' + fmt(a.credits.remain) + '</b> <span style="color:var(--dim);font-size:11px">积分</span>';
          }
        }

        return '<tr>'
          + '<td style="text-align:left">'
          +   '<b>' + esc(a.nickname || a.uid) + '</b>'
          +   '<div style="color:var(--dim);font-size:11px;font-family:monospace">' + esc((a.uid || '').slice(0, 10)) + '...</div>'
          + '</td>'
          + '<td>' + realmBadge + '</td>'
          + '<td>' + creditStr + '</td>'
          + '<td>' + fmt(st.requests || 0) + '</td>'
          + '<td><b style="color:var(--accent)">' + fmtTokens(st.total_tokens || 0) + '</b></td>'
          + '<td><b style="color:var(--accent2)">' + (st.credit != null ? Number(st.credit).toFixed(2) : '0.00') + '</b></td>'
          + '<td style="text-align:left;max-width:440px">' + pills + '</td>'
          + '<td style="color:var(--warn)" title="OpenRouter 价估算：按 OpenRouter 公布的模型价折算，覆盖该账号在所选区间内的请求；按条件定价的模型（输入长度阈值或时段）按每条请求取档；单条请求实际用的策略、三档单价与匹配来源见「最近请求」里那条的悬停提示">'
          +   (st.cost_cny != null && st.cost_cny > 0 ? fmtCost(st.cost_cny) : '<span style="color:var(--dim)">—</span>')
          + '</td>'
          + '</tr>';
      }).join('');
    }
  }

  renderKeyTable(data);
}

/* 按 API Key 的归属表。口径与账号表完全一致（window 桶 = 当前选中范围），
   所以两张表的请求数应当相等；对不上是数据问题，不是渲染能修的，故这里
   不隐藏任何一行——(未知 key) 那行正是用来兜住差额的。 */
function keyRealmCell(k){
  if(k.source === 'bucket') return '<span style="color:var(--dim)">—</span>';
  if(k.realm === 'cn') return '<span class="badge warn" style="font-size:10px">国内版</span>';
  if(k.realm === 'intl') return '<span class="badge s" style="font-size:10px">国际版</span>';
  if(k.realm && !REALM_CHOICES.some(([value]) => value === k.realm)) return '<span class="badge off" style="font-size:10px">出口已移除</span>';
  // realm 为空的 Key 不绑出口，而是跟着模型走：它可能两个出口都用过，
  // 那时代理返回的积分是两个价格体系相加的结果，必须说出来。
  if(k.cross_realm) return '<span class="badge warn" style="font-size:10px">跟随 · 混合</span>';
  return '<span class="badge off" style="font-size:10px">跟随</span>';
}

function keyModelPills(k){
  const pills = (k.models || []).map(m =>
    '<span class="model-pill">'
    + '<b style="color:var(--fg)">' + esc(m.model) + '</b>: '
    + m.requests + '次 · <b style="color:var(--accent)">' + fmtTokens(m.tokens) + '</b> tok'
    + '</span>');
  const rest = k.models_other;
  if(rest){
    pills.push('<span class="model-pill">'
      + '<b style="color:var(--dim)">' + esc(rest.model || '(其他)') + '</b> '
      + '<span style="color:var(--dim)">' + (rest.models || 0) + ' 个模型 · </span>'
      + rest.requests + '次 · ' + fmtTokens(rest.tokens) + ' tok</span>');
  }
  return pills.length ? pills.join('') : '<span style="color:var(--dim)">无调用</span>';
}

function renderKeyTable(data){
  const tbody = document.getElementById('analyticsKeyTbody');
  if(!tbody) return;
  const countEm = document.getElementById('analyticsKeyCount');
  const note = document.getElementById('analyticsKeyNote');
  const keys = data.keys || [];
  if(countEm) countEm.textContent = keys.length ? '(' + keys.length + ' 把)' : '';

  if(note){
    const named = keys.filter(k => k.source !== 'bucket');
    const cross = named.filter(k => k.cross_realm).length;
    const parts = [];
    if(!named.length) parts.push('设置里还没有任何 API Key，全部流量都落在下面的未归属行里。');
    if(cross) parts.push('有 ' + cross + ' 把 Key 没有绑定出口，它的积分由国际版与国内版两套价格相加而来，只能当量级看。');
    parts.push('Key 维度只从本次升级之后开始记录：更早的请求没有这个字段，会一直留在「(切换前)」里且不会再增长。');
    note.innerHTML = parts.join(' ');
  }

  if(!keys.length){
    tbody.innerHTML = '<tr><td colspan="8" class="empty">暂无 API Key 用量数据</td></tr>';
    return;
  }

  tbody.innerHTML = keys.map(k => {
    const st = k.window || {};
    const sub = {panel:'面板 Key', launcher:'启动参数', bucket:'未归属', builtin:'内置'}[k.source] || '';
    let nameCell = '<td style="text-align:left" data-label="API Key">'
      + '<b>' + esc(k.name || k.key) + '</b>';
    if(sub || !k.enabled){
      nameCell += '<div style="font-size:11px">'
        + (sub ? '<span style="color:var(--dim)">' + esc(sub) + '</span>' : '')
        + (!k.enabled && k.source === 'panel' ? '<span class="badge off mini">已禁用</span>' : '')
        + '</div>';
    }
    nameCell += '</td>';

    const reqCell = '<td data-label="请求次数">' + fmt(st.requests || 0) + ' 次'
      + (st.errors ? '<span style="color:var(--bad);font-size:11px"> · 失败 ' + fmt(st.errors) + '</span>' : '')
      + '</td>';
    const tokCell = '<td data-label="消耗总 Token"><b style="color:var(--accent)">'
      + fmtTokens(st.total_tokens || 0) + '</b></td>';
    const splitCell = '<td data-label="输入 · 输出 · 思考" style="font-size:12px">'
      + '<span style="color:var(--accent)">' + fmtTokens(st.prompt_tokens || 0) + '</span>'
      + ' <span style="color:var(--dim-light)">/</span> '
      + '<span style="color:var(--accent2)">' + fmtTokens(st.completion_tokens || 0) + '</span>'
      + ' <span style="color:var(--dim-light)">/</span> '
      + '<span style="color:var(--think)">' + fmtTokens(st.reasoning_tokens || 0) + '</span>'
      + '</td>';
    const cacheCell = '<td data-label="缓存命中">'
      + fmtTokens(st.cached_tokens || 0) + ' <span style="color:var(--dim)">('
      + (st.cache_hit_pct != null ? st.cache_hit_pct.toFixed(1) : '0.0') + '%)</span></td>';
    const creditCell = '<td data-label="消耗积分"><b style="color:var(--accent2)">'
      + (st.credit != null ? Number(st.credit).toFixed(2) : '0.00') + '</b></td>';
    const modelCell = '<td style="text-align:left;max-width:440px" data-label="调用的模型分布">'
      + keyModelPills(k) + '</td>';

    return '<tr>'
      + nameCell
      + '<td data-label="出口">' + keyRealmCell(k) + '</td>'
      + reqCell + tokCell + splitCell + cacheCell + creditCell + modelCell
      + '</tr>';
  }).join('');
}
/* M4 D3 stage 2: every former inline handler goes through this delegated
 * dispatcher, so the page runs under a nonce-based CSP with no
 * 'unsafe-inline' script allowance. Elements carry
 *   data-action=<action> data-on=click|change|input|keydown|scroll
 * plus optional data-arg / data-uid / data-name payloads. */

function updateWorkspace(tab){
  const labels = {gateway:'总览',accounts:'账号池',tasks:'任务中心',analytics:'用量与成本',models:'模型库',logs:'请求与日志',settings:'设置',platforms:'平台与会话'};
  const title = document.getElementById('workspaceCurrentPage');
  if(title) title.textContent = labels[tab] || labels.gateway;
  document.title = (labels[tab] || labels.gateway) + ' · Workbody-FHUB';
}
function closeSidebar(){
  document.body.classList.remove('sidebar-open');
  const button = document.getElementById('mobileMenuButton');
  if(button) button.setAttribute('aria-expanded','false');
}
function toggleSidebar(){
  const opened = document.body.classList.toggle('sidebar-open');
  const button = document.getElementById('mobileMenuButton');
  if(button) button.setAttribute('aria-expanded', String(opened));
  if(opened){
    const first = document.querySelector('#workspaceMenu .main-nav-btn.active');
    if(first) first.focus();
  }
}
document.addEventListener('keydown', event => {
  if(!document.body.classList.contains('sidebar-open')) return;
  if(event.key === 'Escape'){
    closeSidebar();
    const button = document.getElementById('mobileMenuButton');
    if(button) button.focus();
  }
  if(event.key === 'Tab'){
    const focusable = Array.from(document.querySelectorAll('#workspaceMenu a, #workspaceMenu button')).filter(el => el.offsetParent !== null);
    const first = focusable[0], last = focusable[focusable.length-1];
    if(event.shiftKey && document.activeElement === first){ event.preventDefault(); last.focus(); }
    else if(!event.shiftKey && document.activeElement === last){ event.preventDefault(); first.focus(); }
  }
});
