# Bottom Rebound Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Discover an interpretable 3–5 condition bottom-rebound entry rule on historical data without lookahead, freeze it before the final holdout, and report D+1~D+20 plus +10%/+15%/+20% exits.

**Architecture:** Add a pure, testable core module for bottom labels, period assignment, rule search, event paths, and barrier exits. Add one orchestration script that loads the existing adjusted caches, builds 135-symbol discovery and 57-symbol watchlist panels, freezes the rule after Train/Validation, opens Test once, and writes CSV artifacts for a standalone Canvas.

**Tech Stack:** Python 3, pandas, NumPy, pytest, existing `calculator.indicators`, `ma200_macd_golden`, `backtest_qqq_block_v2`.

## Global Constraints

- D is the signal-confirmation close; executable entry is D+1 open.
- Use only D-or-earlier values in strategy conditions.
- Positive training label: 20-day new low, no lower low in the next 20 sessions, and +10% high rebound from D close within 20 sessions.
- Train 2001–2019, Validation 2020–2022, Test 2023–2026; purge rows whose 20-day label window crosses a boundary.
- Test is opened only after the final rule is serialized.
- Final rule has 3–5 interpretable conditions and is not changed after Test.
- Report every D+1~D+20 horizon with sample count.
- Simulate +10%, +15%, +20%; no-stop/D+20 exit primary, -10% and -15% stops as sensitivity; same-day stop wins.
- Use 0.1% fee per side.
- Do not modify Strategy 4 or use its manually derived rule as a candidate.
- Do not commit unless the user explicitly requests a commit.

---

## File Map

- Create `research/strategy4/bottom_rebound_core.py`: pure feature-label, rule-search, event-path, and barrier functions.
- Create `research/strategy4/bottom_rebound_study.py`: cache loading, panel construction, frozen OOS execution, CSV output.
- Create `tests/test_bottom_rebound_core.py`: deterministic synthetic-data unit tests.
- Create `tests/test_bottom_rebound_study.py`: small integration test with injected loaders.
- Create managed Canvas `.../canvases/bottom-rebound-OOS-study.canvas.tsx` only after final CSVs exist.
- Do not modify existing strategy scripts.

---

### Task 1: Bottom labels and purged period assignment

**Files:**
- Create: `research/strategy4/bottom_rebound_core.py`
- Create: `tests/test_bottom_rebound_core.py`

**Interfaces:**
- Produces `label_bottom_candidates(frame: pd.DataFrame, lookback: int = 20, horizon: int = 20, rebound: float = 0.10) -> pd.DataFrame`.
- Produces `assign_periods(frame: pd.DataFrame) -> pd.Series`.
- Required input columns: `Low`, `High`, `Close`; DatetimeIndex.
- Label output columns: `isCandidate`, `isPositiveBottom`, `labelEndDate`, `futureMinLow`, `futureMaxHigh`.

- [ ] **Step 1: Write failing label tests**

```python
def test_positive_bottom_requires_no_lower_low_and_ten_percent_rebound():
    frame = synthetic_ohlc(
        lows=[100] * 20 + [90] + [91] * 20,
        highs=[101] * 20 + [92] + [100] * 20,
        closes=[100] * 20 + [90] + [95] * 20,
    )
    result = label_bottom_candidates(frame)
    assert bool(result.iloc[20]["isCandidate"])
    assert bool(result.iloc[20]["isPositiveBottom"])


def test_future_lower_low_makes_bottom_label_false():
    frame = synthetic_ohlc(
        lows=[100] * 20 + [90, 89] + [91] * 19,
        highs=[101] * 20 + [92] + [100] * 20,
        closes=[100] * 20 + [90] + [95] * 20,
    )
    result = label_bottom_candidates(frame)
    assert bool(result.iloc[20]["isCandidate"])
    assert not bool(result.iloc[20]["isPositiveBottom"])
```

- [ ] **Step 2: Run tests and verify the expected import failure**

Run: `python3 -m pytest tests/test_bottom_rebound_core.py -v`

Expected: FAIL because `bottom_rebound_core` does not exist.

- [ ] **Step 3: Implement forward labels without using them as features**

