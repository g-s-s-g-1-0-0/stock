from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.strategy4.bottom_rebound_core import (
    Condition,
    Rule,
    apply_rule,
    assign_periods,
    build_breadth,
    build_market_features,
    build_stock_features,
    condition_library,
    discover_rule,
    episode_signals,
    event_path,
    label_bottom_candidates,
    load_frozen_rule,
    save_frozen_rule,
    simulate_exit,
    summarize_exits,
    summarize_paths,
)


def synthetic_ohlc(
    lows: list[float],
    highs: list[float],
    closes: list[float],
) -> pd.DataFrame:
    index = pd.bdate_range("2019-01-01", periods=len(closes))
    return pd.DataFrame(
        {
            "Open": closes,
            "High": highs,
            "Low": lows,
            "Close": closes,
            "Volume": 1_000.0,
        },
        index=index,
    )


def synthetic_trending_ohlcv(rows: int) -> pd.DataFrame:
    index = pd.bdate_range("2018-01-01", periods=rows)
    close = pd.Series(
        100 + np.arange(rows) * 0.1 + np.sin(np.arange(rows) / 5),
        index=index,
    )
    return pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]) * 1.001,
            "High": close * 1.02,
            "Low": close * 0.98,
            "Close": close,
            "Volume": 1_000 + np.arange(rows) * 10,
        },
        index=index,
    )


def tiny_ohlc(
    open_: list[float],
    high: list[float],
    low: list[float],
    close: list[float],
) -> pd.DataFrame:
    index = pd.bdate_range("2024-01-02", periods=len(close))
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close},
        index=index,
    )


def rule_discovery_frame(rows: int, qualifying_rows: int) -> pd.DataFrame:
    positives = np.zeros(rows, dtype=bool)
    positives[: int(rows * 0.4)] = True
    positives[:qualifying_rows] = np.arange(qualifying_rows) < int(
        qualifying_rows * 0.8
    )
    return pd.DataFrame(
        {
            "isCandidate": True,
            "isPositiveBottom": positives,
            "labelEndDate": pd.Timestamp("2020-01-31"),
            "d20Excess": np.where(np.arange(rows) < qualifying_rows, 0.01, -0.01),
            "rsi": np.where(np.arange(rows) < qualifying_rows, 24.0, 50.0),
            "cci": 0.0,
            "williamsR": -50.0,
            "adx": 0.0,
            "diSpread": 10.0,
            "pctB": 50.0,
            "ret1": 0.0,
            "ret5": 0.0,
            "ret20": 0.0,
            "dd60": 0.0,
            "dd252": 0.0,
            "distMA200": 0.1,
            "volRatio20": 0.0,
            "atrPct": 0.0,
            "rs20": 0.1,
            "qqqPremium": 20.0,
            "qqqRsi": 60.0,
            "vix": 0.0,
        }
    )


def set_binary_condition_outcomes(
    frame: pd.DataFrame,
    qualifying_rows: int,
    qualifying_positives: int,
    other_positives: int,
    qualifying_excess: float = 0.01,
    other_excess: float = 0.01,
) -> None:
    labels = np.zeros(len(frame), dtype=bool)
    labels[:qualifying_positives] = True
    other_start = qualifying_rows
    labels[other_start : other_start + other_positives] = True
    frame["isPositiveBottom"] = labels
    frame["d20Excess"] = np.where(
        np.arange(len(frame)) < qualifying_rows,
        qualifying_excess,
        other_excess,
    )


def two_condition_frame(intersection_excess: float) -> pd.DataFrame:
    frame = rule_discovery_frame(rows=400, qualifying_rows=0)
    labels = np.zeros(400, dtype=bool)
    labels[0:60] = True
    labels[100:140] = True
    labels[200:240] = True
    labels[300:320] = True
    frame["isPositiveBottom"] = labels
    frame["rsi"] = np.where(np.arange(400) < 200, 24.0, 50.0)
    positions = np.arange(400)
    in_second_condition = (positions < 100) | (
        (positions >= 200) & (positions < 300)
    )
    frame["dd60"] = np.where(in_second_condition, -0.45, 0.0)
    frame["d20Excess"] = 0.01
    frame.loc[:99, "d20Excess"] = intersection_excess
    frame.loc[100:199, "d20Excess"] = 0.02 - intersection_excess
    return frame


def three_condition_frame() -> pd.DataFrame:
    rows_per_cell = 100
    frame = rule_discovery_frame(rows=8 * rows_per_cell, qualifying_rows=0)
    labels = np.zeros(len(frame), dtype=bool)
    for cell in range(8):
        start = cell * rows_per_cell
        stop = start + rows_per_cell
        first = bool(cell & 4)
        second = bool(cell & 2)
        third = bool(cell & 1)
        positive_rate = 0.1 + 0.2 * sum((first, second, third))
        labels[start : start + int(positive_rate * rows_per_cell)] = True
        frame.loc[start : stop - 1, "rsi"] = 24.0 if first else 50.0
        frame.loc[start : stop - 1, "cci"] = -160.0 if second else 0.0
        frame.loc[start : stop - 1, "williamsR"] = -92.0 if third else -50.0
    frame["isPositiveBottom"] = labels
    frame["d20Excess"] = 0.01
    return frame


