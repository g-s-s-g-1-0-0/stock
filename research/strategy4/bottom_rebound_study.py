"""Reproducible discovery and frozen holdout runner for bottom rebounds."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
STRATEGY_DIR = Path(__file__).resolve().parent
for import_path in (ROOT, STRATEGY_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from backtest_qqq_block_v2 import UNIVERSE  # noqa: E402
from research.strategy4.bottom_rebound_core import (  # noqa: E402
    Rule,
    apply_rule,
    assign_periods,
    build_breadth,
    build_market_features,
    build_stock_features,
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
from research.strategy4.ma200_macd_golden import CACHE, dl  # noqa: E402


FEE = 0.001
HORIZON = 20
TARGETS = (0.10, 0.15, 0.20)
STOPS = (None, 0.10, 0.15)
DEFAULT_OUT_DIR = ROOT / "analysis_tmp"
WATCHLIST_MAP = Path(CACHE) / "s4_watchlist_map.json"

FROZEN_RULE_FILE = "bottom_rebound_frozen_rule.json"
METADATA_FILE = "bottom_rebound_metadata.json"
TEST_LOCK_FILE = "bottom_rebound_test_lock.json"
MIN_TRAIN_EVENTS = 100
MIN_VALIDATION_EVENTS = 30

FEATURE_COLUMNS = [
    "rsi",
    "cci",
    "williamsR",
    "macdHist",
    "macdDelta1",
    "macdDelta2",
    "adx",
    "adxDelta1",
    "plusDI",
    "minusDI",
    "diSpread",
    "distMA20",
    "distMA60",
    "distMA144",
    "distMA200",
    "slopeMA20",
    "slopeMA60",
    "slopeMA200",
    "ret1",
    "ret5",
    "ret20",
    "ret60",
    "dd60",
    "dd252",
    "rs20",
    "pctB",
    "bbWidthNorm",
    "volRatio20",
    "atrPct",
    "gapPct",
    "candleBody",
    "candleBodyAbs",
    "upperWick",
    "lowerWick",
    "candleRange",
    "below200",
    "daysBelow200",
    "qqqPremium",
    "qqqRegime",
    "qqqRsi",
    "qqqRsiMin3",
    "qqqMacdHist",
    "qqqRet20",
    "vix",
    "vixChange5",
    "breadthBelow200",
    "breadthRsi30",
    "breadthDd40",
]

SPLITS = {
    "train": ["2001-01-01", "2019-12-31"],
    "validation": ["2020-01-01", "2022-12-31"],
    "test": ["2023-01-01", "2026-08-07"],
}


def load_discovery_universe() -> list[str]:
    """Return the declared universe; availability is recorded by build_panel."""

    return sorted(set(UNIVERSE))


def load_watchlist() -> dict[str, str]:
    """Load the frozen ticker-to-Yahoo-symbol watchlist mapping."""

    if not WATCHLIST_MAP.exists():
        raise FileNotFoundError(f"watchlist map not found: {WATCHLIST_MAP}")
    payload = json.loads(WATCHLIST_MAP.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in payload.items()
    ):
        raise ValueError("s4_watchlist_map.json must contain a string mapping")
    return dict(sorted(payload.items()))


def _country(symbol: str) -> str:
    return "KR" if symbol.endswith((".KS", ".KQ")) else "US"


def _clean_raw(raw: pd.DataFrame | None) -> pd.DataFrame | None:
    if raw is None or raw.empty:
        return None
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(raw.columns):
        return None
    cleaned = raw.loc[:, required].copy()
    cleaned.index = pd.to_datetime(cleaned.index).tz_localize(None)
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")].sort_index()
    cleaned = cleaned.apply(pd.to_numeric, errors="coerce").dropna()
    return cleaned if len(cleaned) > HORIZON else None


def _source_end(
    index: pd.DatetimeIndex,
    cutoff: pd.Timestamp | None,
) -> pd.Timestamp:
    if cutoff is None:
        return index.max()
    future_sessions = index[index > cutoff][:HORIZON]
    return (
        future_sessions[-1]
        if len(future_sessions) == HORIZON
        else index.max()
    )


def _d20_return(
    raw: pd.DataFrame,
    d_index: pd.DatetimeIndex,
) -> pd.Series:
    positions = raw.index.get_indexer(d_index)
    values = np.full(len(d_index), np.nan)
    complete = (positions >= 0) & (positions + HORIZON < len(raw))
    valid_positions = positions[complete]
    entries = raw["Open"].to_numpy()[valid_positions + 1] * (1 + FEE)
    exits = raw["Close"].to_numpy()[valid_positions + HORIZON] * (1 - FEE)
    values[complete] = exits / entries - 1
    return pd.Series(values, index=d_index)


def build_panel(
    symbols: dict[str, str],
    d_cutoff: str | pd.Timestamp | None = None,
    *,
    market_context: pd.DataFrame | None = None,
    universe_d20: pd.Series | None = None,
    universe_name: str = "discovery",
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Build an exact-date point-in-time panel and retain adjusted raw prices."""

    if not isinstance(symbols, dict):
        raise TypeError("symbols must be a ticker-to-symbol mapping")

    qqq_full = _clean_raw(dl("QQQ"))
    vix_full = _clean_raw(dl("^VIX"))
    if qqq_full is None or vix_full is None:
        raise RuntimeError("QQQ and VIX caches are required")
    cutoff = pd.Timestamp(d_cutoff).normalize() if d_cutoff is not None else None
    qqq_source_end = _source_end(qqq_full.index, cutoff)
    qqq = qqq_full.loc[:qqq_source_end]
    qqq_features_raw = qqq if cutoff is None else qqq.loc[:cutoff]
    vix = vix_full if cutoff is None else vix_full.loc[:cutoff]
    qqq_ret20 = qqq_features_raw["Close"].pct_change(20, fill_method=None)

    feature_frames: dict[str, pd.DataFrame] = {}
    prices: dict[str, pd.DataFrame] = {"QQQ": qqq}
    missing: list[str] = []
    cache_ends: dict[str, str] = {}
    source_ends: list[pd.Timestamp] = [qqq_source_end]
    symbol_by_ticker: dict[str, str] = {}

    for ticker, symbol in sorted(symbols.items()):
        raw_full = _clean_raw(dl(symbol))
        if raw_full is None:
            missing.append(ticker)
            continue
        ticker_source_end = _source_end(raw_full.index, cutoff)
        raw = raw_full.loc[:ticker_source_end]
        if len(raw) <= HORIZON:
            missing.append(ticker)
            continue
        prices[ticker] = raw
        symbol_by_ticker[ticker] = symbol
        cache_ends[ticker] = raw.index.max().date().isoformat()
        source_ends.append(ticker_source_end)
        feature_raw = raw if cutoff is None else raw.loc[:cutoff]
        feature_frames[ticker] = build_stock_features(
            feature_raw,
            qqq_ret20=qqq_ret20,
        )

    if not feature_frames:
        raise RuntimeError("no requested stock cache was available")

    if market_context is None:
        breadth = build_breadth(feature_frames)
        market = build_market_features(qqq_features_raw, vix, breadth)
    else:
        market = market_context.copy()
        market.index = pd.to_datetime(market.index)
        market = market.sort_index()
    frames: list[pd.DataFrame] = []
    for ticker, features in feature_frames.items():
        raw = prices[ticker]
        labels = label_bottom_candidates(raw, d_cutoff=cutoff)
        frame = features.copy()
        for column in (
            "isCandidate",
            "isPositiveBottom",
            "labelEndDate",
            "futureMinLow",
            "futureMaxHigh",
        ):
            frame[column] = labels[column]
        frame = frame.join(market, how="left")
        frame["d20Return"] = _d20_return(raw, frame.index)
        frame["date"] = frame.index
        frame["ticker"] = ticker
        frame["symbol"] = symbol_by_ticker[ticker]
        frame["country"] = _country(symbol_by_ticker[ticker])
        frame["universe"] = universe_name
        frame["period"] = assign_periods(frame)
        frames.append(frame.reset_index(drop=True))

    panel = pd.concat(frames, ignore_index=True, sort=False)
    if universe_d20 is None:
        same_date_mean = panel.groupby("date")["d20Return"].transform("mean")
        benchmark_source = "discovery universe"
    else:
        same_date_mean = pd.to_datetime(panel["date"]).map(universe_d20)
        benchmark_source = "discovery universe (external)"
    panel["d20UniverseMean"] = same_date_mean
    panel["d20Excess"] = panel["d20Return"] - same_date_mean

    panel.attrs.update(
        {
            "requestedTickerCount": len(symbols),
            "loadedTickerCount": len(feature_frames),
            "missingTickers": sorted(missing),
            "cacheEndDate": max(cache_ends.values()),
            "cacheEndDatesByTicker": cache_ends,
            "featureColumns": FEATURE_COLUMNS.copy(),
            "panelCache": "no panel cache",
            "sourceOhlcEnd": max(source_ends),
            "dCutoff": cutoff,
            "benchmarkSource": benchmark_source,
            "calendarCaveat": market.attrs.get("calendarCaveat", ""),
        }
    )
    return panel, prices


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_ready(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(
        json.dumps(
            _json_ready(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _replace_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    _write_json(temporary, payload)
    temporary.replace(path)


def _write_json_exclusive(path: Path, payload: dict[str, object]) -> None:
    serialized = (
        json.dumps(
            _json_ready(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )
    with path.open("x", encoding="utf-8") as handle:
        handle.write(serialized)
        handle.flush()


def _panel_metadata(panel: pd.DataFrame) -> dict[str, object]:
    attrs = panel.attrs
    dates = pd.to_datetime(panel["date"]) if "date" in panel else pd.Series(dtype="datetime64[ns]")
    return {
        "dataEndDate": (
            dates.max().date().isoformat() if not dates.empty else None
        ),
        "cacheEndDate": attrs.get("cacheEndDate"),
        "cacheEndDatesByTicker": attrs.get("cacheEndDatesByTicker", {}),
        "requestedTickerCount": attrs.get(
            "requestedTickerCount",
            int(panel["ticker"].nunique()) if "ticker" in panel else 0,
        ),
        "loadedTickerCount": attrs.get(
            "loadedTickerCount",
            int(panel["ticker"].nunique()) if "ticker" in panel else 0,
        ),
        "missingTickers": attrs.get("missingTickers", []),
        "panelCache": attrs.get("panelCache", "no panel cache"),
        "sourceOhlcEnd": attrs.get("sourceOhlcEnd"),
        "dCutoff": attrs.get("dCutoff"),
        "calendarCaveat": attrs.get(
            "calendarCaveat",
            "Stock, QQQ, VIX, and breadth use stored cache dates; US/KR calendars differ.",
        ),
    }


def _top5_positive_excess_share(events: pd.DataFrame) -> float:
    excess = pd.to_numeric(events["d20Excess"], errors="coerce")
    positive = events.loc[excess.gt(0), ["ticker"]].copy()
    positive["positiveExcess"] = excess.loc[excess.gt(0)]
    contributions = positive.groupby("ticker")["positiveExcess"].sum()
    total = float(contributions.sum())
    if total <= 0:
        return np.nan
    return float(contributions.nlargest(5).sum() / total)


def evaluate_stability_gate(
    rule: Rule,
    train: pd.DataFrame,
    validation: pd.DataFrame,
) -> tuple[bool, pd.DataFrame]:
    """Apply the pre-Test stability gates to a discovered rule."""

    rows: list[dict[str, object]] = []

    def record(
        check: str,
        passed: bool,
        value: object,
        threshold: object,
        split: str = "rule",
    ) -> None:
        rows.append(
            {
                "recordType": "stabilityGate",
                "split": split,
                "check": check,
                "value": value,
                "threshold": threshold,
                "passed": bool(passed),
                "reason": "passed" if passed else f"failed:{check}",
            }
        )

    columns = [condition.column for condition in rule.conditions]
    record(
        "condition_count",
        3 <= len(rule.conditions) <= 5,
        len(rule.conditions),
        "3..5",
    )
    record(
        "duplicate_feature_columns",
        len(columns) == len(set(columns)),
        len(set(columns)),
        len(columns),
    )

    for split, frame, minimum in (
        ("train", train, MIN_TRAIN_EVENTS),
        ("validation", validation, MIN_VALIDATION_EVENTS),
    ):
        selected = frame.loc[apply_rule(frame, rule)].copy()
        complete_returns = selected.loc[
            pd.to_numeric(selected["d20Excess"], errors="coerce").notna()
        ].copy()
        complete_returns["d20Excess"] = pd.to_numeric(
            complete_returns["d20Excess"],
            errors="coerce",
        )
        event_count = len(complete_returns)
        mean_excess = float(
            pd.to_numeric(complete_returns["d20Excess"], errors="coerce").mean()
        )
        record(
            "minimum_events",
            event_count >= minimum,
            event_count,
            minimum,
            split,
        )
        record(
            "positive_d20_excess",
            np.isfinite(mean_excess) and mean_excess > 0,
            mean_excess,
            ">0",
            split,
        )

        complete_returns["year"] = pd.to_datetime(
            complete_returns["date"]
        ).dt.year
        yearly = complete_returns.groupby("year")["d20Excess"].agg(
            ["size", "mean"]
        )
        eligible_years = yearly.loc[yearly["size"] >= 5]
        positive_year_ratio = (
            float(eligible_years["mean"].gt(0).mean())
            if not eligible_years.empty
            else 0.0
        )
        record(
            "positive_year_ratio",
            positive_year_ratio >= 0.50,
            positive_year_ratio,
            ">=0.50 among years with >=5 signals",
            split,
        )

        top5_share = _top5_positive_excess_share(complete_returns)
        record(
            "top5_positive_excess_share",
            np.isfinite(top5_share) and top5_share <= 0.60,
            top5_share,
            "<=0.60",
            split,
        )

    audit = pd.DataFrame(rows)
    return bool(audit["passed"].all()), audit


def _raw_signal_mask(
    rows: pd.DataFrame,
    raw: pd.DataFrame,
    selected: pd.Series,
) -> pd.Series:
    mask = pd.Series(False, index=raw.index, dtype=bool)
    selected_dates = pd.to_datetime(rows.loc[selected, "date"])
    mask.loc[mask.index.intersection(selected_dates)] = True
    return mask


def _selected_rows(
    panel: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    selected: pd.Series,
) -> pd.DataFrame:
    chosen: list[pd.DataFrame] = []
    for ticker, rows in panel.groupby("ticker", sort=False):
        raw = prices.get(ticker)
        if raw is None:
            continue
        local_selected = selected.reindex(rows.index, fill_value=False)
        raw_mask = _raw_signal_mask(rows, raw, local_selected)
        signal_positions = episode_signals(raw_mask)
        dates = raw.index[signal_positions]
        chosen.append(rows.loc[rows["date"].isin(dates)])
    if not chosen:
        return panel.iloc[0:0].copy()
    return pd.concat(chosen, ignore_index=True)


def _summary_row(
    period: str,
    strategy: str,
    rows: pd.DataFrame,
) -> dict[str, object]:
    returns = pd.to_numeric(rows.get("d20Return"), errors="coerce")
    excess = pd.to_numeric(rows.get("d20Excess"), errors="coerce")
    complete_labels = rows.loc[
        rows.get("labelEndDate", pd.Series(index=rows.index, dtype=object)).notna()
    ]
    labels = complete_labels.get(
        "isPositiveBottom",
        pd.Series(dtype=bool),
    ).eq(True)
    return {
        "period": period,
        "strategy": strategy,
        "events": len(rows),
        "signalDates": rows["date"].nunique() if not rows.empty else 0,
        "tickers": rows["ticker"].nunique() if not rows.empty else 0,
        "labelEvents": len(complete_labels),
        "labelPrecision": float(labels.mean()),
        "d20Mean": float(returns.mean()),
        "d20Median": float(returns.median()),
        "d20WinRate": float(returns.gt(0).mean()),
        "d20ExcessMean": float(excess.mean()),
    }


def _discovery_summary(
    panel: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    rule: Rule,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for period in ("train", "validation"):
        sample = panel.loc[panel["period"].eq(period)].copy()
        for strategy, mask in (
            ("baseline", sample["isCandidate"].eq(True)),
            ("final", apply_rule(sample, rule)),
        ):
            selected = _selected_rows(sample, prices, mask)
            rows.append(_summary_row(period, strategy, selected))
    return pd.DataFrame(rows)


def run_discovery(
    panel: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    out_dir: str,
) -> Rule:
    """Discover on Train/Validation only and freeze only a stable 3–5 rule."""

    required = {"period", "date", "ticker", "isCandidate"}
    missing = required.difference(panel.columns)
    if missing:
        raise ValueError(f"panel missing required columns: {', '.join(sorted(missing))}")
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    rule_path = output / FROZEN_RULE_FILE
    lock_path = output / TEST_LOCK_FILE
    if rule_path.exists():
        raise RuntimeError("frozen rule already exists; discovery overwrite refused")
    if lock_path.exists():
        raise RuntimeError("Test lock exists; discovery overwrite refused")
    if pd.to_datetime(panel["date"]).ge("2023-01-01").any():
        raise ValueError("discovery panel must not materialize D dates in Test")
    train = panel.loc[panel["period"].eq("train")].copy()
    validation = panel.loc[panel["period"].eq("validation")].copy()
    rule, audit = discover_rule(train, validation)
    discovered_stable = bool(audit.attrs.get("stable", False))
    if "stable" in audit and not audit.empty:
        discovered_stable = discovered_stable or bool(audit.iloc[-1]["stable"])
    gate_passed, gate_audit = evaluate_stability_gate(rule, train, validation)
    stable = discovered_stable and gate_passed
    audit = pd.concat([audit, gate_audit], ignore_index=True, sort=False)
    audit.to_csv(output / "bottom_rebound_condition_audit.csv", index=False)

    frozen_hash: str | None = None
    if stable:
        save_frozen_rule(rule, str(rule_path))
        frozen_hash = _sha256(rule_path)

    summary = _discovery_summary(panel, prices, rule)
    summary.to_csv(
        output / "bottom_rebound_train_validation_summary.csv",
        index=False,
    )
    metadata = {
        **_panel_metadata(panel),
        "split": SPLITS,
        "feePerSide": FEE,
        "entry": "D+1 open",
        "label": (
            "20-session new low at D; no lower low through D+20; "
            "future High reaches D Close +10%"
        ),
        "featureColumns": panel.attrs.get("featureColumns", FEATURE_COLUMNS),
        "outcomeColumnsExcludedFromFeatures": [
            "isPositiveBottom",
            "labelEndDate",
            "futureMinLow",
            "futureMaxHigh",
            "d20Return",
            "d20UniverseMean",
            "d20Excess",
        ],
        "frozenRuleSha256": frozen_hash,
        "stableRule": stable,
        "conditionCount": len(rule.conditions),
        "stabilityGatePassed": gate_passed,
        "stabilityGateFailures": gate_audit.loc[
            ~gate_audit["passed"]
        ].reindex(
            columns=["split", "check", "value", "threshold"]
        ).to_dict("records"),
        "survivorshipBias": (
            "Uses the current declared UNIVERSE and current watchlist mapping; "
            "historical delisted constituents are unavailable."
        ),
        "priceSource": (
            "Yahoo daily cache; OHLC adjusted by adjclose/close where fetched "
            "by fetch_full_history.py."
        ),
    }
    _write_json(output / METADATA_FILE, metadata)
    if not stable:
        raise RuntimeError("no stable rule found; Test remains unopened")
    return rule


def _validate_frozen_rule(
    out_dir: str,
    expected_rule: Rule | None = None,
) -> Rule:
    output = Path(out_dir)
    rule_path = output / FROZEN_RULE_FILE
    metadata_path = output / METADATA_FILE
    if not rule_path.exists() or not metadata_path.exists():
        raise RuntimeError("frozen rule and metadata are required before Test")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected_hash = metadata.get("frozenRuleSha256")
    if not isinstance(expected_hash, str) or not expected_hash:
        raise RuntimeError("frozen rule hash is missing from metadata")
    actual_hash = _sha256(rule_path)
    if actual_hash != expected_hash:
        raise RuntimeError("frozen rule hash mismatch")
    loaded = load_frozen_rule(str(rule_path))
    if not 3 <= len(loaded.conditions) <= 5:
        raise RuntimeError("frozen rule must have 3 through 5 conditions")
    if expected_rule is not None and loaded != expected_rule:
        raise RuntimeError("provided rule does not match frozen rule")
    return loaded


def _create_test_lock(
    output: Path,
    rule_hash: str,
    data_end: object,
) -> Path:
    lock_path = output / TEST_LOCK_FILE
    payload = {
        "status": "running",
        "ruleSha256": rule_hash,
        "dataEnd": data_end,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "completedAt": None,
        "outputSha256": {},
    }
    try:
        _write_json_exclusive(lock_path, payload)
    except FileExistsError as error:
        raise RuntimeError("Test lock already exists; repeat Test refused") from error
    return lock_path


def _update_test_lock(
    lock_path: Path,
    status: str,
    **updates: object,
) -> None:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    payload.update(updates)
    payload["status"] = status
    if status in {"completed", "failed"}:
        payload["completedAt"] = datetime.now(timezone.utc).isoformat()
    _replace_json(lock_path, payload)


def _scope_frames(panel: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    if "universe" in panel:
        watch_mask = panel["universe"].eq("watchlist")
    else:
        watch_mask = pd.Series(False, index=panel.index)
    discovery = panel.loc[~watch_mask].copy()
    discovery_dates = pd.to_datetime(discovery["date"])
    scopes = [
        (
            "final_test",
            discovery.loc[discovery_dates.ge("2023-01-01")].copy(),
        ),
        ("full_period_diagnostic", discovery),
    ]
    watchlist = panel.loc[watch_mask].copy()
    if not watchlist.empty:
        scopes.append(("watchlist_diagnostic", watchlist))
    return scopes


def _strategy_masks(frame: pd.DataFrame, rule: Rule) -> Iterable[tuple[str, pd.Series]]:
    yield "baseline", frame["isCandidate"].eq(True).fillna(False)
    yield "final", apply_rule(frame, rule)


def _row_for_date(rows: pd.DataFrame, date: pd.Timestamp) -> pd.Series:
    matched = rows.loc[pd.to_datetime(rows["date"]).eq(date)]
    return matched.iloc[0]


def _event_metadata(
    row: pd.Series,
    scope: str,
    strategy: str,
) -> dict[str, object]:
    signal_date = pd.Timestamp(row["date"])
    return {
        "scope": scope,
        "variant": scope,
        "strategy": strategy,
        "period": row.get("period", "diagnostic"),
        "universe": row.get("universe", "discovery"),
        "ticker": row["ticker"],
        "symbol": row.get("symbol", row["ticker"]),
        "country": row.get("country", "US"),
        "year": signal_date.year,
        "qqqRegime": row.get("qqqRegime", np.nan),
        "isPositiveBottom": row.get("isPositiveBottom", False),
        "labelEndDate": row.get("labelEndDate", pd.NaT),
    }


def _path_events(
    frame: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    rule: Rule,
    scope: str,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for strategy, selected in _strategy_masks(frame, rule):
        for ticker, rows in frame.groupby("ticker", sort=False):
            raw = prices.get(ticker)
            if raw is None:
                continue
            local = selected.reindex(rows.index, fill_value=False)
            raw_mask = _raw_signal_mask(rows, raw, local)
            for signal_index in episode_signals(raw_mask):
                row = _row_for_date(rows, raw.index[signal_index])
                records.append(
                    {
                        **event_path(raw, signal_index, HORIZON, FEE),
                        **_event_metadata(row, scope, strategy),
                    }
                )
    return pd.DataFrame(records)


def _benchmark_paths(
    frame: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    dates: Iterable[pd.Timestamp],
) -> tuple[dict[int, dict[pd.Timestamp, float]], dict[int, dict[pd.Timestamp, float]]]:
    requested_dates = {pd.Timestamp(date) for date in dates}
    universe_values: dict[int, dict[pd.Timestamp, list[float]]] = {
        day: {} for day in range(1, HORIZON + 1)
    }
    tickers = frame["ticker"].drop_duplicates().tolist()
    for ticker in tickers:
        raw = prices.get(ticker)
        if raw is None:
            continue
        positions = {date: index for index, date in enumerate(raw.index)}
        for date in requested_dates:
            signal_index = positions.get(date)
            if signal_index is None:
                continue
            record = event_path(raw, signal_index, HORIZON, FEE)
            for day in range(1, HORIZON + 1):
                value = record[f"d{day}"]
                if pd.notna(value):
                    universe_values[day].setdefault(date, []).append(float(value))
    universe = {
        day: {
            date: float(np.mean(values))
            for date, values in date_values.items()
        }
        for day, date_values in universe_values.items()
    }

    qqq: dict[int, dict[pd.Timestamp, float]] = {
        day: {} for day in range(1, HORIZON + 1)
    }
    qqq_raw = prices.get("QQQ")
    if qqq_raw is not None:
        positions = {date: index for index, date in enumerate(qqq_raw.index)}
        for date in requested_dates:
            signal_index = positions.get(date)
            if signal_index is None:
                continue
            record = event_path(qqq_raw, signal_index, HORIZON, FEE)
            for day in range(1, HORIZON + 1):
                value = record[f"d{day}"]
                if pd.notna(value):
                    qqq[day][date] = float(value)
    return universe, qqq


def _attach_benchmarks(
    events: pd.DataFrame,
    universe: dict[int, dict[pd.Timestamp, float]],
    qqq: dict[int, dict[pd.Timestamp, float]],
) -> pd.DataFrame:
    if events.empty:
        return events
    out = events.copy()
    signal_dates = pd.to_datetime(out["signalDate"])
    benchmark_columns: dict[str, pd.Series] = {}
    for day in range(1, HORIZON + 1):
        returns = (
            pd.to_numeric(out[f"d{day}"], errors="coerce")
            if f"d{day}" in out
            else pd.Series(np.nan, index=out.index)
        )
        universe_values = signal_dates.map(universe[day])
        qqq_values = signal_dates.map(qqq[day])
        benchmark_columns[f"d{day}"] = returns
        benchmark_columns[f"universeD{day}"] = universe_values
        benchmark_columns[f"universeEx{day}"] = returns - universe_values
        benchmark_columns[f"qqqD{day}"] = qqq_values
        benchmark_columns[f"qqqEx{day}"] = returns - qqq_values
    benchmark_frame = pd.DataFrame(benchmark_columns, index=out.index)
    return pd.concat(
        [out.drop(columns=list(benchmark_frame.columns), errors="ignore"), benchmark_frame],
        axis=1,
    )


def _exit_trades(
    frame: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    rule: Rule,
    scope: str,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for strategy, selected in _strategy_masks(frame, rule):
        for ticker, rows in frame.groupby("ticker", sort=False):
            raw = prices.get(ticker)
            if raw is None:
                continue
            local = selected.reindex(rows.index, fill_value=False)
            raw_mask = _raw_signal_mask(rows, raw, local)
            candidates = np.flatnonzero(raw_mask.to_numpy())
            for target in TARGETS:
                for stop in STOPS:
                    simulated = {
                        int(index): simulate_exit(
                            raw,
                            int(index),
                            target,
                            stop,
                            HORIZON,
                            FEE,
                        )
                        for index in candidates
                    }
                    exits = pd.Series(
                        {
                            index: trade["exitIndex"]
                            for index, trade in simulated.items()
                        },
                        dtype="Int64",
                    )
                    for signal_index in episode_signals(raw_mask, exits):
                        row = _row_for_date(rows, raw.index[signal_index])
                        records.append(
                            {
                                **simulated[signal_index],
                                **_event_metadata(row, scope, strategy),
                            }
                        )
    return pd.DataFrame(records)


def _summarize_by_scope(
    frame: pd.DataFrame,
    summarizer: object,
) -> pd.DataFrame:
    summaries: list[pd.DataFrame] = []
    if frame.empty:
        return pd.DataFrame()
    for scope, group in frame.groupby("scope", sort=False):
        summary = summarizer(group)
        summary.insert(0, "scope", scope)
        summaries.append(summary)
    return pd.concat(summaries, ignore_index=True, sort=False)


def _period_summary(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if events.empty:
        return pd.DataFrame()
    for identifiers, group in events.groupby(
        ["scope", "strategy", "period", "universe"],
        dropna=False,
        sort=False,
    ):
        d20 = pd.to_numeric(group["d20"], errors="coerce")
        excess = pd.to_numeric(group["universeEx20"], errors="coerce")
        complete_d20 = d20.dropna()
        complete_labels = group["labelEndDate"].notna()
        labels = group.loc[complete_labels, "isPositiveBottom"].eq(True)
        rows.append(
            {
                **dict(
                    zip(
                        ["scope", "strategy", "period", "universe"],
                        identifiers,
                        strict=True,
                    )
                ),
                "signals": len(group),
                "events": len(complete_d20),
                "signalDates": group.loc[d20.notna(), "signalDate"].nunique(),
                "tickers": group.loc[d20.notna(), "ticker"].nunique(),
                "labelEvents": int(complete_labels.sum()),
                "labelPrecision": float(labels.mean()),
                "d20Mean": float(complete_d20.mean()),
                "d20Median": (
                    float(complete_d20.median())
                    if not complete_d20.empty
                    else np.nan
                ),
                "d20WinRate": float(complete_d20.gt(0).mean()),
                "d20UniverseExcess": float(excess.mean()),
            }
        )
    return pd.DataFrame(rows)


def _concentration(events: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    if events.empty:
        return pd.DataFrame()
    for (scope, strategy), group in events.groupby(
        ["scope", "strategy"],
        sort=False,
    ):
        complete = group.loc[pd.to_numeric(group["d20"], errors="coerce").notna()]
        total = len(complete)
        dimensions = {
            "period": "period",
            "ticker": "ticker",
            "country": "country",
            "regime": "qqqRegime",
            "year": "year",
        }
        for dimension, column in dimensions.items():
            for value, sample in complete.groupby(column, dropna=False):
                rows.append(
                    {
                        "scope": scope,
                        "strategy": strategy,
                        "dimension": dimension,
                        "value": value,
                        "events": len(sample),
                        "share": len(sample) / total if total else np.nan,
                        "d20Mean": sample["d20"].mean(),
                        "d20UniverseExcess": sample["universeEx20"].mean(),
                        "top5Excluded": False,
                    }
                )
        top_five = complete["ticker"].value_counts().head(5).index
        without_top = complete.loc[~complete["ticker"].isin(top_five)]
        positive_share = _top5_positive_excess_share(
            complete.rename(columns={"universeEx20": "d20Excess"})
        )
        rows.append(
            {
                "scope": scope,
                "strategy": strategy,
                "dimension": "top5Contribution",
                "value": ",".join(map(str, top_five)),
                "events": total,
                "share": np.nan,
                "d20Mean": complete["d20"].mean(),
                "d20UniverseExcess": complete["universeEx20"].mean(),
                "top5Excluded": False,
                "top5PositiveContributionShare": positive_share,
            }
        )
        rows.append(
            {
                "scope": scope,
                "strategy": strategy,
                "dimension": "top5Sensitivity",
                "value": "top5Excluded",
                "events": len(without_top),
                "share": len(without_top) / total if total else np.nan,
                "d20Mean": without_top["d20"].mean(),
                "d20UniverseExcess": without_top["universeEx20"].mean(),
                "top5Excluded": True,
                "top5PositiveContributionShare": positive_share,
            }
        )
    return pd.DataFrame(rows)


def _bootstrap(events: pd.DataFrame, repetitions: int = 1000) -> pd.DataFrame:
    rng = np.random.default_rng(20260809)
    rows: list[dict[str, object]] = []
    if events.empty:
        return pd.DataFrame()
    for (scope, strategy), group in events.groupby(
        ["scope", "strategy"],
        sort=False,
    ):
        for metric in ("d20", "universeEx20"):
            numeric = pd.to_numeric(group[metric], errors="coerce")
            sample = group.loc[numeric.notna()].copy()
            sample["_metric"] = numeric.loc[numeric.notna()]
            for cluster in ("signalDate", "ticker"):
                clustered = [
                    values.to_numpy(dtype=float)
                    for _, values in sample.groupby(cluster)["_metric"]
                ]
                if not clustered:
                    estimate = low = high = np.nan
                else:
                    draws = np.empty(repetitions, dtype=float)
                    for repetition in range(repetitions):
                        selected = rng.integers(
                            0,
                            len(clustered),
                            size=len(clustered),
                        )
                        draws[repetition] = np.concatenate(
                            [clustered[index] for index in selected]
                        ).mean()
                    estimate = float(sample["_metric"].mean())
                    low, high = np.quantile(draws, [0.025, 0.975])
                rows.append(
                    {
                        "scope": scope,
                        "strategy": strategy,
                        "metric": metric,
                        "cluster": cluster,
                        "clusters": len(clustered),
                        "estimate": estimate,
                        "reportedMean": float(sample["_metric"].mean()),
                        "ciLow": low,
                        "ciHigh": high,
                        "repetitions": repetitions,
                    }
                )
    return pd.DataFrame(rows)


def _watchlist_output(path: pd.DataFrame, exits: pd.DataFrame) -> pd.DataFrame:
    watch_path = path.loc[path.get("scope", pd.Series(dtype=object)).eq(
        "watchlist_diagnostic"
    )].copy()
    watch_exits = exits.loc[exits.get("scope", pd.Series(dtype=object)).eq(
        "watchlist_diagnostic"
    )].copy()
    if not watch_path.empty:
        watch_path.insert(0, "recordType", "path")
    if not watch_exits.empty:
        watch_exits.insert(0, "recordType", "exit")
        watch_exits["stopLabel"] = watch_exits["stop"].map(
            lambda value: "none" if pd.isna(value) else f"{float(value):.2f}"
        )
    if watch_path.empty and watch_exits.empty:
        return pd.DataFrame(columns=["recordType", "scope", "strategy"])
    return pd.concat([watch_path, watch_exits], ignore_index=True, sort=False)


def run_frozen_test(
    rule: Rule,
    panel: pd.DataFrame,
    prices: dict[str, pd.DataFrame],
    out_dir: str,
) -> dict[str, pd.DataFrame]:
    """Open Test through the hash gate and write Test/diagnostic outputs."""

    frozen_rule = _validate_frozen_rule(out_dir, rule)
    output = Path(out_dir)
    rule_hash = _sha256(output / FROZEN_RULE_FILE)
    data_end = _panel_metadata(panel).get("cacheEndDate") or pd.to_datetime(
        panel["date"]
    ).max()
    lock_path = _create_test_lock(output, rule_hash, data_end)
    try:
        scopes = _scope_frames(panel)
        discovery = next(
            frame for scope, frame in scopes if scope == "full_period_diagnostic"
        )
        pending_events: list[pd.DataFrame] = []
        all_trades: list[pd.DataFrame] = []
        for scope, frame in scopes:
            if frame.empty:
                continue
            pending_events.append(
                _path_events(frame, prices, frozen_rule, scope)
            )
            all_trades.append(
                _exit_trades(frame, prices, frozen_rule, scope)
            )

        signal_dates = (
            pd.concat(pending_events, ignore_index=True)["signalDate"].unique()
            if pending_events
            and any(not frame.empty for frame in pending_events)
            else []
        )
        universe, qqq = _benchmark_paths(
            discovery,
            prices,
            signal_dates,
        )
        all_events = [
            _attach_benchmarks(frame, universe, qqq)
            for frame in pending_events
        ]
        events = (
            pd.concat(all_events, ignore_index=True, sort=False)
            if all_events
            else pd.DataFrame()
        )
        trades = (
            pd.concat(all_trades, ignore_index=True, sort=False)
            if all_trades
            else pd.DataFrame()
        )
        path = _summarize_by_scope(events, summarize_paths)
        exits = _summarize_by_scope(trades, summarize_exits)
        periods = _period_summary(events)
        concentration = _concentration(events)
        bootstrap = _bootstrap(events)
        watchlist = _watchlist_output(path, exits)

        output_paths = {
            "bottom_rebound_events.pkl": events,
            "bottom_rebound_d1_d20.csv": path,
            "bottom_rebound_target_exits.csv": exits,
            "bottom_rebound_periods.csv": periods,
            "bottom_rebound_concentration.csv": concentration,
            "bottom_rebound_bootstrap.csv": bootstrap,
            "bottom_rebound_watchlist.csv": watchlist,
        }
        for filename, frame in output_paths.items():
            path_name = output / filename
            if filename.endswith(".pkl"):
                frame.to_pickle(path_name)
            else:
                frame.to_csv(path_name, index=False)
        output_hashes = {
            filename: _sha256(output / filename)
            for filename in output_paths
        }
        _update_test_lock(
            lock_path,
            "completed",
            outputSha256=output_hashes,
        )
        return {
            "events": events,
            "path": path,
            "exits": exits,
            "periods": periods,
            "concentration": concentration,
            "bootstrap": bootstrap,
            "watchlist": watchlist,
        }
    except BaseException as error:
        _update_test_lock(
            lock_path,
            "failed",
            error=f"{type(error).__name__}: {error}",
        )
        raise


def _build_discovery_panel(
    d_cutoff: str | pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    symbols = {ticker: ticker for ticker in load_discovery_universe()}
    return build_panel(symbols, d_cutoff=d_cutoff)


def _combine_for_test(
    discovery: pd.DataFrame,
    discovery_prices: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    market_columns = [
        column
        for column in (
            "qqqPremium",
            "qqqRegime",
            "qqqRsi",
            "qqqRsiMin3",
            "qqqMacdHist",
            "qqqRet20",
            "vix",
            "vixChange5",
            "breadthBelow200",
            "breadthRsi30",
            "breadthDd40",
        )
        if column in discovery
    ]
    market_context = (
        discovery.sort_values("date")
        .drop_duplicates("date")
        .set_index("date")[market_columns]
    )
    universe_d20 = (
        discovery.groupby("date")["d20Return"].mean().sort_index()
    )
    watchlist, watch_prices = build_panel(
        load_watchlist(),
        market_context=market_context,
        universe_d20=universe_d20,
        universe_name="watchlist",
    )
    combined = pd.concat([discovery, watchlist], ignore_index=True, sort=False)
    combined.attrs = discovery.attrs.copy()
    return combined, {**discovery_prices, **watch_prices}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=("discover", "test", "all"),
        required=True,
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = parser.parse_args(argv)

    output = Path(args.out_dir)
    output.mkdir(parents=True, exist_ok=True)
    if args.stage == "test":
        rule = _validate_frozen_rule(str(output))
        discovery, prices = _build_discovery_panel()
        combined, prices = _combine_for_test(discovery, prices)
        results = run_frozen_test(rule, combined, prices, str(output))
        print(
            "final Test and separate full-period/watchlist diagnostics written: "
            f"{len(results['events']):,} event rows"
        )
        return

    discovery, prices = _build_discovery_panel(d_cutoff="2022-12-31")
    rule = run_discovery(discovery, prices, str(output))
    print(
        "Train/Validation discovery frozen (Test aggregates not opened): "
        + " & ".join(condition.name for condition in rule.conditions)
    )
    if args.stage == "all":
        discovery, prices = _build_discovery_panel()
        combined, prices = _combine_for_test(discovery, prices)
        results = run_frozen_test(rule, combined, prices, str(output))
        print(
            "final Test and separate full-period/watchlist diagnostics written: "
            f"{len(results['events']):,} event rows"
        )


if __name__ == "__main__":
    main()