```python
def label_bottom_candidates(frame, lookback=20, horizon=20, rebound=0.10):
    out = frame.copy()
    prior_low = out["Low"].rolling(lookback).min().shift(1)
    out["isCandidate"] = out["Low"].le(prior_low)
    future_min, future_max, end_dates = [], [], []
    for i in range(len(out)):
        window = out.iloc[i + 1 : i + 1 + horizon]
        complete = len(window) == horizon
        future_min.append(window["Low"].min() if complete else np.nan)
        future_max.append(window["High"].max() if complete else np.nan)
        end_dates.append(window.index[-1] if complete else pd.NaT)
    out["futureMinLow"] = future_min
    out["futureMaxHigh"] = future_max
    out["labelEndDate"] = end_dates
    out["isPositiveBottom"] = (
        out["isCandidate"]
        & out["futureMinLow"].ge(out["Low"])
        & out["futureMaxHigh"].ge(out["Close"] * (1 + rebound))
    )
    return out
```

- [ ] **Step 4: Add purged-boundary tests**

```python
def test_period_assignment_purges_label_windows_crossing_boundaries():
    frame = pd.DataFrame({
        "date": pd.to_datetime(["2019-12-01", "2019-12-20", "2020-01-02", "2022-12-20", "2023-01-03"]),
        "labelEndDate": pd.to_datetime(["2019-12-30", "2020-01-20", "2020-02-01", "2023-01-20", "2023-02-01"]),
    })
    assert assign_periods(frame).tolist() == ["train", "purged", "validation", "purged", "test"]
```

- [ ] **Step 5: Implement `assign_periods` and rerun tests**

Run: `python3 -m pytest tests/test_bottom_rebound_core.py -v`

Expected: all Task 1 tests PASS.

---

### Task 2: Point-in-time feature and market panel

**Files:**
- Modify: `research/strategy4/bottom_rebound_core.py`
- Modify: `tests/test_bottom_rebound_core.py`

**Interfaces:**
- Produces `build_stock_features(raw: pd.DataFrame) -> pd.DataFrame`.
- Produces `build_market_features(qqq: pd.DataFrame, vix: pd.DataFrame, breadth: pd.DataFrame) -> pd.DataFrame`.
- Produces `build_breadth(feature_frames: dict[str, pd.DataFrame]) -> pd.DataFrame`.
- Stock output includes `rsi`, `cci`, `williamsR`, `macdHist`, `macdDelta1`, `adx`, `diSpread`, `distMA20/60/144/200`, `slopeMA20/60/200`, `ret1/5/20/60`, `dd60/252`, `rs20`, `pctB`, `bbWidthNorm`, `volRatio20`, `atrPct`, `gapPct`, candle features, and `daysBelow200`.
- Returns, drawdowns, MA distances, ATR, gaps, and relative strength use decimal fractions; `pctB` and `qqqPremium` use percentage points to match existing project fields.
- Market output includes `qqqPremium`, `qqqRegime`, `qqqRsi`, `qqqRsiMin3`, `qqqMacdHist`, `vix`, `vixChange5`, and three breadth ratios.

- [ ] **Step 1: Write tests proving features use current/past rows only**

```python
def test_stock_features_are_unchanged_when_future_prices_change():
    raw = synthetic_trending_ohlcv(320)
    before = build_stock_features(raw).iloc[250].copy()
    changed = raw.copy()
    changed.iloc[251:, changed.columns.get_loc("Close")] *= 10
    after = build_stock_features(changed).iloc[250]
    pd.testing.assert_series_equal(before, after, check_names=False)
```

- [ ] **Step 2: Implement stock features using existing indicators**

Use `calculator.indicators.add_indicators(raw)`, then derive only backward-looking rolling or expanding columns. Compute ATR as 14-day rolling true range, Williams %R from 14-day high/low, and `daysBelow200` with a forward loop over the already-known boolean sequence.

- [ ] **Step 3: Add breadth test**

```python
def test_breadth_is_same_date_cross_section_only():
    frames = {
        "A": pd.DataFrame({"below200": [True], "rsi": [20], "dd60": [-0.5]}, index=[DATE]),
        "B": pd.DataFrame({"below200": [False], "rsi": [40], "dd60": [-0.1]}, index=[DATE]),
    }
    breadth = build_breadth(frames)
    assert breadth.loc[DATE, "breadthBelow200"] == 0.5
    assert breadth.loc[DATE, "breadthRsi30"] == 0.5
    assert breadth.loc[DATE, "breadthDd40"] == 0.5
```

