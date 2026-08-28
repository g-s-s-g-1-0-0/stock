from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.strategy4 import bottom_rebound_study as study
from research.strategy4.bottom_rebound_core import Condition, Rule


def synthetic_prices(
    start: str = "2018-01-01",
    rows: int = 360,
    slope: float = 0.05,
) -> pd.DataFrame:
    index = pd.bdate_range(start, periods=rows)
    close = pd.Series(100 + np.arange(rows) * slope, index=index)
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close * 1.03,
            "Low": close * 0.97,
            "Close": close,
            "Volume": 1_000 + np.arange(rows),
        },
        index=index,
    )


def stable_rule() -> Rule:
    return Rule(
        (
            Condition("rsi≤40", "rsi", "<=", 40),
            Condition("cci≤-100", "cci", "<=", -100),
            Condition("williamsR≤-80", "williamsR", "<=", -80),
        )
    )


def small_pipeline_inputs() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    train = pd.bdate_range("2019-10-01", periods=30)
    validation = pd.bdate_range("2022-10-03", periods=30)
    test = pd.bdate_range("2024-01-02", periods=45)
    dates = train.append(validation).append(test)
    raw = synthetic_prices(rows=len(dates))
    raw.index = dates
    tickers = ["AAA", "BBB"]
    prices = {"QQQ": raw}
    for number, ticker in enumerate(tickers):
        multiplier = 1 + number / 100
        prices[ticker] = raw.assign(
            Open=raw["Open"] * multiplier,
            High=raw["High"] * multiplier,
            Low=raw["Low"] * multiplier,
            Close=raw["Close"] * multiplier,
        )

    frames = []
    for ticker in tickers:
        frame = pd.DataFrame(
            {
                "date": dates,
                "ticker": ticker,
                "symbol": ticker,
                "country": "US",
                "universe": "discovery",
                "period": (
                    ["train"] * len(train)
                    + ["validation"] * len(validation)
                    + ["test"] * len(test)
                ),
                "isCandidate": (
                    [True] * len(train)
                    + [True] * len(validation)
                    + [False] * len(test)
                ),
                "isPositiveBottom": True,
                "labelEndDate": dates,
                "d20Return": 0.02,
                "d20Excess": 0.01,
                "rsi": 35.0,
                "cci": -150.0,
                "williamsR": -90.0,
                "qqqRegime": "normal",
            }
        )
        for offset in (0, 35):
            frame.loc[len(train) + len(validation) + offset, "isCandidate"] = True
            frame.loc[len(train) + len(validation) + offset, "isPositiveBottom"] = True
        incomplete = len(train) + len(validation) + 35
        frame.loc[incomplete, "labelEndDate"] = pd.NaT
        frame.loc[incomplete, "isPositiveBottom"] = False
        frames.append(frame)
    panel = pd.concat(frames, ignore_index=True)
    panel.attrs.update(
        {
            "missingTickers": ["ANSS", "SQ"],
            "cacheEndDate": "2024-03-04",
            "panelCache": "no panel cache",
        }
    )
    return panel, prices


def fake_discover_rule(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    max_conditions: int = 5,
) -> tuple[Rule, pd.DataFrame]:
    assert set(train["period"]) == {"train"}
    assert set(validation["period"]) == {"validation"}
    rule = stable_rule()
    audit = pd.DataFrame(
        [
            {
                "recordType": "final",
                "candidate": "stable",
                "stable": True,
                "trainEvents": len(train),
                "validationEvents": len(validation),
            }
        ]
    )
    audit.attrs["stable"] = True
    return rule, audit


def fake_stability_gate(
    rule: Rule,
    train: pd.DataFrame,
    validation: pd.DataFrame,
) -> tuple[bool, pd.DataFrame]:
    return True, pd.DataFrame(
        [{"recordType": "stabilityGate", "check": "synthetic", "passed": True}]
    )


