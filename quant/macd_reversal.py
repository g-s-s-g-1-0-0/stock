"""The setup actually observed in late July 2026, measured on 27 years.

Strategy 1 cannot fire in that window: it needs QQQ more than 3% below its
200-day average and VIX at 22, and July 2026 bottomed at +2.93% and 20.66. So
the trade that was watched on screen was never the trade the service codes.

This module states that observed setup as its own rule -- a market that has
cooled out of its overheated band, a stock under its own 200-day average and
oversold, and a MACD histogram that has started turning up -- and measures it
with the same engine, costs and benchmark as every other strategy here.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, data, engine, legacy_indicators, legacy_market, sp500_data

QQQ_MAX_PREMIUM = 9.0
"""Above this the service calls the market an overheated range top."""

RSI_MAX = 35.0
CCI_MIN = -150.0


def _market(state: pd.DataFrame, index: pd.Index) -> pd.Series:
    premium = state["premiumPercent"].reindex(index).ffill(limit=5)
    return premium.le(QQQ_MAX_PREMIUM).fillna(False)


def signals(
    panels: dict[str, pd.DataFrame],
    state: pd.DataFrame,
    turn: str = "either",
    require_oversold: bool = True,
    below_ma200: bool = True,
) -> dict[str, pd.DataFrame]:
    """Signal masks for the observed setup.

    ``turn`` selects how the MACD condition is read:
    ``shrinking`` for a histogram still negative but rising two bars in a row,
    ``cross`` for the bar the histogram crosses zero, ``either`` for both.
    """
    out: dict[str, pd.DataFrame] = {}
    for ticker, panel in panels.items():
        legacy_indicators.add_legacy(panel)
        hist, hist1, hist2 = panel["legMacdHist"], panel["legMacdHistD1"], panel["legMacdHistD2"]

        shrinking = hist.lt(0) & hist.gt(hist1) & hist1.gt(hist2)
        cross = hist1.le(0) & hist.gt(0)
        macd_turn = {"shrinking": shrinking, "cross": cross, "either": shrinking | cross}[turn]

        mask = _market(state, panel.index) & macd_turn.fillna(False)
        if below_ma200:
            mask &= panel["Close"].lt(panel["legMa200"]).fillna(False)
        if require_oversold:
            mask &= (
                panel["legRsi"].round(2).lt(RSI_MAX) | panel["legCci"].round(2).lt(CCI_MIN)
            ).fillna(False)

        mask &= panel["eligible"].astype(bool)
        strength = -panel["legRsi"].fillna(50.0)
        out[ticker] = pd.DataFrame({"signal": mask, "strength": strength.where(mask)})
    return out


def _closed(ledger: pd.DataFrame) -> pd.DataFrame:
    keep = (
        ledger["filled"].astype("boolean").fillna(False)
        & ~ledger.get("censored", pd.Series(False, index=ledger.index)).astype("boolean").fillna(False)
        & ledger["dedupKept"].astype("boolean").fillna(False)
    )
    return ledger[keep].copy()


def run(panels, state, growth, *, hold: int, exit_policy: str, label: str, **kwargs):
    bar = config.Barriers(4.0, 2.0, hold, label)
    ledger = engine.build_ledger(
        panels,
        signals(panels, state, **kwargs),
        bar,
        label,
        entry_mode="nextOpen",
        exit_policy=exit_policy,
        universe_growth=growth,
    )
    return _closed(ledger) if not ledger.empty else ledger


def summarize(trades: pd.DataFrame, title: str) -> dict:
    if trades.empty:
        print(f"{title}: no trades")
        return {}
    row = {
        "setup": title,
        "trades": len(trades),
        "realized%": trades["retNet"].mean() * 100,
        "median%": trades["retNet"].median() * 100,
        "win%": trades["retNet"].gt(0).mean() * 100,
        "universe%": trades["universeRet"].mean() * 100,
        "excess%": trades["excessRet"].mean() * 100,
        "mfe%": trades["mfeHold"].mean() * 100,
    }
    return row


def era_excess(trades: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(trades["signalDate"])
    rows = []
    for name, start, end in config.ERAS:
        window = trades[(dates >= start) & (dates <= end)]
        if window.empty:
            continue
        rows.append(
            {
                "era": name,
                "trades": len(window),
                "realized%": window["retNet"].mean() * 100,
                "universe%": window["universeRet"].mean() * 100,
                "excess%": window["excessRet"].mean() * 100,
            }
        )
    return pd.DataFrame(rows)


def july_2026(panels: dict[str, pd.DataFrame], state: pd.DataFrame) -> pd.DataFrame:
    """What the rule flagged in the window that was watched on screen."""
    masks = signals(panels, state)
    rows = []
    for ticker, table in masks.items():
        hits = table.index[table["signal"].to_numpy(bool)]
        hits = hits[(hits >= "2026-07-20") & (hits <= "2026-07-31")]
        panel = panels[ticker]
        for stamp in hits:
            position = panel.index.get_loc(stamp)
            forward = panel["Close"].iloc[position:]
            rows.append(
                {
                    "ticker": ticker,
                    "signalDate": stamp.date(),
                    "close": panel["Close"].iat[position],
                    "rsi": round(panel["legRsi"].iat[position], 1),
                    "ret5d%": (forward.iloc[min(5, len(forward) - 1)] / forward.iloc[0] - 1) * 100,
                    "toEnd%": (forward.iloc[-1] / forward.iloc[0] - 1) * 100,
                    "days": len(forward) - 1,
                }
            )
    return pd.DataFrame(rows).sort_values("toEnd%", ascending=False)


def main() -> None:
    panels, growth = sp500_data.build()
    qqq, vix = data.load_market("QQQ"), data.load_market("_VIX")
    state = legacy_market.build_state(qqq, vix["Close"])

    print(f"\n{'=' * 96}\n관측된 셋업: QQQ 이격도 <= 9% + 종가 < MA200 + (RSI<35 or CCI<-150) + MACD 히스토그램 반등")
    print(f"{'=' * 96}")

    variants = [
        ("MACD 축소(반등 전), 20일 보유", dict(turn="shrinking"), 20, "time"),
        ("MACD 골든크로스, 20일 보유", dict(turn="cross"), 20, "time"),
        ("둘 중 하나, 20일 보유", dict(turn="either"), 20, "time"),
        ("둘 중 하나, 40일 보유", dict(turn="either"), 40, "time"),
        ("둘 중 하나, 익절/손절 배리어 40일", dict(turn="either"), 40, "barrier"),
        ("MACD 조건 제거(과매도만), 20일", dict(turn="either", require_oversold=True), 20, "time"),
    ]

    summary = []
    keep = None
    for title, kwargs, hold, policy in variants[:5]:
        trades = run(panels, state, growth, hold=hold, exit_policy=policy, label="obs", **kwargs)
        row = summarize(trades, title)
        if row:
            summary.append(row)
        if title.startswith("둘 중 하나, 20일"):
            keep = trades

    print("\n" + pd.DataFrame(summary).round(2).to_string(index=False))

    if keep is not None and not keep.empty:
        print("\n--- 시대별 (둘 중 하나 / 20일 보유) ---")
        print(era_excess(keep).round(2).to_string(index=False))

    print("\n--- 2026년 7월 20~31일에 실제로 잡힌 종목 ---")
    hits = july_2026(panels, state)
    if hits.empty:
        print("없음")
    else:
        print(f"{len(hits)}건, 평균 {hits['toEnd%'].mean():.2f}% (데이터 종료일까지)")
        print(hits.head(25).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
