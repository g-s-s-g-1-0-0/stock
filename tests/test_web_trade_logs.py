from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import record_web_api_logs as logs


def test_parse_log_tasks_ignores_stock_universe_and_keeps_market_trends():
    assert logs.parse_log_tasks(["stock-universe", "market-trends"]) == {"market-trends"}
    assert logs.parse_log_tasks([
        "stock-universe",
        "valuation",
        "technical",
        "market-trends",
        "market-events",
    ]) == {"value-analysis", "technical-analysis", "market-trends"}


def test_load_watchlist_tickers_includes_all_investment_types(monkeypatch):
    monkeypatch.setattr(logs, "supabase_request", lambda path: [{
        "tickers": ["AAPL"],
        "tickers_by_type": {
            "long_term": ["MSFT", "AAPL"],
            "swing": ["NVDA"],
        },
    }])

    assert logs.load_watchlist_tickers([]) == ["AAPL", "MSFT", "NVDA"]


def test_buy_signals_append_profile_specific_trades(monkeypatch, tmp_path):
    cache_path, _ = patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(logs, "load_watchlist_tickers_by_type", lambda stocks: {
        "long_term": ["MSFT"],
        "swing": ["MSFT"],
    })

    logs.update_trade_logs(
        [{"ticker": "MSFT", "name": "Microsoft", "market": "US", "currentPrice": "$100.00", "opinion": "매수"}],
        {},
        {"MSFT": {"entrySignalCodes": "1", "현재가": "$100.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = updated["rows"]
    assert [row["investmentType"] for row in rows] == ["long_term", "swing"]
    assert all(row["status"] == "보유 중" for row in rows)
    assert rows[0]["slotId"].startswith("MSFT_long_term_1_")
    assert rows[1]["slotId"].startswith("MSFT_swing_1_")


def test_long_term_trade_does_not_auto_exit_on_target(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "MSFT_long_term_1_20260701_1",
                "investmentType": "long_term",
                "ticker": "MSFT",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.07.01",
                "buyPrice": "$100.00",
                "currentPrice": "$100.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "MSFT", "name": "Microsoft", "market": "US", "currentPrice": "$130.00", "opinion": "관망"}],
        {},
        {"MSFT": {"현재가": "$130.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert row["investmentType"] == "long_term"
    assert row["status"] == "보유 중"
    assert row["sellPrice"] == "-"


def test_strategy_3_enters_swing_only_and_exits_on_sideways_peak(monkeypatch, tmp_path):
    cache_path, _ = patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(logs, "load_watchlist_tickers_by_type", lambda stocks: {
        "long_term": ["NVDA"],
        "swing": ["NVDA"],
    })
    # Force seed path so previous-opinion continuity gate does not block first entry.
    monkeypatch.setattr(logs, "runtime_reset_requested", lambda: True)

    logs.update_trade_logs(
        [{"ticker": "NVDA", "name": "NVIDIA", "market": "US", "currentPrice": "$100.00", "opinion": "매수"}],
        {},
        {"NVDA": {"entrySignalCodes": "3", "현재가": "$100.00"}},
        {"peakTriggered": False, "regimeLabel": "정상장"},
    )
    opened = logs.load_json(cache_path, {})["rows"]
    assert len(opened) == 1
    assert opened[0]["investmentType"] == "swing"
    assert opened[0]["strategy"].startswith("3.")

    # Rewrite open trade with today's buy date/price, then hit 횡보장 고점.
    today = logs.kst_trade_date()
    public_path = logs.TRADE_LOG_PUBLIC_PATH
    public_path.write_text(logs.json.dumps({
        "rows": [{
            **opened[0],
            "buyDate": today,
            "buyPrice": "$100.00",
            "currentPrice": "$105.00",
        }]
    }), encoding="utf-8")
    logs.update_trade_logs(
        [{"ticker": "NVDA", "name": "NVIDIA", "market": "US", "currentPrice": "$105.00", "opinion": "매수"}],
        {},
        {"NVDA": {"entrySignalCodes": "3", "현재가": "$105.00", "C - Close": "$105.00", "dailyPriceDate": today}},
        {"peakTriggered": True, "regimeLabel": "횡보장 고점"},
    )
    closed = logs.load_json(cache_path, {})["rows"][0]
    assert closed["status"] == "실패 익절"
    assert "횡보장 고점" in str(closed.get("exitReason") or "")


def test_strategy_3_ignores_recovery_end_and_peak_without_sideways(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [{
            "slotId": f"NVDA_swing_3_{today.replace('.', '')}_1",
            "investmentType": "swing",
            "ticker": "NVDA",
            "strategy": "3. 정상장 볼린저 워시아웃",
            "buyDate": today,
            "buyPrice": "$100.00",
            "currentPrice": "$105.00",
            "sellDate": "보유 중",
            "sellPrice": "-",
            "returnPct": 0,
            "holdingDays": "-",
            "status": "보유 중",
        }]
    }), encoding="utf-8")
    monkeypatch.setattr(logs, "load_watchlist_tickers_by_type", lambda stocks: {
        "long_term": [],
        "swing": ["NVDA"],
    })

    logs.update_trade_logs(
        [{"ticker": "NVDA", "name": "NVIDIA", "market": "US", "currentPrice": "$105.00", "opinion": "매수"}],
        {},
        {"NVDA": {"현재가": "$105.00"}},
        {"peakTriggered": True, "regimeLabel": "정상장", "isRecoveryMarket": False},
    )
    # Peak alone must not close S3 unless own rules (TP/SL/time/횡보장 고점) fire.
    row = logs.load_json(cache_path, {})["rows"][0]
    assert row["status"] == "보유 중"


def patch_log_paths(monkeypatch, tmp_path):
    cache_path = tmp_path / "data" / "cache" / "trade-logs.json"
    public_path = tmp_path / "web" / "public" / "api" / "trade-logs.json"
    monkeypatch.setattr(logs, "TRADE_LOG_CACHE_PATH", cache_path)
    monkeypatch.setattr(logs, "TRADE_LOG_PUBLIC_PATH", public_path)
    return cache_path, public_path


def test_nasdaq_peak_liquidates_only_non_exempt_strategy_slots(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    payload = {
        "rows": [
            {
                "ticker": "NVDA",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.05.01",
                "buyPrice": "$100.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            },
            {
                "ticker": "NVDA",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.05.02",
                "buyPrice": "$95.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            },
        ],
    }
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps(payload), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "NVDA", "name": "NVIDIA", "market": "US", "currentPrice": "$110.00", "opinion": "관망"}],
        {},
        {"NVDA": {}},
        {"peakTriggered": True},
    )

    updated = logs.load_json(cache_path, {})
    rows = updated["rows"]
    assert [row["status"] for row in rows] == ["보유 중", "익절"]
    assert rows[0]["sellDate"] == "보유 중"
    assert rows[1]["sellDate"] != "보유 중"
    assert rows[1]["exitReason"] == "나스닥 고점 청산/강제매도"
    assert updated["meta"]["closedTrades"] == 1
    assert updated["meta"]["nasdaqPeakLiquidation"] is True


def test_exit_updates_stock_and_technical_opinion_to_sell(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "WULF",
                "name": "TeraWulf",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.05.23",
                "buyPrice": "$22.84",
                "currentPrice": "$25.84",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "WULF", "name": "TeraWulf", "market": "US", "currentPrice": "$25.84", "opinion": "관망", "strategies": []}]
    technical = {"WULF": {"opinion": "관망", "opinionReason": "-", "entrySignalCodes": "", "현재가": "$25.84"}}

    changed = logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": True})

    updated = logs.load_json(cache_path, {})
    assert changed is True
    assert updated["rows"][0]["status"] == "익절"
    assert stocks[0]["opinion"] == "매도"
    assert stocks[0]["opinionReason"] == "나스닥 고점 청산/강제매도"
    assert stocks[0]["strategies"] == []
    assert technical["WULF"]["opinion"] == "매도"
    assert technical["WULF"]["opinionReason"] == "나스닥 고점 청산/강제매도"
    assert technical["WULF"]["exitReason"] == "나스닥 고점 청산/강제매도"
    assert technical["WULF"]["entrySignalCodes"] == ""


def test_closed_market_defers_peak_liquidation_and_restores_previous_opinion(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "TE",
                "name": "TE Connectivity",
                "market": "US",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.23",
                "buyPrice": "$100.00",
                "currentPrice": "$115.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    monkeypatch.setenv("DEFER_CLOSED_MARKET_SIGNALS", "true")
    monkeypatch.setattr(logs, "is_stock_market_open", lambda market, now: False)
    stocks = [{
        "ticker": "TE",
        "name": "TE Connectivity",
        "market": "US",
        "currentPrice": "$115.00",
        "opinion": "매도",
        "opinionReason": "나스닥 고점 청산/강제매도",
        "strategies": [],
    }]
    previous_stocks = {
        "TE": {
            "ticker": "TE",
            "name": "TE Connectivity",
            "market": "US",
            "currentPrice": "$114.00",
            "opinion": "매수",
            "opinionReason": "보유 유지",
            "strategies": ["2. 상승 추세 이평선 눌림목"],
        }
    }
    technical = {
        "TE": {
            "opinion": "매도",
            "opinionReason": "나스닥 고점 청산/강제매도",
            "exitReason": "나스닥 고점 청산/강제매도",
            "entrySignalCodes": "",
            "현재가": "$115.00",
        }
    }
    previous_technical = {
        "TE": {
            "opinion": "매수",
            "opinionReason": "보유 유지",
            "entrySignalCodes": "2",
            "entryStrategy": "2. 상승 추세 이평선 눌림목",
        }
    }

    changed = logs.update_trade_logs(stocks, previous_stocks, technical, {"peakTriggered": True}, previous_technical)

    updated = logs.load_json(cache_path, {})
    assert changed is True
    assert updated["rows"][0]["status"] == "보유 중"
    assert updated["rows"][0]["sellDate"] == "보유 중"
    assert updated["meta"]["closedTrades"] == 0
    assert stocks[0]["opinion"] == "매수"
    assert stocks[0]["opinionReason"] == "보유 유지"
    assert stocks[0]["strategies"] == ["2. 상승 추세 이평선 눌림목"]
    assert technical["TE"]["opinion"] == "매수"
    assert technical["TE"]["opinionReason"] == "보유 유지"
    assert technical["TE"]["entrySignalCodes"] == "H"
    assert "exitReason" not in technical["TE"]


def test_live_h_strategy_target_exit_runs_when_daily_price_date_is_unchanged(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "TE_2_20260624_1",
                "ticker": "TE",
                "name": "TE Connectivity",
                "market": "US",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.24",
                "buyPrice": "$100.00",
                "currentPrice": "$105.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "TE", "name": "TE Connectivity", "market": "US", "currentPrice": "$113.00", "opinion": "관망", "strategies": []}]
    technical = {
        "TE": {
            "opinion": "관망",
            "opinionReason": "-",
            "entrySignalCodes": "",
            "현재가": "$113.00",
            "C - Close": "$105.00",
            "dailyPriceDate": "2026-06-30",
        }
    }
    previous_technical = {"TE": {"dailyPriceDate": "2026-06-30"}}

    changed = logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": False}, previous_technical)

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert changed is True
    assert row["status"] == "익절"
    assert row["sellPrice"] == "$113.00"
    assert row["returnPct"] == 13.0
    assert row["exitReason"] == "목표 수익 달성 즉시 매도 +13.00% [20일선 지지·재돌파 기준 +12%]"
    assert stocks[0]["opinion"] == "매도"
    assert technical["TE"]["opinion"] == "매도"


def test_live_h_strategy_stop_is_ignored_until_fresh_daily_close(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "TE_2_20260624_1",
                "ticker": "TE",
                "name": "TE Connectivity",
                "market": "US",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.24",
                "buyPrice": "$100.00",
                "currentPrice": "$100.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "TE", "name": "TE Connectivity", "market": "US", "currentPrice": "$79.00", "opinion": "관망", "strategies": []}]
    technical = {
        "TE": {
            "opinion": "관망",
            "opinionReason": "-",
            "entrySignalCodes": "",
            "현재가": "$79.00",
            "C - Close": "$100.00",
            "20일 이동평균선": "$100.00",
            "dailyPriceDate": "2026-06-30",
        }
    }
    previous_technical = {"TE": {"dailyPriceDate": "2026-06-30"}}

    logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": False}, previous_technical)

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert row["status"] == "보유 중"
    assert row["sellPrice"] == "-"


def test_fresh_daily_h_strategy_exits_on_ma20_support_failure(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "TE_2_20260624_1",
                "ticker": "TE",
                "name": "TE Connectivity",
                "market": "US",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.24",
                "buyPrice": "$100.00",
                "currentPrice": "$100.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "TE", "name": "TE Connectivity", "market": "US", "currentPrice": "$100.00", "opinion": "관망", "strategies": []}]
    technical = {
        "TE": {
            "opinion": "관망",
            "opinionReason": "-",
            "entrySignalCodes": "",
            "현재가": "$100.00",
            "C - Close": "$94.90",
            "20일 이동평균선": "$100.00",
            "dailyPriceDate": "2026-07-01",
        }
    }
    previous_technical = {"TE": {"dailyPriceDate": "2026-06-30"}}

    changed = logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": False}, previous_technical)

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert changed is True
    assert row["status"] == "손절"
    assert row["sellPrice"] == "$94.90"
    assert row["exitReason"] == "20일선 지지 실패 손절 -5.10% [20일선 대비 -5%]"


def test_extended_target_touch_arms_ef_exit_without_selling(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "BE",
                "name": "Bloom Energy",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.06",
                "buyPrice": "$265.11",
                "currentPrice": "$312.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "BE", "name": "Bloom Energy", "market": "US", "currentPrice": "$329.00", "opinion": "관망", "strategies": []}]
    technical = {
        "BE": {
            "opinion": "관망",
            "opinionReason": "-",
            "entrySignalCodes": "",
            "현재가": "$329.00",
            "C - Close": "$284.99",
            "MACD Histogram (D)": "-1.59",
            "M - H (D-1)": "-3.17",
            "M - H (D-2)": "-5.07",
            "dailyPriceDate": "2026-06-17",
        }
    }
    previous_technical = {"BE": {"dailyPriceDate": "2026-06-18"}}

    changed = logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": False}, previous_technical)

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert changed is False
    assert row["status"] == "보유 중"
    assert row["sellDate"] == "보유 중"
    assert row["sellPrice"] == "-"
    assert row["returnPct"] == 0
    assert "exitReason" not in row
    assert row["upperExitArmedDate"] == logs.kst_trade_date()
    assert stocks[0]["opinion"] == "관망"
    assert technical["BE"]["opinion"] == "관망"


def test_stale_daily_indicator_exit_is_ignored_when_extended_target_not_touched(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "BE",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.06",
                "buyPrice": "$265.11",
                "currentPrice": "$280.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "BE", "name": "Bloom Energy", "market": "US", "currentPrice": "$300.00", "opinion": "관망", "strategies": []}]
    technical = {
        "BE": {
            "opinion": "관망",
            "entrySignalCodes": "",
            "현재가": "$300.00",
            "C - Close": "$329.00",
            "MACD Histogram (D)": "-1.59",
            "M - H (D-1)": "-3.17",
            "M - H (D-2)": "-5.07",
            "dailyPriceDate": "2026-06-17",
        }
    }
    previous_technical = {"BE": {"dailyPriceDate": "2026-06-18"}}

    changed = logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": False}, previous_technical)

    updated = logs.load_json(cache_path, {})
    assert changed is False
    assert updated["rows"][0]["status"] == "보유 중"
    assert updated["meta"]["closedTrades"] == 0


def test_fresh_daily_indicator_exit_uses_daily_close_price(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "BE",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.06",
                "buyPrice": "$265.11",
                "currentPrice": "$300.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "BE", "name": "Bloom Energy", "market": "US", "currentPrice": "$300.00", "opinion": "관망", "strategies": []}]
    technical = {
        "BE": {
            "opinion": "관망",
            "entrySignalCodes": "",
            "현재가": "$300.00",
            "C - Close": "$329.00",
            "MACD Histogram (D)": "-1.59",
            "M - H (D-1)": "-3.17",
            "M - H (D-2)": "-5.07",
            "dailyPriceDate": "2026-06-19",
        }
    }
    previous_technical = {"BE": {"dailyPriceDate": "2026-06-18"}}

    changed = logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": False}, previous_technical)

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert changed is True
    assert row["status"] == "익절"
    assert row["sellPrice"] == "$329.00"
    assert row["returnPct"] == 24.1
    assert row["exitReason"] == "목표 수익 구간 + MACD 히스토그램 둔화전환 매도 +24.10% [200일선 상방 & 스퀴즈 저점 기준 +20%]"


def test_recent_closed_trade_preserves_sell_opinion_during_reentry_cooldown(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "WULF",
                "name": "TeraWulf",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.05.23",
                "buyPrice": "$22.84",
                "currentPrice": "$24.59",
                "sellDate": today,
                "sellTimestamp": f"{today.replace('.', '-')}T15:00:00+09:00",
                "sellPrice": "$25.84",
                "returnPct": 13.13,
                "holdingDays": "-",
                "status": "익절",
                "exitReason": "목표 수익 달성 즉시 매도 +13.13% [급락 후 회복장 20일선 눌림 기준 +12%]",
            }
        ]
    }), encoding="utf-8")
    stocks = [{"ticker": "WULF", "name": "TeraWulf", "market": "US", "currentPrice": "$24.59", "opinion": "관망", "strategies": []}]
    technical = {"WULF": {"opinion": "관망", "opinionReason": "-", "entrySignalCodes": "", "현재가": "$24.59"}}

    changed = logs.update_trade_logs(stocks, {"WULF": {"opinion": "매도"}}, technical, {"peakTriggered": False})

    updated = logs.load_json(cache_path, {})
    assert changed is True
    assert updated["meta"]["appendedOpenTrades"] == 0
    assert stocks[0]["opinion"] == "매도"
    assert stocks[0]["opinionReason"] == "목표 수익 달성 즉시 매도 +13.13% [급락 후 회복장 20일선 눌림 기준 +12%]"
    assert technical["WULF"]["opinion"] == "매도"
    assert technical["WULF"]["opinionReason"] == "목표 수익 달성 즉시 매도 +13.13% [급락 후 회복장 20일선 눌림 기준 +12%]"


def test_sell_opinion_turns_watch_after_hold_even_when_price_recovers(monkeypatch, tmp_path):
    """After the fixed post-sale hold window, opinion must move 매도→관망 monotonically.

    Regression: a sold position whose price recovered above the reentry threshold used
    to flap 매도↔관망 because clearing was gated on price-based sell_reentry_allowed.
    Now the displayed opinion is purely time-based, so a recovered price stays 관망.
    """
    from datetime import timedelta

    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    sell_time = logs.datetime.now(logs.timezone.utc).astimezone(logs.KST) - timedelta(days=3)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "CRDO",
                "name": "Credo Technology Group Holding",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.05.15",
                "buyPrice": "$174.37",
                "currentPrice": "$229.00",
                "sellDate": sell_time.strftime("%Y.%m.%d"),
                "sellTimestamp": sell_time.isoformat(),
                "sellPrice": "$229.00",
                "returnPct": 31.33,
                "holdingDays": "-",
                "status": "익절",
                "exitReason": "목표 수익 구간 + MACD 히스토그램 둔화전환 매도",
            }
        ]
    }), encoding="utf-8")
    # Price recovered well above the sell price (no reentry-drop), yet hold window expired.
    stocks = [{"ticker": "CRDO", "name": "Credo Technology Group Holding", "market": "US", "currentPrice": "$240.00", "opinion": "매도", "opinionReason": "목표 수익 구간 + MACD 히스토그램 둔화전환 매도", "strategies": []}]
    technical = {"CRDO": {"opinion": "매도", "opinionReason": "목표 수익 구간 + MACD 히스토그램 둔화전환 매도", "exitReason": "목표 수익 구간 + MACD 히스토그램 둔화전환 매도", "entrySignalCodes": "", "현재가": "$240.00"}}

    changed = logs.update_trade_logs(stocks, {}, technical, {"peakTriggered": False})

    assert changed is True
    assert stocks[0]["opinion"] == "관망"
    assert "opinionReason" not in stocks[0]
    assert technical["CRDO"]["opinion"] == "관망"
    assert "exitReason" not in technical["CRDO"]


def test_nasdaq_peak_uses_existing_trade_price_when_stock_cache_omits_ticker(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    payload = {
        "rows": [
            {
                "ticker": "NVDA",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.05.01",
                "buyPrice": "$100.00",
                "currentPrice": "$120.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            },
        ],
    }
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps(payload), encoding="utf-8")

    logs.update_trade_logs([], {}, {}, {"peakTriggered": True})

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert row["sellPrice"] == "$120.00"
    assert row["returnPct"] == 20.0
    assert row["status"] == "익절"


def test_profitable_exit_before_strategy_target_is_failure_profit(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    payload = {
        "rows": [
            {
                "ticker": "AVGO",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.05.01",
                "buyPrice": "$100.00",
                "currentPrice": "$115.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            },
        ],
    }
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps(payload), encoding="utf-8")

    logs.update_trade_logs([], {}, {}, {"peakTriggered": True})

    updated = logs.load_json(cache_path, {})
    row = updated["rows"][0]
    assert row["returnPct"] == 15.0
    assert row["status"] == "실패 익절"


def test_h_strategy_twelve_percent_target_is_success_profit():
    trade = {"strategy": "2. 상승 추세 이평선 눌림목"}

    assert logs.target_return_pct(trade["strategy"]) == 12.0
    assert logs.trade_status_for_exit(trade, 15.46) == "익절"


def test_closed_trade_status_is_normalized_to_strategy_target(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "GLW_2_20260622_1",
                "ticker": "GLW",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.22",
                "buyPrice": "$194.92",
                "sellDate": "2026.06.25",
                "sellPrice": "$225.05",
                "returnPct": 15.46,
                "holdingDays": "-",
                "status": "실패 익절",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs([], {}, {}, {"peakTriggered": False})

    updated = logs.load_json(cache_path, {})
    assert updated["rows"][0]["status"] == "익절"
    assert updated["meta"]["correctedClosedStatuses"] == 1


def test_buy_signals_append_one_open_trade_per_strategy(monkeypatch, tmp_path):
    cache_path, _ = patch_log_paths(monkeypatch, tmp_path)

    logs.update_trade_logs(
        [{"ticker": "MSFT", "name": "Microsoft", "market": "US", "currentPrice": "$100.00", "opinion": "매수"}],
        {},
        {"MSFT": {"entrySignalCodes": "A,D", "현재가": "$100.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = updated["rows"]
    assert [row["strategy"] for row in rows] == [
        "1. 시장 공포 저점 진입",
        "1. 시장 공포 저점 진입",
    ]
    assert [row["investmentType"] for row in rows] == ["swing", "swing"]
    assert all(row["status"] == "보유 중" for row in rows)
    assert updated["meta"]["appendedOpenTrades"] == 2


def test_same_strategy_does_not_duplicate_while_signal_never_left(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "MP",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": today,
                "buyPrice": "$100.00",
                "currentPrice": "$101.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "MP", "name": "MP Materials", "market": "US", "currentPrice": "$101.00", "opinion": "매수"}],
        {},
        {"MP": {"entrySignalCodes": "1", "현재가": "$101.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    assert len([row for row in updated["rows"] if row["status"] == "보유 중"]) == 1
    assert updated["meta"]["appendedOpenTrades"] == 0


def test_same_strategy_adds_slot_after_ten_percent_drop_and_ten_days(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "MP",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": today,
                "buyPrice": "$100.00",
                "currentPrice": "$90.00",
                "restoreWatchDate": "2026.05.01",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "MP", "name": "MP Materials", "market": "US", "currentPrice": "$90.00", "opinion": "매수"}],
        {},
        {"MP": {"entrySignalCodes": "1", "현재가": "$90.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert len(rows) == 2
    assert rows[1]["strategy"] == "1. 시장 공포 저점 진입"
    assert rows[1]["investmentType"] == "swing"
    assert rows[1]["slotId"].startswith("MP_1_")
    assert updated["meta"]["appendedOpenTrades"] == 1


def test_ef_family_blocks_cross_strategy_slot_until_restore_condition(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "DL",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": today,
                "buyPrice": "$100.00",
                "currentPrice": "$99.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "DL", "name": "DL", "market": "US", "currentPrice": "$99.00", "opinion": "매수"}],
        {"DL": {"opinion": "매수"}},
        {"DL": {"entrySignalCodes": "2", "현재가": "$99.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert len(rows) == 1
    assert rows[0]["strategy"] == "2. 상승 추세 이평선 눌림목"
    assert "restoreWatchDate" in rows[0]
    assert updated["meta"]["appendedOpenTrades"] == 0


def test_ef_family_adds_cross_strategy_slot_after_ten_percent_drop_ten_days_and_two_signals(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "DL",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": today,
                "buyPrice": "$100.00",
                "currentPrice": "$90.00",
                "restoreWatchDate": "2026.05.01",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "DL", "name": "DL", "market": "US", "currentPrice": "$90.00", "opinion": "매수"}],
        {"DL": {"opinion": "매수"}},
        {"DL": {"entrySignalCodes": "2", "현재가": "$90.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert len(rows) == 1
    assert rows[0]["restoreSignalCounts"] == {"F": 1}
    assert updated["meta"]["appendedOpenTrades"] == 0

    logs.update_trade_logs(
        [{"ticker": "DL", "name": "DL", "market": "US", "currentPrice": "$90.00", "opinion": "매수"}],
        {"DL": {"opinion": "매수"}},
        {"DL": {"entrySignalCodes": "2", "현재가": "$90.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert [row["strategy"] for row in rows] == [
        "2. 상승 추세 이평선 눌림목",
        "2. 상승 추세 이평선 눌림목",
    ]
    assert rows[1]["investmentType"] == "swing"
    assert rows[1]["slotId"].startswith("DL_2_")
    assert "restoreSignalCounts" not in rows[0]
    assert updated["meta"]["appendedOpenTrades"] == 1


def test_same_day_sell_does_not_reopen_same_strategy(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "MP",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.05.01",
                "buyPrice": "$100.00",
                "currentPrice": "$130.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "MP", "name": "MP Materials", "market": "US", "currentPrice": "$130.00", "opinion": "매수"}],
        {},
        {"MP": {"entrySignalCodes": "1", "현재가": "$130.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    assert len(updated["rows"]) == 1
    assert updated["rows"][0]["status"] == "익절"
    assert updated["meta"]["appendedOpenTrades"] == 0


def test_offlist_ticker_does_not_generate_buy_signal(monkeypatch, tmp_path):
    # 관심종목(watchlist)에 없는 종목은 매수 신호가 계산돼도 trade가 추가되지 않고,
    # 의견은 관망으로 강제된다(보유 포지션 청산 추적과 매수 시그널을 분리).
    cache_path, _ = patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(logs, "load_watchlist_tickers_by_type", lambda stocks: {"long_term": [], "swing": ["MSFT"]})

    stock = {"ticker": "ACLS", "name": "Axcelis", "market": "US", "currentPrice": "$154.49", "opinion": "매수"}
    technical = {"ACLS": {"opinion": "매수", "entrySignalCodes": "2", "entryStrategy": "2. 상승 추세 이평선 눌림목", "현재가": "$154.49"}}

    changed = logs.update_trade_logs([stock], {}, technical, {"peakTriggered": False})

    updated = logs.load_json(cache_path, {})
    assert updated["rows"] == []
    assert updated["meta"]["appendedOpenTrades"] == 0
    assert changed is True
    assert stock["opinion"] == "관망"
    assert technical["ACLS"]["opinion"] == "관망"
    assert technical["ACLS"]["entrySignalCodes"] == ""


def test_offlist_held_trade_keeps_tracking_but_blocks_additional_buy(monkeypatch, tmp_path):
    # 관심종목에서 제거됐어도 '보유 중' 기록은 유지되며, 매수/추가매수만 차단된다.
    # (청산되기 전까지는 trade-log에 남아 청산 조건을 계속 추적)
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(logs, "load_watchlist_tickers_by_type", lambda stocks: {"long_term": [], "swing": ["MSFT"]})
    monkeypatch.setattr(logs, "kst_trade_date", lambda: "2026.05.25")
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "ACLS_2_20260522_1",
                "ticker": "ACLS",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.05.22",
                "buyPrice": "$152.51",
                "currentPrice": "$152.51",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    # 관심종목이 아니어도 매수 신호로 의견이 계산될 수 있다(보유라 universe 포함). 추가매수는 차단돼야 한다.
    stock = {"ticker": "ACLS", "name": "Axcelis", "market": "US", "currentPrice": "$154.49", "opinion": "매수"}
    technical = {"ACLS": {"opinion": "매수", "entrySignalCodes": "2", "현재가": "$154.49"}}
    logs.update_trade_logs([stock], {}, technical, {"peakTriggered": False})

    updated = logs.load_json(cache_path, {})
    acls_rows = [row for row in updated["rows"] if row["ticker"] == "ACLS"]
    assert len(acls_rows) == 1  # 보유 기록 유지, 추가 trade 없음
    assert acls_rows[0]["status"] == "보유 중"
    assert updated["meta"]["appendedOpenTrades"] == 0
    # 매수 시그널은 차단되어 의견은 관망으로 정리된다.
    assert stock["opinion"] == "관망"


def test_held_trade_buy_signal_without_add_slot_keeps_buy_opinion(monkeypatch, tmp_path):
    # 보유 중 '매수' 종목은 추가매수 조건(-10%/대기일)을 못 채워도 의견은 '매수'를 유지한다.
    # 추가매수 '신호'(추가 슬롯/진입 코드)만 보류될 뿐, 의견을 관망으로 강제로 내리지 않는다(GAS와 동일).
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(logs, "load_watchlist_tickers_by_type", lambda stocks: {"long_term": [], "swing": ["INTC"]})
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "INTC_2_20260606_1",
                "ticker": "INTC",
                "strategy": "2. 상승 추세 이평선 눌림목",
                "buyDate": "2026.06.06",
                "buyPrice": "$102.90",
                "currentPrice": "$102.90",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
                "restoreWatchDate": "2026.06.06",
            }
        ]
    }), encoding="utf-8")

    stock = {"ticker": "INTC", "name": "Intel", "market": "US", "currentPrice": "$109.82", "opinion": "매수", "strategies": ["2. 상승 추세 이평선 눌림목"]}
    technical = {"INTC": {"opinion": "매수", "entrySignalCodes": "2", "entryStrategy": "2. 상승 추세 이평선 눌림목", "현재가": "$109.82"}}

    changed = logs.update_trade_logs([stock], {"INTC": {"opinion": "관망"}}, technical, {"peakTriggered": False})

    updated = logs.load_json(cache_path, {})
    intc_rows = [row for row in updated["rows"] if row["ticker"] == "INTC"]
    assert len(intc_rows) == 1
    # 추가 슬롯은 생성되지 않는다(추가매수 조건 미충족).
    assert updated["meta"]["appendedOpenTrades"] == 0
    assert changed is True
    # 의견은 '매수' 유지, 추가매수 신호(코드/전략 리스트)만 비운다.
    assert stock["opinion"] == "매수"
    assert stock["strategies"] == []
    assert technical["INTC"]["opinion"] == "매수"
    assert technical["INTC"]["entrySignalCodes"] == ""


def test_offlist_held_trade_still_liquidates_on_exit(monkeypatch, tmp_path):
    # 관심종목 밖 보유 종목도 청산 조건이 충족되면 정상적으로 매도 처리된다(나스닥 고점 강제 청산).
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(logs, "load_watchlist_tickers_by_type", lambda stocks: {"long_term": [], "swing": ["MSFT"]})
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "slotId": "OFL_1_20260501_1",
                "ticker": "OFL",
                "strategy": "1. 시장 공포 저점 진입",
                "buyDate": "2026.05.01",
                "buyPrice": "$100.00",
                "currentPrice": "$120.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "OFL", "name": "Offlist Co", "market": "US", "currentPrice": "$120.00", "opinion": "관망"}],
        {},
        {"OFL": {}},
        {"peakTriggered": True},
    )

    updated = logs.load_json(cache_path, {})
    ofl_rows = [row for row in updated["rows"] if row["ticker"] == "OFL"]
    assert len(ofl_rows) == 1
    assert ofl_rows[0]["status"] != "보유 중"
    assert ofl_rows[0]["exitReason"] == "나스닥 고점 청산/강제매도"
