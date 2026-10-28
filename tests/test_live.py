import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_live_endpoint_matrix():
    checks = {
        "/": 200,
        "/api/indices": 200,
        "/api/stocks?index=top100": 200,
        "/api/stocks?index=sp500": 200,
        "/api/stocks?index=ndx100": 200,
        "/api/stock/AAPL?range=1mo&interval=1d": 200,
        "/api/stock/AAPL?range=1y&interval=1wk": 200,
        "/api/stock/AAPL?range=1y&interval=1mo": 200,
        "/api/compare?symbols=AAPL,MSFT,NVDA&range=6mo": 200,
        "/api/fundamentals/AAPL": 200,
        "/api/export/AAPL?range=1mo&fmt=csv": 200,
        "/api/export/AAPL?range=1mo&fmt=json": 200,
        "/api/logo/AAPL": 200,
    }
    for path, expected in checks.items():
        status, _, body = get(path)
        assert status == expected, (path, status, body[:300])


def test_invalid_inputs_are_rejected():
    cases = [
        "/api/stocks?index=bad",
        "/api/stock/AAPL?range=bad",
        "/api/stock/AAPL?range=1mo&interval=5m",
        "/api/export/AAPL?range=1mo&fmt=xml",
        "/api/compare?symbols=&range=1y",
    ]
    for path in cases:
        status, _, _ = get(path)
        assert status in (400, 404), (path, status)
    too_many = ",".join(f"S{i}" for i in range(16))
    status, _, _ = get(f"/api/compare?symbols={too_many}&range=1y")
    assert status == 400


def test_live_payload_shapes_and_finite_values():
    status, _, body = get("/api/stock/AAPL?range=1mo&interval=1d")
    data = json.loads(body)
    assert status == 200 and data["bars"]
    for row in data["bars"]:
        assert len(row) == 6
        assert row[3] <= min(row[1], row[2]) <= max(row[1], row[2]) <= row[4]
    status, _, body = get("/api/compare?symbols=AAPL,MSFT&range=3mo")
    data = json.loads(body)
    assert set(data["series"]) == {"AAPL", "MSFT"}
    assert all(len(v["data"]) > 0 for v in data["series"].values())
    status, _, body = get("/api/fundamentals/AAPL")
    data = json.loads(body)
    assert status == 200
    assert {"metrics", "annual", "dividends"} <= set(data)
    assert data["annual"]


def test_frontend_static_contracts():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    required_html = ["selectionbar", "selectMode", "confirmSelection", "fundamentals", "chartwrap"]
    assert all(x in html for x in required_html)
    assert "confirmFundamentalSelection" in js
    assert "confirm.style.display = \"block\"" in js
    assert "confirm.disabled = false" in js
    assert "selectionMode = true" in js
    assert "setMode(\"fundamentals\")" in js


def test_database_integrity():
    con = sqlite3.connect("market.db")
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"bars", "meta", "fundamentals_cache"} <= tables
    row = con.execute("select date,open,high,low,close from bars where ticker='AAPL' order by date desc limit 1").fetchone()
    assert row is not None
    assert row[3] <= min(row[1], row[4]) <= max(row[1], row[4]) <= row[2]
