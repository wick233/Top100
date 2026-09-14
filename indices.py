"""指数成分股清单抓取与缓存
数据源: slickcharts.com (S&P500 / Nasdaq100 成分股)
带 6 小时内存缓存; 抓取失败时回退内置静态快照,保证离线可用。
"""
import threading
import time
import re

import requests
from bs4 import BeautifulSoup

# ---------- 内置静态回退清单 ----------
FALLBACK = {
    "sp500": [
        (1, "NVDA", "Nvidia"), (2, "AAPL", "Apple"), (3, "MSFT", "Microsoft"),
        (4, "AMZN", "Amazon"), (5, "META", "Meta Platforms"), (6, "AVGO", "Broadcom"),
        (7, "GOOGL", "Alphabet"), (8, "GOOG", "Alphabet Class C"), (9, "TSLA", "Tesla"),
        (10, "LLY", "Eli Lilly"), (11, "BRK-B", "Berkshire Hathaway"), (12, "JPM", "JPMorgan Chase"),
        (13, "WMT", "Walmart"), (14, "V", "Visa"), (15, "XOM", "Exxon Mobil"),
        (16, "MA", "Mastercard"), (17, "COST", "Costco"), (18, "UNH", "UnitedHealth"),
        (19, "ORCL", "Oracle"), (20, "PG", "Procter & Gamble"), (21, "HD", "Home Depot"),
        (22, "NFLX", "Netflix"), (23, "JNJ", "Johnson & Johnson"), (24, "BAC", "Bank of America"),
        (25, "CRM", "Salesforce"), (26, "ABBV", "AbbVie"), (27, "KO", "Coca-Cola"),
        (28, "AMD", "Advanced Micro Devices"), (29, "TMO", "Thermo Fisher"), (30, "PEP", "PepsiCo"),
    ],
    "ndx100": [
        (1, "NVDA", "Nvidia"), (2, "AAPL", "Apple"), (3, "MSFT", "Microsoft"),
        (4, "AMZN", "Amazon"), (5, "META", "Meta Platforms"), (6, "AVGO", "Broadcom"),
        (7, "GOOGL", "Alphabet"), (8, "TSLA", "Tesla"), (9, "GOOG", "Alphabet Class C"),
        (10, "COST", "Costco"), (11, "NFLX", "Netflix"), (12, "AMD", "Advanced Micro Devices"),
        (13, "TMUS", "T-Mobile"), (14, "CSCO", "Cisco"), (15, "LIN", "Linde"),
        (16, "PEP", "PepsiCo"), (17, "QCOM", "Qualcomm"), (18, "INTU", "Intuit"),
        (19, "ADBE", "Adobe"), (20, "ISRG", "Intuitive Surgical"), (21, "AMGN", "Amgen"),
        (22, "TXN", "Texas Instruments"), (23, "BKNG", "Booking"), (24, "SBUX", "Starbucks"),
        (25, "MU", "Micron"), (26, "ADI", "Analog Devices"), (27, "INTC", "Intel"),
        (28, "LRCX", "Lam Research"), (29, "MDLZ", "Mondelez"), (30, "PANW", "Palo Alto Networks"),
    ],
}

INDICES = {
    "top100": {"name": "市值 Top100", "desc": "美股市值最大的100家公司"},
    "sp500":  {"name": "标普500", "desc": "S&P 500 指数成分股"},
    "ndx100": {"name": "纳指100", "desc": "Nasdaq-100 指数成分股"},
}

_SCRAPE_URLS = {
    "sp500": "https://www.slickcharts.com/sp500",
    "ndx100": "https://www.slickcharts.com/nasdaq100",
}

_cache = {}
_lock = threading.Lock()
_TTL = 6 * 3600  # 6 小时

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def _parse_pct(s):
    try:
        return float(re.sub(r"[^0-9.\-]", "", s))
    except ValueError:
        return 0.0


def fetch_index(index_id, force=False):
    """返回 [{rank,symbol,ticker,name,weight_pct,...}, ...]; 失败回退内置清单。
    symbol 与 ticker 双字段输出,兼容新旧前端。"""
    if index_id == "top100":
        from top100 import TOP100
        return [{"rank": i + 1, "symbol": t, "ticker": t, "name": n,
                 "weight_pct": None, "market_cap_b": float(m), "sector": s}
                for i, (t, n, m, s) in enumerate(TOP100)]

    now = time.time()
    with _lock:
        hit = _cache.get(index_id)
        if hit and not force and hit[0] > now:
            return hit[1]

    data = None
    url = _SCRAPE_URLS.get(index_id)
    try:
        r = requests.get(url, headers=_HEADERS, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            tbl = (soup.find("table", class_="table table-hover table-borderless table-sm")
                   or soup.find("table"))
            data = []
            if tbl:
                for tr in tbl.find_all("tr")[1:]:
                    tds = tr.find_all("td")
                    if len(tds) < 4:
                        continue
                    sym = tds[2].get_text(strip=True)
                    if not re.fullmatch(r"[A-Z0-9.\-]+", sym):
                        continue
                    data.append({
                        "rank": int(tds[0].get_text(strip=True) or 0),
                        "symbol": sym,
                        "ticker": sym,
                        "name": tds[1].get_text(strip=True),
                        "weight_pct": _parse_pct(tds[3].get_text(strip=True)),
                        "market_cap_b": None,
                        "sector": None,
                    })
    except Exception:
        data = None

    if not data:  # 回退内置
        data = [{"rank": r, "symbol": s, "ticker": s, "name": n,
                 "weight_pct": None, "market_cap_b": None, "sector": None}
                for r, s, n in FALLBACK.get(index_id, [])]
        data[0]["fallback"] = True

    with _lock:
        _cache[index_id] = (now + _TTL, data)
    return data