def test_positive_bottom_requires_no_lower_low_and_ten_percent_rebound() -> None:
    frame = synthetic_ohlc(
        lows=[100] * 20 + [90] + [91] * 20,
        highs=[101] * 20 + [92] + [100] * 20,
        closes=[100] * 20 + [90] + [95] * 20,
    )

    result = label_bottom_candidates(frame)

    assert bool(result.iloc[20]["isCandidate"])
    assert bool(result.iloc[20]["isPositiveBottom"])


def test_future_lower_low_makes_bottom_label_false() -> None:
    frame = synthetic_ohlc(
        lows=[100] * 20 + [90, 89] + [91] * 19,
        highs=[101] * 20 + [92] + [100] * 20,
        closes=[100] * 20 + [90] + [95] * 20,
    )

    result = label_bottom_candidates(frame)

    assert bool(result.iloc[20]["isCandidate"])
    assert not bool(result.iloc[20]["isPositiveBottom"])


def test_incomplete_future_window_does_not_create_a_label() -> None:
    frame = synthetic_ohlc(
        lows=[100] * 20 + [90] + [91] * 19,
        highs=[101] * 20 + [92] + [100] * 19,
        closes=[100] * 20 + [90] + [95] * 19,
    )

    result = label_bottom_candidates(frame)
    row = result.iloc[20]

    assert bool(row["isCandidate"])
    assert not bool(row["isPositiveBottom"])
    assert pd.isna(row["labelEndDate"])
    assert pd.isna(row["futureMinLow"])
    assert pd.isna(row["futureMaxHigh"])


def test_label_cutoff_uses_future_source_rows_without_emitting_test_d() -> None:
    frame = synthetic_ohlc(
        lows=[100] * 20 + [90] + [91] * 20,
        highs=[101] * 20 + [92] + [100] * 20,
        closes=[100] * 20 + [90] + [95] * 20,
    )
    cutoff = frame.index[20]

    result = label_bottom_candidates(frame, d_cutoff=cutoff)

    assert result.index.max() == cutoff
    assert len(result) == 21
    assert bool(result.loc[cutoff, "isPositiveBottom"])


def test_period_assignment_purges_label_windows_crossing_boundaries() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2019-12-01",
                    "2019-12-20",
                    "2020-01-02",
                    "2022-12-20",
                    "2023-01-03",
                ]
            ),
            "labelEndDate": pd.to_datetime(
                [
                    "2019-12-30",
                    "2020-01-20",
                    "2020-02-01",
                    "2023-01-20",
                    "2023-02-01",
                ]
            ),
        }
    )

    assert assign_periods(frame).tolist() == [
        "train",
        "purged",
        "validation",
        "purged",
        "test",
    ]


def test_period_assignment_excludes_after_fixed_test_end_and_purges_censoring() -> None:
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-08-01", "2026-08-07", "2026-08-08"]
            ),
            "labelEndDate": pd.to_datetime(
                ["2026-08-07", None, "2026-08-28"]
            ),
        }
    )

    assert assign_periods(frame).tolist() == ["test", "purged", "excluded"]


def test_stock_features_are_unchanged_when_future_prices_change() -> None:
    raw = synthetic_trending_ohlcv(320)
    before = build_stock_features(raw).iloc[250].copy()
    changed = raw.copy()
    changed.loc[
        changed.index[251:],
        ["Open", "High", "Low", "Close", "Volume"],
    ] *= 10

    after = build_stock_features(changed).iloc[250]

    pd.testing.assert_series_equal(before, after, check_names=False)


def test_stock_feature_units_match_the_plan() -> None:
    raw = synthetic_trending_ohlcv(320)
    raw["qqqRet20"] = 0.01

    features = build_stock_features(raw)
    row = features.iloc[-1]
    close = raw["Close"]
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    lower = ma20 - 2 * std20
    upper = ma20 + 2 * std20

    assert row["ret20"] == pytest.approx(close.pct_change(20).iloc[-1])
    assert row["distMA20"] == pytest.approx(close.iloc[-1] / ma20.iloc[-1] - 1)
    assert row["rs20"] == pytest.approx(row["ret20"] - 0.01)
    assert row["pctB"] == pytest.approx(
        (close.iloc[-1] - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]) * 100
    )
    assert abs(row["atrPct"]) < 1
    assert abs(row["gapPct"]) < 1


