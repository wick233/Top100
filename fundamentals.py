"""公司基本面、年度财报与分红数据。
数据源为 yfinance；结果写入 SQLite fundamentals_cache，24 小时内复用。
"""
import json
import math
import time

import yfinance as yf

from store import _get_conn, _db_lock

FUNDAMENTALS_TTL = 24 * 3600


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _statement_value(frame, row_name, column):
    if (frame is None or frame.empty or row_name not in frame.index
            or column not in frame.columns):
        return None
    return _finite(frame.loc[row_name, column])


def _ensure_table():
    with _db_lock:
        conn = _get_conn()
        conn.execute(
            "CREATE TABLE IF NOT EXISTS fundamentals_cache("
            "ticker TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL)"
        )
        conn.commit()


def _cached(ticker):
    _ensure_table()
    with _db_lock:
        row = _get_conn().execute(
            "SELECT payload, updated_at FROM fundamentals_cache WHERE ticker=?", (ticker,)
        ).fetchone()
    if row and time.time() - row[1] < FUNDAMENTALS_TTL:
        return json.loads(row[0])
    return None


def _save(ticker, payload):
    _ensure_table()
    with _db_lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO fundamentals_cache(ticker,payload,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (ticker, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        conn.commit()


def get_fundamentals(ticker, force=False):
    ticker = ticker.upper()
    if not force:
        hit = _cached(ticker)
        if hit:
            return hit

    stock = yf.Ticker(ticker)
    info = stock.info or {}
    income = stock.income_stmt
    balance = stock.balance_sheet
    cashflow = stock.cashflow

    columns = []
    for frame in (income, balance, cashflow):
        if frame is not None and not frame.empty:
            columns.extend(frame.columns.tolist())
    columns = sorted(set(columns), reverse=True)[:5]

    annual = []
    for col in columns:
        date_text = col.strftime("%Y-%m-%d") if callable(getattr(col, "strftime", None)) else str(col)[:10]
        annual.append({
            "date": date_text,
            "revenue": _statement_value(income, "Total Revenue", col),
            "net_income": _statement_value(income, "Net Income", col),
            "ebitda": _statement_value(income, "EBITDA", col),
            "free_cash_flow": _statement_value(cashflow, "Free Cash Flow", col),
            "operating_cash_flow": _statement_value(cashflow, "Operating Cash Flow", col),
            "total_assets": _statement_value(balance, "Total Assets", col),
            "total_debt": _statement_value(balance, "Total Debt", col),
            "stockholders_equity": _statement_value(balance, "Stockholders Equity", col),
        })

    dividends = []
    try:
        for date, amount in stock.dividends.tail(40).items():
            value = _finite(amount)
            if value is not None:
                dividends.append({"date": date.strftime("%Y-%m-%d"), "amount": value})
    except Exception:
        pass

    yield_value = _finite(info.get("dividendYield"))
    # yfinance may expose 0.33 for 0.33%, not 33%; preserve the provider's percentage convention.
    payout_ratio = _finite(info.get("payoutRatio"))
    payload = {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency") or "USD",
        "metrics": {
            "market_cap": _finite(info.get("marketCap")),
            "trailing_pe": _finite(info.get("trailingPE")),
            "forward_pe": _finite(info.get("forwardPE")),
            "price_to_book": _finite(info.get("priceToBook")),
            "trailing_eps": _finite(info.get("trailingEps")),
            "forward_eps": _finite(info.get("forwardEps")),
            "dividend_yield_pct": yield_value,
            "dividend_rate": _finite(info.get("dividendRate")),
            "payout_ratio_pct": payout_ratio * 100 if payout_ratio is not None else None,
            "beta": _finite(info.get("beta")),
            "fifty_two_week_high": _finite(info.get("fiftyTwoWeekHigh")),
            "fifty_two_week_low": _finite(info.get("fiftyTwoWeekLow")),
        },
        "annual": annual,
        "dividends": dividends,
        "updated_at": int(time.time()),
    }
    _save(ticker, payload)
    return payload