def pretest_panel(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.loc[pd.to_datetime(panel["date"]).lt("2023-01-01")].copy()
    result.attrs = panel.attrs.copy()
    return result


def test_load_discovery_universe_keeps_full_declared_universe() -> None:
    symbols = study.load_discovery_universe()

    assert len(symbols) == 139
    assert {"ANSS", "SQ"}.issubset(symbols)


def test_build_panel_uses_available_cache_and_records_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qqq = synthetic_prices(slope=0.10)
    vix = synthetic_prices(slope=0.01)
    available = {
        "QQQ": qqq,
        "^VIX": vix,
        "AAA": synthetic_prices(slope=0.20),
        "BBB": synthetic_prices(slope=-0.02),
    }
    monkeypatch.setattr(study, "dl", lambda symbol: available.get(symbol))

    panel, prices = study.build_panel(
        {"AAA": "AAA", "BBB": "BBB", "ANSS": "ANSS", "SQ": "SQ"},
        d_cutoff="2022-12-31",
    )

    assert set(prices) >= {"AAA", "BBB", "QQQ"}
    assert panel.attrs["missingTickers"] == ["ANSS", "SQ"]
    assert panel.attrs["loadedTickerCount"] == 2
    assert panel.attrs["requestedTickerCount"] == 4
    assert panel.attrs["panelCache"] == "no panel cache"
    assert "cacheKey" not in panel.attrs
    assert pd.notna(panel.loc[panel["ticker"] == "AAA", "rs20"]).any()
    observed = panel.loc[
        (panel["ticker"] == "AAA") & panel["d20Return"].notna()
    ].iloc[-1]
    expected = (
        prices["AAA"].loc[observed["date"]:].iloc[20]["Close"]
        * (1 - study.FEE)
        / (
            prices["AAA"].loc[observed["date"]:].iloc[1]["Open"]
            * (1 + study.FEE)
        )
        - 1
    )
    assert observed["d20Return"] == pytest.approx(expected)
    same_date = panel.loc[panel["date"] == observed["date"], "d20Return"]
    assert observed["d20Excess"] == pytest.approx(
        observed["d20Return"] - same_date.mean()
    )
    assert "d20Return" not in panel.attrs["featureColumns"]
    assert "d20Excess" not in panel.attrs["featureColumns"]

    market_columns = [
        column
        for column in study.FEATURE_COLUMNS
        if column.startswith(("qqq", "vix", "breadth"))
        and column in panel
    ]
    market_context = (
        panel.drop_duplicates("date").set_index("date")[market_columns].copy()
    )
    for column in ("breadthBelow200", "breadthRsi30", "breadthDd40"):
        market_context[column] = 0.123
    discovery_benchmark = pd.Series(0.25, index=market_context.index)
    watchlist, _ = study.build_panel(
        {"AAA": "AAA"},
        d_cutoff="2022-12-31",
        market_context=market_context,
        universe_d20=discovery_benchmark,
        universe_name="watchlist",
    )
    assert watchlist["breadthBelow200"].dropna().eq(0.123).all()
    assert watchlist["d20UniverseMean"].dropna().eq(0.25).all()
    assert watchlist.attrs["benchmarkSource"] == "discovery universe (external)"


def test_discovery_panel_never_materializes_test_dates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = synthetic_prices(start="2021-01-04", rows=560)
    available = {"QQQ": raw, "^VIX": raw, "AAA": raw}
    monkeypatch.setattr(study, "dl", lambda symbol: available.get(symbol))

    panel, prices = study.build_panel({"AAA": "AAA"}, d_cutoff="2022-12-31")

    assert panel["date"].max() <= pd.Timestamp("2022-12-31")
    assert not panel["date"].ge("2023-01-01").any()
    assert prices["AAA"].index.max() > pd.Timestamp("2022-12-31")
    assert prices["AAA"].index.max() <= panel.attrs["sourceOhlcEnd"]


def test_pipeline_freezes_before_test_and_test_never_rewrites_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel, prices = small_pipeline_inputs()
    monkeypatch.setattr(study, "discover_rule", fake_discover_rule)
    monkeypatch.setattr(study, "evaluate_stability_gate", fake_stability_gate)

    rule = study.run_discovery(pretest_panel(panel), prices, str(tmp_path))
    frozen = tmp_path / "bottom_rebound_frozen_rule.json"
    before = frozen.read_bytes()
    outputs = study.run_frozen_test(rule, panel, prices, str(tmp_path))

    assert frozen.read_bytes() == before
    lock = json.loads(
        (tmp_path / study.TEST_LOCK_FILE).read_text(encoding="utf-8")
    )
    assert lock["status"] == "completed"
    assert lock["ruleSha256"] == hashlib.sha256(before).hexdigest()
    assert set(lock["outputSha256"]) == {
        "bottom_rebound_events.pkl",
        "bottom_rebound_d1_d20.csv",
        "bottom_rebound_target_exits.csv",
        "bottom_rebound_periods.csv",
        "bottom_rebound_concentration.csv",
        "bottom_rebound_bootstrap.csv",
        "bottom_rebound_watchlist.csv",
    }
    assert set(outputs) >= {
        "events",
        "path",
        "exits",
        "periods",
        "concentration",
        "bootstrap",
        "watchlist",
    }
    final_path = outputs["path"].loc[
        (outputs["path"]["scope"] == "final_test")
        & (outputs["path"]["strategy"] == "final")
    ]
    assert final_path["day"].tolist() == list(range(1, 21))
    final_exits = outputs["exits"].loc[
        (outputs["exits"]["scope"] == "final_test")
        & (outputs["exits"]["strategy"] == "final")
    ]
    combinations = {
        (float(row.target), None if pd.isna(row.stop) else float(row.stop))
        for row in final_exits.itertuples()
    }
    assert combinations == {
        (target, stop)
        for target in (0.10, 0.15, 0.20)
        for stop in (None, 0.10, 0.15)
    }
    with pytest.raises(RuntimeError, match="lock"):
        study.run_frozen_test(rule, panel, prices, str(tmp_path))


def test_discovery_refuses_to_overwrite_frozen_rule_or_test_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel, prices = small_pipeline_inputs()
    monkeypatch.setattr(study, "discover_rule", fake_discover_rule)
    monkeypatch.setattr(study, "evaluate_stability_gate", fake_stability_gate)
    discovery = pretest_panel(panel)
    study.run_discovery(discovery, prices, str(tmp_path))

    with pytest.raises(RuntimeError, match="already exists"):
        study.run_discovery(discovery, prices, str(tmp_path))

    other = tmp_path / "other"
    other.mkdir()
    (other / study.TEST_LOCK_FILE).write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="lock"):
        study.run_discovery(discovery, prices, str(other))