def test_rs20_optional_series_is_aligned_to_stock_dates() -> None:
    raw = synthetic_trending_ohlcv(320)
    aligned_dates = raw.index[::2]
    qqq_ret20 = pd.Series(
        np.linspace(-0.05, 0.05, len(aligned_dates)),
        index=aligned_dates,
    )

    features = build_stock_features(raw, qqq_ret20=qqq_ret20)
    observed_date = aligned_dates[-1]
    missing_date = raw.index[-1]

    assert features.loc[observed_date, "rs20"] == pytest.approx(
        features.loc[observed_date, "ret20"] - qqq_ret20.loc[observed_date]
    )
    assert missing_date not in qqq_ret20.index
    assert pd.isna(features.loc[missing_date, "rs20"])


@pytest.mark.parametrize(
    ("bad_index", "message"),
    [
        (
            pd.DatetimeIndex(["2024-01-02", "2024-01-01"]),
            "monotonically increasing",
        ),
        (
            pd.DatetimeIndex(["2024-01-01", "2024-01-01"]),
            "duplicate dates",
        ),
    ],
)
def test_stock_features_reject_invalid_datetime_index(
    bad_index: pd.DatetimeIndex,
    message: str,
) -> None:
    raw = synthetic_trending_ohlcv(2)
    raw.index = bad_index

    with pytest.raises(ValueError, match=message):
        build_stock_features(raw)


def test_breadth_is_same_date_cross_section_only() -> None:
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    frames = {
        "A": pd.DataFrame(
            {
                "below200": [True, True],
                "rsi": [20, 20],
                "dd60": [-0.5, -0.5],
            },
            index=dates,
        ),
        "B": pd.DataFrame(
            {
                "below200": [False, True],
                "rsi": [40, 20],
                "dd60": [-0.1, -0.5],
            },
            index=dates,
        ),
    }

    breadth = build_breadth(frames)

    assert breadth.loc[dates[0], "breadthBelow200"] == 0.5
    assert breadth.loc[dates[0], "breadthRsi30"] == 0.5
    assert breadth.loc[dates[0], "breadthDd40"] == 0.5
    assert breadth.loc[dates[1], "breadthBelow200"] == 1.0
    assert breadth.loc[dates[1], "breadthRsi30"] == 1.0
    assert breadth.loc[dates[1], "breadthDd40"] == 1.0


def test_ma200_warmup_is_excluded_from_breadth_denominator() -> None:
    raw = synthetic_trending_ohlcv(200)
    features = build_stock_features(raw)
    date = raw.index[198]
    observed = pd.DataFrame(
        {"below200": [True], "rsi": [20], "dd60": [-0.5]},
        index=[date],
    )

    assert pd.isna(features.loc[date, "below200"])
    assert features.loc[date, "daysBelow200"] == 0

    breadth = build_breadth(
        {
            "warmup": features.loc[[date], ["below200", "rsi", "dd60"]],
            "observed": observed,
        }
    )

    assert breadth.loc[date, "breadthBelow200"] == 1.0


def test_market_features_use_exact_dates_and_only_vix_forward_fills() -> None:
    qqq = synthetic_trending_ohlcv(260)
    missing_date = qqq.index[-2]
    prior_date = qqq.index[-3]
    vix = pd.DataFrame(
        {"Close": [20.0, 30.0]},
        index=[prior_date, qqq.index[-1]],
    )
    breadth = pd.DataFrame(
        {
            "breadthBelow200": [0.4],
            "breadthRsi30": [0.3],
            "breadthDd40": [0.2],
        },
        index=[qqq.index[-1]],
    )

    result = build_market_features(qqq, vix, breadth)

    assert result.loc[missing_date, "vix"] == 20.0
    assert pd.isna(result.loc[missing_date, "breadthBelow200"])
    assert result.loc[qqq.index[-1], "breadthBelow200"] == 0.4
    expected_premium = (
        qqq["Close"].iloc[-1] / qqq["Close"].rolling(200).mean().iloc[-1] - 1
    ) * 100
    assert result["qqqPremium"].iloc[-1] == pytest.approx(expected_premium)
    assert result.attrs["calendarCaveat"]


def test_rule_is_candidate_low_and_all_conditions() -> None:
    frame = pd.DataFrame(
        {
            "isCandidate": [True, True, False],
            "rsi": [24, 35, 20],
            "dd60": [-0.5, -0.5, -0.5],
        }
    )
    rule = Rule(
        (
            Condition("RSI≤25", "rsi", "<=", 25),
            Condition("60일낙폭≤-40%", "dd60", "<=", -0.40),
        )
    )

    assert apply_rule(frame, rule).tolist() == [True, False, False]


def test_condition_library_uses_fixed_domain_thresholds() -> None:
    conditions = condition_library()

    assert len(conditions) == 59
    assert conditions[:5] == [
        Condition("rsi≤20", "rsi", "<=", 20.0),
        Condition("rsi≤25", "rsi", "<=", 25.0),
        Condition("rsi≤30", "rsi", "<=", 30.0),
        Condition("rsi≤35", "rsi", "<=", 35.0),
        Condition("rsi≤40", "rsi", "<=", 40.0),
    ]
    assert Condition("vix≥30", "vix", ">=", 30.0) in conditions


