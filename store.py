"""SQLite 历史K线数据落盘存储。
表 bars: (ticker, interval, date, open, high, low, close, volume)
表 meta:  (ticker, interval, updated_at)  最近一次抓取时间
接口: get_bars 优先读库,过期才抓 Yahoo 并写库; export_bars 导出 CSV/JSON。
"""
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import yfinance as yf

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market.db")
FRESH_SECONDS = 6 * 3600  # 库里数据 6 小时内视为新鲜

_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS bars("
            "ticker TEXT, interval TEXT, date TEXT, "
            "open REAL, high REAL, low REAL, close REAL, volume INTEGER, "
            "PRIMARY KEY(ticker, interval, date))")
        _conn.execute(
            "CREATE TABLE IF NOT EXISTS meta("
            "ticker TEXT, interval TEXT, updated_at REAL, "
            "PRIMARY KEY(ticker, interval))")
        _conn.commit()
    return _conn


def _is_fresh(ticker, interval):
    conn = _get_conn()
    row = conn.execute(
        "SELECT updated_at FROM meta WHERE ticker=? AND interval=?",
        (ticker, interval)).fetchone()
    return bool(row and row[0] and (time.time() - row[0] < FRESH_SECONDS))


def _mark_fresh(ticker, interval):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO meta(ticker, interval, updated_at) VALUES(?,?,?) "
        "ON CONFLICT(ticker, interval) DO UPDATE SET updated_at=excluded.updated_at",
        (ticker, interval, time.time()))
    conn.commit()


def _load_rows(ticker, interval, start=None, end=None):
    conn = _get_conn()
    sql = "SELECT date, open, high, low, close, volume FROM bars WHERE ticker=? AND interval=?"
    args = [ticker, interval]
    if start:
        sql += " AND date>=?"; args.append(start)
    if end:
        sql += " AND date<=?"; args.append(end)
    sql += " ORDER BY date"
    return conn.execute(sql, args).fetchall()


def _save_rows(ticker, interval, rows):
    """rows: list of (date, open, high, low, close, volume)"""
    if not rows:
        return
    conn = _get_conn()
    conn.executemany(
        "INSERT OR REPLACE INTO bars(ticker, interval, date, open, high, low, close, volume) "
        "VALUES(?,?,?,?,?,?,?,?)",
        [(ticker, interval, r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows])
    conn.commit()


def _fetch_yahoo(ticker, interval, period):
    """从 yahoo 拉取并返回标准行 list。"""
    df = yf.Ticker(ticker).history(period=period, interval=interval,
                                   auto_adjust=False, raise_errors=True)
    if df is None or df.empty:
        return []
    rows = []
    for ts in df.index:
        row = df.loc[ts]
        o, h, l, c = (float(row["Open"]), float(row["High"]),
                      float(row["Low"]), float(row["Close"]))
        if any(v != v or v in (float("inf"), float("-inf")) for v in (o, h, l, c)):
            continue
        rows.append(("%04d-%02d-%02d" % (ts.year, ts.month, ts.day),
                     round(o, 2), round(c, 2), round(l, 2), round(h, 2),
                     int(row["Volume"])))
    return rows


# range → 需要回溯多少天，用于判断库里数据是否覆盖到该周期
_RANGE_DAYS = {
    "1mo": 31, "3mo": 95, "6mo": 185, "1y": 370,
    "2y": 740, "5y": 1850, "max": 3650,
}


def _cover_start(period):
    days = _RANGE_DAYS.get(period, 95)
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")


def _has_coverage(ticker, interval, cover_start):
    conn = _get_conn()
    row = conn.execute(
        "SELECT MIN(date), MAX(date) FROM bars WHERE ticker=? AND interval=?",
        (ticker, interval)).fetchone()
    if not row or row[0] is None or row[1] is None:
        return False
    # 库里最早日期不早于所需回溯起点，且接近当前 → 认为覆盖该周期
    return row[0] <= cover_start


def get_bars(ticker, interval, period, start=None, end=None):
    """返回 [{date, open, close, low, high, volume}, ...] 升序。
    优先读库；库数据不覆盖所请求的 period 才重新抓取补齐。"""
    # 缓存(DB)是否覆盖到该周期：是则直接切片返回，否才抓取
    if _has_coverage(ticker, interval, _cover_start(period)):
        rows = _load_rows(ticker, interval, start, end)
        if rows:
            return _rows_to_dicts(rows)
    # 抓取该周期数据并入库（INSERT OR REPLACE，会补全历史）
    new_rows = _fetch_yahoo(ticker, interval, period)
    if new_rows:
        _save_rows(ticker, interval, new_rows)
    # 无论抓取成功与否,都从库读(抓取失败则返回库里已有历史)
    return _rows_to_dicts(_load_rows(ticker, interval, start, end))


def _rows_to_dicts(rows):
    return [{"date": r[0], "open": r[1], "close": r[2], "low": r[3], "high": r[4], "volume": r[5]}
            for r in rows]


def export_bars(ticker, interval, period, fmt="csv"):
    """导出为 CSV 或 JSON 文本。"""
    rows = get_bars(ticker, interval, period)
    header = "date,open,high,low,close,volume"
    if fmt == "json":
        import json
        return json.dumps(rows, ensure_ascii=False), "application/json", f"{ticker}.json"
    lines = [header]
    for r in rows:
        lines.append(f"{r['date']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}")
    return "\n".join(lines) + "\n", "text/csv", f"{ticker}.csv"