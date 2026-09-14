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
  let curRange = "1mo";
  let mode = "kline";
  let indicator = "ma"; // ma | macd | rsi | boll
  let overlayIdx = null; // 对比图叠加的指数
  let curPeriod = "1d";  // 1d | 1wk | 1mo
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
        const b = document.createElement("div");
        b.className = "idx" + (ix.id === curIndex ? " active" : "");
        b.textContent = ix.name;
        b.dataset.ix = ix.id;
        b.title = ix.desc;
        b.onclick = () => switchIndex(ix.id);
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
    overlayIdx = null;
    loadStocks(curIndex);
  }

  // ---------- 股票列表 ----------
  async function loadStocks(index) {
    listEl.innerHTML = `<div class="empty">加载中…</div>`;
    try {
      const r = await fetch(`/api/stocks?index=${index}`);
      stocks = await r.json();
      if (index === "top100") await enrichMarketCaps();
      renderList();
      if (stocks.length) select(stocks[0].symbol, false); // 初始加载不自动进移动端图表
      const ix = indices.find(i => i.id === index);
      const ixName = ix ? ix.desc : "";
      ctitle.parentElement.querySelector(".hint")?.remove();
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
    return mode === "compare" ? compareSel.has(symOf(s)) : symOf(s) === current;
  }

  function renderList() {
    const arr = filterStocks();
    if (!arr.length) { listEl.innerHTML = `<div class="empty">无匹配结果</div>`; return; }
    listEl.innerHTML = "";
    const frag = document.createDocumentFragment();
    arr.forEach(s => {
      const sym = symOf(s);
      const r = document.createElement("div");
      r.className = "row" + (isActive(s) ? " active" : "");
      r.dataset.t = sym;
      r.innerHTML = `
        <div class="rank">${mode === "compare" && isActive(s) ? "✓" : (s.rank ?? "")}</div>
        <img class="logo" loading="lazy" alt=""
             src="${LOGO(sym)}"
             onerror="this.onerror=null;this.classList.add('fallback');this.src='data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2236%22 height=%2236%22><rect width=%2236%22 height=%2236%22 fill=%22%23f0ede6%22/><text x=%2218%22 y=%2223%22 font-size=%2214%22 text-anchor=%22middle%22 fill=%22%23d97757%22 font-family=%22sans-serif%22 font-weight=%22bold%22>${sym[0]}</text></svg>'">
        <div class="sym">${sym}<small>${nameOf(s)}</small></div>
        <div class="mcap"><b>${fmtSize(s)}</b>${s.sector || ""}</div>`;
      r.onclick = () => mode === "compare" ? toggleCompare(sym) : select(sym);
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

  // ---------- 图表 ----------
  async function renderChart() {
    if (!chart) {
      chart = echarts.init(document.getElementById("kline"));
      window.addEventListener("resize", () => chart.resize());
    }
    if (mode === "compare") return renderCompare();
    return loadKline(current, curRange);
  }

  async function loadKline(symbol, range) {
    chart.showLoading({ text: "加载中…", color: "#d97757", textColor: "#9b9a93" });
    try {
      const r = await fetch(`/api/stock/${symbol}?range=${range}`);
      if (!r.ok) throw new Error((await r.json()).detail || "请求失败");
      renderKline(await r.json());
    } catch (e) {
      chart.hideLoading();
      ctitle.innerHTML += `<small style="color:var(--up)"> ${e.message}</small>`;
    }
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
      ctitle.innerHTML = `多公司对比<small>区间: ${d.range} · 已选 ${Object.keys(d.series).length} 家${ov ? " · 叠加 " + overlayIdx : ""}</small>`;
      renderCompareChart(d, ov);
    } catch (e) {
      chart.hideLoading();
      ctitle.innerHTML += `<small style="color:var(--up)"> ${e.message}</small>`;
    }
  }

  const PALETTE = ["#d97757", "#2e7d32", "#1f6feb", "#7a5af8", "#d18800",
                   "#0d9488", "#d43f5e", "#5a67f0", "#c2552f", "#3478a3"];

  function renderCompareChart(d, ov) {
    const keys = Object.keys(d.series);
    const colors = {};
    keys.forEach((k, i) => colors[k] = PALETTE[i % PALETTE.length]);
    const series = keys.map(k => ({
      name: `${k} ${d.series[k].name}`, type: "line", data: d.series[k].data,
      smooth: true, showSymbol: false, symbol: "circle", symbolSize: 5,
      lineStyle: { width: 2, color: colors[k] },
      itemStyle: { color: colors[k] },
      emphasis: { focus: "series" }
    }));
    const legend = [...keys.map(k => `${k} ${d.series[k].name}`)];
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

    const klineSeries = { name: "K线", type: "candlestick", data: kdata, itemStyle: { color: "#d97757", color0: "#2e7d32", borderColor: "#d97757", borderColor0: "#2e7d32" } };
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
        mkLine("DIF", m.dif.map(f), "#d18800"),
        mkLine("DEA", m.dea.map(f), "#1f6feb")
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
    yAxes.push({ gridIndex: 1, splitLine: { show: false }, axisLabel: { color: "#6f6e69", formatter: v => fmtVol(v) } });
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

  // ---------- 模式切换 ----------
  function setMode(m) {
    mode = m;
    document.querySelectorAll(".mode-tab").forEach(x => x.classList.toggle("active", x.dataset.mode === m));
    const indTabs = document.getElementById("ind-tabs");
    if (indTabs) indTabs.style.display = m === "kline" ? "flex" : "none";
    const perTabs = document.getElementById("per-tabs");
    if (perTabs) perTabs.style.display = m === "kline" ? "flex" : "none";
    document.getElementById("idxoverlay").style.display = m === "compare" ? "flex" : "none";
    if (m === "compare") {
      if (compareSel.size === 0) {
        // 默认选中当前 + 前一家, 便于立即对比
        const order = filterStocks().map(symOf);
        compareSel.add(current || order[0]);
        if (order[1] && compareSel.size < 2) compareSel.add(order[1]);
      }
      renderList(); renderChips(); renderCompare();
    } else {
      renderChips();
      if (current) renderChart();
    }
  }

  // ---------- 事件 ----------
  qEl.addEventListener("input", () => renderList());
  document.querySelectorAll(".tab").forEach(t =>
    t.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
      sortMode = t.dataset.sort;
      if (sortMode === "mover") { showRank(); return; }
      // 非涨跌 tab: 隐藏排行面板,显示列表
      document.getElementById("rankpanel").style.display = "none";
      listEl.style.display = "";
      renderList();
    }));
  document.querySelectorAll(".mode-tab").forEach(t =>
    t.addEventListener("click", () => {
      if (t.dataset.mode) setMode(t.dataset.mode);
      if (t.dataset.ind) {
        indicator = t.dataset.ind;
        document.querySelectorAll("#ind-tabs .mode-tab").forEach(x => x.classList.toggle("active", x.dataset.ind === indicator));
        if (current) renderChart();
      }
      if (t.dataset.per) {
        curPeriod = t.dataset.per;
        document.querySelectorAll("#per-tabs .mode-tab").forEach(x => x.classList.toggle("active", x.dataset.per === curPeriod));
        if (current) renderChart();
      }
    }));
  document.querySelectorAll(".range").forEach(r =>
    r.addEventListener("click", () => {
      document.querySelectorAll(".range").forEach(x => x.classList.remove("active"));
      r.classList.add("active");
      curRange = r.dataset.r;
      renderChart();
    }));
  document.getElementById("back").addEventListener("click", () => {
    document.body.classList.remove("chart-open");
    setTimeout(() => chart && chart.resize(), 50);
  });
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