def test_discover_rule_accepts_only_train_and_validation() -> None:
    signature = inspect.signature(discover_rule)

    assert list(signature.parameters) == ["train", "validation", "max_conditions"]


def test_discover_rule_selects_best_candidate_and_audits_metrics() -> None:
    train = rule_discovery_frame(rows=200, qualifying_rows=100)
    validation = rule_discovery_frame(rows=100, qualifying_rows=50)

    rule, audit = discover_rule(train, validation, max_conditions=1)

    assert rule == Rule((Condition("rsi≤25", "rsi", "<=", 25.0),))
    selected = audit.loc[
        (audit["recordType"] == "candidate") & audit["accepted"]
    ].iloc[0]
    assert selected["step"] == 1
    assert selected["candidate"] == "rsi≤25"
    assert selected["trainEvents"] == 100
    assert selected["trainPrecision"] == pytest.approx(0.8)
    assert selected["trainPrecisionLift"] == pytest.approx(0.4)
    assert selected["validationEvents"] == 50
    assert selected["validationPrecision"] == pytest.approx(0.8)
    assert selected["validationPrecisionLift"] == pytest.approx(0.4)
    assert selected["validationD20ExcessMean"] == pytest.approx(0.01)
    assert selected["reason"] == "selected"
    assert audit.iloc[-1]["recordType"] == "final"
    assert not bool(audit.iloc[-1]["stable"])


def test_discover_rule_rejects_candidate_below_event_minimum() -> None:
    train = rule_discovery_frame(rows=200, qualifying_rows=99)
    validation = rule_discovery_frame(rows=100, qualifying_rows=29)

    rule, audit = discover_rule(train, validation, max_conditions=1)

    candidate = audit.loc[
        (audit["recordType"] == "candidate")
        & (audit["candidate"] == "rsi≤25")
    ].iloc[0]
    assert rule.conditions == ()
    assert not bool(candidate["accepted"])
    assert candidate["reason"] == "insufficient_events"


def test_discover_rule_requires_label_end_date() -> None:
    train = rule_discovery_frame(rows=200, qualifying_rows=100).drop(
        columns="labelEndDate"
    )
    validation = rule_discovery_frame(rows=100, qualifying_rows=50)

    with pytest.raises(ValueError, match="labelEndDate"):
        discover_rule(train, validation, max_conditions=1)


def test_discover_rule_excludes_incomplete_labels_and_missing_d20() -> None:
    train = rule_discovery_frame(rows=201, qualifying_rows=101)
    validation = rule_discovery_frame(rows=101, qualifying_rows=51)
    train.loc[0, "isPositiveBottom"] = False
    validation.loc[0, "isPositiveBottom"] = False
    train.loc[0, "labelEndDate"] = pd.NaT
    validation.loc[0, "labelEndDate"] = pd.NaT
    train.loc[1, "d20Excess"] = np.nan
    validation.loc[1, "d20Excess"] = np.nan

    _, audit = discover_rule(train, validation, max_conditions=1)

    selected = audit.loc[
        (audit["recordType"] == "candidate") & audit["accepted"]
    ].iloc[0]
    assert selected["trainEvents"] == 100
    assert selected["validationEvents"] == 50
    assert selected["validationD20ExcessMean"] == pytest.approx(0.01)


@pytest.mark.parametrize(
    ("train_positives", "validation_positives", "reason"),
    [
        (50, 60, "non_positive_train_precision_lift"),
        (60, 50, "non_positive_validation_precision_lift"),
    ],
)
def test_discover_rule_requires_positive_lift_in_both_splits(
    train_positives: int,
    validation_positives: int,
    reason: str,
) -> None:
    train = rule_discovery_frame(rows=200, qualifying_rows=100)
    validation = rule_discovery_frame(rows=200, qualifying_rows=100)
    set_binary_condition_outcomes(
        train,
        qualifying_rows=100,
        qualifying_positives=train_positives,
        other_positives=100 - train_positives,
    )
    set_binary_condition_outcomes(
        validation,
        qualifying_rows=100,
        qualifying_positives=validation_positives,
        other_positives=100 - validation_positives,
    )

    rule, audit = discover_rule(train, validation, max_conditions=1)

    candidate = audit.loc[
        (audit["recordType"] == "candidate")
        & (audit["candidate"] == "rsi≤25")
    ].iloc[0]
    assert rule.conditions == ()
    assert candidate["reason"] == reason


