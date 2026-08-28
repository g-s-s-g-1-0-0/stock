"""Does the ATR entry filter survive the real exit path, or only forward returns?

`strategy3_entry_scan` measured fixed-horizon forward returns. The live rule
exits on +12/-12/20일/횡보장 고점, which truncates exactly the moves a
high-volatility name makes, so the filter has to be re-measured through the
actual exit before it can be recommended. Threshold comes from the 1999-2012
half only, as in the scan.
"""

from __future__ import annotations

import pandas as pd

from quant import config, legacy_run, sp500_data, strategy3_exit

ATR_THRESHOLD = 0.0296
STOPS = (0.12, 0.15, 0.18)
OUT = f"{config.__file__.rsplit('/', 1)[0]}/out"


def _row(label: str, ledger: pd.DataFrame) -> dict:
    summary = strategy3_exit.summarize(ledger, label)
    keep = ("policy", "trades", "mean%", "median%", "win%", "hold", "worst%", "excess%")
    return {
        **{k: v for k, v in summary.items() if k in keep},
        **{k: v for k, v in strategy3_exit.portfolio(ledger).items()
           if k in ("taken", "total%", "CAGR%", "MDD%")},
    }


def main() -> None:
    panels, growth = sp500_data.build()
    state = legacy_run.build_state()
    signals = strategy3_exit.build_signals(panels, state)
    filtered = strategy3_exit.apply_entry_filter(signals, panels, "atrPct", ATR_THRESHOLD)

    base_n = sum(int(s.sum()) for s in signals[0].values())
    kept_n = sum(int(s.sum()) for s in filtered[0].values())
    print(f"signals: {base_n} -> {kept_n} after ATR% >= {ATR_THRESHOLD:.4f} ({kept_n / base_n:.1%})")

    banded = strategy3_exit.apply_entry_filter(signals, panels, "atrPct", ATR_THRESHOLD, upper=0.08)
    capped = strategy3_exit.apply_entry_filter(signals, panels, "atrPct", 0.0, upper=0.08)
    band_n = sum(int(s.sum()) for s in banded[0].values())
    print(f"ATR% 3.0~8.0% band: {band_n} signals ({band_n / base_n:.1%})")

    rows = []
    for name, pack in (
        ("진입필터 없음", signals),
        ("ATR% 상위 20%만(>=3.0%)", filtered),
        ("ATR% 3.0~8.0% 밴드", banded),
        ("ATR% <=8.0%만(기존 연구안)", capped),
    ):
        for stop in STOPS:
            policy = "native" if stop == 0.12 else f"native_stop{int(stop * 100)}"
            if policy != "native":
                continue
            ledger = strategy3_exit.build_ledger(panels, state, "native", growth, signals=pack)
            rows.append(_row(f"{name} · 현행청산", ledger))
            ledger.to_csv(f"{OUT}/ledger_s3_native_{'atr' if pack is not signals else 'all'}.csv",
                          index=False)
        for stop in (0.18, 0.25):
            ledger = strategy3_exit.build_ledger(
                panels, state, f"stop:{stop}", growth, signals=pack
            )
            rows.append(_row(f"{name} · 익절없음/손절-{int(stop * 100)}%", ledger))

    print("\n" + "=" * 108)
    print("Strategy 3: ATR entry filter x exit policy / point-in-time S&P 500")
    print("=" * 108)
    print(pd.DataFrame(rows).round(2).to_string(index=False))

    print("\n--- ATR-filtered, 현행청산, by era ---")
    ledger = strategy3_exit.build_ledger(panels, state, "native", growth, signals=filtered)
    from quant import legacy_backtest

    print(legacy_backtest.eras(ledger).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
