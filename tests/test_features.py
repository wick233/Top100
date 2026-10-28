import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
import store


@pytest.fixture
def client():
    return TestClient(server.app)


def test_fundamentals_endpoint_exposes_metrics_statements_and_dividends(client, monkeypatch):
    payload = {
        "ticker": "AAPL",
        "name": "Apple",
        "metrics": {"trailing_pe": 25.5, "dividend_yield_pct": 0.5},
        "annual": [{"date": "2025-09-30", "revenue": 100.0, "net_income": 20.0,
                    "free_cash_flow": 18.0, "total_assets": 200.0, "total_debt": 50.0}],
        "dividends": [{"date": "2025-08-10", "amount": 0.25}],
    }
    monkeypatch.setattr(server, "get_fundamentals", lambda ticker: payload)
    response = client.get("/api/fundamentals/AAPL")
    assert response.status_code == 200
    assert response.json() == payload


def test_compare_returns_multiple_company_series(client, monkeypatch):
    rows = [
        {"date": "2025-01-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
        {"date": "2025-01-03", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 120},
    ]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/api/compare?symbols=AAPL,MSFT&range=1y")
    assert response.status_code == 200
    body = response.json()
    assert set(body["series"]) == {"AAPL", "MSFT"}
    assert len(body["series"]["AAPL"]["data"]) == 2


def test_compare_rejects_more_than_fifteen_symbols(client):
    symbols = ",".join(f"S{i}" for i in range(16))
    response = client.get(f"/api/compare?symbols={symbols}&range=1y")
    assert response.status_code == 400


def test_index_history_endpoint_returns_selected_period(client, monkeypatch):
    rows = [
        {"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 108, "volume": 1000},
        {"date": "2025-01-03", "open": 108, "high": 115, "low": 105, "close": 112, "volume": 1200},
    ]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/api/index-history/sp500?range=1y&interval=1wk")
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "^GSPC"
    assert body["name"] == "标普500指数"
    assert body["range"] == "1y"
    assert body["interval"] == "1wk"
    assert len(body["bars"]) == 2


def test_index_history_endpoint_rejects_unknown_index(client):
    response = client.get("/api/index-history/not-an-index")
    assert response.status_code == 400


def test_index_history_endpoint_caches_same_query(client, monkeypatch):
    rows = [{"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 108, "volume": 1000}]
    calls = []

    def fake_get_bars(*args, **kwargs):
        calls.append(args)
        return rows

    monkeypatch.setattr(server, "get_bars", fake_get_bars)
    server._index_history_cache.clear()
    assert client.get("/api/index-history/sp500?range=1mo&interval=1d").status_code == 200
    assert client.get("/api/index-history/sp500?range=1mo&interval=1d").status_code == 200
    assert len(calls) == 1


def test_store_uses_local_daily_data_when_latest_is_current(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "market.db"))
    store._conn = None
    rows = [("2025-01-02", 100, 108, 95, 110, 1000)]
    monkeypatch.setattr(store, "_fetch_yahoo", lambda *args: (_ for _ in ()).throw(AssertionError("should not fetch")))
    monkeypatch.setattr(store, "_has_coverage", lambda ticker, interval, start: True)
    monkeypatch.setattr(store, "_latest_date", lambda ticker, interval: store._last_weekday())
    monkeypatch.setattr(store, "_is_fresh", lambda ticker, interval: False)
    monkeypatch.setattr(store, "_load_rows", lambda *args: rows)
    result = store.get_bars("^GSPC", "1d", "1mo")
    assert result[0]["date"] == "2025-01-02"
    store._conn = None


def test_quote_endpoint_caches_realtime_market_cap(client, monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = {"marketCap": 123_000_000_000}

    monkeypatch.setattr(server.yf, "Ticker", FakeTicker)
    server._cache.pop("quote:AAPL", None)
    first = client.get("/api/quote/AAPL")
    second = client.get("/api/quote/AAPL")
    assert first.json() == second.json()
    assert first.json()["marketCap"] == 123.0


def test_index_report_page_renders_table_without_javascript(client, monkeypatch):
    rows = [{"date": "2025-01-02", "open": 100, "high": 110, "low": 95,
             "close": 108, "volume": 1000}]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/report/sp500")
    assert response.status_code == 200
    assert "标普500指数" in response.text
    assert "2025-01-02" in response.text
    assert "<table" not in response.text
    assert "type:'candlestick'" in response.text

def test_index_report_page_renders_price_chart(client, monkeypatch):
    rows = [
        {"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 108, "volume": 1000},
        {"date": "2025-01-03", "open": 108, "high": 115, "low": 105, "close": 112, "volume": 1200},
    ]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/report/sp500")
    assert response.status_code == 200
    assert 'id=\'price-chart\'' not in response.text
    assert "<table" not in response.text
    assert "type:'candlestick'" in response.text


def test_index_report_page_matches_top100_detail_chart(client, monkeypatch):
    rows = [{"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 108, "volume": 1000}]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/report/sp500?range=1mo&interval=1d")
    assert "echarts.min.js" in response.text
    assert "type:'candlestick'" in response.text
    assert "dataZoom" in response.text
    assert "1月" in response.text and "5年" in response.text
    assert "color:'#2e7d32'" in response.text
    assert "color0:'#c62828'" in response.text


def test_index_report_range_buttons_are_real_links(client, monkeypatch):
    rows = [{"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 108, "volume": 1000}]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/report/sp500?range=1mo&interval=1d")
    assert "href='/report/sp500?range=1mo&interval=1d'" in response.text
    assert "href='/report/sp500?range=5y&interval=1d'" in response.text
    assert "href='/report/sp500?range=1mo&interval=1wk'" in response.text


def test_index_report_volume_axis_uses_compact_labels(client, monkeypatch):
    rows = [{"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 108, "volume": 5_000_000_000}]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/report/sp500")
    assert "fmtVolume" in response.text
    assert "splitNumber:3" in response.text


def test_index_report_shows_period_return_percentage(client, monkeypatch):
    rows = [
        {"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 100, "volume": 1000},
        {"date": "2025-01-03", "open": 105, "high": 115, "low": 100, "close": 110, "volume": 1200},
    ]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/report/sp500?range=1mo&interval=1d")
    assert "区间涨幅" in response.text
    assert "+10.00%" in response.text


def test_index_report_tooltip_shows_daily_return_percentage(client, monkeypatch):
    rows = [{"date": "2025-01-02", "open": 100, "high": 110, "low": 95, "close": 105, "volume": 1000}]
    monkeypatch.setattr(server, "get_bars", lambda ticker, interval, period: rows)
    response = client.get("/report/sp500")
    assert "candleTooltip" in response.text
    assert "涨跌：" in response.text
    assert "toFixed(2)" in response.text


def test_index_buttons_stay_on_single_page():
    html = Path("static/index.html").read_text()
    js = Path("static/app.js").read_text()
    assert "href=\"/\"" in html
    assert "b.addEventListener(\"click\"" in js
    assert "window.location.href = `/report/${ix.id}" not in js


def test_index_buttons_render_report_in_same_page_container():
    html = Path("static/index.html").read_text()
    assert 'id="indexInline"' in html
    assert "fetch(`/api/index-history/${id}" in html
    assert "echarts.init(document.getElementById('indexInlineChart'))" in html


def test_sqlite_range_request_is_sliced(monkeypatch, tmp_path):
    db_path = tmp_path / "market.db"
    monkeypatch.setattr(store, "DB_PATH", str(db_path))
    monkeypatch.setattr(store, "_conn", None)
    rows = [
        ("2020-01-02", 1, 1.2, 0.9, 1.1, 100),
        ("2025-08-20", 2, 2.2, 1.9, 2.1, 200),
        ("2025-09-10", 3, 3.2, 2.9, 3.1, 300),
    ]
    store._save_rows("TEST", "1d", rows)
    monkeypatch.setattr(store, "_fetch_yahoo", lambda *args, **kwargs: [])
    result = store.get_bars("TEST", "1d", "1mo", now_date="2025-09-14")
    assert [r["date"] for r in result] == ["2025-08-20", "2025-09-10"]


def test_sqlite_columns_store_true_ohlc_values(monkeypatch, tmp_path):
    db_path = tmp_path / "market.db"
    monkeypatch.setattr(store, "DB_PATH", str(db_path))
    monkeypatch.setattr(store, "_conn", None)
    store._save_rows("TEST", "1d", [("2025-09-10", 10, 11, 9, 12, 100)])
    raw = store._get_conn().execute(
        "SELECT open, high, low, close FROM bars WHERE ticker='TEST'"
    ).fetchone()
    assert raw == (10, 12, 9, 11)


def test_frontend_contains_all_indicator_modes():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    assert all(name in html for name in ["MACD", "RSI", "布林"])
    assert 'xAxisIndex: 2, yAxisIndex: 2' in js
    assert 'name: "DIF", type: "line", xAxisIndex: 2, yAxisIndex: 2' in js
    assert 'name: "DEA", type: "line", xAxisIndex: 2, yAxisIndex: 2' in js


def test_top100_kline_uses_us_market_colors():
    js = Path("static/app.js").read_text()
    assert 'color: "#2e7d32", color0: "#c62828"' in js
    assert 'borderColor: "#2e7d32", borderColor0: "#c62828"' in js


def test_frontend_supports_standalone_index_history_view():
    js = Path("static/app.js").read_text()
    assert "loadIndexHistory" in js
    assert "/api/index-history/" in js
    assert "indexHistoryView" in js


def test_frontend_has_fundamentals_mode_and_panel():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    assert 'data-mode="fundamentals"' in html
    assert 'id="fundamentals"' in html
    assert "/api/fundamentals/" in js


def test_market_cap_sort_displays_contiguous_rank():
    js = Path("static/app.js").read_text()
    assert "displayRank = sortMode === \"rank\" ? index + 1" in js
    assert "arr.forEach((s, index)" in js


def test_kline_detail_includes_selected_period_return():
    js = Path("static/app.js").read_text()
    assert "区间涨幅" in js
    assert "periodReturn" in js
    assert "d.bars[0][2]" in js
    assert "d.bars[d.bars.length - 1][2]" in js


def test_switching_from_fundamentals_resizes_chart_after_showing_container():
    js = Path("static/app.js").read_text()
    assert 'document.getElementById("chartwrap").style.display = m === "fundamentals" ? "none" : ""' in js
    assert "setTimeout(() => chart && chart.resize(), 50)" in js


def test_fundamentals_mode_supports_multi_company_comparison():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    assert "fundamentalSel" in js
    assert "loadFundamentalsCompare" in js
    assert "data-mode=\"fundamentals\"" in html


def test_sort_tabs_exit_multi_select_mode():
    js = Path("static/app.js").read_text()
    assert "enterSingleCompanyMode();" in js


def test_mobile_sort_tabs_return_to_company_list_view():
    js = Path("static/app.js").read_text()
    assert 'document.body.classList.remove("chart-open")' in js
    assert 'if (mqMobile.matches) document.body.classList.remove("chart-open")' in js


def test_list_selection_has_explicit_confirm_to_fundamentals_compare():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    assert 'id="selectionbar"' in html
    assert 'id="confirmSelection"' in html
    assert "selectionMode" in js
    assert "confirmFundamentalSelection" in js
    assert "confirm.disabled = false" in js
    assert "if (!fundamentalSel.size)" in js


def test_confirm_syncs_fundamental_selection_to_price_comparison():
    js = Path("static/app.js").read_text()
    assert "compareSel = new Set(fundamentalSel)" in js


def test_kline_button_keeps_mobile_detail_view():
    js = Path("static/app.js").read_text()
    assert "function enterKlineMode" in js
    assert 'document.body.classList.add("chart-open")' in js


def test_fundamentals_panel_has_stable_scroll_layout():
    html = Path("static/index.html").read_text()
    assert "min-height:0" in html
    assert "overflow:auto" in html
    assert "table-layout:fixed" in html


def test_multi_select_button_has_direct_mobile_handler_and_cache_bust():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    assert "selectMode.addEventListener(\"click\", toggleSelectionMode)" in js
    assert "function toggleSelectionMode" in js
    assert "app.js?v=" in html
    assert js.count("selectMode.addEventListener(\"click\", toggleSelectionMode)") == 1
    assert "selectMode.onclick = toggleSelectionMode" not in js


def test_initial_multi_select_uses_fundamental_selection_before_confirm():
    js = Path("static/app.js").read_text()
    assert "if (selectionMode) return fundamentalSel.has(symOf(s));" in js
    assert "if (mode === \"fundamentals\") loadFundamentalsCompare();" in js
    assert "else if (selectionMode) toggleFundamental(sym);" in js


def test_latest_frontend_bundle_version_is_loaded():
    html = Path("static/index.html").read_text()
    assert "app.js?v=20260919-37" in html


def test_switching_views_preserves_fundamental_multi_selection():
    js = Path("static/app.js").read_text()
    assert "if (!fundamentalSel.size && compareSel.size > 1)" in js
    assert "function enterKlineMode" in js
    kline_block = js.split("function enterKlineMode", 1)[1].split("function enterSingleCompanyMode", 1)[0]
    assert "fundamentalSel.clear();" not in kline_block


def test_compare_mode_syncs_all_confirmed_companies():
    js = Path("static/app.js").read_text()
    assert "if (fundamentalSel.size > 1) compareSel = new Set(fundamentalSel);" in js
    assert "comparisonReturns" in js


def test_fundamental_report_has_non_overlapping_responsive_table():
    html = Path("static/index.html").read_text()
    assert "overflow-wrap:break-word" in html
    assert "min-width:720px" in html
    assert ".fundamentals{display:flex" in html


def test_price_compare_uses_one_stable_chart_container():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    assert "chart.clear();" in js
    assert "setTimeout(() => chart && chart.resize(), 80)" in js
    assert ".chart{display:flex" in html
    assert "min-height:420px" in html


def test_kline_after_multi_select_preserves_all_companies():
    js = Path("static/app.js").read_text()
    block = js.split("function enterKlineMode", 1)[1].split("function enterSingleCompanyMode", 1)[0]
    assert 'setMode("kline")' in block
    assert "if (current) renderChart();" in block
    assert "compareSel.clear();" not in block


def test_kline_menu_restores_chart_after_fundamentals_detail():
    js = Path("static/app.js").read_text()
    block = js.split("function enterKlineMode", 1)[1].split("function enterSingleCompanyMode", 1)[0]
    assert 'document.getElementById("fundamentals").style.display = "none"' in block
    assert 'document.getElementById("chartwrap").style.display = ""' in block
    assert "if (current) renderChart();" in block


def test_kline_menu_opens_candlestick_not_compare_mode():
    js = Path("static/app.js").read_text()
    block = js.split("function enterKlineMode", 1)[1].split("function enterSingleCompanyMode", 1)[0]
    assert 'setMode("kline")' in block
    assert "if (current) renderChart();" in block
    assert "if (compareSel.size > 1)" in block


def test_multi_selected_kline_renders_all_selected_series():
    js = Path("static/app.js").read_text()
    block = js.split("function enterKlineMode", 1)[1].split("function enterSingleCompanyMode", 1)[0]
    assert "if (compareSel.size > 1)" in block
    assert "renderCompare();" in block
    assert "compareSel = new Set(fundamentalSel)" in block


def test_kline_entry_opens_mobile_detail_container():
    js = Path("static/app.js").read_text()
    block = js.split("function enterKlineMode", 1)[1].split("function enterSingleCompanyMode", 1)[0]
    assert 'document.body.classList.add("chart-open")' in block


def test_multi_kline_keeps_kline_mode_while_using_shared_chart():
    js = Path("static/app.js").read_text()
    block = js.split("function enterKlineMode", 1)[1].split("function enterSingleCompanyMode", 1)[0]
    assert "mode = \"kline\"" in block
    assert 'setMode("compare")' not in block
    assert "renderCompare();" in block


def test_kline_range_change_preserves_multi_company_series():
    js = Path("static/app.js").read_text()
    assert 'if (mode === "kline" && compareSel.size > 1) return renderCompare();' in js


def test_fundamentals_compare_uses_responsive_matrix():
    js = Path("static/app.js").read_text()
    html = Path("static/index.html").read_text()
    assert "comparison-shell" in js
    assert "comparison-grid" in js
    assert "comparison-company" in js
    assert "comparison-section" in js
    assert "position:sticky" in html
    assert "scroll-snap-type:x proximity" in html


def test_multi_kline_displays_period_return_for_each_company():
    js = Path("static/app.js").read_text()
    assert "seriesReturn" in js
    assert "区间涨幅" in js
    assert "comparisonReturns" in js