@pytest.mark.parametrize("validation_excess", [0.0, -0.001])
def test_discover_rule_rejects_non_positive_validation_excess(
    validation_excess: float,
) -> None:
    train = rule_discovery_frame(rows=200, qualifying_rows=100)
    validation = rule_discovery_frame(rows=200, qualifying_rows=100)
    for frame in (train, validation):
        set_binary_condition_outcomes(
            frame,
            qualifying_rows=100,
            qualifying_positives=60,
            other_positives=40,
        )
    validation.loc[:99, "d20Excess"] = validation_excess

    rule, audit = discover_rule(train, validation, max_conditions=1)

    candidate = audit.loc[
        (audit["recordType"] == "candidate")
        & (audit["candidate"] == "rsi≤25")
    ].iloc[0]
    assert rule.conditions == ()
    assert candidate["reason"] == "non_positive_validation_d20_excess"


@pytest.mark.parametrize(
    ("qualifying_positives", "other_positives", "accepted"),
    [(52, 48, True), (51, 49, False)],
)
def test_discover_rule_enforces_two_point_lift_improvement_boundary(
    qualifying_positives: int,
    other_positives: int,
    accepted: bool,
) -> None:
    train = rule_discovery_frame(rows=200, qualifying_rows=100)
    validation = rule_discovery_frame(rows=200, qualifying_rows=100)
    for frame in (train, validation):
        set_binary_condition_outcomes(
            frame,
            qualifying_rows=100,
            qualifying_positives=qualifying_positives,
            other_positives=other_positives,
        )

    rule, audit = discover_rule(train, validation, max_conditions=1)

    candidate = audit.loc[
        (audit["recordType"] == "candidate")
        & (audit["candidate"] == "rsi≤25")
    ].iloc[0]
    assert bool(candidate["accepted"]) is accepted
    assert bool(rule.conditions) is accepted
    if not accepted:
        assert candidate["reason"] == "lift_improvement_below_2pp"


@pytest.mark.parametrize(
    ("intersection_excess", "second_condition_selected"),
    [(0.008, True), (0.0079, False)],
)
def test_discover_rule_enforces_validation_excess_decline_boundary(
    intersection_excess: float,
    second_condition_selected: bool,
) -> None:
    train = two_condition_frame(intersection_excess=0.01)
    validation = two_condition_frame(intersection_excess=intersection_excess)

    rule, audit = discover_rule(train, validation, max_conditions=2)

    second = audit.loc[
        (audit["recordType"] == "candidate")
        & (audit["step"] == 2)
        & (audit["candidate"] == "dd60≤-0.4")
    ].iloc[0]
    assert (len(rule.conditions) == 2) is second_condition_selected
    assert bool(second["accepted"]) is second_condition_selected
    assert second["validationBaselineD20ExcessMean"] == pytest.approx(0.01)
    assert second["validationCurrentD20ExcessMean"] == pytest.approx(0.01)
    assert second["validationCandidateD20ExcessMean"] == pytest.approx(
        intersection_excess
    )
    assert second["validationD20ExcessDecline"] == pytest.approx(
        0.01 - intersection_excess
    )
    assert second["validationBaselinePrecision"] == pytest.approx(0.4)
    assert second["validationCurrentPrecision"] == pytest.approx(0.5)
    assert second["validationCurrentPrecisionLift"] == pytest.approx(0.1)
    if not second_condition_selected:
        assert second["reason"] == "validation_d20_excess_decline"


def test_discover_rule_marks_only_three_or_more_conditions_stable() -> None:
    train = three_condition_frame()
    validation = three_condition_frame()

    two_condition_rule, two_condition_audit = discover_rule(
        train,
        validation,
        max_conditions=2,
    )
    stable_rule, stable_audit = discover_rule(
        train,
        validation,
        max_conditions=3,
    )

    assert len(two_condition_rule.conditions) == 2
    assert not bool(two_condition_audit.iloc[-1]["stable"])
    assert len(stable_rule.conditions) == 3
    assert bool(stable_audit.iloc[-1]["stable"])
    assert stable_audit.attrs["stable"] is True


def test_frozen_rule_round_trip_is_deterministic(tmp_path: Path) -> None:
    rule = Rule(
        (
            Condition("RSI≤25", "rsi", "<=", 25),
            Condition("60일낙폭≤-40%", "dd60", "<=", -0.40),
        )
    )
    first_path = tmp_path / "rule.json"
    second_path = tmp_path / "rule-copy.json"

    save_frozen_rule(rule, str(first_path))
    loaded = load_frozen_rule(str(first_path))
    save_frozen_rule(loaded, str(second_path))

    assert loaded == rule
    assert first_path.read_bytes() == second_path.read_bytes()