- [ ] **Step 4: Implement market features and exact joins**

Join by stored cache date. Record US/KR calendar caveat in output metadata; do not forward-fill stock prices. VIX may forward-fill only onto QQQ dates.

- [ ] **Step 5: Run feature tests**

Run: `python3 -m pytest tests/test_bottom_rebound_core.py -v`

Expected: all Task 1–2 tests PASS.

---

### Task 3: Interpretable condition library and frozen rule search

**Files:**
- Modify: `research/strategy4/bottom_rebound_core.py`
- Modify: `tests/test_bottom_rebound_core.py`

**Interfaces:**
- Add frozen dataclass `Condition(name: str, column: str, operator: str, threshold: float)`.
- Add frozen dataclass `Rule(conditions: tuple[Condition, ...])`.
- Produces `condition_library() -> list[Condition]` using fixed domain thresholds.
- Produces `apply_rule(frame: pd.DataFrame, rule: Rule) -> pd.Series`.
- Produces `discover_rule(train: pd.DataFrame, validation: pd.DataFrame, max_conditions: int = 5) -> tuple[Rule, pd.DataFrame]`.
- Produces `save_frozen_rule(rule: Rule, path: str) -> None` and `load_frozen_rule(path: str) -> Rule`.

- [ ] **Step 1: Write rule-application tests**

```python
def test_rule_is_candidate_low_and_all_conditions():
    frame = pd.DataFrame({"isCandidate": [True, True], "rsi": [24, 35], "dd60": [-0.5, -0.5]})
    rule = Rule((
        Condition("RSI≤25", "rsi", "<=", 25),
        Condition("60일낙폭≤-40%", "dd60", "<=", -0.40),
    ))
    assert apply_rule(frame, rule).tolist() == [True, False]
```

- [ ] **Step 2: Implement a fixed threshold library**

Include no Strategy 4 or recent-common-core composite. Use individual thresholds:

```python
THRESHOLDS = {
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
```

- [ ] **Step 3: Write a discovery test proving Test rows are not accepted**

```python
def test_discover_rule_accepts_only_train_and_validation():
    signature = inspect.signature(discover_rule)
    assert list(signature.parameters) == ["train", "validation", "max_conditions"]
```

- [ ] **Step 4: Implement greedy forward selection**

For each step:

1. Start from `isCandidate`.
2. Evaluate each unused condition.
3. Require Train events ≥100 and Validation events ≥30.
4. Require both Train and Validation +10-label precision lift >0.
5. Require Validation executable `d20ExcessMean > 0`.
6. Rank by `min(trainPrecisionLift, validationPrecisionLift)`.
7. Add a condition only if the minimum lift improves by at least 2 percentage points and Validation `d20ExcessMean` does not decline by more than 0.2 percentage points.
8. Stop at five conditions or when no condition passes.
9. If fewer than three conditions survive, write the audit but do not freeze a strategy or open Test; report “no stable rule found.”

Write every evaluated step to the returned audit DataFrame.

- [ ] **Step 5: Test deterministic freezing**

```python
def test_frozen_rule_round_trip(tmp_path):
    rule = Rule((Condition("RSI≤25", "rsi", "<=", 25),))
    path = tmp_path / "rule.json"
    save_frozen_rule(rule, str(path))
    assert load_frozen_rule(str(path)) == rule
```

- [ ] **Step 6: Run rule-search tests**

Run: `python3 -m pytest tests/test_bottom_rebound_core.py -v`

Expected: all Task 1–3 tests PASS.

---

### Task 4: D+1~D+20 paths and target/stop simulation

**Files:**
- Modify: `research/strategy4/bottom_rebound_core.py`
- Modify: `tests/test_bottom_rebound_core.py`

**Interfaces:**
- Produces `episode_signals(mask: pd.Series, exits: pd.Series | None = None) -> list[int]`.
- Produces `event_path(raw: pd.DataFrame, signal_index: int, horizon: int = 20, fee: float = 0.001) -> dict[str, float]`.
- Produces `simulate_exit(raw: pd.DataFrame, signal_index: int, target: float, stop: float | None, horizon: int = 20, fee: float = 0.001) -> dict[str, object]`.
- Produces `summarize_paths(events: pd.DataFrame) -> pd.DataFrame`.
- Produces `summarize_exits(trades: pd.DataFrame) -> pd.DataFrame`.

