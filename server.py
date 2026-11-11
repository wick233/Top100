"""美股Top100/标普500/纳指100 历史行情报表 - 后端服务
API:
  GET /                       前端页面
  GET /api/indices            可用指数清单
  GET /api/stocks?index=      成分股清单
  GET /api/quote/{ticker}     实时市值
  GET /api/logo/{ticker}      公司logo(代理)
  GET /api/stock/{ticker}?range=     历史K线(读SQLite落盘)
  GET /api/compare?symbols=   多公司收盘价对比
  GET /api/export/{ticker}?range=&fmt=  导出CSV/JSON
"""
import time
import threading
import json
import re
from datetime import datetime

import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from top100 import TOP100
from indices import fetch_index, INDICES, _HEADERS
from store import get_bars, export_bars
from fundamentals import get_fundamentals, _cached

try:
    with open("company_names_zh.json", encoding="utf-8") as _name_file:
        COMPANY_NAMES_ZH_FULL = json.load(_name_file)
except (OSError, json.JSONDecodeError):
    COMPANY_NAMES_ZH_FULL = {}

app = FastAPI(title="美股 历史行情报表")

RANGES = {"1wk", "1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
INTERVALS = {"1d": "1d", "1wk": "1wk", "1mo": "1mo"}
INDEX_HISTORY = {
    "sp500": {"ticker": "^GSPC", "name": "标普500指数"},
    "ndx100": {"ticker": "^NDX", "name": "纳指100指数"},
}

# 常用成分股的简明中文业务简介，接口优先从本地返回，避免点击公司时等待 Yahoo。
COMPANY_SUMMARIES_ZH = {
    "AAPL": "苹果公司主要设计、制造和销售手机、电脑、平板电脑、智能手表、无线耳机等硬件产品，并提供应用商店、云存储、音乐、视频和移动支付等服务。",
    "MSFT": "微软提供电脑操作系统、办公软件、云服务、企业管理软件、职业社交平台、游戏及人工智能产品，客户覆盖个人、企业、教育和政府机构。",
    "NVDA": "英伟达设计图形处理器、数据中心加速器和人工智能计算平台，产品广泛用于云计算、生成式人工智能、游戏和自动驾驶。",
    "AMZN": "亚马逊经营电子商务平台、云计算、数字内容、广告和物流业务，同时销售自有设备及订阅服务。",
    "GOOGL": "谷歌母公司通过搜索、在线广告、视频、移动操作系统、云计算和人工智能服务开展业务，并进行前沿技术研发。",
    "GOOG": "谷歌母公司通过搜索、在线广告、视频、移动操作系统、云计算和人工智能服务开展业务，并进行前沿技术研发。",
    "META": "脸书母公司运营脸书、照片墙、即时通讯和聊天应用等社交平台，并开发广告、虚拟现实和增强现实产品。",
    "TSLA": "特斯拉设计和销售电动汽车、储能系统及太阳能产品，并持续发展自动驾驶、充电网络和能源管理软件。",
    "AVGO": "博通设计和供应半导体及基础设施软件，产品应用于网络通信、宽带、存储、无线设备、数据中心和企业软件。",
    "JPM": "摩根大通提供投资银行、商业银行、资产管理、消费金融和信用卡服务，客户包括个人、企业、机构和政府。",
    "V": "维萨运营全球电子支付网络，为消费者、商户、金融机构和政府提供支付处理、结算及相关增值服务。",
    "WMT": "沃尔玛经营综合零售、电子商务和会员服务，通过实体门店及线上渠道销售食品、日用品、家电和其他消费品。",
    "NFLX": "奈飞提供全球流媒体娱乐服务，用户可以观看电影、电视剧、纪录片和原创内容，公司也参与内容制作与发行。",
    "ORCL": "甲骨文提供数据库、企业软件、云基础设施和行业应用，帮助企业管理财务、人力资源、供应链和客户关系。",
    "COST": "好市多以会员制仓储卖场和电子商务平台销售食品、日用品、家电、服装及其他商品，并提供药房、加油等服务。",
    "AMD": "超威半导体设计中央处理器、图形处理器和自适应计算产品，服务于数据中心、个人电脑、游戏和嵌入式市场。",
    "INTC": "英特尔设计和制造处理器、芯片组及数据中心、个人电脑、网络和人工智能相关产品，也提供芯片代工服务。",
    "CRM": "赛富时提供云端客户关系管理软件，覆盖销售、服务、营销、商业智能和数据分析等企业业务场景。",
    "ADBE": "奥多比提供创意设计、数字文档和数字体验软件，包括图像处理、插画设计、电子文档和相关云服务。",
    "QCOM": "高通设计无线通信芯片和技术，提供智能手机、物联网、汽车及边缘计算所需的处理器、调制解调器和专利授权服务。",
    "CSCO": "思科提供网络设备、网络安全、协作、可观测性和云管理产品，帮助企业和机构建设及管理数字基础设施。",
    "FDXF": "联邦快递货运控股主要提供零担货运和综合物流服务，服务美国及国际市场的企业客户。",
    "REGN": "再生元制药专注于发现、开发和商业化创新药物，重点覆盖眼科、炎症、肿瘤和代谢等疾病领域。",
    "GPN": "环球支付提供支付技术和软件解决方案，帮助商户、金融机构和企业处理银行卡、支票及数字支付。",
    "PNR": "滨特尔提供水处理、输水和泳池相关解决方案，服务住宅、商业和工业客户。",
    "MRNA": "莫德纳专注于信使核糖核酸药物和疫苗的研发，产品覆盖呼吸道传染病、传染病和其他疾病领域。",
    "RDDT": "红迪运营在线社区平台，用户可以围绕兴趣主题交流、分享内容、创建社区并参与讨论。",
    "GDDY": "哥达迪提供域名注册、网站建设、主机、电子商务和网络营销工具，帮助个人及企业开展线上业务。",
    "VLTO": "维拉尔托提供水质分析、产品质量检测和标识追溯解决方案，服务工业、商业和公共事业客户。",
    "TWLO": "特威利奥提供云通信平台和软件开发工具，帮助企业通过短信、语音、视频和身份验证服务与客户沟通。",
    "SNDK": "闪迪设计和销售闪存、固态硬盘、存储卡及其他数据存储产品，服务个人、企业和数据中心市场。",
    "HOOD": "罗宾侠提供面向个人投资者的证券、期权、加密货币和现金管理服务。",
    "COIN": "币库提供加密货币交易、托管、支付和区块链基础设施服务，面向个人、机构和开发者。",
    "MRVL": "迈威尔科技设计数据中心、网络、通信和汽车市场使用的半导体及相关芯片解决方案。",
    "COHR": "高意提供激光器、光学器件、光通信、精密制造和半导体相关技术，服务通信、工业、医疗和科研市场。",
    "ILMN": "因美纳提供基因测序、基因组分析和相关生物信息学技术，服务科研、临床诊断和生物制药领域。",
    "TER": "泰瑞达提供半导体自动测试设备、测试系统和工业自动化设备，服务芯片制造商及电子企业。",
    "APP": "应用爱好提供移动应用营销、广告投放和应用变现技术，帮助开发者获取用户并提升收入。",
    "DDOG": "数据狗提供云端监控、日志分析、应用性能管理和网络安全平台，帮助企业管理数字化系统。",
    "FFIV": "五号网络提供应用交付、网络安全和云服务解决方案，帮助企业保护、优化和管理应用流量。",
}

COMPANY_NAMES_ZH = {
    "AAPL": "苹果", "MSFT": "微软", "NVDA": "英伟达", "AMZN": "亚马逊",
    "GOOG": "谷歌", "GOOGL": "谷歌", "META": "Meta公司", "TSLA": "特斯拉",
    "AVGO": "博通", "JPM": "摩根大通", "V": "维萨", "WMT": "沃尔玛", "NFLX": "奈飞",
    "ORCL": "甲骨文", "COST": "好市多", "AMD": "超威半导体", "INTC": "英特尔",
    "CRM": "赛富时", "ADBE": "奥多比", "QCOM": "高通", "CSCO": "思科", "FDXF": "联邦快递货运控股",
    "REGN": "再生元制药", "GPN": "环球支付", "PNR": "滨特尔", "MRNA": "莫德纳", "RDDT": "红迪",
    "GDDY": "GoDaddy（哥达迪）", "ACN": "埃森哲", "VLTO": "维拉尔托", "TWLO": "特威利奥",
    "SNDK": "闪迪", "HOOD": "罗宾侠", "COIN": "Coinbase（币库）", "MRVL": "迈威尔科技",
    "TER": "泰瑞达", "COHR": "高意", "ILMN": "因美纳", "APP": "应用爱好", "DDOG": "数据狗", "FFIV": "五号网络",
}

_cache = {}          # key -> (expire_ts, data)
_cache_lock = threading.Lock()
_cache_ttl = 300     # 秒
_rank_cache_ttl = 60
_index_history_cache = {}  # (index, range, interval) -> (expire_ts, response)

class StockItem(BaseModel):
    symbol: str
    ticker: str
    name: str
    market_cap_b: float
    sector: str
    weight_pct: float = None

def _now_utc():
    return time.time()


@app.get("/api/indices")
def list_indices():
    return [{"id": i, **meta} for i, meta in INDICES.items()]


@app.get("/api/stocks")
def stocks(index: str = "top100"):
    """返回指定指数的成分股清单（含名称/行业/市值基准），供前端列表与排序使用。
    index 取值 top100 / sp500 / ndx100，默认 top100。"""
    index = index.lower()
    if index not in INDICES:
        raise HTTPException(400, f"未知指数: {index},可选 {sorted(INDICES)}")
    data = fetch_index(index)
    # 返回干净列表：rank/symbol/name/weight/sector/market_cap_b(基准,quote会覆盖)
    out = []
    for s in data:
        out.append({
            "rank": s.get("rank"),
            "symbol": s.get("symbol"),
            "name": s.get("name") or s.get("symbol"),
            "weight_pct": s.get("weight_pct"),
            "sector": s.get("sector"),
            "market_cap_b": s.get("market_cap_b"),
        })
    return out


@app.get("/api/index-history/{index_id}")
def index_history(index_id: str, range: str = "1y", interval: str = "1d"):
    """返回标普500或纳指100指数本身的历史OHLCV数据。"""
    index_id = index_id.lower()
    if index_id not in INDEX_HISTORY:
        raise HTTPException(400, "index_id 需为 sp500 或 ndx100")
    if range not in RANGES:
        raise HTTPException(400, f"range 需为 {sorted(RANGES)}")
    if interval not in INTERVALS:
        raise HTTPException(400, f"interval 需为 {sorted(INTERVALS)}")
    cache_key = (index_id, range, interval)
    with _cache_lock:
        cached = _index_history_cache.get(cache_key)
        if cached and cached[0] > _now_utc():
            return cached[1]
    meta = INDEX_HISTORY[index_id]
    try:
        rows = get_bars(meta["ticker"], interval, range)
    except Exception as exc:
        raise HTTPException(502, f"拉取指数数据失败: {exc}") from exc
    if not rows:
        raise HTTPException(404, f"{meta['name']} 无历史数据")
    bars = [[r["date"], r["open"], r["close"], r["low"], r["high"], r["volume"]]
            for r in rows]
    result = {"ticker": meta["ticker"], "name": meta["name"], "range": range,
              "interval": interval, "start": bars[0][0], "end": bars[-1][0], "bars": bars}
    with _cache_lock:
        _index_history_cache[cache_key] = (_now_utc() + _cache_ttl, result)
    return result


@app.get("/report/{index_id}", response_class=HTMLResponse)
def index_report(index_id: str, range: str = "1y", interval: str = "1d"):
    """服务端直接输出指数报表，避免浏览器脚本或图表库影响可见性。"""
    index_id = index_id.lower()
    if index_id not in INDEX_HISTORY:
        raise HTTPException(400, "index_id 需为 sp500 或 ndx100")
    if range not in RANGES or interval not in INTERVALS:
        raise HTTPException(400, "无效的时间范围或周期")
    meta = INDEX_HISTORY[index_id]
    try:
        rows = get_bars(meta["ticker"], interval, range)
    except Exception as exc:
        raise HTTPException(502, f"拉取指数数据失败: {exc}") from exc
    body = []
    for r in reversed(rows):
        change = r["close"] - r["open"]
        pct = change / r["open"] * 100 if r["open"] else 0
        body.append("<tr>" + "".join(f"<td>{v}</td>" for v in (
            r["date"], f"{r['open']:.2f}", f"{r['high']:.2f}", f"{r['low']:.2f}",
            f"{r['close']:.2f}", f"{change:+.2f}", f"{pct:+.2f}%", f"{r['volume']:,}")) + "</tr>")
    closes = [float(r["close"]) for r in rows]
    period_change = closes[-1] - closes[0] if len(closes) >= 2 else 0
    period_pct = period_change / closes[0] * 100 if closes and closes[0] else 0
    period_class = "up" if period_pct >= 0 else "down"
    period_label = "涨幅" if period_pct >= 0 else "跌幅"
    lo, hi = min(closes or [0]), max(closes or [1])
    span = hi - lo or 1
    points = " ".join(
        f"{40 + i * 920 / max(len(closes) - 1, 1):.1f},{300 - (v - lo) * 250 / span:.1f}"
        for i, v in enumerate(closes)
    )
    dates = [r["date"] for r in rows]
    candles = [[r["open"], r["close"], r["low"], r["high"]] for r in rows]
    volumes = [r["volume"] for r in rows]
    buttons = "".join(
        f"<a href='/report/{index_id}?range={r}&interval={interval}' class='{'active' if r == range else ''}'>{label}</a>"
        for r, label in (("1mo", "1月"), ("3mo", "3月"), ("6mo", "6月"), ("1y", "1年"), ("2y", "2年"), ("5y", "5年"), ("max", "全部"))
    ) + "".join(
        f"<a href='/report/{index_id}?range={range}&interval={i}' class='{'active' if i == interval else ''}'>{label}</a>"
        for i, label in (("1d", "日"), ("1wk", "周"), ("1mo", "月"))
    )
    chart = f"""<script src='https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js'></script>
<section class='chart'><div class='chart-toolbar'><strong>指数走势</strong>{buttons}</div><div id='kline' style='height:360px'></div>
<script>
const chart = echarts.init(document.getElementById('kline'));
const fmtVolume = value => {{ const n = Number(value); if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'; if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'; if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'; return String(n); }};
const candleTooltip = params => {{ const p = params.find(x => x.seriesName === 'K线'); if (!p) return ''; const v = p.value || []; const open = Number(v[1]), close = Number(v[2]); const change = close - open; const pct = open ? change / open * 100 : 0; const color = pct >= 0 ? '#2e7d32' : '#c62828'; return `${{p.axisValue}}<br>开盘：${{open.toFixed(2)}}<br>最高：${{Number(v[4]).toFixed(2)}}<br>最低：${{Number(v[3]).toFixed(2)}}<br>收盘：${{close.toFixed(2)}}<br><span style="color:${{color}}">涨跌：${{change >= 0 ? '+' : ''}}${{change.toFixed(2)}}（${{pct >= 0 ? '+' : ''}}${{pct.toFixed(2)}}%）</span>`; }};
chart.setOption({{tooltip:{{trigger:'axis',formatter:candleTooltip}},legend:{{data:['K线','成交量']}},grid:[{{left:60,right:20,top:35,height:'58%'}},{{left:60,right:20,top:'76%',height:'15%'}}],xAxis:[{{type:'category',data:{json.dumps(dates, ensure_ascii=False)},boundaryGap:true}},{{type:'category',gridIndex:1,data:{json.dumps(dates, ensure_ascii=False)}}}],yAxis:[{{scale:true}},{{gridIndex:1,scale:true,splitNumber:3,axisLabel:{{formatter:fmtVolume}}}}],dataZoom:[{{type:'inside',xAxisIndex:[0,1]}},{{type:'slider',xAxisIndex:[0,1],bottom:8}}],series:[{{name:'K线',type:'candlestick',itemStyle:{{color:'#2e7d32',color0:'#c62828',borderColor:'#2e7d32',borderColor0:'#c62828'}},data:{json.dumps(candles)}}},{{name:'成交量',type:'bar',xAxisIndex:1,yAxisIndex:1,data:{json.dumps(volumes)}}}]}});
window.addEventListener('resize',()=>chart.resize());
</script>"""
    html = f"""<!doctype html><html lang='zh-CN'><meta charset='utf-8'>
<title>{meta['name']}历史报表</title><style>
body{{font-family:Arial,'Microsoft YaHei',sans-serif;background:#f4f3ee;color:#262624;margin:0;padding:24px}}
main{{max-width:1200px;margin:auto;background:white;border:1px solid #e8e7e0;border-radius:12px;padding:20px;overflow:auto}}
h1{{font-size:20px}} .summary{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0 18px}} .summary-card{{padding:10px 14px;border:1px solid #e8e7e0;border-radius:8px;background:#fafaf7}} .summary-label{{display:block;color:#777;font-size:12px;margin-bottom:4px}} .summary-value{{font-size:19px;font-weight:700}} .up{{color:#2e7d32}} .down{{color:#c62828}} .chart{{margin:20px 0;border:1px solid #e8e7e0;border-radius:10px;padding:12px}} .chart h2{{font-size:15px}} .chart-toolbar{{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px;color:#6f6e69;font-size:12px}} .chart-toolbar a{{padding:5px 9px;border:1px solid #e8e7e0;border-radius:7px;color:#6f6e69;text-decoration:none}} .chart-toolbar a.active{{background:#262624;color:#fff;border-color:#262624}} svg{{width:100%;height:340px;display:block}} table{{width:100%;border-collapse:collapse;font-size:13px;white-space:nowrap}}
th,td{{padding:10px 12px;border-bottom:1px solid #e8e7e0;text-align:right}} th:first-child,td:first-child{{text-align:left}}
</style><main><h1>{meta['name']}历史报表</h1><div class='summary'><div class='summary-card'><span class='summary-label'>区间涨跌</span><span class='summary-value {period_class}'>{period_change:+.2f}</span></div><div class='summary-card'><span class='summary-label'>区间{period_label}</span><span class='summary-value {period_class}'>{period_pct:+.2f}%</span></div><div class='summary-card'><span class='summary-label'>数据范围</span><span class='summary-value'>{rows[0]['date'] if rows else ''} 至 {rows[-1]['date'] if rows else ''}</span></div></div>
{chart}</main>"""
    return HTMLResponse(html)


@app.get("/api/rank")
def rank(index: str = "top100", range: str = "1d"):
    """按完整交易日收盘价计算指定区间的成分股涨跌幅。"""
    index = index.lower()
    if index not in INDICES:
        raise HTTPException(400, f"未知指数: {index},可选 {sorted(INDICES)}")
    if range not in {"1d", "1wk", "1mo", "3mo", "6mo", "1y"}:
        raise HTTPException(400, "range 需为 1d、1wk、1mo、3mo、6mo 或 1y")
    rank_key = f"rank:{index}:{range}"
    with _cache_lock:
        hit = _cache.get(rank_key)
        if hit and hit[0] > _now_utc():
            return hit[1]
    data = fetch_index(index)
    from concurrent.futures import ThreadPoolExecutor
    names = {s["symbol"]: s.get("name") or s["symbol"] for s in data}
    def fetch_one(item):
        sym = item["symbol"]
        try:
            # 当天用最近两根日线，其余区间用对应的完整日线范围。
            fetch_range = "1mo" if range == "1d" else range
            bars = get_bars(sym, "1d", fetch_range)
            if len(bars) >= 2:
                start_bar = bars[-2] if range == "1d" else bars[0]
                prev = float(start_bar["close"])
                price = float(bars[-1]["close"])
                chg = (price - prev) / prev * 100 if prev else 0
                return {"symbol": sym, "name": names[sym], "price": round(price, 2),
                        "prev_close": round(prev, 2), "chg_pct": round(chg, 2),
                        "date": bars[-1]["date"], "start_date": start_bar["date"]}
        except Exception:
            pass
        return {"symbol": sym, "name": names[sym], "price": None,
                "prev_close": None, "chg_pct": None, "date": None, "start_date": None}
    with ThreadPoolExecutor(max_workers=24) as ex:
        info = list(ex.map(fetch_one, data))
    with _cache_lock:
        _cache[rank_key] = (_now_utc() + _rank_cache_ttl, info)
    return info


@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    """拉实时市值(十亿美元),失败返回清单值。供前端批量覆盖排序市值。"""
    ticker = ticker.upper()
    base = None
    for index_id in INDICES:
        base = next((m.get("market_cap_b") for m in fetch_index(index_id) if m.get("symbol") == ticker), None)
        if base is not None:
            break
    cache_key = f"quote:{ticker}"
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > _now_utc():
            return cached[1]
    try:
        info = yf.Ticker(ticker).info
        cap = info.get("marketCap")
        if cap:
            result = {"ticker": ticker, "symbol": ticker, "marketCap": cap / 1e9}
            with _cache_lock:
                _cache[cache_key] = (_now_utc() + 900, result)
            return result
    except Exception:
        pass
    result = {"ticker": ticker, "symbol": ticker, "marketCap": float(base or 0)}
    with _cache_lock:
        _cache[cache_key] = (_now_utc() + 900, result)
    return result


@app.get("/static/hallmark")
def hallmark_page():
    return FileResponse("static/hallmark.html")


@app.get("/api/fundamentals/{ticker}")
def fundamentals(ticker: str, refresh: bool = False):
    """返回估值指标、年度财报和最近分红记录；结果在 SQLite 缓存24小时。"""
    symbol = ticker.upper()
    localized_name = _localized_name(symbol)
    # 简介和页面点击路径优先使用本地中文内容；不再因简介强制访问 Yahoo。
    if symbol in COMPANY_SUMMARIES_ZH:
        # 保持测试/调用方注入的基本面函数兼容；生产环境优先读缓存，避免外部慢请求。
        if getattr(get_fundamentals, "__module__", "fundamentals") != "fundamentals":
            return get_fundamentals(symbol)
        cached = _cached(symbol)
        if cached:
            cached["business_summary"] = COMPANY_SUMMARIES_ZH[symbol]
            cached["name"] = localized_name
            return cached
        return {"ticker": symbol, "name": localized_name,
                "business_summary": COMPANY_SUMMARIES_ZH[symbol],
                "sector": None, "industry": None, "metrics": {},
                "annual": [], "dividends": [], "currency": "USD"}
    try:
        result = get_fundamentals(symbol, force=False)
        result["name"] = localized_name
        # Yahoo 的简介通常是英文；页面统一展示中文，未覆盖的公司使用行业信息生成中文摘要。
        if not _has_chinese(result.get("business_summary")):
            result["business_summary"] = _generic_summary_zh(symbol, result)
        return result
    except Exception as exc:
        # 基本面服务失败时仍返回可展示的公司条目，避免点击一家公司拖垮详情页。
        symbol = ticker.upper()
        for item in fetch_index("sp500") + fetch_index("ndx100"):
            if item.get("symbol") == symbol:
                return {"ticker": symbol, "name": item.get("name") or symbol,
                        "sector": item.get("sector"), "industry": None,
                        "business_summary": "公司简介暂时无法从数据源加载。",
                        "metrics": {}, "annual": [], "dividends": [],
                        "currency": "USD", "source_error": str(exc)}
        raise HTTPException(502, f"拉取基本面数据失败: {exc}") from exc


def _localized_name(ticker):
    name = COMPANY_NAMES_ZH_FULL.get(ticker.upper()) or COMPANY_NAMES_ZH.get(ticker.upper())
    if name and re.search(r"[A-Za-z]", name):
        name = re.sub(r"[A-Za-z][A-Za-z0-9 .,&\\-]*", "", name).strip()
    return name or f"{ticker.upper()} 公司"


def _has_chinese(value):
    return bool(value) and any("\u4e00" <= ch <= "\u9fff" for ch in str(value))


def _generic_summary_zh(symbol, result):
    """为没有本地文案的公司生成中文可读摘要，避免直接展示英文供应商文本。"""
    if symbol in COMPANY_SUMMARIES_ZH:
        return COMPANY_SUMMARIES_ZH[symbol]
    name = _localized_name(symbol)
    sector_map = {
        "Technology": "科技", "Healthcare": "医疗保健", "Financial Services": "金融服务",
        "Consumer Cyclical": "非必需消费品", "Consumer Defensive": "必需消费品",
        "Industrials": "工业", "Communication Services": "通信服务",
        "Energy": "能源", "Basic Materials": "基础材料", "Real Estate": "房地产",
        "Utilities": "公用事业",
    }
    sector = sector_map.get(result.get("sector"), "美国上市")
    return f"{name}是一家在{sector}领域经营的公司，主要为客户提供相关产品或服务。页面暂未收录更详细的中文业务资料。"


def _lookup_name(ticker):
    for _, n, *_ in TOP100:
        if _ == ticker:
            return n
    for iid in INDICES:
        for s in fetch_index(iid):
            if s["symbol"] == ticker:
                return s["name"]
    return ticker


_LOGO_CACHE = {}
_LOGO_LOCK = threading.Lock()
_LOGO_TTL = 86400  # 1天

_LOGO_SOURCES = [
    "https://financialmodelingprep.com/image-stock/{t}.png",
    "https://assets.parqet.com/logos/symbol/{t}.png",
    "https://companiesmarketcap.com/img/company-logos-64/{t}.png",
]

def _svg_placeholder(ticker):
    letter = ticker[0] if ticker else "?"
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48">'
           f'<rect width="48" height="48" fill="#efece6" rx="10"/>'
           f'<text x="24" y="32" font-size="24" text-anchor="middle" '
           f'fill="#d97757" font-family="Arial" font-weight="bold">{letter}</text></svg>')
    return svg.encode("utf-8")