def test_event_path_enters_next_open_and_charges_both_sides() -> None:
    raw = tiny_ohlc(
        open_=[100, 110],
        high=[101, 121],
        low=[99, 109],
        close=[100, 120],
    )

    event = event_path(raw, signal_index=0, horizon=1, fee=0.001)

    expected = 120 * 0.999 / (110 * 1.001) - 1
    assert event["d1"] == pytest.approx(expected)
    assert event["signalIndex"] == 0
    assert event["signalDate"] == raw.index[0]
    assert event["entryIndex"] == 1
    assert event["entryDate"] == raw.index[1]
    assert event["exitIndex"] == 1
    assert event["exitDate"] == raw.index[1]
    assert event["reason"] == "horizon"


def test_event_path_returns_nan_for_unobserved_horizons() -> None:
    raw = tiny_ohlc(
        open_=[100, 100, 100],
        high=[101, 102, 103],
        low=[99, 98, 97],
        close=[100, 101, 102],
    )

    event = event_path(raw, signal_index=1, horizon=2)

    assert event["d1"] == pytest.approx(102 * 0.999 / (100 * 1.001) - 1)
    assert pd.isna(event["d2"])
    assert event["exitIndex"] is None
    assert pd.isna(event["exitDate"])
    assert event["reason"] == "censored"


def test_event_path_reports_cumulative_mfe_and_mae() -> None:
    raw = tiny_ohlc(
        open_=[100, 100, 100],
        high=[101, 110, 105],
        low=[99, 95, 90],
        close=[100, 102, 101],
    )

    event = event_path(raw, signal_index=0, horizon=2)
    entry = 100 * 1.001

    assert event["mfe1"] == pytest.approx(110 / entry - 1)
    assert event["mfe2"] == pytest.approx(110 / entry - 1)
    assert event["mae1"] == pytest.approx(95 / entry - 1)
    assert event["mae2"] == pytest.approx(90 / entry - 1)


def test_event_path_censors_all_horizons_after_first_incomplete_ohlc() -> None:
    raw = tiny_ohlc(
        open_=[100, 100, 100, 100],
        high=[101, 110, np.nan, 120],
        low=[99, 95, 94, 90],
        close=[100, 102, 103, 110],
    )

    event = event_path(raw, signal_index=0, horizon=3)

    assert pd.notna(event["d1"])
    assert pd.notna(event["mfe1"])
    assert pd.notna(event["mae1"])
    for day in (2, 3):
        assert pd.isna(event[f"d{day}"])
        assert pd.isna(event[f"mfe{day}"])
        assert pd.isna(event[f"mae{day}"])
    assert event["reason"] == "censored"
    assert event["exitIndex"] is None
    assert pd.isna(event["exitDate"])


def test_event_path_exact_twenty_day_horizon_has_time_exit() -> None:
    raw = tiny_ohlc(
        open_=[100] * 21,
        high=[101 + day for day in range(21)],
        low=[99] * 21,
        close=[100 + day for day in range(21)],
    )

    event = event_path(raw, signal_index=0, horizon=20)

    assert event["d20"] == pytest.approx(120 * 0.999 / (100 * 1.001) - 1)
    assert event["exitIndex"] == 20
    assert event["exitDate"] == raw.index[20]
    assert event["reason"] == "horizon"


def test_same_day_target_and_stop_uses_stop_first_and_sell_fee() -> None:
    raw = tiny_ohlc(
        open_=[100, 100],
        high=[101, 120],
        low=[99, 80],
        close=[100, 110],
    )

    trade = simulate_exit(raw, 0, target=0.10, stop=0.10, horizon=1)

    entry = 100 * 1.001
    stop_price = entry * 0.90
    assert trade["reason"] == "stop"
    assert trade["days"] == 1
    assert trade["return"] == pytest.approx(stop_price * 0.999 / entry - 1)
    assert trade["exitPrice"] == pytest.approx(stop_price * 0.999)
    assert trade["exitIndex"] == 1
    assert trade["exitDate"] == raw.index[1]


def test_target_exit_uses_barrier_price_and_sell_fee() -> None:
    raw = tiny_ohlc(
        open_=[100, 100],
        high=[101, 120],
        low=[99, 99],
        close=[100, 105],
    )

    trade = simulate_exit(raw, 0, target=0.10, stop=None, horizon=1)

    entry = 100 * 1.001
    target_price = entry * 1.10
    assert trade["reason"] == "target"
    assert trade["return"] == pytest.approx(target_price * 0.999 / entry - 1)
    assert trade["exitPrice"] == pytest.approx(target_price * 0.999)


def test_unhit_barriers_exit_at_horizon_close_with_sell_fee() -> None:
    raw = tiny_ohlc(
        open_=[100, 100, 100],
        high=[101, 105, 106],
        low=[99, 96, 95],
        close=[100, 102, 104],
    )

    trade = simulate_exit(raw, 0, target=0.20, stop=0.10, horizon=2)

    assert trade["reason"] == "horizon"
    assert trade["days"] == 2
    assert trade["return"] == pytest.approx(104 * 0.999 / (100 * 1.001) - 1)
    assert trade["exitIndex"] == 2
    assert trade["exitDate"] == raw.index[2]