- [ ] **Step 1: Write next-open and fee test**

```python
def test_event_path_enters_next_open_and_charges_both_sides():
    raw = tiny_ohlc(open_=[100, 110], high=[101, 121], low=[99, 109], close=[100, 120])
    event = event_path(raw, signal_index=0, horizon=1, fee=0.001)
    expected = 120 * 0.999 / (110 * 1.001) - 1
    assert event["d1"] == pytest.approx(expected)
```

- [ ] **Step 2: Write same-day stop-first test**

```python
def test_same_day_target_and_stop_uses_stop_first():
    raw = tiny_ohlc(open_=[100, 100], high=[101, 120], low=[99, 80], close=[100, 110])
    trade = simulate_exit(raw, 0, target=0.10, stop=0.10, horizon=1)
    assert trade["reason"] == "stop"
    assert trade["days"] == 1
```

- [ ] **Step 3: Implement path and barrier functions**

Entry is `Open[D+1] * (1 + fee)`. Target and stop are tested against each session High/Low. Target exit receives target price less sell fee; stop exit receives stop price less sell fee. If neither hits, exit at D+20 Close less sell fee. Return NaN for unobserved horizons rather than shortening the holding period.

- [ ] **Step 4: Implement one-position-per-ticker signal filtering**

After each signal, suppress subsequent signals through its actual exit index. For the no-stop event path, use a 20-session holding window. For each barrier variant, use its own exit index.

- [ ] **Step 5: Add summary assertions**

Assert D+1 through D+20 rows exist; each row includes events, signalDates, tickers, mean, median, winRate, p25, p75, QQQ excess, universe excess, MFE, and MAE. Exit summary must include targetHitRate, medianHitDay, winRate, mean, median, profitFactor, averageWin, averageLoss, payoffRatio, maxLosingStreak, and equityMaxDrawdown.

- [ ] **Step 6: Run event and exit tests**

Run: `python3 -m pytest tests/test_bottom_rebound_core.py -v`

Expected: all Task 1–4 tests PASS.

---

### Task 5: Reproducible discovery and frozen OOS runner

**Files:**
- Create: `research/strategy4/bottom_rebound_study.py`
- Create: `tests/test_bottom_rebound_study.py`

**Interfaces:**
- Produces `load_discovery_universe() -> list[str]`.
- Produces `load_watchlist() -> dict[str, str]`.
- Produces `build_panel(symbols: dict[str, str]) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]`.
- Produces `run_discovery(panel: pd.DataFrame, prices: dict[str, pd.DataFrame], out_dir: str) -> Rule`.
- Produces `run_frozen_test(rule: Rule, panel: pd.DataFrame, prices: dict[str, pd.DataFrame], out_dir: str) -> dict[str, pd.DataFrame]`.
- CLI stages: `--stage discover`, `--stage test`, `--stage all`.

- [ ] **Step 1: Write a loader-injected integration test**

```python
def test_pipeline_freezes_rule_before_test(tmp_path, monkeypatch):
    monkeypatch.setattr(study, "dl", synthetic_loader)
    rule = study.run_discovery(train_validation_panel(), synthetic_prices(), str(tmp_path))
    assert (tmp_path / "bottom_rebound_frozen_rule.json").exists()
    outputs = study.run_frozen_test(rule, holdout_panel(), synthetic_prices(), str(tmp_path))
    assert set(outputs) >= {"path", "exits", "periods", "concentration"}
```

- [ ] **Step 2: Implement panel construction**

Load available UNIVERSE symbols, record missing ANSS/SQ, compute stock features once, build breadth once, attach QQQ/VIX features, attach bottom labels, and retain raw prices by ticker. Build the watchlist panel separately with the same functions and frozen rule.

- [ ] **Step 3: Implement discovery stage**

Write:

- `bottom_rebound_condition_audit.csv`
- `bottom_rebound_frozen_rule.json`
- `bottom_rebound_train_validation_summary.csv`
- `bottom_rebound_metadata.json`

The metadata records data end date, missing symbols, split dates, fees, label definition, feature list, and SHA-256 of the frozen rule.

- [ ] **Step 4: Implement Test gate**

