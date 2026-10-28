(() => {
  "use strict";
  const listEl = document.getElementById("list");
  const qEl = document.getElementById("q");
  const ctitle = document.getElementById("ctitle");
  const idxbarEl = document.getElementById("idxbar");
  const chiprowEl = document.getElementById("chiprow");

  let indices = [];
  let curIndex = "top100";
  let stocks = [];
  let current = null;          // K线模式当前选中
  let compareSel = new Set();  // 对比模式选中的代码
  let fundamentalSel = new Set(); // 基本面对比选中的代码
  let selectionMode = false;
  let curRange = "1mo";
  let mode = "kline";
  let indicator = "ma"; // ma | macd | rsi | boll
  let overlayIdx = null; // 对比图叠加的指数
  let curPeriod = "1d";  // 1d | 1wk | 1mo
  let indexHistoryView = false;
  let chart = null;

  const LOGO = s => `/api/logo/${s}`;

  const mqMobile = window.matchMedia("(max-width:768px)");
  mqMobile.addEventListener?.("change", () => {
    if (document.body.classList.contains("chart-open")) setTimeout(() => chart && chart.resize(), 50);
  });

  // ---------- 指数 ----------
  async function loadIndices() {
    try {
      indices = await (await fetch("/api/indices")).json();
      idxbarEl.innerHTML = "";
      indices.forEach(ix => {
        const b = document.createElement("a");
        b.className = "idx" + (ix.id === curIndex ? " active" : "");
        b.textContent = ix.name;
        b.dataset.ix = ix.id;
        b.title = ix.desc;
        b.href = ix.id === "top100" ? "/" : `/report/${ix.id}?range=${curRange}&interval=${curPeriod}`;
        if (ix.id === "top100") b.addEventListener("click", e => { e.preventDefault(); switchIndex(ix.id); });
        idxbarEl.appendChild(b);
      });
    } catch (e) {
      idxbarEl.innerHTML = `<div class="hint">指数加载失败</div>`;
    }
  }

  function switchIndex(id) {
    if (id === curIndex) return;
    curIndex = id;
    document.querySelectorAll(".idx").forEach(x => x.classList.toggle("active", x.dataset.ix === id));
    qEl.value = "";
    current = null;
    compareSel = new Set();
    fundamentalSel = new Set();
    overlayIdx = null;
    indexHistoryView = id !== "top100";
    if (indexHistoryView) {
      document.body.classList.add("index-history-open");
      listEl.style.display = "none";
      document.getElementById("rankpanel").style.display = "none";
      document.getElementById("chartwrap").style.display = "flex";
      document.getElementById("indexReport").style.display = "none";
      document.getElementById("indexInline").style.display = "none";
      loadIndexHistory(id);
    } else {
      document.body.classList.remove("index-history-open");
      document.getElementById("indexReport").style.display = "none";
      document.getElementById("chartwrap").style.display = "";
      listEl.style.display = "";
      loadStocks(curIndex);
    }
  }

  async function loadIndexHistory(indexId) {
    mode = "kline";
    document.querySelectorAll(".mode-tab").forEach(x => x.classList.toggle("active", x.dataset.mode === "kline"));
    document.getElementById("ind-tabs").style.display = "flex";
    document.getElementById("per-tabs").style.display = "flex";
    document.getElementById("ranges").style.display = "flex";
    document.getElementById("idxoverlay").style.display = "none";
    document.getElementById("chartwrap").style.display = "flex";
    document.getElementById("fundamentals").style.display = "none";
    const report = document.getElementById("indexReport");
    report.style.display = "none";
    try {
      const r = await fetch(`/api/index-history/${indexId}?range=${curRange}&interval=${curPeriod}`);
      if (!r.ok) throw new Error((await r.json()).detail || "请求失败");
      const d = await r.json();
      current = null;
      ctitle.innerHTML = `${d.name}<small>${d.range} · ${d.start} 至 ${d.end}</small>`;
      if (typeof echarts === "undefined") {
        await new Promise((resolve, reject) => {
          const tag = document.createElement("script");
          tag.src = "https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js";
          tag.onload = resolve;
          tag.onerror = () => reject(new Error("图表库加载失败，请检查网络或 CDN"));
          document.head.appendChild(tag);
        });
      }
      if (!chart) {
        chart = echarts.init(document.getElementById("kline"));
        window.addEventListener("resize", () => chart.resize());
      }
      chart.showLoading({ text: "加载中…", color: "#d97757", textColor: "#9b9a93" });
      renderKline(d);
      requestAnimationFrame(() => chart.resize());
      setTimeout(() => chart.resize(), 80);
    } catch (e) {
      if (chart) chart.hideLoading();
      document.getElementById("chartwrap").innerHTML = `<div class="empty">指数图表加载失败：${e.message}</div>`;
      ctitle.innerHTML = `指数走势<small style="color:var(--up)">${e.message}</small>`;
    }
  }

  function renderIndexReport(d) {
    const report = document.getElementById("indexReport");
    const rows = d.bars.slice().reverse().map(b => {
      const change = Number(b[2]) - Number(b[1]);
      const pct = Number(b[1]) ? change / Number(b[1]) * 100 : 0;
      const color = change >= 0 ? "var(--up)" : "var(--down)";
      return `<tr><td>${b[0]}</td><td>${fmtPrice(b[1])}</td><td>${fmtPrice(b[4])}</td><td>${fmtPrice(b[3])}</td><td>${fmtPrice(b[2])}</td><td style="color:${color}">${change >= 0 ? "+" : ""}${change.toFixed(2)}</td><td style="color:${color}">${change >= 0 ? "+" : ""}${pct.toFixed(2)}%</td><td>${fmtVol(b[5])}</td></tr>`;
    }).join("");
    report.innerHTML = `<h2>${d.name} · ${d.start} 至 ${d.end} · 共 ${d.bars.length} 条</h2><table><thead><tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th><th>涨跌</th><th>涨跌幅</th><th>成交量</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---------- 股票列表 ----------
  async function loadStocks(index) {
    listEl.innerHTML = `<div class="empty">加载中…</div>`;
    try {
      const r = await fetch(`/api/stocks?index=${index}`);
      stocks = await r.json();
      renderList();
      if (stocks.length) select(stocks[0].symbol, false); // 初始加载不自动进移动端图表
      const ix = indices.find(i => i.id === index);
      const ixName = ix ? ix.desc : "";
      ctitle.parentElement.querySelector(".hint")?.remove();
      if (index === "top100") {
        // 先显示基准市值，实时市值在后台补齐，不阻塞首页首屏。
        enrichMarketCaps().then(() => renderList()).catch(() => {});
      }
    } catch (e) {
      listEl.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
    }
  }

  async function enrichMarketCaps() {
    const B = 12;
    const caps = new Map();
    for (let i = 0; i < stocks.length; i += B) {
      await Promise.all(stocks.slice(i, i + B).map(async s => {
        try {
          const t = await fetch(`/api/quote/${symOf(s)}`);
          if (t.ok) caps.set(symOf(s), (await t.json()).marketCap);
        } catch (e) {}
      }));
    }
    stocks.forEach(s => { if (caps.has(symOf(s))) s.market_cap_b = caps.get(symOf(s)); });
  }

  let sortMode = "rank";
  function filterStocks() {
    const kw = qEl.value.trim().toLowerCase();
    let arr = stocks.filter(s =>
      !kw || symOf(s).toLowerCase().includes(kw) || nameOf(s).toLowerCase().includes(kw));
    if (sortMode === "name") {
      arr = arr.slice().sort((a, b) => nameOf(a).localeCompare(nameOf(b)));
    } else {
      arr = arr.slice().sort((a, b) => sizeVal(b) - sizeVal(a));
    }
    return arr;
  }
  function sizeVal(s) {
    return s.weight_pct != null ? s.weight_pct : (s.market_cap_b || 0);
  }
  function fmtSize(s) {
    return s.weight_pct != null ? s.weight_pct.toFixed(2) + "%" : fmtCap(s.market_cap_b);
  }
  function fmtCap(b) {
    if (!b) return "—";
    if (b >= 1000) return (b / 1000).toFixed(2) + " 万亿$";
    return Math.round(b) + " 十亿$";
  }

  let rankChart = null;
  async function showRank() {
    const panel = document.getElementById("rankpanel");
    const rankchartEl = document.getElementById("rankchart");
    listEl.style.display = "none";
    panel.style.display = "flex";
    if (!rankChart) {
      rankChart = echarts.init(rankchartEl);
    }
    rankChart.showLoading({ text: "加载中…", color: "#d97757", textColor: "#9b9a93" });
    try {
      const r = await fetch(`/api/rank?index=${curIndex}`);
      const data = await r.json();
      const ok = data.filter(x => x.chg_pct != null).sort((a, b) => b.chg_pct - a.chg_pct);
      const gainers = ok.slice(0, 8);
      const losers = ok.slice(-8).reverse();
      const barData = (arr) => arr.map(x => ({
        value: x.chg_pct, symbol: x.symbol, price: x.price
      })).reverse(); // ECharts 横向条形从下往上,reverse让涨跌顺序直观
      const opt = {
        backgroundColor: "transparent",
        title: [{ text: "今日领涨", left: 10, top: 0, textStyle: { color: "#262624", fontSize: 12, fontWeight: 600 } },
                { text: "今日领跌", left: "52%", top: 0, textStyle: { color: "#262624", fontSize: 12, fontWeight: 600 } }],
        tooltip: { trigger: "item", formatter: p => `${p.name} ${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%` },
        grid: [
          { left: 8, right: "52%", top: 28, bottom: 10, containLabel: true },
          { left: "52%", right: 8, top: 28, bottom: 10, containLabel: true }
        ],
        xAxis: [
          { type: "value", axisLabel: { color: "#6f6e69", formatter: v => v + "%" }, splitLine: { lineStyle: { color: "#efece6" } } },
          { type: "value", gridIndex: 1, axisLabel: { color: "#6f6e69", formatter: v => v + "%" }, splitLine: { lineStyle: { color: "#efece6" } } }
        ],
        yAxis: [
          { type: "category", data: barData(gainers).map(x => x.symbol), axisLabel: { color: "#262624", fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } },
          { type: "category", gridIndex: 1, data: barData(losers).map(x => x.symbol), axisLabel: { color: "#262624", fontSize: 11 }, axisLine: { show: false }, axisTick: { show: false } }
        ],
        series: [
          { type: "bar", data: barData(gainers), barWidth: 12, itemStyle: { color: p => p.value >= 0 ? "#d97757" : "#2e7d32", borderRadius: 3 } },
          { type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: barData(losers), barWidth: 12, itemStyle: { color: p => p.value >= 0 ? "#d97757" : "#2e7d32", borderRadius: 3 } }
        ]
      };
      rankChart.setOption(opt, true);
      rankChart.hideLoading();
    } catch (e) {
      rankChart.hideLoading();
      panel.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
    }
  }

  function symOf(s) { return s.symbol || s.ticker || ""; }
  function nameOf(s) { return s.name || ""; }
  function isActive(s) {
    if (mode === "compare") return compareSel.has(symOf(s));
    if (mode === "fundamentals") return fundamentalSel.has(symOf(s));
    if (selectionMode) return fundamentalSel.has(symOf(s));
    return symOf(s) === current;
  }

  function renderList() {
    const arr = filterStocks();
    if (!arr.length) { listEl.innerHTML = `<div class="empty">无匹配结果</div>`; return; }
    listEl.innerHTML = "";
    const frag = document.createDocumentFragment();
    arr.forEach((s, index) => {
      const sym = symOf(s);
      const displayRank = sortMode === "rank" ? index + 1 : (s.rank ?? "");
      const r = document.createElement("div");
      r.className = "row" + (isActive(s) ? " active" : "");
      r.dataset.t = sym;
      r.innerHTML = `
        <div class="rank">${mode === "compare" && isActive(s) ? "✓" : displayRank}</div>
        <img class="logo" loading="lazy" alt=""
             src="${LOGO(sym)}"
             onerror="this.onerror=null;this.classList.add('fallback');this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2236%22 height=%2236%22><rect width=%2236%22 height=%2236%22 fill=%22%23f0ede6%22/><text x=%2218%22 y=%2223%22 font-size=%2214%22 text-anchor=%22middle%22 fill=%22%23d97757%22 font-family=%22sans-serif%22 font-weight=%22bold%22>${sym[0]}</text></svg>'">
        <div class="sym">${sym}<small>${nameOf(s)}</small></div>
        <div class="mcap"><b>${fmtSize(s)}</b>${s.sector || ""}</div>`;
      r.onclick = () => {
        if (mode === "compare") toggleCompare(sym);
        else if (mode === "fundamentals") toggleFundamental(sym);
        else if (selectionMode) toggleFundamental(sym);
        else select(sym);
      };
      frag.appendChild(r);
    });
    listEl.appendChild(frag);
  }

  // ---------- K线模式 ----------
  async function select(symbol, openMobile = true) {
    current = symbol;
    renderList();
    const s = stocks.find(x => symOf(x) === symbol);
    ctitle.innerHTML = `${symbol} — ${s ? nameOf(s) : ""}<small>${s ? fmtSize(s) : ""}${s && s.sector ? " · " + s.sector : ""}</small>`;
    hideChips();
    // 仅在用户主动点击时才进入移动端图表视图(初始加载停留在列表)
    if (mqMobile.matches && openMobile) {
      document.body.classList.add("chart-open");
      setTimeout(() => chart && chart.resize(), 50);
    }
    await renderChart();
  }

  // ---------- 对比模式 ----------
  function toggleCompare(symbol) {
    if (compareSel.has(symbol)) compareSel.delete(symbol); else compareSel.add(symbol);
    renderList();
    renderChips();
    if (compareSel.size >= 2) renderCompare();
    else if (compareSel.size === 1) renderCompare(); // 单家也显示一条线
  }

  function renderChips() {
    if (compareSel.size === 0) { chiprowEl.style.display = "none"; return; }
    chiprowEl.style.display = "flex";
    chiprowEl.innerHTML = "";
    const names = new Map(stocks.map(s => [symOf(s), nameOf(s)]));
    compareSel.forEach(sym => {
      const c = document.createElement("span");
      c.className = "chip";
      c.innerHTML = `<img src="${LOGO(sym)}" alt="" onerror="this.style.visibility='hidden'">${sym}<span class="x" data-s="${sym}">×</span>`;
      c.querySelector(".x").onclick = e => { e.stopPropagation(); toggleCompare(sym); };
      chiprowEl.appendChild(c);
    });
  }

  function hideChips() { compareSel.clear(); renderChips(); }

  function toggleFundamental(symbol) {
    selectionMode = true;
    if (fundamentalSel.has(symbol)) fundamentalSel.delete(symbol);
    else if (fundamentalSel.size < 8) fundamentalSel.add(symbol);
    renderList();
    updateSelectionBar();
    if (mode === "fundamentals") loadFundamentalsCompare();
  }

  function renderFundamentalChips() {
    if (mode !== "fundamentals" || fundamentalSel.size === 0) {
      chiprowEl.style.display = "none";
      return;
    }
    chiprowEl.style.display = "flex";
    chiprowEl.innerHTML = [...fundamentalSel].map(sym =>
      `<span class="chip"><img src="${LOGO(sym)}" alt="">${sym}<span class="x" data-f="${sym}">×</span></span>`
    ).join("");
    chiprowEl.querySelectorAll(".x").forEach(x => x.onclick = () => toggleFundamental(x.dataset.f));
  }

  function updateSelectionBar() {
    const hint = document.getElementById("selectionHint");
    const toggle = document.getElementById("selectMode");
    const confirm = document.getElementById("confirmSelection");
    if (!hint || !toggle || !confirm) return;
    hint.textContent = selectionMode ? `已选 ${fundamentalSel.size} 家` : "单击公司查看详情";
    toggle.textContent = selectionMode ? "取消多选" : "多选对比";
    confirm.style.display = "block";
    confirm.disabled = false;
    confirm.classList.toggle("ready", selectionMode && fundamentalSel.size > 0);
  }

  // ---------- 图表 ----------
  async function renderChart() {
    if (indexHistoryView) return loadIndexHistory(curIndex);
    if (!chart) {
      chart = echarts.init(document.getElementById("kline"));
      window.addEventListener("resize", () => chart.resize());
    }
    if (mode === "compare") return renderCompare();
    if (mode === "kline" && compareSel.size > 1) return renderCompare();
    if (mode === "fundamentals") return loadFundamentals(current);
    return loadKline(current, curRange);
  }

  async function loadKline(symbol, range) {
    chart.showLoading({ text: "加载中…", color: "#d97757", textColor: "#9b9a93" });
    try {
      const r = await fetch(`/api/stock/${symbol}?range=${range}&interval=${curPeriod}`);
      if (!r.ok) throw new Error((await r.json()).detail || "请求失败");
      const d = await r.json();
      updatePeriodReturn(d);
      renderKline(d);
    } catch (e) {
      chart.hideLoading();
      ctitle.innerHTML += `<small style="color:var(--up)"> ${e.message}</small>`;
    }
  }

  function updatePeriodReturn(d) {
    if (!d.bars || d.bars.length < 2) return;
    const firstClose = Number(d.bars[0][2]);
    const lastClose = Number(d.bars[d.bars.length - 1][2]);
    const periodReturn = firstClose ? (lastClose - firstClose) / firstClose * 100 : 0;
    const change = lastClose - firstClose;
    const sign = periodReturn >= 0 ? "+" : "";
    const color = periodReturn >= 0 ? "var(--up)" : "var(--down)";
    const rangeText = document.querySelector(`#ranges .range[data-r="${d.range}"]`)?.textContent || d.range;
    ctitle.innerHTML = `${d.ticker} — ${d.name}<small>${rangeText} · ${d.start} 至 ${d.end} · 区间涨幅 <b style="color:${color}">${sign}${periodReturn.toFixed(2)}%</b> (${sign}${change.toFixed(2)}) · ${firstClose.toFixed(2)} → ${lastClose.toFixed(2)}</small>`;
  }

  async function renderCompare() {
    const syms = [...compareSel];
    chart.showLoading({ text: "加载中…", color: "#d97757", textColor: "#9b9a93" });
    try {
      const req = [fetch(`/api/compare?symbols=${syms.join(",")}&range=${curRange}`)];
      if (overlayIdx) req.push(fetch(`/api/compare?symbols=${overlayIdx}&range=${curRange}`));
      const [res, resOv] = await Promise.all(req);
      if (!res.ok) throw new Error((await res.json()).detail || "请求失败");
      const d = await res.json();
      let ov = null;
      if (resOv) { if (!resOv.ok) throw new Error((await resOv.json()).detail); ov = await resOv.json(); }
      ctitle.innerHTML = `多公司对比<small>区间: ${d.range} · ${Object.entries(d.comparisonReturns || {}).map(([k, v]) => `${k} ${v >= 0 ? "+" : ""}${Number(v).toFixed(2)}%`).join(" · ")}</small>`;
      renderCompareChart(d, ov);
      setTimeout(() => chart && chart.resize(), 80);
    } catch (e) {
      chart.hideLoading();
      ctitle.innerHTML += `<small style="color:var(--up)"> ${e.message}</small>`;
    }
  }

  const PALETTE = ["#d97757", "#2e7d32", "#1f6feb", "#7a5af8", "#d18800",
                   "#0d9488", "#d43f5e", "#5a67f0", "#c2552f", "#3478a3"];

  function renderCompareChart(d, ov) {
    chart.clear();
    const keys = Object.keys(d.series);
    const colors = {};
    keys.forEach((k, i) => colors[k] = PALETTE[i % PALETTE.length]);
    const series = keys.map(k => {
      const seriesReturn = d.comparisonReturns?.[k] ?? d.series[k].return_pct ?? 0;
      const returnText = `${seriesReturn >= 0 ? "+" : ""}${Number(seriesReturn).toFixed(2)}%`;
      return {
        name: `${k} ${returnText}`, type: "line", data: d.series[k].data,
        smooth: true, showSymbol: false, symbol: "circle", symbolSize: 5,
        lineStyle: { width: 2, color: colors[k] },
        itemStyle: { color: colors[k] },
        emphasis: { focus: "series" }
      };
    });
    const legend = series.map(s => s.name);
    // 叠加指数为虚线
    if (ov) {
      const oname = ov.series[overlayIdx] ? ov.series[overlayIdx].name : overlayIdx;
      legend.push(`指数 ${oname}`);
      series.push({
        name: `指数 ${oname}`, type: "line", data: ov.series[overlayIdx].data,
        smooth: true, showSymbol: false, symbol: "diamond", symbolSize: 5,
        lineStyle: { width: 1.5, type: "dashed", color: "#8a8a85" },
        itemStyle: { color: "#8a8a85" },
        emphasis: { focus: "series" }
      });
    }
    const option = {
      backgroundColor: "transparent", animation: false,
      color: keys.map(k => colors[k]),
      tooltip: {
        trigger: "axis",
        backgroundColor: "#fff", borderColor: "#e8e7e0", textStyle: { color: "#262624", fontSize: 12 },
        axisPointer: { type: "cross", lineStyle: { color: "#c9c8c0" }, label: { backgroundColor: "#262624" } },
        formatter: p => {
          const t = new Date(p[0].value[0]).toLocaleDateString("zh-CN");
          let s = `<div style="font-weight:600;margin-bottom:4px">${t}</div>`;
          p.forEach(x => s += `<div>${x.marker} <b>${x.seriesName.split(" ")[0]}</b> · ${fmtPrice(x.value[1])} ${x.seriesName.startsWith("指数") ? "(指数)" : ""}</div>`);
          return s;
        }
      },
      legend: { type: "scroll", top: 0, textStyle: { color: "#6f6e69" }, data: legend },
      grid: { left: 62, right: 20, top: 40, bottom: 60 },
      xAxis: { type: "time", axisLine: { lineStyle: { color: "#c9c8c0" } }, axisLabel: { color: "#6f6e69" } },
      yAxis: {
        type: "value", scale: true,
        splitLine: { lineStyle: { color: "#efece6" } },
        axisLabel: { color: "#6f6e69", formatter: v => fmtPrice(v) }
      },
      dataZoom: [
        { type: "inside", xAxisIndex: 0, start: 0, end: 100 },
        { type: "slider", xAxisIndex: 0, bottom: 8, borderColor: "#e8e7e0", height: 16,
          textStyle: { color: "#9b9a93" }, dataBackground: { lineStyle: { color: "#d97757" }, areaStyle: { color: "#d97757", opacity: .12 } } }
      ],
      series
    };
    chart.setOption(option, true);
    chart.hideLoading();
  }

  function fmtPrice(v) {
    if (v >= 1000) return v.toLocaleString("en-US", { minimumFractionDigits: 0 });
    return v.toLocaleString("en-US", { minimumFractionDigits: 2 });
  }

  function renderKline(d) {
    const dates = d.bars.map(b => b[0]);
    const kdata = d.bars.map(b => [b[1], b[2], b[3], b[4]]);
    const vols = d.bars.map(b => b[5]);
    const closes = kdata.map(k => k[1]);
    const ma = (n) => {
      const out = [];
      for (let i = 0; i < kdata.length; i++) {
        if (i < n - 1) { out.push("-"); continue; }
        let s = 0; for (let j = i - n + 1; j <= i; j++) s += kdata[j][1];
        out.push(+(s / n).toFixed(2));
      }
      return out;
    };
    const ema = (arr, n) => {
      const k = 2 / (n + 1), out = [];
      let prev = null;
      for (const v of arr) { out.push(prev == null ? v : v * k + prev * (1 - k)); prev = out[out.length - 1]; }
      return out;
    };
    const MACD = () => {
      const e12 = ema(closes, 12), e26 = ema(closes, 26);
      const dif = closes.map((_, i) => e12[i] - e26[i]);
      const dea = ema(dif, 9);
      return { dif, dea, hist: dif.map((v, i) => v - dea[i]) };
    };
    const RSI = (n = 14) => {
      const gains = [], losses = [];
      for (let i = 1; i < closes.length; i++) {
        const ch = closes[i] - closes[i - 1];
        gains.push(Math.max(ch, 0)); losses.push(Math.max(-ch, 0));
      }
      const out = new Array(closes.length).fill(null);
      if (gains.length >= n) {
        let ag = gains.slice(0, n).reduce((a, b) => a + b, 0) / n;
        let al = losses.slice(0, n).reduce((a, b) => a + b, 0) / n;
        out[n] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
        for (let i = n + 1; i < closes.length; i++) {
          ag = (ag * (n - 1) + gains[i - 1]) / n;
          al = (al * (n - 1) + losses[i - 1]) / n;
          out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
        }
      }
      return out;
    };
    const BOLL = (n = 20) => {
      const mid = ma(n), up = [], low = [];
      for (let i = 0; i < kdata.length; i++) {
        if (i < n - 1) { up.push("-"); low.push("-"); continue; }
        const win = closes.slice(i - n + 1, i + 1);
        const a = win.reduce((s, v) => s + v, 0) / n;
        const sd = Math.sqrt(win.reduce((s, v) => s + (v - a) ** 2, 0) / n);
        up.push(+(a + 2 * sd).toFixed(2)); low.push(+(a - 2 * sd).toFixed(2));
      }
      return { mid, up, low };
    };

    const hasSub = indicator === "macd" || indicator === "rsi";
    const grids = hasSub ? [
      { left: 62, right: 20, top: 32, height: "44%" },
      { left: 62, right: 20, top: "50%", height: "13%" },
      { left: 62, right: 20, top: "67%", height: "20%" }
    ] : [
      { left: 62, right: 20, top: 30, height: "56%" },
      { left: 62, right: 20, top: "73%", height: "16%" }
    ];

    const klineSeries = { name: "K线", type: "candlestick", data: kdata, itemStyle: { color: "#2e7d32", color0: "#c62828", borderColor: "#2e7d32", borderColor0: "#c62828" } };
    const volSeries = { name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: vols, itemStyle: { color: p => p.value >= 0 ? "rgba(216,119,87,.45)" : "rgba(46,125,50,.45)" } };
    const mkLine = (name, data, color) => ({ name, type: "line", data, smooth: true, showSymbol: false, lineStyle: { width: 1, color }, itemStyle: { color } });

    let legendData = ["K线"], mainSeries;
    if (indicator === "boll") {
      const b = BOLL();
      legendData = ["K线", "BOLL上", "BOLL中", "BOLL下"];
      mainSeries = [klineSeries, mkLine("BOLL上", b.up, "#d18800"), mkLine("BOLL中", b.mid, "#1f6feb"), mkLine("BOLL下", b.low, "#d18800")];
    } else {
      legendData = ["K线", "MA5", "MA20", "MA60"];
      mainSeries = [klineSeries, mkLine("MA5", ma(5), "#d18800"), mkLine("MA20", ma(20), "#1f6feb"), mkLine("MA60", ma(60), "#7a5af8")];
    }

    let subSeries = [], subYAxis = null;
    if (indicator === "macd") {
      const m = MACD();
      legendData.push("DIF", "DEA");
      const f = v => +v.toFixed(3);
      subSeries = [
        { name: "MACD", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: m.hist.map(f), itemStyle: { color: p => p.value >= 0 ? "rgba(216,119,87,.55)" : "rgba(46,125,50,.55)" } },
        { name: "DIF", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: m.dif.map(f), smooth: true, showSymbol: false, lineStyle: { width: 1, color: "#d18800" }, itemStyle: { color: "#d18800" } },
        { name: "DEA", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: m.dea.map(f), smooth: true, showSymbol: false, lineStyle: { width: 1, color: "#1f6feb" }, itemStyle: { color: "#1f6feb" } }
      ];
      subYAxis = { gridIndex: 2, splitLine: { show: false }, axisLabel: { color: "#6f6e69", formatter: v => v.toFixed(2) } };
    } else if (indicator === "rsi") {
      legendData.push("RSI14");
      const r = RSI(14);
      const rn = v => v == null ? "-" : +v.toFixed(1);
      subSeries = [
        { name: "RSI14", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: r.map(rn), smooth: true, showSymbol: false, lineStyle: { width: 1.5, color: "#7a5af8" }, itemStyle: { color: "#7a5af8" } },
        { name: "超买70", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: closes.map(() => 70), showSymbol: false, lineStyle: { width: 1, type: "dashed", color: "#c9c8c0" }, tooltip: { show: false } },
        { name: "超卖30", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: closes.map(() => 30), showSymbol: false, lineStyle: { width: 1, type: "dashed", color: "#c9c8c0" }, tooltip: { show: false } }
      ];
      subYAxis = { gridIndex: 2, min: 0, max: 100, splitLine: { lineStyle: { color: "#efece6" } }, axisLabel: { color: "#6f6e69" } };
    }

    const xAxes = [{ type: "category", data: dates, boundaryGap: true, axisLine: { lineStyle: { color: "#c9c8c0" } }, axisLabel: { color: "#6f6e69" } }];
    xAxes.push({ type: "category", gridIndex: 1, data: dates, boundaryGap: true, axisLabel: { show: false }, axisLine: { lineStyle: { color: "#c9c8c0" } } });
    if (hasSub) xAxes.push({ type: "category", gridIndex: 2, data: dates, boundaryGap: true, axisLabel: { show: false }, axisLine: { lineStyle: { color: "#c9c8c0" } } });

    const yAxes = [{ scale: true, splitLine: { lineStyle: { color: "#efece6" } }, axisLabel: { color: "#6f6e69", formatter: v => fmtPrice(v) } }];
    yAxes.push({ gridIndex: 1, splitLine: { show: false }, splitNumber: 3, axisLabel: { color: "#6f6e69", formatter: v => fmtVol(v) } });
    if (hasSub) yAxes.push(subYAxis);

    const zidx = hasSub ? [0, 1, 2] : [0, 1];
    const zoom = [
      { type: "inside", xAxisIndex: zidx, start: 60, end: 100 },
      { type: "slider", xAxisIndex: zidx, bottom: hasSub ? 6 : 8, start: 60, end: 100, borderColor: "#e8e7e0", height: 16, textStyle: { color: "#9b9a93" }, dataBackground: { lineStyle: { color: "#d97757" }, areaStyle: { color: "#d97757", opacity: .12 } } }
    ];

    const option = {
      backgroundColor: "transparent", animation: false,
      axisPointer: { link: [{ xAxisIndex: "all" }], label: { backgroundColor: "#262624" } },
      tooltip: {
        trigger: "axis", axisPointer: { type: "cross", lineStyle: { color: "#c9c8c0" } },
        backgroundColor: "#fff", borderColor: "#e8e7e0", textStyle: { color: "#262624", fontSize: 12 },
        formatter: p => {
          const i = p[0].dataIndex;
          const [o, c, l, h] = kdata[i];
          const chg = c - o, pct = ((c - o) / o * 100).toFixed(2);
          const col = chg >= 0 ? "var(--up)" : "var(--down)";
          const sign = chg >= 0 ? "+" : "";
          const rows = p.map(x => {
            if (x.seriesName === "成交量") return `${x.marker} 成交量: ${fmtVol(vols[i])}`;
            if (x.seriesName === "RSI14") return `${x.marker} RSI(14): ${x.value}`;
            if (x.seriesName === "超买70" || x.seriesName === "超卖30") return null;
            if (["DIF", "DEA", "MACD"].includes(x.seriesName)) return `${x.marker} ${x.seriesName}: ${x.value}`;
            return `${x.marker} 收盘: ${fmtPrice(x.value)} <span style="color:${col}">(${sign}${fmtPrice(chg)}, ${sign}${pct}%)</span>`;
          }).filter(Boolean);
          return `<div style="font-weight:600;margin-bottom:4px">${d.ticker} · ${dates[i]}</div>${rows.join("<br>")}`;
        }
      },
      legend: { data: legendData, textStyle: { color: "#6f6e69" }, top: 0, type: "scroll" },
      grid: grids,
      xAxis: xAxes, yAxis: yAxes,
      dataZoom: zoom,
      series: [...mainSeries, volSeries, ...subSeries]
    };
    chart.setOption(option, true);
    chart.hideLoading();
  }

  function fmtVol(v) {
    if (v >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(1) + "K";
    return v;
  }

  function fmtNumber(v, digits = 2) {
    if (v == null) return "—";
    const a = Math.abs(v);
    if (a >= 1e12) return (v / 1e12).toFixed(2) + "T";
    if (a >= 1e9) return (v / 1e9).toFixed(2) + "B";
    if (a >= 1e6) return (v / 1e6).toFixed(2) + "M";
    return Number(v).toLocaleString("en-US", { maximumFractionDigits: digits });
  }

  async function loadFundamentals(symbol) {
    const panel = document.getElementById("fundamentals");
    panel.innerHTML = '<div class="empty">正在加载基本面数据…</div>';
    try {
      const response = await fetch(`/api/fundamentals/${symbol}`);
      if (!response.ok) throw new Error((await response.json()).detail || "请求失败");
      const d = await response.json(), m = d.metrics || {};
      const cards = [
        ["市值", fmtNumber(m.market_cap)], ["市盈率 TTM", fmtNumber(m.trailing_pe)],
        ["预期市盈率", fmtNumber(m.forward_pe)], ["市净率", fmtNumber(m.price_to_book)],
        ["每股收益 TTM", fmtNumber(m.trailing_eps)], ["预期 EPS", fmtNumber(m.forward_eps)],
        ["股息率", m.dividend_yield_pct == null ? "—" : fmtNumber(m.dividend_yield_pct) + "%"],
        ["年度股息", m.dividend_rate == null ? "—" : "$" + fmtNumber(m.dividend_rate)],
        ["派息率", m.payout_ratio_pct == null ? "—" : fmtNumber(m.payout_ratio_pct) + "%"],
        ["Beta", fmtNumber(m.beta)], ["52周高", fmtNumber(m.fifty_two_week_high)],
        ["52周低", fmtNumber(m.fifty_two_week_low)]
      ];
      const annualRows = (d.annual || []).map(x => `<tr><td>${x.date}</td><td>${fmtNumber(x.revenue)}</td><td>${fmtNumber(x.net_income)}</td><td>${fmtNumber(x.ebitda)}</td><td>${fmtNumber(x.free_cash_flow)}</td><td>${fmtNumber(x.total_assets)}</td><td>${fmtNumber(x.total_debt)}</td></tr>`).join("");
      const dividendRows = (d.dividends || []).slice().reverse().map(x => `<tr><td>${x.date}</td><td>$${fmtNumber(x.amount, 4)}</td></tr>`).join("");
      panel.innerHTML = `<div class="metric-grid">${cards.map(([k,v]) => `<div class="metric-card"><small>${k}</small><b>${v}</b></div>`).join("")}</div><div class="report-card"><h3>年度财报 · ${d.currency || "USD"}</h3><table class="report-table"><thead><tr><th>财年</th><th>营收</th><th>净利润</th><th>EBITDA</th><th>自由现金流</th><th>总资产</th><th>总负债</th></tr></thead><tbody>${annualRows || '<tr><td colspan="7">暂无年度财报</td></tr>'}</tbody></table></div><div class="report-card"><h3>最近分红</h3><table class="report-table"><thead><tr><th>日期</th><th>每股股息</th></tr></thead><tbody>${dividendRows || '<tr><td colspan="2">暂无分红记录</td></tr>'}</tbody></table></div>`;
      ctitle.innerHTML = `${d.ticker} — ${d.name}<small>${d.sector || ""}${d.industry ? " · " + d.industry : ""}</small>`;
    } catch (e) {
      panel.innerHTML = `<div class="empty">基本面加载失败: ${e.message}</div>`;
    }
  }

  async function loadFundamentalsCompare() {
    const symbols = [...fundamentalSel];
    const panel = document.getElementById("fundamentals");
    if (!symbols.length) {
      panel.innerHTML = '<div class="empty">请从左侧选择一家公司或多家公司</div>';
      return;
    }
    panel.innerHTML = '<div class="empty">正在加载基本面对比…</div>';
    try {
      const responses = await Promise.all(symbols.map(s => fetch(`/api/fundamentals/${s}`)));
      const data = await Promise.all(responses.map(async r => {
        if (!r.ok) throw new Error((await r.json()).detail || "请求失败");
        return r.json();
      }));
      const groups = [
        ["估值", [
          ["市值", "market_cap", v => fmtNumber(v)], ["市盈率 TTM", "trailing_pe", v => fmtNumber(v)],
          ["预期市盈率", "forward_pe", v => fmtNumber(v)], ["市净率", "price_to_book", v => fmtNumber(v)]
        ]],
        ["盈利能力", [
          ["每股收益 TTM", "trailing_eps", v => fmtNumber(v)], ["预期 EPS", "forward_eps", v => fmtNumber(v)]
        ]],
        ["股东回报", [
          ["股息率", "dividend_yield_pct", v => v == null ? "—" : fmtNumber(v) + "%"],
          ["年度股息", "dividend_rate", v => v == null ? "—" : "$" + fmtNumber(v)],
          ["派息率", "payout_ratio_pct", v => v == null ? "—" : fmtNumber(v) + "%"]
        ]],
        ["风险与区间", [
          ["Beta", "beta", v => fmtNumber(v)], ["52周高", "fifty_two_week_high", v => fmtNumber(v)],
          ["52周低", "fifty_two_week_low", v => fmtNumber(v)]
        ]]
      ];
      const cols = `140px repeat(${data.length}, minmax(150px, 1fr))`;
      const companies = data.map(d => `<div class="comparison-company"><img src="${LOGO(d.ticker)}" alt=""><b>${d.ticker}</b><small>${d.name}</small></div>`).join("");
      const rows = groups.map(([group, metrics]) => {
        const section = `<div class="comparison-section" style="grid-column:1/-1">${group}</div>`;
        return section + metrics.map(([label, key, format]) =>
          `<div class="comparison-label">${label}</div>${data.map(d => `<div class="comparison-value">${format(d.metrics?.[key])}</div>`).join("")}`
        ).join("");
      }).join("");
      panel.innerHTML = `<div class="comparison-shell"><div class="comparison-title"><div><b>基本面对比</b><small>${data.length} 家公司 · 横向滑动查看更多</small></div></div><div class="comparison-grid" style="grid-template-columns:${cols}"><div class="comparison-corner">指标</div>${companies}${rows}</div></div>`;
      ctitle.innerHTML = `基本面对比<small>已选 ${data.length} 家 · 点击左侧公司可增删（最多8家）</small>`;
    } catch (e) {
      panel.innerHTML = `<div class="empty">基本面对比加载失败: ${e.message}</div>`;
    }
  }

  // ---------- 模式切换 ----------
  function enterKlineMode() {
    document.getElementById("fundamentals").style.display = "none";
    document.getElementById("chartwrap").style.display = "";
    document.body.classList.add("chart-open");
    mode = "kline";
    document.querySelectorAll(".mode-tab").forEach(x => x.classList.toggle("active", x.dataset.mode === "kline"));
    selectionMode = false;
    overlayIdx = null;
    if (fundamentalSel.size > 1) compareSel = new Set(fundamentalSel);
    renderChips();
    if (compareSel.size > 1) {
      renderList();
      renderCompare();
      setTimeout(() => chart && chart.resize(), 80);
      return;
    }
    setMode("kline");
    renderList();
    if (current) renderChart();
    setTimeout(() => chart && chart.resize(), 80);
  }

  function enterSingleCompanyMode() {
    compareSel.clear();
    fundamentalSel.clear();
    overlayIdx = null;
    selectionMode = false;
    updateSelectionBar();
    renderChips();
    renderFundamentalChips();
    setMode("kline");
    if (mqMobile.matches) document.body.classList.remove("chart-open");
    renderList();
  }

  function setMode(m) {
    mode = m;
    document.querySelectorAll(".mode-tab").forEach(x => x.classList.toggle("active", x.dataset.mode === m));
    const indTabs = document.getElementById("ind-tabs");
    if (indTabs) indTabs.style.display = m === "kline" ? "flex" : "none";
    const perTabs = document.getElementById("per-tabs");
    if (perTabs) perTabs.style.display = m === "kline" ? "flex" : "none";
    document.getElementById("ranges").style.display = m === "fundamentals" ? "none" : "flex";
    document.getElementById("idxoverlay").style.display = m === "compare" ? "flex" : "none";
    document.getElementById("chartwrap").style.display = m === "fundamentals" ? "none" : "";
    document.getElementById("fundamentals").style.display = m === "fundamentals" ? "block" : "none";
    if (m === "compare") {
      if (fundamentalSel.size > 1) compareSel = new Set(fundamentalSel);
      if (compareSel.size === 0) {
        // 默认选中当前 + 前一家, 便于立即对比
        const order = filterStocks().map(symOf);
        compareSel.add(current || order[0]);
        if (order[1] && compareSel.size < 2) compareSel.add(order[1]);
      }
      renderList(); renderChips(); renderCompare();
    } else if (m === "fundamentals") {
      if (!fundamentalSel.size && compareSel.size > 1) fundamentalSel = new Set(compareSel);
      if (fundamentalSel.size === 0 && current) fundamentalSel.add(current);
      renderList();
      renderFundamentalChips();
      loadFundamentalsCompare();
    } else {
      renderChips();
      if (current) {
        renderChart();
        // 基本面面板隐藏图表时,ECharts会记住零/小尺寸;恢复后重新测量容器。
        setTimeout(() => chart && chart.resize(), 50);
      }
    }
  }

  // ---------- 事件 ----------
  qEl.addEventListener("input", () => renderList());
  document.querySelectorAll(".tab").forEach(t =>
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
      if (indexHistoryView) return;
      sortMode = t.dataset.sort;
      enterSingleCompanyMode();
      if (sortMode === "mover") { showRank(); return; }
      // 非涨跌 tab: 隐藏排行面板,显示列表
      document.getElementById("rankpanel").style.display = "none";
      listEl.style.display = "";
      renderList();
    }));
  document.querySelectorAll(".mode-tab").forEach(t =>
    t.addEventListener("click", () => {
      if (t.dataset.mode) {
        if (t.dataset.mode === "kline") enterKlineMode();
        else setMode(t.dataset.mode);
      }
      if (t.dataset.ind) {
        indicator = t.dataset.ind;
        document.querySelectorAll("#ind-tabs .mode-tab").forEach(x => x.classList.toggle("active", x.dataset.ind === indicator));
        if (indexHistoryView) loadIndexHistory(curIndex); else if (current) renderChart();
      }
      if (t.dataset.per) {
        curPeriod = t.dataset.per;
        document.querySelectorAll("#per-tabs .mode-tab").forEach(x => x.classList.toggle("active", x.dataset.per === curPeriod));
        if (indexHistoryView) loadIndexHistory(curIndex); else if (current) renderChart();
      }
    }));
  document.querySelectorAll("#ranges .range").forEach(r =>
    r.addEventListener("click", () => {
      document.querySelectorAll("#ranges .range").forEach(x => x.classList.remove("active"));
      r.classList.add("active");
      curRange = r.dataset.r;
      if (indexHistoryView) loadIndexHistory(curIndex); else renderChart();
    }));
  document.getElementById("back").addEventListener("click", () => {
    document.body.classList.remove("chart-open");
    setTimeout(() => chart && chart.resize(), 50);
  });
  function toggleSelectionMode(event) {
    event?.preventDefault();
    event?.stopPropagation();
    selectionMode = !selectionMode;
    if (!selectionMode) fundamentalSel.clear();
    updateSelectionBar();
    renderList();
  }
  const selectMode = document.getElementById("selectMode");
  selectMode.addEventListener("click", toggleSelectionMode);
  function confirmFundamentalSelection(event) {
    event?.preventDefault();
    event?.stopPropagation();
    if (!fundamentalSel.size) {
      updateSelectionBar();
      return;
    }
    selectionMode = false;
    compareSel = new Set(fundamentalSel);
    setMode("fundamentals");
    renderList();
    renderFundamentalChips();
    loadFundamentalsCompare();
    if (mqMobile.matches) document.body.classList.add("chart-open");
  }
  document.getElementById("confirmSelection").addEventListener("click", confirmFundamentalSelection);
  document.getElementById("confirmSelection").onclick = confirmFundamentalSelection;
  // 对比图叠加大盘指数
  document.querySelectorAll("#idxoverlay .range").forEach(el =>
    el.addEventListener("click", () => {
      const val = el.dataset.ix === "off" ? null : el.dataset.ix;
      if (overlayIdx === val) return;
      overlayIdx = val;
      document.querySelectorAll("#idxoverlay .range").forEach(x => x.classList.toggle("active", x.dataset.ix === (val || "off")));
      if (mode === "compare" && compareSel.size) renderCompare();
    }));

  loadIndices();
  loadStocks(curIndex);
})();