def test_simulate_exit_right_censors_incomplete_horizon() -> None:
    raw = tiny_ohlc(
        open_=[100, 100],
        high=[101, 105],
        low=[99, 96],
        close=[100, 102],
    )

    trade = simulate_exit(raw, 0, target=0.20, stop=None, horizon=2)

    assert trade["reason"] == "censored"
    assert pd.isna(trade["return"])
    assert pd.isna(trade["days"])
    assert trade["exitIndex"] is None
    assert pd.isna(trade["exitDate"])


@pytest.mark.parametrize("target", [0.10, 0.15, 0.20])
@pytest.mark.parametrize("stop", [None, 0.10, 0.15])
def test_simulate_exit_accepts_all_orchestrator_variants(
    target: float,
    stop: float | None,
) -> None:
    raw = tiny_ohlc(
        open_=[100, 100],
        high=[101, 101],
        low=[99, 99],
        close=[100, 100],
    )

    trade = simulate_exit(raw, 0, target=target, stop=stop, horizon=1)

    assert trade["target"] == target
    assert pd.isna(trade["stop"]) if stop is None else trade["stop"] == stop


@pytest.mark.parametrize("parameter", ["target", "stop"])
@pytest.mark.parametrize("bad_value", [np.nan, np.inf, True, -0.10, 1.0, 1.10])
def test_simulate_exit_rejects_invalid_barriers(
    parameter: str,
    bad_value: object,
) -> None:
    raw = tiny_ohlc(
        open_=[100, 100],
        high=[101, 101],
        low=[99, 99],
        close=[100, 100],
    )
    arguments: dict[str, object] = {
        "signal_index": 0,
        "target": 0.10,
        "stop": 0.10,
        "horizon": 1,
    }
    arguments[parameter] = bad_value

    with pytest.raises((TypeError, ValueError), match=parameter):
        simulate_exit(raw, **arguments)


def test_episode_signals_uses_fixed_window_or_actual_exit_index() -> None:
    dates = pd.bdate_range("2024-01-02", periods=30)
    mask = pd.Series(False, index=dates)
    mask.iloc[[0, 5, 20, 21, 25]] = True

    assert episode_signals(mask) == [0, 21]

    exits = pd.Series({0: 5, 20: 21, 25: 29}, dtype="Int64")
    assert episode_signals(mask, exits=exits) == [0, 20, 25]


def test_episode_signals_validates_exit_indices() -> None:
    mask = pd.Series([True, False], index=pd.bdate_range("2024-01-02", periods=2))

    with pytest.raises(ValueError, match="before signal"):
        episode_signals(mask, exits=pd.Series({0: -1}))


def test_episode_signals_uses_exit_indices_from_simulated_trades() -> None:
    raw = tiny_ohlc(
        open_=[100] * 7,
        high=[101, 101, 120, 101, 120, 101, 120],
        low=[99] * 7,
        close=[100] * 7,
    )
    mask = pd.Series([True, True, True, True, True, True, False], index=raw.index)
    exit_indices = pd.Series(
        {
            signal_index: simulate_exit(
                raw,
                signal_index,
                target=0.10,
                stop=None,
                horizon=2,
            )["exitIndex"]
            for signal_index in np.flatnonzero(mask.to_numpy())
        },
        dtype="Int64",
    )

    assert episode_signals(mask, exits=exit_indices) == [0, 3, 5]


@pytest.mark.parametrize(
    ("function_name", "kwargs", "message"),
    [
        ("event_path", {"signal_index": True}, "signal_index"),
        ("event_path", {"horizon": 0}, "horizon"),
        ("event_path", {"fee": 1.0}, "fee"),
        ("simulate_exit", {"target": 0.0}, "target"),
        ("simulate_exit", {"stop": 0.0}, "stop"),
    ],
)
def test_event_functions_validate_inputs(
    function_name: str,
    kwargs: dict[str, object],
    message: str,
) -> None:
    raw = tiny_ohlc(
        open_=[100, 100],
        high=[101, 101],
        low=[99, 99],
        close=[100, 100],
    )
    if function_name == "event_path":
        arguments: dict[str, object] = {
            "signal_index": 0,
            "horizon": 1,
            "fee": 0.001,
        }
        arguments.update(kwargs)
        with pytest.raises((TypeError, ValueError), match=message):
            event_path(raw, **arguments)
    else:
        arguments = {
            "signal_index": 0,
            "target": 0.10,
            "stop": None,
            "horizon": 1,
            "fee": 0.001,
        }
        arguments.update(kwargs)
        with pytest.raises((TypeError, ValueError), match=message):
            simulate_exit(raw, **arguments)


