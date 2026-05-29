from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import record_web_api_logs as logs


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
                "strategy": "A. 200일선 상방 & 모멘텀 재가속",
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
                "strategy": "D. 200일선 상방 & 상승 흐름 강화",
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
                "strategy": "D. 200일선 상방 & 상승 흐름 강화",
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


def test_recent_closed_trade_preserves_sell_opinion_during_reentry_cooldown(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "WULF",
                "name": "TeraWulf",
                "strategy": "G. 급락 후 회복장 20일선 눌림",
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
                "strategy": "E. 200일선 상방 & 스퀴즈 저점",
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
                "strategy": "B. 200일선 하방 & 공황 저점",
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
                "strategy": "B. 200일선 하방 & 공황 저점",
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
        "A. 200일선 상방 & 모멘텀 재가속",
        "D. 200일선 상방 & 상승 흐름 강화",
    ]
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
                "strategy": "D. 200일선 상방 & 상승 흐름 강화",
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
        {"MP": {"entrySignalCodes": "D", "현재가": "$101.00"}},
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
                "strategy": "D. 200일선 상방 & 상승 흐름 강화",
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
        {"MP": {"entrySignalCodes": "D", "현재가": "$90.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert len(rows) == 2
    assert rows[1]["strategy"] == "D. 200일선 상방 & 상승 흐름 강화"
    assert rows[1]["slotId"].startswith("MP_D_")
    assert updated["meta"]["appendedOpenTrades"] == 1


def test_ef_family_blocks_cross_strategy_slot_until_restore_condition(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    today = logs.kst_trade_date()
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "DL",
                "strategy": "E. 200일선 상방 & 스퀴즈 저점",
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
        {"DL": {"entrySignalCodes": "F", "현재가": "$99.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert len(rows) == 1
    assert rows[0]["strategy"] == "E. 200일선 상방 & 스퀴즈 저점"
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
                "strategy": "E. 200일선 상방 & 스퀴즈 저점",
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
        {"DL": {"entrySignalCodes": "F", "현재가": "$90.00"}},
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
        {"DL": {"entrySignalCodes": "F", "현재가": "$90.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert [row["strategy"] for row in rows] == [
        "E. 200일선 상방 & 스퀴즈 저점",
        "F. 200일선 상방 & BB 극단 저점",
    ]
    assert rows[1]["slotId"].startswith("DL_F_")
    assert "restoreSignalCounts" not in rows[0]
    assert updated["meta"]["appendedOpenTrades"] == 1


def test_same_day_sell_does_not_reopen_same_strategy(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "MP",
                "strategy": "D. 200일선 상방 & 상승 흐름 강화",
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
        {"MP": {"entrySignalCodes": "D", "현재가": "$130.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    assert len(updated["rows"]) == 1
    assert updated["rows"][0]["status"] == "익절"
    assert updated["meta"]["appendedOpenTrades"] == 0
