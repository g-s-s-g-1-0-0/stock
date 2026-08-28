"""Pure point-in-time helpers for the bottom-rebound study."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from calculator import market_regime
from calculator.indicators import add_indicators


_TRAIN_START = pd.Timestamp("2001-01-01")
_TRAIN_END = pd.Timestamp("2019-12-31")
_VALIDATION_END = pd.Timestamp("2022-12-31")
_TEST_START = pd.Timestamp("2023-01-01")
_TEST_END = pd.Timestamp("2026-08-07")

_BREADTH_COLUMNS = (
    "breadthBelow200",
    "breadthRsi30",
    "breadthDd40",
)

_CONDITION_THRESHOLDS = {
    "rsi": ("<=", [20, 25, 30, 35, 40]),
    "cci": ("<=", [-200, -150, -100]),
    "williamsR": ("<=", [-95, -90, -80]),
    "adx": (">=", [20, 25, 30, 40]),
    "diSpread": ("<=", [-20, -10, 0]),
    "pctB": ("<=", [0, 5, 20]),
    "ret1": ("<=", [-0.07, -0.05, -0.03]),
    "ret5": ("<=", [-0.15, -0.10, -0.05]),
    "ret20": ("<=", [-0.30, -0.20, -0.10]),
    "dd60": ("<=", [-0.50, -0.40, -0.30, -0.20]),
    "dd252": ("<=", [-0.60, -0.50, -0.40, -0.30]),
    "distMA200": ("<=", [-0.20, -0.10, 0.0]),
    "volRatio20": (">=", [1.0, 1.5, 2.0]),
    "atrPct": (">=", [0.03, 0.05, 0.08]),
    "rs20": ("<=", [-0.20, -0.10, 0.0]),
    "qqqPremium": ("<=", [-3, 0, 9]),
    "qqqRsi": ("<=", [30, 40, 50]),
    "vix": (">=", [18, 22, 30]),
}

_MIN_TRAIN_EVENTS = 100
_MIN_VALIDATION_EVENTS = 30
_MIN_LIFT_IMPROVEMENT = 0.02
_MAX_VALIDATION_EXCESS_DECLINE = 0.002


@dataclass(frozen=True)
class Condition:
    """One deterministic, interpretable threshold condition."""

    name: str
    column: str
    operator: str
    threshold: float

    def __post_init__(self) -> None:
        if self.operator not in {"<=", ">="}:
            raise ValueError(f"unsupported condition operator: {self.operator}")
        object.__setattr__(self, "threshold", float(self.threshold))


@dataclass(frozen=True)
class Rule:
    """An ordered conjunction of conditions."""

    conditions: tuple[Condition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "conditions", tuple(self.conditions))


def _require_datetime_index(frame: pd.DataFrame | pd.Series) -> None:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("frame must use a DatetimeIndex")
    if not frame.index.is_monotonic_increasing:
        raise ValueError("DatetimeIndex must be monotonically increasing")
    if frame.index.has_duplicates:
        raise ValueError("DatetimeIndex must not contain duplicate dates")


def _require_columns(frame: pd.DataFrame, columns: set[str]) -> None:
    missing = sorted(columns.difference(frame.columns))
    if missing:
        raise ValueError(f"missing required columns: {', '.join(missing)}")


def condition_library() -> list[Condition]:
    """Return the fixed, ordered domain-threshold search space."""

    operator_symbols = {"<=": "≤", ">=": "≥"}
    return [
        Condition(
            name=f"{column}{operator_symbols[operator]}{float(threshold):g}",
            column=column,
            operator=operator,
            threshold=float(threshold),
        )
        for column, (operator, thresholds) in _CONDITION_THRESHOLDS.items()
        for threshold in thresholds
    ]


def apply_rule(frame: pd.DataFrame, rule: Rule) -> pd.Series:
    """Apply the candidate-low gate and every condition in ``rule``."""

    _require_columns(
        frame,
        {"isCandidate", *(condition.column for condition in rule.conditions)},
    )
    mask = frame["isCandidate"].eq(True).fillna(False)
    for condition in rule.conditions:
        values = pd.to_numeric(frame[condition.column], errors="coerce")
        if condition.operator == "<=":
            comparison = values.le(condition.threshold)
        elif condition.operator == ">=":
            comparison = values.ge(condition.threshold)
        else:
            raise ValueError(f"unsupported condition operator: {condition.operator}")
        mask &= comparison.fillna(False)
    return mask.astype(bool)


def _complete_labeled_candidates(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["isCandidate"].eq(True).fillna(False)
        & frame["isPositiveBottom"].notna()
        & frame["labelEndDate"].notna()
    )


def _rule_metrics(
    frame: pd.DataFrame,
    rule: Rule,
    baseline_precision: float,
) -> dict[str, float | int]:
    event_mask = apply_rule(frame, rule) & _complete_labeled_candidates(frame)
    events = int(event_mask.sum())
    labels = frame.loc[event_mask, "isPositiveBottom"].eq(True)
    precision = float(labels.mean()) if events else np.nan
    d20_excess = pd.to_numeric(
        frame.loc[event_mask, "d20Excess"],
        errors="coerce",
    )
    return {
        "events": events,
        "precision": precision,
        "precisionLift": precision - baseline_precision,
        "d20ExcessMean": float(d20_excess.mean()),
    }


def discover_rule(
    train: pd.DataFrame,
    validation: pd.DataFrame,
    max_conditions: int = 5,
) -> tuple[Rule, pd.DataFrame]:
    """Greedily select a frozen rule using Train and Validation only."""

    if (
        isinstance(max_conditions, bool)
        or not isinstance(max_conditions, int)
        or not 1 <= max_conditions <= 5
    ):
        raise ValueError("max_conditions must be an integer from 1 through 5")

    conditions = condition_library()
    required_columns = {
        "isCandidate",
        "isPositiveBottom",
        "labelEndDate",
        "d20Excess",
        *(condition.column for condition in conditions),
    }
    _require_columns(train, required_columns)
    _require_columns(validation, required_columns)

    train_baseline_mask = _complete_labeled_candidates(train)
    validation_baseline_mask = _complete_labeled_candidates(validation)
    train_baseline_precision = float(
        train.loc[train_baseline_mask, "isPositiveBottom"].eq(True).mean()
    )
    validation_baseline_precision = float(
        validation.loc[
            validation_baseline_mask,
            "isPositiveBottom",
        ].eq(True).mean()
    )
    validation_baseline_excess = float(
        pd.to_numeric(
            validation.loc[validation_baseline_mask, "d20Excess"],
            errors="coerce",
        ).mean()
    )

    selected: list[Condition] = []
    audit_rows: list[dict[str, object]] = []

    for step in range(1, max_conditions + 1):
        current_rule = Rule(tuple(selected))
        current_train_metrics = _rule_metrics(
            train,
            current_rule,
            train_baseline_precision,
        )
        current_validation_metrics = _rule_metrics(
            validation,
            current_rule,
            validation_baseline_precision,
        )
        current_min_lift = min(
            float(current_train_metrics["precisionLift"]),
            float(current_validation_metrics["precisionLift"]),
        )
        current_validation_excess = float(
            current_validation_metrics["d20ExcessMean"]
        )
        step_rows: list[dict[str, object]] = []
        eligible: list[tuple[float, int, Condition, int]] = []
        for library_index, condition in enumerate(conditions):
            if condition in selected:
                continue

            proposed_rule = Rule((*selected, condition))
            train_metrics = _rule_metrics(
                train,
                proposed_rule,
                train_baseline_precision,
            )
            validation_metrics = _rule_metrics(
                validation,
                proposed_rule,
                validation_baseline_precision,
            )
            min_lift = min(
                float(train_metrics["precisionLift"]),
                float(validation_metrics["precisionLift"]),
            )
            validation_excess_decline = (
                current_validation_excess
                - float(validation_metrics["d20ExcessMean"])
            )

            reason = "eligible"
            if (
                train_metrics["events"] < _MIN_TRAIN_EVENTS
                or validation_metrics["events"] < _MIN_VALIDATION_EVENTS
            ):
                reason = "insufficient_events"
            elif not float(train_metrics["precisionLift"]) > 0:
                reason = "non_positive_train_precision_lift"
            elif not float(validation_metrics["precisionLift"]) > 0:
                reason = "non_positive_validation_precision_lift"
            elif not float(validation_metrics["d20ExcessMean"]) > 0:
                reason = "non_positive_validation_d20_excess"
            elif not min_lift + 1e-12 >= (
                current_min_lift + _MIN_LIFT_IMPROVEMENT
            ):
                reason = "lift_improvement_below_2pp"
            elif (
                np.isfinite(current_validation_excess)
                and validation_excess_decline
                > _MAX_VALIDATION_EXCESS_DECLINE + 1e-12
            ):
                reason = "validation_d20_excess_decline"

            row: dict[str, object] = {
                "recordType": "candidate",
                "step": step,
                "candidate": condition.name,
                "column": condition.column,
                "operator": condition.operator,
                "threshold": condition.threshold,
                "trainEvents": train_metrics["events"],
                "trainPrecision": train_metrics["precision"],
                "trainBaselinePrecision": train_baseline_precision,
                "trainPrecisionLift": train_metrics["precisionLift"],
                "trainCurrentPrecision": current_train_metrics["precision"],
                "trainCurrentPrecisionLift": current_train_metrics[
                    "precisionLift"
                ],
                "trainCandidatePrecision": train_metrics["precision"],
                "trainCandidatePrecisionLift": train_metrics["precisionLift"],
                "validationEvents": validation_metrics["events"],
                "validationPrecision": validation_metrics["precision"],
                "validationBaselinePrecision": validation_baseline_precision,
                "validationPrecisionLift": validation_metrics["precisionLift"],
                "validationCurrentPrecision": current_validation_metrics[
                    "precision"
                ],
                "validationCurrentPrecisionLift": current_validation_metrics[
                    "precisionLift"
                ],
                "validationCandidatePrecision": validation_metrics["precision"],
                "validationCandidatePrecisionLift": validation_metrics[
                    "precisionLift"
                ],
                "validationD20ExcessMean": validation_metrics["d20ExcessMean"],
                "validationBaselineD20ExcessMean": validation_baseline_excess,
                "validationCurrentD20ExcessMean": current_validation_excess,
                "validationCandidateD20ExcessMean": validation_metrics[
                    "d20ExcessMean"
                ],
                "validationD20ExcessDecline": validation_excess_decline,
                "minPrecisionLift": min_lift,
                "accepted": False,
                "reason": reason,
                "stable": pd.NA,
            }
            row_index = len(step_rows)
            step_rows.append(row)
            if reason == "eligible":
                eligible.append(
                    (min_lift, library_index, condition, row_index)
                )

        if not eligible:
            audit_rows.extend(step_rows)
            break

        _, _, best_condition, best_row_index = max(
            eligible,
            key=lambda candidate: (candidate[0], -candidate[1]),
        )
        for _, _, _, row_index in eligible:
            step_rows[row_index]["reason"] = "lower_ranked_candidate"
        best_row = step_rows[best_row_index]
        best_row["accepted"] = True
        best_row["reason"] = "selected"
        audit_rows.extend(step_rows)

        selected.append(best_condition)

    final_rule = Rule(tuple(selected))
    final_train_metrics = _rule_metrics(
        train,
        final_rule,
        train_baseline_precision,
    )
    final_validation_metrics = _rule_metrics(
        validation,
        final_rule,
        validation_baseline_precision,
    )
    stable = len(final_rule.conditions) >= 3
    audit_rows.append(
        {
            "recordType": "final",
            "step": len(final_rule.conditions),
            "candidate": " & ".join(
                condition.name for condition in final_rule.conditions
            ),
            "column": pd.NA,
            "operator": pd.NA,
            "threshold": np.nan,
            "trainEvents": final_train_metrics["events"],
            "trainPrecision": final_train_metrics["precision"],
            "trainBaselinePrecision": train_baseline_precision,
            "trainPrecisionLift": final_train_metrics["precisionLift"],
            "trainCurrentPrecision": final_train_metrics["precision"],
            "trainCurrentPrecisionLift": final_train_metrics["precisionLift"],
            "trainCandidatePrecision": final_train_metrics["precision"],
            "trainCandidatePrecisionLift": final_train_metrics["precisionLift"],
            "validationEvents": final_validation_metrics["events"],
            "validationPrecision": final_validation_metrics["precision"],
            "validationBaselinePrecision": validation_baseline_precision,
            "validationPrecisionLift": final_validation_metrics[
                "precisionLift"
            ],
            "validationCurrentPrecision": final_validation_metrics["precision"],
            "validationCurrentPrecisionLift": final_validation_metrics[
                "precisionLift"
            ],
            "validationCandidatePrecision": final_validation_metrics[
                "precision"
            ],
            "validationCandidatePrecisionLift": final_validation_metrics[
                "precisionLift"
            ],
            "validationD20ExcessMean": final_validation_metrics[
                "d20ExcessMean"
            ],
            "validationBaselineD20ExcessMean": validation_baseline_excess,
            "validationCurrentD20ExcessMean": final_validation_metrics[
                "d20ExcessMean"
            ],
            "validationCandidateD20ExcessMean": final_validation_metrics[
                "d20ExcessMean"
            ],
            "validationD20ExcessDecline": 0.0,
            "minPrecisionLift": min(
                float(final_train_metrics["precisionLift"]),
                float(final_validation_metrics["precisionLift"]),
            ),
            "accepted": stable,
            "reason": (
                "stable_rule_found" if stable else "no_stable_rule_found"
            ),
            "stable": stable,
        }
    )
    audit = pd.DataFrame(audit_rows)
    audit.attrs["stable"] = stable
    audit.attrs["message"] = (
        "stable rule found" if stable else "no stable rule found"
    )
    return final_rule, audit


def save_frozen_rule(rule: Rule, path: str) -> None:
    """Serialize an ordered rule to deterministic UTF-8 JSON."""

    payload = {
        "conditions": [
            {
                "name": condition.name,
                "column": condition.column,
                "operator": condition.operator,
                "threshold": condition.threshold,
            }
            for condition in rule.conditions
        ]
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    )
    Path(path).write_text(f"{serialized}\n", encoding="utf-8")


def load_frozen_rule(path: str) -> Rule:
    """Load a rule written by :func:`save_frozen_rule`."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(
        payload.get("conditions"),
        list,
    ):
        raise ValueError("frozen rule JSON must contain a conditions list")
    try:
        conditions = tuple(
            Condition(
                name=item["name"],
                column=item["column"],
                operator=item["operator"],
                threshold=item["threshold"],
            )
            for item in payload["conditions"]
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid frozen rule condition") from error
    return Rule(conditions)


def label_bottom_candidates(
    frame: pd.DataFrame,
    lookback: int = 20,
    horizon: int = 20,
    rebound: float = 0.10,
    d_cutoff: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Attach complete-window training labels to 20-session-low candidates."""

    _require_datetime_index(frame)
    _require_columns(frame, {"Low", "High", "Close"})
    if lookback <= 0 or horizon <= 0:
        raise ValueError("lookback and horizon must be positive")
    if rebound < 0:
        raise ValueError("rebound must be non-negative")

    source = frame
    if d_cutoff is None:
        out = source.copy()
    else:
        cutoff = pd.Timestamp(d_cutoff)
        out = source.loc[source.index <= cutoff].copy()
    prior_low = source["Low"].rolling(lookback).min().shift(1).reindex(out.index)
    out["isCandidate"] = out["Low"].le(prior_low).fillna(False)

    future_min = np.full(len(out), np.nan)
    future_max = np.full(len(out), np.nan)
    end_dates = np.full(len(out), np.datetime64("NaT"), dtype="datetime64[ns]")

    source_positions = source.index.get_indexer(out.index)
    for output_index, source_index in enumerate(source_positions):
        window = source.iloc[source_index + 1 : source_index + 1 + horizon]
        complete = (
            len(window) == horizon
            and window[["Low", "High"]].notna().all().all()
        )
        if not complete:
            continue
        future_min[output_index] = float(window["Low"].min())
        future_max[output_index] = float(window["High"].max())
        end_dates[output_index] = window.index[-1].to_datetime64()

    out["futureMinLow"] = future_min
    out["futureMaxHigh"] = future_max
    out["labelEndDate"] = pd.to_datetime(end_dates)
    out["isPositiveBottom"] = (
        out["isCandidate"]
        & out["labelEndDate"].notna()
        & out["futureMinLow"].ge(out["Low"])
        & out["futureMaxHigh"].ge(out["Close"] * (1 + rebound))
    )
    return out


def assign_periods(frame: pd.DataFrame) -> pd.Series:
    """Assign chronological splits and purge labels crossing split boundaries."""

    _require_columns(frame, {"labelEndDate"})
    if "date" in frame:
        dates = pd.to_datetime(frame["date"])
    elif isinstance(frame.index, pd.DatetimeIndex):
        _require_datetime_index(frame)
        dates = pd.Series(frame.index, index=frame.index)
    else:
        raise ValueError("frame must contain date or use a DatetimeIndex")

    label_ends = pd.to_datetime(frame["labelEndDate"])
    result = pd.Series("excluded", index=frame.index, dtype="object", name="period")

    complete = label_ends.notna()
    train_dates = dates.between(_TRAIN_START, _TRAIN_END)
    validation_dates = dates.between(_TRAIN_END + pd.Timedelta(days=1), _VALIDATION_END)
    test_dates = dates.between(_TEST_START, _TEST_END)

    result.loc[train_dates & complete & label_ends.le(_TRAIN_END)] = "train"
    result.loc[
        validation_dates & complete & label_ends.le(_VALIDATION_END)
    ] = "validation"
    result.loc[test_dates & complete & label_ends.le(_TEST_END)] = "test"

    crossed_boundary = (
        (train_dates & (~complete | label_ends.gt(_TRAIN_END)))
        | (validation_dates & (~complete | label_ends.gt(_VALIDATION_END)))
        | (test_dates & (~complete | label_ends.gt(_TEST_END)))
    )
    result.loc[crossed_boundary] = "purged"
    return result


def build_stock_features(
    raw: pd.DataFrame,
    qqq_ret20: pd.Series | None = None,
) -> pd.DataFrame:
    """Build D-close stock features using current and earlier rows only."""

    _require_datetime_index(raw)
    _require_columns(raw, {"Open", "High", "Low", "Close", "Volume"})

    out = add_indicators(raw)
    close = out["Close"]
    high = out["High"]
    low = out["Low"]
    open_ = out["Open"]

    out["rsi"] = out["RSI"]
    out["cci"] = out["CCI"]
    out["macdHist"] = out["MACD_Hist"]
    out["macdDelta1"] = out["MACD_Hist"].diff()
    out["macdDelta2"] = out["MACD_Hist"].diff(2)
    out["adx"] = out["ADX"]
    out["adxDelta1"] = out["ADX"].diff()
    out["plusDI"] = out["PlusDI"]
    out["minusDI"] = out["MinusDI"]
    out["diSpread"] = out["PlusDI"] - out["MinusDI"]

    for period in (20, 60, 144):
        out[f"MA{period}"] = close.rolling(period).mean()
    for period in (20, 60, 144, 200):
        ma = out[f"MA{period}"]
        out[f"distMA{period}"] = close / ma.replace(0, np.nan) - 1
    for period in (20, 60, 200):
        ma = out[f"MA{period}"]
        out[f"slopeMA{period}"] = ma / ma.shift(5).replace(0, np.nan) - 1

    for period in (1, 5, 20, 60):
        out[f"ret{period}"] = close.pct_change(period, fill_method=None)
    for period in (60, 252):
        out[f"dd{period}"] = close / close.rolling(period).max() - 1

    if qqq_ret20 is not None:
        _require_datetime_index(qqq_ret20)
        benchmark_ret20 = pd.to_numeric(qqq_ret20, errors="coerce").reindex(out.index)
        out["rs20"] = out["ret20"] - benchmark_ret20
    elif "qqqRet20" in raw:
        out["rs20"] = out["ret20"] - pd.to_numeric(
            raw["qqqRet20"], errors="coerce"
        )
    else:
        out["rs20"] = np.nan

    high14 = high.rolling(14).max()
    low14 = low.rolling(14).min()
    range14 = (high14 - low14).replace(0, np.nan)
    out["williamsR"] = (close - high14) / range14 * 100
    out["pctB"] = out["PctB"]
    out["bbWidthNorm"] = out["BB_Width"] / out["MA20"].replace(0, np.nan)
    out["volRatio20"] = out["Volume"] / out["Volume"].rolling(20).mean().replace(
        0, np.nan
    )

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atrPct"] = true_range.rolling(14).mean() / close.replace(0, np.nan)
    out["gapPct"] = open_ / previous_close.replace(0, np.nan) - 1

    scale = close.abs().replace(0, np.nan)
    candle_top = pd.concat([open_, close], axis=1).max(axis=1)
    candle_bottom = pd.concat([open_, close], axis=1).min(axis=1)
    out["candleBody"] = (close - open_) / scale
    out["candleBodyAbs"] = (close - open_).abs() / scale
    out["upperWick"] = (high - candle_top) / scale
    out["lowerWick"] = (candle_bottom - low) / scale
    out["candleRange"] = (high - low) / scale

    out["below200"] = close.lt(out["MA200"]).astype("boolean").mask(
        close.isna() | out["MA200"].isna()
    )
    consecutive_days: list[int] = []
    current_run = 0
    for is_below in out["below200"].array:
        if pd.isna(is_below):
            current_run = 0
        else:
            current_run = current_run + 1 if bool(is_below) else 0
        consecutive_days.append(current_run)
    out["daysBelow200"] = consecutive_days
    return out


def build_breadth(
    feature_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Compute exact-date cross-sectional breadth without temporal filling."""

    if not feature_frames:
        return pd.DataFrame(columns=_BREADTH_COLUMNS, dtype=float)

    rows: list[pd.DataFrame] = []
    for frame in feature_frames.values():
        _require_datetime_index(frame)
        _require_columns(frame, {"below200", "rsi", "dd60"})
        below = pd.to_numeric(frame["below200"], errors="coerce")
        rsi = pd.to_numeric(frame["rsi"], errors="coerce")
        drawdown = pd.to_numeric(frame["dd60"], errors="coerce")
        rows.append(
            pd.DataFrame(
                {
                    "breadthBelow200": below,
                    "breadthRsi30": rsi.lt(30).where(rsi.notna()),
                    "breadthDd40": drawdown.le(-0.40).where(drawdown.notna()),
                },
                index=frame.index,
            )
        )

    combined = pd.concat(rows)
    return combined.groupby(level=0).mean().sort_index()


def build_market_features(
    qqq: pd.DataFrame,
    vix: pd.DataFrame,
    breadth: pd.DataFrame,
) -> pd.DataFrame:
    """Build QQQ/VIX/breadth features on exact QQQ cache dates."""

    _require_datetime_index(qqq)
    _require_datetime_index(vix)
    _require_datetime_index(breadth)
    _require_columns(qqq, {"Open", "High", "Low", "Close", "Volume"})
    _require_columns(vix, {"Close"})
    _require_columns(breadth, set(_BREADTH_COLUMNS))

    qqq_features = add_indicators(qqq)
    out = pd.DataFrame(index=qqq.index)
    out["qqqPremium"] = (
        qqq_features["Close"] / qqq_features["MA200"].replace(0, np.nan) - 1
    ) * 100
    recent_min = out["qqqPremium"].rolling(60, min_periods=1).min()
    recovery = recent_min.le(market_regime.QQQ_RECOVERY_MIN_DIST) & out[
        "qqqPremium"
    ].ge(0)
    out["qqqRegime"] = [
        market_regime.qqq_regime_label(premium, bool(is_recovery))
        for premium, is_recovery in zip(out["qqqPremium"], recovery, strict=True)
    ]
    out["qqqRsi"] = qqq_features["RSI"]
    out["qqqRsiMin3"] = out["qqqRsi"].rolling(3).min()
    out["qqqMacdHist"] = qqq_features["MACD_Hist"]
    out["qqqRet20"] = qqq_features["Close"].pct_change(20, fill_method=None)

    vix_close = pd.to_numeric(vix["Close"], errors="coerce").sort_index()
    combined_dates = vix_close.index.union(out.index)
    out["vix"] = vix_close.reindex(combined_dates).ffill().reindex(out.index)
    out["vixChange5"] = out["vix"].pct_change(5, fill_method=None)

    out = out.join(breadth.loc[:, list(_BREADTH_COLUMNS)], how="left")
    out.attrs["calendarCaveat"] = (
        "Stock, QQQ, VIX, and breadth are joined by stored cache date; "
        "US/KR holiday calendars can differ. Stock prices are never forward-filled; "
        "only VIX is forward-filled onto QQQ dates."
    )
    return out


def _validate_event_inputs(
    raw: pd.DataFrame,
    signal_index: int,
    horizon: int,
    fee: float,
) -> None:
    _require_datetime_index(raw)
    _require_columns(raw, {"Open", "High", "Low", "Close"})
    if (
        isinstance(signal_index, bool)
        or not isinstance(signal_index, (int, np.integer))
    ):
        raise TypeError("signal_index must be an integer")
    if not 0 <= int(signal_index) < len(raw):
        raise ValueError("signal_index is outside raw")
    if isinstance(horizon, bool) or not isinstance(horizon, (int, np.integer)):
        raise TypeError("horizon must be an integer")
    if int(horizon) <= 0:
        raise ValueError("horizon must be positive")
    if isinstance(fee, bool) or not isinstance(
        fee,
        (int, float, np.integer, np.floating),
    ):
        raise TypeError("fee must be numeric")
    if not np.isfinite(float(fee)) or not 0 <= float(fee) < 1:
        raise ValueError("fee must be between zero and one")

    prices = raw.loc[:, ["Open", "High", "Low", "Close"]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    original_non_null = raw.loc[:, ["Open", "High", "Low", "Close"]].notna()
    if (prices.isna() & original_non_null).any().any():
        raise ValueError("OHLC prices must be numeric")
    finite_values = prices.to_numpy(dtype=float)
    if np.isinf(finite_values).any():
        raise ValueError("OHLC prices must be finite")
    if (finite_values[np.isfinite(finite_values)] <= 0).any():
        raise ValueError("OHLC prices must be positive")


def _price_at(raw: pd.DataFrame, column: str, index: int) -> float:
    value = pd.to_numeric(
        pd.Series([raw.iloc[index][column]]),
        errors="coerce",
    ).iloc[0]
    return float(value) if pd.notna(value) else np.nan


def episode_signals(
    mask: pd.Series,
    exits: pd.Series | None = None,
) -> list[int]:
    """Return positional signals after enforcing one open position per ticker."""

    if not isinstance(mask, pd.Series):
        raise TypeError("mask must be a pandas Series")
    if exits is not None and not isinstance(exits, pd.Series):
        raise TypeError("exits must be a pandas Series or None")

    candidates = np.flatnonzero(mask.eq(True).fillna(False).to_numpy())
    selected: list[int] = []
    blocked_through = -1
    for candidate in candidates:
        signal_index = int(candidate)
        if signal_index <= blocked_through:
            continue

        if exits is None:
            exit_index = signal_index + 20
        else:
            signal_label = mask.index[signal_index]
            if signal_label in exits.index:
                exit_value = exits.loc[signal_label]
            elif signal_index in exits.index:
                exit_value = exits.loc[signal_index]
            elif len(exits) == len(mask):
                exit_value = exits.iloc[signal_index]
            else:
                exit_value = pd.NA

            if pd.isna(exit_value):
                exit_index = len(mask) - 1
            elif (
                isinstance(exit_value, bool)
                or not isinstance(exit_value, (int, np.integer))
            ):
                raise TypeError("exit indices must be integers")
            else:
                exit_index = int(exit_value)
                if exit_index < signal_index:
                    raise ValueError("exit index cannot be before signal index")
                if exit_index >= len(mask):
                    raise ValueError("exit index is outside mask")

        selected.append(signal_index)
        blocked_through = exit_index
    return selected


def event_path(
    raw: pd.DataFrame,
    signal_index: int,
    horizon: int = 20,
    fee: float = 0.001,
) -> dict[str, object]:
    """Build executable D+1-close paths and cumulative intraday excursions."""

    _validate_event_inputs(raw, signal_index, horizon, fee)
    signal_index = int(signal_index)
    horizon = int(horizon)
    fee = float(fee)
    entry_index = signal_index + 1
    result: dict[str, object] = {
        "signalIndex": signal_index,
        "signalDate": raw.index[signal_index],
        "entryIndex": entry_index if entry_index < len(raw) else None,
        "entryDate": (
            raw.index[entry_index] if entry_index < len(raw) else pd.NaT
        ),
        "entryPrice": np.nan,
        "exitIndex": None,
        "exitDate": pd.NaT,
        "reason": "censored",
        "availableDays": 0,
    }
    for day in range(1, horizon + 1):
        result[f"d{day}"] = np.nan
        result[f"mfe{day}"] = np.nan
        result[f"mae{day}"] = np.nan

    if entry_index >= len(raw):
        return result
    entry_open = _price_at(raw, "Open", entry_index)
    if not np.isfinite(entry_open):
        return result
    entry_price = entry_open * (1 + fee)
    result["entryPrice"] = entry_price

    running_high = -np.inf
    running_low = np.inf
    available_rows = max(0, min(horizon, len(raw) - entry_index))
    for day in range(1, available_rows + 1):
        row_index = signal_index + day
        open_ = _price_at(raw, "Open", row_index)
        close = _price_at(raw, "Close", row_index)
        high = _price_at(raw, "High", row_index)
        low = _price_at(raw, "Low", row_index)
        if not all(np.isfinite(value) for value in (open_, high, low, close)):
            break
        result["availableDays"] = day
        result[f"d{day}"] = close * (1 - fee) / entry_price - 1
        running_high = max(running_high, high)
        running_low = min(running_low, low)
        result[f"mfe{day}"] = running_high / entry_price - 1
        result[f"mae{day}"] = running_low / entry_price - 1

    horizon_index = signal_index + horizon
    if (
        result["availableDays"] == horizon
        and horizon_index < len(raw)
        and np.isfinite(_price_at(raw, "Close", horizon_index))
    ):
        result["exitIndex"] = horizon_index
        result["exitDate"] = raw.index[horizon_index]
        result["reason"] = "horizon"
    return result


def _validate_barrier(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float, np.integer, np.floating),
    ):
        raise TypeError(f"{name} must be numeric")
    numeric = float(value)
    if not np.isfinite(numeric) or not 0 < numeric < 1:
        raise ValueError(f"{name} must be between zero and one")
    return numeric


def simulate_exit(
    raw: pd.DataFrame,
    signal_index: int,
    target: float,
    stop: float | None,
    horizon: int = 20,
    fee: float = 0.001,
) -> dict[str, object]:
    """Simulate stop-first High/Low barriers and a D+horizon close exit."""

    _validate_event_inputs(raw, signal_index, horizon, fee)
    target = _validate_barrier(target, "target")
    stop_value = None if stop is None else _validate_barrier(stop, "stop")
    signal_index = int(signal_index)
    horizon = int(horizon)
    fee = float(fee)
    entry_index = signal_index + 1
    result: dict[str, object] = {
        "signalIndex": signal_index,
        "signalDate": raw.index[signal_index],
        "entryIndex": entry_index if entry_index < len(raw) else None,
        "entryDate": (
            raw.index[entry_index] if entry_index < len(raw) else pd.NaT
        ),
        "entryPrice": np.nan,
        "target": target,
        "stop": np.nan if stop_value is None else stop_value,
        "exitIndex": None,
        "exitDate": pd.NaT,
        "exitPrice": np.nan,
        "return": np.nan,
        "days": np.nan,
        "reason": "censored",
    }
    if entry_index >= len(raw):
        return result

    entry_open = _price_at(raw, "Open", entry_index)
    if not np.isfinite(entry_open):
        return result
    entry_price = entry_open * (1 + fee)
    target_price = entry_price * (1 + target)
    stop_price = (
        entry_price * (1 - stop_value) if stop_value is not None else None
    )
    result["entryPrice"] = entry_price

    available_days = min(horizon, len(raw) - entry_index)
    for day in range(1, available_days + 1):
        row_index = signal_index + day
        high = _price_at(raw, "High", row_index)
        low = _price_at(raw, "Low", row_index)
        if not np.isfinite(high) or not np.isfinite(low):
            return result

        reason: str | None = None
        barrier_price: float | None = None
        if stop_price is not None and low <= stop_price:
            reason = "stop"
            barrier_price = stop_price
        elif high >= target_price:
            reason = "target"
            barrier_price = target_price

        if reason is not None and barrier_price is not None:
            net_exit_price = barrier_price * (1 - fee)
            result.update(
                {
                    "exitIndex": row_index,
                    "exitDate": raw.index[row_index],
                    "exitPrice": net_exit_price,
                    "return": net_exit_price / entry_price - 1,
                    "days": day,
                    "reason": reason,
                }
            )
            return result

    horizon_index = signal_index + horizon
    if horizon_index >= len(raw):
        return result
    horizon_close = _price_at(raw, "Close", horizon_index)
    if not np.isfinite(horizon_close):
        return result
    net_exit_price = horizon_close * (1 - fee)
    result.update(
        {
            "exitIndex": horizon_index,
            "exitDate": raw.index[horizon_index],
            "exitPrice": net_exit_price,
            "return": net_exit_price / entry_price - 1,
            "days": horizon,
            "reason": "horizon",
        }
    )
    return result


def _summary_groups(
    frame: pd.DataFrame,
    keys: list[str],
) -> list[tuple[dict[str, object], pd.DataFrame]]:
    group_keys = [key for key in keys if key in frame.columns]
    if not group_keys:
        return [({}, frame)]
    grouped = frame.groupby(group_keys, dropna=False, sort=False)
    groups: list[tuple[dict[str, object], pd.DataFrame]] = []
    for values, group in grouped:
        value_tuple = values if isinstance(values, tuple) else (values,)
        groups.append((dict(zip(group_keys, value_tuple, strict=True)), group))
    return groups


def _excess_mean(
    sample: pd.DataFrame,
    day: int,
    prefix: str,
) -> float:
    direct_column = f"{prefix}Ex{day}"
    benchmark_column = f"{prefix}D{day}"
    if direct_column in sample:
        values = pd.to_numeric(sample[direct_column], errors="coerce")
    elif benchmark_column in sample:
        values = pd.to_numeric(sample[f"d{day}"], errors="coerce") - pd.to_numeric(
            sample[benchmark_column],
            errors="coerce",
        )
    else:
        return np.nan
    return float(values.mean())


def summarize_paths(events: pd.DataFrame) -> pd.DataFrame:
    """Summarize every executable D+1 through D+20 event horizon."""

    if not isinstance(events, pd.DataFrame):
        raise TypeError("events must be a pandas DataFrame")
    if not events.empty:
        _require_columns(events, {"signalDate", "ticker"})

    rows: list[dict[str, object]] = []
    groups = _summary_groups(
        events,
        ["variant", "strategy", "period", "universe"],
    )
    for identifiers, group in groups:
        path_eligible = pd.Series(True, index=group.index, dtype=bool)
        mfe_eligible = pd.Series(True, index=group.index, dtype=bool)
        mae_eligible = pd.Series(True, index=group.index, dtype=bool)
        for day in range(1, 21):
            return_column = f"d{day}"
            if return_column in group:
                returns = pd.to_numeric(group[return_column], errors="coerce")
                path_eligible &= returns.notna()
            else:
                returns = pd.Series(np.nan, index=group.index, dtype=float)
                path_eligible &= False
            sample = group.loc[path_eligible].copy()
            values = returns.loc[path_eligible]

            mfe_column = f"mfe{day}"
            mae_column = f"mae{day}"
            if mfe_column in group:
                mfe_values = pd.to_numeric(group[mfe_column], errors="coerce")
                mfe_eligible &= mfe_values.notna()
            else:
                mfe_values = pd.Series(np.nan, index=group.index, dtype=float)
                mfe_eligible &= False
            if mae_column in group:
                mae_values = pd.to_numeric(group[mae_column], errors="coerce")
                mae_eligible &= mae_values.notna()
            else:
                mae_values = pd.Series(np.nan, index=group.index, dtype=float)
                mae_eligible &= False
            row: dict[str, object] = {
                **identifiers,
                "day": day,
                "events": int(len(sample)),
                "signalDates": (
                    int(sample["signalDate"].nunique())
                    if "signalDate" in sample
                    else 0
                ),
                "tickers": (
                    int(sample["ticker"].nunique()) if "ticker" in sample else 0
                ),
                "mean": float(values.mean()) if not values.empty else np.nan,
                "median": float(values.median()) if not values.empty else np.nan,
                "winRate": float(values.gt(0).mean()),
                "p25": float(values.quantile(0.25)) if not values.empty else np.nan,
                "p75": float(values.quantile(0.75)) if not values.empty else np.nan,
                "qqqExcess": _excess_mean(sample, day, "qqq"),
                "universeExcess": _excess_mean(sample, day, "universe"),
                "MFE": float(mfe_values.loc[path_eligible & mfe_eligible].mean()),
                "MAE": float(mae_values.loc[path_eligible & mae_eligible].mean()),
            }
            rows.append(row)
    return pd.DataFrame(rows)


def _max_losing_streak(returns: pd.Series) -> int:
    maximum = 0
    current = 0
    for value in returns:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


_EXIT_SUMMARY_GROUP_COLUMNS = [
    "variant",
    "strategy",
    "period",
    "universe",
    "target",
    "stop",
]
_EXIT_SUMMARY_METRIC_COLUMNS = [
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
_EXIT_SUMMARY_COLUMNS = [
    *_EXIT_SUMMARY_GROUP_COLUMNS,
    *_EXIT_SUMMARY_METRIC_COLUMNS,
]


def summarize_exits(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize exits; empty inputs return zero rows with a fixed schema."""

    if not isinstance(trades, pd.DataFrame):
        raise TypeError("trades must be a pandas DataFrame")
    if trades.empty:
        return pd.DataFrame(columns=_EXIT_SUMMARY_COLUMNS)
    _require_columns(trades, {"reason", "days", "return"})

    rows: list[dict[str, object]] = []
    groups = _summary_groups(
        trades,
        _EXIT_SUMMARY_GROUP_COLUMNS,
    )
    for identifiers, group in groups:
        if "return" in group:
            numeric_returns = pd.to_numeric(group["return"], errors="coerce")
        else:
            numeric_returns = pd.Series(np.nan, index=group.index, dtype=float)
        completed = group.loc[numeric_returns.notna()].copy()
        returns = numeric_returns.loc[numeric_returns.notna()]
        target_hits = completed["reason"].eq("target")
        hit_days = pd.to_numeric(
            completed.loc[target_hits, "days"],
            errors="coerce",
        )
        wins = returns.loc[returns > 0]
        losses = returns.loc[returns < 0]
        gross_profit = float(wins.sum())
        gross_loss = float(-losses.sum())
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = np.inf
        else:
            profit_factor = np.nan
        average_win = float(wins.mean())
        average_loss = float(losses.mean())
        payoff_ratio = (
            average_win / abs(average_loss)
            if np.isfinite(average_win)
            and np.isfinite(average_loss)
            and average_loss != 0
            else np.nan
        )

        ordered = completed.copy()
        ordered["_return"] = returns
        if "exitDate" in ordered:
            ordered = ordered.sort_values("exitDate", kind="stable")
        ordered_returns = ordered["_return"]
        equity = (1 + ordered_returns).cumprod()
        equity_with_start = pd.concat(
            [pd.Series([1.0]), equity.reset_index(drop=True)],
            ignore_index=True,
        )
        equity_drawdown = equity_with_start / equity_with_start.cummax() - 1

        row: dict[str, object] = {
            **{
                column: identifiers.get(column, np.nan)
                for column in _EXIT_SUMMARY_GROUP_COLUMNS
            },
            **identifiers,
            "trades": int(len(completed)),
            "censored": int(len(group) - len(completed)),
            "targetHitRate": float(target_hits.mean()),
            "medianHitDay": (
                float(hit_days.median()) if not hit_days.empty else np.nan
            ),
            "winRate": float(returns.gt(0).mean()),
            "mean": float(returns.mean()),
            "median": float(returns.median()),
            "PF": profit_factor,
            "profitFactor": profit_factor,
            "avgWin": average_win,
            "averageWin": average_win,
            "avgLoss": average_loss,
            "averageLoss": average_loss,
            "payoffRatio": payoff_ratio,
            "maxLosingStreak": _max_losing_streak(ordered_returns),
            "equityMaxDrawdown": float(equity_drawdown.min()),
        }
        rows.append(row)
    return pd.DataFrame(rows, columns=_EXIT_SUMMARY_COLUMNS)
