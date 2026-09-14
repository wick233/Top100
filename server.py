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
from datetime import datetime

import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from top100 import TOP100
from indices import fetch_index, INDICES, _HEADERS
from store import get_bars, export_bars

app = FastAPI(title="美股 历史行情报表")

RANGES = {"1mo", "3mo", "6mo", "1y", "2y", "5y", "max"}
INTERVALS = {"1d": "1d", "1wk": "1wk", "1mo": "1mo"}

_cache = {}          # key -> (expire_ts, data)
_cache_lock = threading.Lock()
_cache_ttl = 300     # 秒

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


@app.get("/api/rank")
def rank(index: str = "top100"):
    """返回指定指数成分股按当日涨跌幅排序的排行。并发拉取 fast_info。"""
    index = index.lower()
    if index not in INDICES:
        raise HTTPException(400, f"未知指数: {index},可选 {sorted(INDICES)}")
    data = fetch_index(index)
    # 并发拉取 fast_info (当日价+涨跌幅)
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
    with ThreadPoolExecutor(max_workers=12) as ex:
        info = list(ex.map(fetch_one, [s["symbol"] for s in data]))
    return info
    return data


@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    """拉实时市值(十亿美元),失败返回清单值。供前端批量覆盖排序市值。"""
    ticker = ticker.upper()
    base = next((m for t, _, m, _ in TOP100 if t == ticker), None)
    if base is None:
        raise HTTPException(404, f"未知代码: {ticker}")
    try:
        info = yf.Ticker(ticker).info
        cap = info.get("marketCap")
        if cap:
            return {"ticker": ticker, "symbol": ticker, "marketCap": cap / 1e9}
    except Exception:
        pass
    return {"ticker": ticker, "symbol": ticker, "marketCap": float(base)}


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
            r = requests.get(src.format(t=ticker), headers=_HEADERS, timeout=10)
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
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:15]
    if not syms:
        raise HTTPException(400, "symbols 不能为空,逗号分隔")
    if range not in RANGES:
        raise HTTPException(400, f"range 需为 {sorted(RANGES)}")

    key = f"cmp:{','.join(syms)}:{range}"
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > _now_utc():
            return hit[1]

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

    result = {"range": range, "series": out}
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