def test_failed_test_run_leaves_failed_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel, prices = small_pipeline_inputs()
    monkeypatch.setattr(study, "discover_rule", fake_discover_rule)
    monkeypatch.setattr(study, "evaluate_stability_gate", fake_stability_gate)
    rule = study.run_discovery(pretest_panel(panel), prices, str(tmp_path))
    monkeypatch.setattr(
        study,
        "_path_events",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        study.run_frozen_test(rule, panel, prices, str(tmp_path))

    lock = json.loads(
        (tmp_path / study.TEST_LOCK_FILE).read_text(encoding="utf-8")
    )
    assert lock["status"] == "failed"
    assert "boom" in lock["error"]


def test_discovery_outputs_never_aggregate_test_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel, prices = small_pipeline_inputs()
    monkeypatch.setattr(study, "discover_rule", fake_discover_rule)
    monkeypatch.setattr(study, "evaluate_stability_gate", fake_stability_gate)

    study.run_discovery(pretest_panel(panel), prices, str(tmp_path))

    summary = pd.read_csv(
        tmp_path / "bottom_rebound_train_validation_summary.csv"
    )
    audit = pd.read_csv(tmp_path / "bottom_rebound_condition_audit.csv")
    assert set(summary["period"]) == {"train", "validation"}
    assert "test" not in audit.astype(str).to_numpy()


def test_test_gate_rejects_missing_or_mismatched_frozen_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel, prices = small_pipeline_inputs()
    rule = stable_rule()

    with pytest.raises(RuntimeError, match="frozen rule"):
        study.run_frozen_test(rule, panel, prices, str(tmp_path))

    monkeypatch.setattr(study, "discover_rule", fake_discover_rule)
    monkeypatch.setattr(study, "evaluate_stability_gate", fake_stability_gate)
    study.run_discovery(pretest_panel(panel), prices, str(tmp_path))
    metadata_path = tmp_path / "bottom_rebound_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["frozenRuleSha256"] = hashlib.sha256(b"wrong").hexdigest()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(RuntimeError, match="hash"):
        study.run_frozen_test(rule, panel, prices, str(tmp_path))


def test_watchlist_scope_has_d1_d20_and_nine_exit_combinations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, prices = small_pipeline_inputs()
    watchlist = discovery.copy()
    watchlist["universe"] = "watchlist"
    watchlist["country"] = "KR"
    combined = pd.concat([discovery, watchlist], ignore_index=True)
    combined.attrs = discovery.attrs.copy()
    monkeypatch.setattr(study, "discover_rule", fake_discover_rule)
    monkeypatch.setattr(study, "evaluate_stability_gate", fake_stability_gate)
    rule = study.run_discovery(pretest_panel(discovery), prices, str(tmp_path))

    outputs = study.run_frozen_test(rule, combined, prices, str(tmp_path))

    watch = outputs["watchlist"]
    path_rows = watch.loc[watch["recordType"] == "path"]
    exit_rows = watch.loc[watch["recordType"] == "exit"]
    assert set(path_rows["day"].dropna().astype(int)) == set(range(1, 21))
    assert len(
        exit_rows[["strategy", "target", "stopLabel"]].drop_duplicates()
    ) == 18
    assert set(exit_rows["stopLabel"]) == {"none", "0.10", "0.15"}
    counts = outputs["path"].loc[
        (outputs["path"]["scope"] == "final_test")
        & (outputs["path"]["strategy"] == "final"),
        "events",
    ].tolist()
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > counts[-1]
    final_period = outputs["periods"].loc[
        (outputs["periods"]["scope"] == "final_test")
        & (outputs["periods"]["strategy"] == "final")
    ].iloc[0]
    assert final_period["labelEvents"] < final_period["signals"]
    assert final_period["labelPrecision"] == pytest.approx(1.0)


def test_watchlist_uses_discovery_universe_benchmark() -> None:
    discovery, prices = small_pipeline_inputs()
    watchlist = discovery.loc[discovery["ticker"].eq("AAA")].copy()
    watchlist["ticker"] = "WATCH"
    watchlist["symbol"] = "WATCH"
    watchlist["universe"] = "watchlist"
    watch_raw = prices["AAA"].copy()
    watch_raw["Close"] *= 2
    watch_raw["High"] *= 2
    watch_raw["Low"] *= 2
    watch_raw["Open"] *= 2
    prices["WATCH"] = watch_raw
    events = pd.DataFrame(
        {
            "signalDate": [discovery.loc[discovery["period"].eq("test"), "date"].iloc[0]],
            "d1": [0.50],
        }
    )

    universe, qqq = study._benchmark_paths(discovery, prices, events["signalDate"])
    attached = study._attach_benchmarks(events, universe, qqq)

    date = pd.Timestamp(events.iloc[0]["signalDate"])
    expected = np.mean(
        [
            study.event_path(prices[ticker], 60, horizon=20, fee=study.FEE)["d1"]
            for ticker in sorted(discovery["ticker"].unique())
        ]
    )
    assert universe[1][date] == pytest.approx(expected)
    assert attached.iloc[0]["universeEx1"] == pytest.approx(0.50 - expected)


def test_stability_gate_production_function_checks_all_constraints() -> None:
    panel, _ = small_pipeline_inputs()
    train_seed = panel.loc[
        panel["period"].eq("train") & panel["ticker"].eq("AAA")
    ]
    validation_seed = panel.loc[
        panel["period"].eq("validation") & panel["ticker"].eq("AAA")
    ]
    train = pd.concat(
        [
            train_seed.assign(ticker=f"T{number:02d}")
            for number in range(10)
        ],
        ignore_index=True,
    )
    validation = pd.concat(
        [
            validation_seed.assign(ticker=f"T{number:02d}")
            for number in range(10)
        ],
        ignore_index=True,
    )

    passed, audit = study.evaluate_stability_gate(
        stable_rule(),
        train,
        validation,
    )

    assert passed
    assert audit["passed"].all()
    duplicate_rule = Rule(
        (
            Condition("rsi≤40", "rsi", "<=", 40),
            Condition("rsi≤35", "rsi", "<=", 35),
            Condition("cci≤-100", "cci", "<=", -100),
        )
    )
    duplicate_passed, duplicate_audit = study.evaluate_stability_gate(
        duplicate_rule,
        train,
        validation,
    )
    assert not duplicate_passed
    assert "duplicate_feature_columns" in set(
        duplicate_audit.loc[~duplicate_audit["passed"], "check"]
    )

    concentrated = train.copy()
    concentrated["ticker"] = "ONE"
    concentration_passed, concentration_audit = study.evaluate_stability_gate(
        stable_rule(),
        concentrated,
        validation,
    )
    assert not concentration_passed
    failed_checks = set(
        concentration_audit.loc[~concentration_audit["passed"], "check"]
    )
    assert "top5_positive_excess_share" in failed_checks


def test_failed_stability_gate_records_reasons_without_freezing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel, prices = small_pipeline_inputs()
    monkeypatch.setattr(study, "discover_rule", fake_discover_rule)

    with pytest.raises(RuntimeError, match="no stable rule"):
        study.run_discovery(pretest_panel(panel), prices, str(tmp_path))

    assert not (tmp_path / study.FROZEN_RULE_FILE).exists()
    audit = pd.read_csv(tmp_path / "bottom_rebound_condition_audit.csv")
    assert "stabilityGate" in set(audit["recordType"])
    metadata = json.loads(
        (tmp_path / study.METADATA_FILE).read_text(encoding="utf-8")
    )
    assert not metadata["stableRule"]
    assert metadata["stabilityGateFailures"]


def test_bootstrap_uses_event_weighted_point_estimate() -> None:
    events = pd.DataFrame(
        {
            "scope": "final_test",
            "strategy": "final",
            "signalDate": pd.to_datetime(
                ["2024-01-02", "2024-01-02", "2024-01-02", "2024-01-03"]
            ),
            "ticker": ["A", "B", "C", "D"],
            "d20": [1.0, 1.0, 1.0, -1.0],
            "universeEx20": [0.4, 0.4, 0.4, -0.4],
        }
    )

    result = study._bootstrap(events, repetitions=200)

    d20 = result.loc[result["metric"].eq("d20")]
    assert d20["estimate"].tolist() == pytest.approx(
        [events["d20"].mean()] * 2
    )
    assert d20["reportedMean"].tolist() == pytest.approx(
        [events["d20"].mean()] * 2
    )