`--stage test` must refuse to run when the frozen rule or metadata hash is missing. It loads but never rewrites the frozen rule. Test output includes the unfiltered 20-day-low baseline and the final rule.

- [ ] **Step 5: Implement Test and watchlist outputs**

Write:

- `bottom_rebound_events.pkl`
- `bottom_rebound_d1_d20.csv`
- `bottom_rebound_target_exits.csv`
- `bottom_rebound_periods.csv`
- `bottom_rebound_concentration.csv`
- `bottom_rebound_bootstrap.csv`
- `bottom_rebound_watchlist.csv`

- [ ] **Step 6: Run integration tests**

Run: `python3 -m pytest tests/test_bottom_rebound_core.py tests/test_bottom_rebound_study.py -v`

Expected: all tests PASS.

---

### Task 6: Execute discovery, freeze, and open the holdout once

**Files:**
- Generated only under `analysis_tmp/`

**Interfaces:**
- Consumes the CLI from Task 5.
- Produces the complete artifact set from Task 5.

- [ ] **Step 1: Run Train/Validation discovery only**

Run: `python3 research/strategy4/bottom_rebound_study.py --stage discover`

Expected: prints the chosen conditions and writes a frozen-rule hash without any Test metrics.

- [ ] **Step 2: Inspect the audit for predeclared validity gates**

Check that the chosen rule:

- has no more than five conditions;
- uses only documented feature columns;
- has Train ≥100 and Validation ≥30 events;
- has positive Train and Validation precision lift;
- has positive Validation D+20 universe excess;
- contains no Strategy 4 composite.

If no rule passes, stop and report “no stable rule found”; do not loosen thresholds.

- [ ] **Step 3: Run the final Test once**

Run: `python3 research/strategy4/bottom_rebound_study.py --stage test`

Expected: writes Test, full-period diagnostic, and watchlist outputs without altering the rule hash.

- [ ] **Step 4: Verify output invariants**

Run a Python assertion script checking:

- D+1~D+20 are all present;
- sample counts are non-increasing;
- targets are exactly 10%, 15%, 20%;
- stops are exactly none, 10%, 15%;
- recent censored events are absent from unavailable horizons;
- Test event count/ticker/date gates are reported;
- frozen-rule hash before and after Test is identical.

---

### Task 7: Statistical checks and standalone Canvas

**Files:**
- Create: `/Users/jungsoo.kim/.cursor/projects/Users-jungsoo-kim-Desktop-backtest/canvases/bottom-rebound-OOS-study.canvas.tsx`
- Do not create helper Canvas files.

**Interfaces:**
- Consumes only final CSV values embedded inline.
- Displays Train/Validation/Test separately and identifies the final Test as holdout.

- [ ] **Step 1: Verify significance and concentration CSVs**

Require both signal-date and ticker-cluster bootstrap rows, year/ticker/market breakdowns, top-five contribution share, top-five-excluded sensitivity, KR/US split, and watchlist-only results.

- [ ] **Step 2: Create the Canvas**

Include:

- frozen 3–5 condition rule;
- label definition vs executable signal distinction;
- D+1~D+20 mean, median, positive rate, and universe excess charts;
- +10%/+15%/+20% target table for no stop, -10%, -15%;
- target hit-day distribution;
- baseline vs final rule;
- Train/Validation/Test stability;
- watchlist 57 result;
- concentration, bootstrap, survivorship, calendar, and right-censoring caveats;
- explicit verdict: validated, promising-only, failed, or insufficient sample.

- [ ] **Step 3: Run final verification**

Run:

```bash
python3 -m pytest tests/test_bottom_rebound_core.py tests/test_bottom_rebound_study.py -v
python3 -m py_compile research/strategy4/bottom_rebound_core.py research/strategy4/bottom_rebound_study.py
git diff --check -- research/strategy4/bottom_rebound_core.py research/strategy4/bottom_rebound_study.py tests/test_bottom_rebound_core.py tests/test_bottom_rebound_study.py
```

Expected: tests pass, compilation exits 0, diff check exits 0, Canvas TypeScript check reports no errors.

- [ ] **Step 4: Hand off results**

Report the holdout verdict first, then the D+1~D+20 and target-exit conclusions. Link the Canvas and list data/selection limitations. Do not claim strategy validity when either cluster confidence interval includes zero.