def test_summarize_paths_has_all_horizons_and_required_statistics() -> None:
    events = pd.DataFrame(
        {
            "signalDate": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "ticker": ["A", "B"],
            "d1": [0.10, -0.10],
            "d2": [0.20, np.nan],
            "qqqEx1": [0.08, -0.12],
            "qqqEx2": [0.15, np.nan],
            "universeEx1": [0.05, -0.15],
            "universeEx2": [0.10, np.nan],
            "mfe1": [0.15, 0.02],
            "mfe2": [0.25, np.nan],
            "mae1": [-0.02, -0.20],
            "mae2": [-0.03, np.nan],
        }
    )

    summary = summarize_paths(events)

    assert summary["day"].tolist() == list(range(1, 21))
    assert {
        "events",
        "signalDates",
        "tickers",
        "mean",
        "median",
        "winRate",
        "p25",
        "p75",
        "qqqExcess",
        "universeExcess",
        "MFE",
        "MAE",
    }.issubset(summary.columns)
    day1 = summary.loc[summary["day"] == 1].iloc[0]
    assert day1["events"] == 2
    assert day1["signalDates"] == 1
    assert day1["tickers"] == 2
    assert day1["mean"] == pytest.approx(0.0)
    assert day1["winRate"] == pytest.approx(0.5)
    assert day1["qqqExcess"] == pytest.approx(-0.02)
    assert day1["universeExcess"] == pytest.approx(-0.05)
    day2 = summary.loc[summary["day"] == 2].iloc[0]
    assert day2["events"] == 1
    assert summary.loc[summary["day"] == 3, "events"].iloc[0] == 0


def test_summarize_paths_never_restores_event_after_missing_horizon() -> None:
    events = pd.DataFrame(
        {
            "signalDate": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "ticker": ["A", "B"],
            "d1": [0.01, 0.01],
            "d2": [np.nan, 0.02],
            "d3": [0.03, 0.03],
            "mfe1": [0.02, 0.02],
            "mfe2": [np.nan, 0.03],
            "mfe3": [0.04, 0.04],
            "mae1": [-0.01, -0.01],
            "mae2": [np.nan, -0.02],
            "mae3": [-0.03, -0.03],
        }
    )

    summary = summarize_paths(events)

    assert summary.loc[summary["day"].isin([1, 2, 3]), "events"].tolist() == [
        2,
        1,
        1,
    ]
    day3 = summary.loc[summary["day"] == 3].iloc[0]
    assert day3["MFE"] == pytest.approx(0.04)
    assert day3["MAE"] == pytest.approx(-0.03)


def test_summarize_exits_reports_required_metrics_and_excludes_censored() -> None:
    trades = pd.DataFrame(
        {
            "target": [0.10] * 5,
            "stop": [0.10] * 5,
            "reason": ["target", "stop", "target", "horizon", "censored"],
            "days": [2, 1, 4, 20, np.nan],
            "return": [0.10, -0.10, 0.20, -0.05, np.nan],
            "exitDate": pd.to_datetime(
                ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", None]
            ),
        }
    )

    summary = summarize_exits(trades)

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["trades"] == 4
    assert row["censored"] == 1
    assert row["targetHitRate"] == pytest.approx(0.5)
    assert row["medianHitDay"] == pytest.approx(3.0)
    assert row["winRate"] == pytest.approx(0.5)
    assert row["mean"] == pytest.approx(0.0375)
    assert row["median"] == pytest.approx(0.025)
    assert row["profitFactor"] == pytest.approx(2.0)
    assert row["PF"] == pytest.approx(2.0)
    assert row["averageWin"] == pytest.approx(0.15)
    assert row["avgWin"] == pytest.approx(0.15)
    assert row["averageLoss"] == pytest.approx(-0.075)
    assert row["avgLoss"] == pytest.approx(-0.075)
    assert row["payoffRatio"] == pytest.approx(2.0)
    assert row["maxLosingStreak"] == 1
    expected_equity = pd.Series([1.10, 0.99, 1.188, 1.1286])
    expected_drawdown = (expected_equity / expected_equity.cummax() - 1).min()
    assert row["equityMaxDrawdown"] == pytest.approx(expected_drawdown)


@pytest.mark.parametrize(
    "trades",
    [
        pd.DataFrame(),
        pd.DataFrame(columns=["reason", "days", "return", "target", "stop"]),
    ],
)
def test_summarize_exits_returns_fixed_schema_for_empty_inputs(
    trades: pd.DataFrame,
) -> None:
    summary = summarize_exits(trades)

    assert summary.empty
    assert summary.columns.tolist() == [
        "variant",
        "strategy",
        "period",
        "universe",
        "target",
        "stop",
        "trades",
        "censored",
        "targetHitRate",
        "medianHitDay",
        "winRate",
        "mean",
        "median",
        "PF",
        "profitFactor",
        "avgWin",
        "averageWin",
        "avgLoss",
        "averageLoss",
        "payoffRatio",
        "maxLosingStreak",
        "equityMaxDrawdown",
    ]