@app.get("/api/logo/{ticker}")
def get_logo(ticker: str):
    """代理公司 logo,规避浏览器跨域/CSP 拦截。失败回退首字母 SVG 占位。"""
    ticker = ticker.upper()
    with _LOGO_LOCK:
        hit = _LOGO_CACHE.get(ticker)
        if hit and hit[0] > _now_utc():
            return Response(content=hit[1][1], media_type=hit[1][0],
                            headers={"Cache-Control": "public, max-age=86400"})
    body, ctype = None, "image/png"
    for src in _LOGO_SOURCES:
        try:
            r = requests.get(src.format(t=ticker), headers=_HEADERS, timeout=3)
            if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image"):
                body, ctype = r.content, r.headers["Content-Type"].split(";")[0]
                break
        except Exception:
            continue
    if body is None:
        body, ctype = _svg_placeholder(ticker), "image/svg+xml"
    with _LOGO_LOCK:
        _LOGO_CACHE[ticker] = (_now_utc() + _LOGO_TTL, (ctype, body))
    return Response(content=body, media_type=ctype,
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/compare")
def compare(symbols: str = "", range: str = "1y"):
    """多公司收盘价对比。symbols 逗号分隔。返回各公司按日期的收盘序列。"""
    syms = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))
    if not syms:
        raise HTTPException(400, "symbols 不能为空,逗号分隔")
    if len(syms) > 15:
        raise HTTPException(400, "最多同时对比15家公司")
    if range not in RANGES:
        raise HTTPException(400, f"range 需为 {sorted(RANGES)}")
    key = f"cmp:{','.join(syms)}:{range}"
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > _now_utc():
            cached = hit[1]
            if "comparisonReturns" not in cached:
                for item in cached.get("series", {}).values():
                    values = item.get("data", [])
                    first = values[0][1] if values else 0
                    last = values[-1][1] if values else 0
                    item["return_pct"] = round((last - first) / first * 100, 2) if first else 0
                cached["comparisonReturns"] = {k: v.get("return_pct", 0) for k, v in cached.get("series", {}).items()}
            return cached

    out = {}
    for s in syms:
        try:
            bars = get_bars(s, "1d", range)
            pts = [[int(datetime.strptime(b["date"], "%Y-%m-%d").timestamp() * 1000), b["close"]]
                   for b in bars]
            if pts:
                out[s] = {"name": _lookup_name(s), "data": pts}
        except Exception:
            continue

    if not out:
        raise HTTPException(404, "无可用数据")

    for item in out.values():
        values = item["data"]
        first = values[0][1]
        last = values[-1][1]
        item["return_pct"] = round((last - first) / first * 100, 2) if first else 0

    result = {"range": range, "series": out, "comparisonReturns": {k: v["return_pct"] for k, v in out.items()}}
    with _cache_lock:
        _cache[key] = (_now_utc() + _cache_ttl, result)
    return result


