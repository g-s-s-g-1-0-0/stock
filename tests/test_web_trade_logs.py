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


def test_nasdaq_peak_liquidates_all_open_strategy_slots(monkeypatch, tmp_path):
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
                "buyPrice": "$105.00",
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
        [{"ticker": "NVDA", "name": "NVIDIA", "market": "US", "currentPrice": "$120.00", "opinion": "관망"}],
        {},
        {"NVDA": {}},
        {"peakTriggered": True},
    )

    updated = logs.load_json(cache_path, {})
    rows = updated["rows"]
    assert [row["status"] for row in rows] == ["익절", "익절"]
    assert all(row["sellDate"] != "보유 중" for row in rows)
    assert all(row["exitReason"] == "나스닥 고점 청산/강제매도" for row in rows)
    assert updated["meta"]["closedTrades"] == 2
    assert updated["meta"]["nasdaqPeakLiquidation"] is True


def test_nasdaq_peak_uses_existing_trade_price_when_stock_cache_omits_ticker(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    payload = {
        "rows": [
            {
                "ticker": "NVDA",
                "strategy": "A. 200일선 상방 & 모멘텀 재가속",
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
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "MP",
                "strategy": "D. 200일선 상방 & 상승 흐름 강화",
                "buyDate": "2026.05.01",
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


def test_same_strategy_adds_slot_after_restore_wait(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "MP",
                "strategy": "D. 200일선 상방 & 상승 흐름 강화",
                "buyDate": "2026.05.01",
                "buyPrice": "$100.00",
                "currentPrice": "$98.00",
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
        [{"ticker": "MP", "name": "MP Materials", "market": "US", "currentPrice": "$98.00", "opinion": "매수"}],
        {},
        {"MP": {"entrySignalCodes": "D", "현재가": "$98.00"}},
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
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "DL",
                "strategy": "E. 200일선 상방 & 스퀴즈 저점",
                "buyDate": "2026.05.01",
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


def test_ef_family_adds_cross_strategy_slot_after_five_percent_drop_and_two_signals(monkeypatch, tmp_path):
    cache_path, public_path = patch_log_paths(monkeypatch, tmp_path)
    public_path.parent.mkdir(parents=True)
    public_path.write_text(logs.json.dumps({
        "rows": [
            {
                "ticker": "DL",
                "strategy": "E. 200일선 상방 & 스퀴즈 저점",
                "buyDate": "2026.05.01",
                "buyPrice": "$100.00",
                "currentPrice": "$95.00",
                "sellDate": "보유 중",
                "sellPrice": "-",
                "returnPct": 0,
                "holdingDays": "-",
                "status": "보유 중",
            }
        ]
    }), encoding="utf-8")

    logs.update_trade_logs(
        [{"ticker": "DL", "name": "DL", "market": "US", "currentPrice": "$95.00", "opinion": "매수"}],
        {"DL": {"opinion": "매수"}},
        {"DL": {"entrySignalCodes": "F", "현재가": "$95.00"}},
        {"peakTriggered": False},
    )

    updated = logs.load_json(cache_path, {})
    rows = [row for row in updated["rows"] if row["status"] == "보유 중"]
    assert len(rows) == 1
    assert rows[0]["restoreSignalCounts"] == {"F": 1}
    assert updated["meta"]["appendedOpenTrades"] == 0

    logs.update_trade_logs(
        [{"ticker": "DL", "name": "DL", "market": "US", "currentPrice": "$95.00", "opinion": "매수"}],
        {"DL": {"opinion": "매수"}},
        {"DL": {"entrySignalCodes": "F", "현재가": "$95.00"}},
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
