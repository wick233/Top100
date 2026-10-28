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
from fundamentals import get_fundamentals

app = FastAPI(title="美股 历史行情报表")

RANGES = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
INTERVALS = {"1d": "1d", "1wk": "1wk", "1mo": "1mo"}
INDEX_HISTORY = {
    "sp500": {"ticker": "^GSPC", "name": "标普500指数"},
    "ndx100": {"ticker": "^NDX", "name": "纳指100指数"},
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
def rank(index: str = "top100"):
    """返回指定指数成分股按当日涨跌幅排序的排行，缓存60秒。"""
    index = index.lower()
    if index not in INDICES:
        raise HTTPException(400, f"未知指数: {index},可选 {sorted(INDICES)}")
    rank_key = f"rank:{index}"
    with _cache_lock:
        hit = _cache.get(rank_key)
        if hit and hit[0] > _now_utc():
            return hit[1]
    data = fetch_index(index)
    from concurrent.futures import ThreadPoolExecutor
    def fetch_one(sym):
        try:
            fi = yf.Ticker(sym).fast_info
            prev = fi["previous_close"]
            price = fi["last_price"]
            if prev:
                chg = (price - prev) / prev * 100
                return {"symbol": sym, "price": round(price, 2),
                        "prev_close": round(prev, 2), "chg_pct": round(chg, 2)}
        except Exception:
            pass
        return {"symbol": sym, "price": None, "prev_close": None, "chg_pct": None}
    with ThreadPoolExecutor(max_workers=24) as ex:
        info = list(ex.map(fetch_one, [s["symbol"] for s in data]))
    with _cache_lock:
        _cache[rank_key] = (_now_utc() + _rank_cache_ttl, info)
    return info


@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    """拉实时市值(十亿美元),失败返回清单值。供前端批量覆盖排序市值。"""
    ticker = ticker.upper()
    base = next((m for t, _, m, _ in TOP100 if t == ticker), None)
    if base is None:
        raise HTTPException(404, f"未知代码: {ticker}")
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
    result = {"ticker": ticker, "symbol": ticker, "marketCap": float(base)}
    with _cache_lock:
        _cache[cache_key] = (_now_utc() + 900, result)
    return result


@app.get("/static/hallmark")
def hallmark_page():
    return FileResponse("static/hallmark.html")


@app.get("/api/fundamentals/{ticker}")
def fundamentals(ticker: str, refresh: bool = False):
    """返回估值指标、年度财报和最近分红记录；结果在 SQLite 缓存24小时。"""
    try:
        symbol = ticker.upper()
        return get_fundamentals(symbol, force=True) if refresh else get_fundamentals(symbol)
    except Exception as exc:
        raise HTTPException(502, f"拉取基本面数据失败: {exc}") from exc


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