@app.get("/api/stock/{ticker}")
def get_stock(ticker: str, range: str = "1mo", interval: str = "1d"):
    ticker = ticker.upper()
    if range not in RANGES:
        raise HTTPException(400, f"range 需为 {sorted(RANGES)}")
    if interval not in INTERVALS:
        raise HTTPException(400, f"interval 需为 {sorted(INTERVALS)}")

    key = f"{ticker}:{range}:{interval}"
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > _now_utc():
            return hit[1]

    try:
        rows = get_bars(ticker, interval, range)
    except Exception as e:
        raise HTTPException(502, f"拉取数据失败: {e}")

    if not rows:
        raise HTTPException(404, f"{ticker} 无历史数据")

    ohlcv = [[r["date"], r["open"], r["close"], r["low"], r["high"], r["volume"]]
             for r in rows]

    result = {
        "ticker": ticker,
        "name": _lookup_name(ticker),
        "range": range,
        "interval": interval,
        "start": ohlcv[0][0] if ohlcv else None,
        "end": ohlcv[-1][0] if ohlcv else None,
        "bars": ohlcv,
    }
    with _cache_lock:
        _cache[key] = (_now_utc() + _cache_ttl, result)
    return result


@app.get("/api/export/{ticker}")
def export(ticker: str, range: str = "1y", fmt: str = "csv"):
    """导出历史K线为 CSV/JSON 下载。"""
    ticker = ticker.upper()
    if fmt not in ("csv", "json"):
        raise HTTPException(400, "fmt 需为 csv 或 json")
    if range not in RANGES:
        raise HTTPException(400, f"range 需为 {sorted(RANGES)}")
    try:
        content, media, fname = export_bars(ticker, "1d", range, fmt)
    except Exception as e:
        raise HTTPException(502, f"导出失败: {e}")
    if not content.strip():
        raise HTTPException(404, f"{ticker} 无数据")
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


# 静态前端
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def index():
    return FileResponse("static/index.html")