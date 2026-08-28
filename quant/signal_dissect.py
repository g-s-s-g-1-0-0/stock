"""Why did one window's signals work when the 27-year average does not?

The observed setup beat the equal-weight universe by 2.69% in late July 2026
and lost 0.53% on average since 1999. Something separated that window's
winners from its losers, or nothing did and it was noise.

The method is deliberately two-staged. Stage one ranks every feature by how
well it separates that window's winners from its losers -- that is data
mining, and on its own it proves nothing. Stage two takes whatever stage one
found and applies it to the other 27 years, which is the only part that can
support a conclusion. Skipping stage two would repeat exactly the error being
investigated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from quant import config, data, engine, legacy_market, macd_reversal, sp500_data

WINDOW = ("2026-07-20", "2026-07-31")
HOLD = 20

FEATURES = {
    "rsi14": "RSI(14)",
    "rsi2": "RSI(2) 초단기 과매도",
    "legCci": "CCI",
    "adx14": "ADX 추세강도",
    "diSpread": "+DI − −DI",
    "macdHistSlope": "MACD 히스토그램 기울기",
    "macdHistAccel": "MACD 히스토그램 가속도",
    "ma200Dist": "MA200 대비 이격(%)",
    "distHigh52": "52주 고점 대비",
    "dd60": "60일 고점 대비 낙폭",
    "mom126": "6개월 모멘텀",
    "ma20Slope": "MA20 5일 기울기",
    "atrPct": "ATR%",
    "bbWidthRatio": "볼밴폭 / 60일평균",
    "legPctB": "%B",
    "volRatio20": "거래량비율(20일)",
    "lowerTail": "아랫꼬리 비율",
    "logDollarVol": "일평균 거래대금(log)",
}


def derive(panel: pd.DataFrame) -> pd.DataFrame:
    """Add the comparison features the raw panels do not already carry."""
    panel["diSpread"] = panel["legPlusDi"] - panel["legMinusDi"]
    panel["macdHistSlope"] = panel["legMacdHist"] - panel["legMacdHistD1"]
    panel["macdHistAccel"] = (
        panel["legMacdHist"] - 2 * panel["legMacdHistD1"] + panel["legMacdHistD2"]
    )
    panel["ma200Dist"] = panel["legMa200Dist"]
    panel["ma20Slope"] = panel["legMa20"] / panel["legMa20Prev5"] - 1.0
    panel["bbWidthRatio"] = panel["legBbWidth"] / panel["legBbWidthAvg60"].replace(0, np.nan)
    panel["logDollarVol"] = np.log10(panel["dollarVolume20"].clip(lower=1.0))
    return panel


def window_table(panels, masks, growth, start: str, end: str) -> pd.DataFrame:
    """One row per signal in the window, with features and excess return."""
    last = max(panel.index[-1] for panel in panels.values())
    rows = []
    for ticker, table in masks.items():
        panel = panels[ticker]
        hits = table.index[table["signal"].to_numpy(bool)]
        for stamp in hits[(hits >= start) & (hits <= end)]:
            position = panel.index.get_loc(stamp)
            entry = position + 1
            if entry >= len(panel):
                continue
            ret = panel["Close"].iat[-1] / panel["Open"].iat[entry] - 1.0
            row = {
                "ticker": ticker,
                "signalDate": stamp,
                "ret": ret,
                "excess": ret - growth.between(panel.index[entry], last),
            }
            for column in FEATURES:
                row[column] = panel[column].iat[position]
            rows.append(row)
    frame = pd.DataFrame(rows)
    return frame.sort_values("signalDate").drop_duplicates("ticker", keep="first")


def auc(values: pd.Series, wins: pd.Series) -> float:
    """Rank-based separation. 0.5 is no signal, 1.0 sorts winners perfectly."""
    ok = values.notna()
    values, wins = values[ok], wins[ok]
    if wins.nunique() < 2:
        return np.nan
    ranks = values.rank()
    positive, negative = int(wins.sum()), int((~wins).sum())
    return (ranks[wins].sum() - positive * (positive + 1) / 2) / (positive * negative)


def separation(frame: pd.DataFrame) -> pd.DataFrame:
    wins = frame["excess"] > 0
    rows = []
    for column, label in FEATURES.items():
        rows.append(
            {
                "feature": column,
                "설명": label,
                "AUC": auc(frame[column], wins),
                "이긴군 중위": frame.loc[wins, column].median(),
                "진군 중위": frame.loc[~wins, column].median(),
            }
        )
    table = pd.DataFrame(rows)
    table["|AUC-0.5|"] = (table["AUC"] - 0.5).abs()
    return table.sort_values("|AUC-0.5|", ascending=False)


def history(panels, state, growth) -> pd.DataFrame:
    """The same setup over 27 years, carrying the same features per trade."""
    bar = config.Barriers(4.0, 2.0, HOLD, "obs")
    ledger = engine.build_ledger(
        panels,
        macd_reversal.signals(panels, state),
        bar,
        "obs",
        entry_mode="nextOpen",
        exit_policy="time",
        universe_growth=growth,
        context_columns=tuple(FEATURES),
    )
    return macd_reversal._closed(ledger)


def test_filter(trades: pd.DataFrame, name: str, mask: pd.Series) -> dict:
    kept = trades[mask.fillna(False)]
    if kept.empty:
        return {"filter": name, "trades": 0}
    dates = pd.to_datetime(kept["signalDate"])
    recent = kept[dates >= "2013-01-01"]
    return {
        "filter": name,
        "trades": len(kept),
        "비중%": len(kept) / len(trades) * 100,
        "실현%": kept["retNet"].mean() * 100,
        "유니버스%": kept["universeRet"].mean() * 100,
        "초과%": kept["excessRet"].mean() * 100,
        "승률%": kept["retNet"].gt(0).mean() * 100,
        "2013+초과%": recent["excessRet"].mean() * 100 if len(recent) else np.nan,
    }


def main() -> None:
    panels, growth = sp500_data.build()
    qqq, vix = data.load_market("QQQ"), data.load_market("_VIX")
    state = legacy_market.build_state(qqq, vix["Close"])

    masks = macd_reversal.signals(panels, state)
    for panel in panels.values():
        derive(panel)

    frame = window_table(panels, masks, growth, *WINDOW)
    wins = frame["excess"] > 0
    print(f"\n{'=' * 92}\n1단계: 2026년 7월 20~31일 신호를 이긴 종목 / 진 종목으로 가르기")
    print(f"{'=' * 92}")
    print(f"종목 {len(frame)}개 (중복 신호는 첫 신호만), 유니버스를 이긴 종목 {int(wins.sum())}개")
    print(f"이긴군 평균 초과 {frame.loc[wins, 'excess'].mean() * 100:.2f}%, "
          f"진군 평균 초과 {frame.loc[~wins, 'excess'].mean() * 100:.2f}%")
    table = separation(frame)
    print("\n분리력 순위 (AUC 0.5 = 구분 못 함):")
    print(table.round(3).to_string(index=False))

    trades = history(panels, state, growth)
    print(f"\n{'=' * 92}\n2단계: 1단계에서 나온 변수를 27년 {len(trades):,}거래에 적용")
    print(f"{'=' * 92}")

    checks = [("필터 없음 (기준선)", pd.Series(True, index=trades.index))]
    for _, row in table.head(4).iterrows():
        column, label = row["feature"], row["설명"]
        threshold = frame.loc[wins, column].median()
        above = row["AUC"] > 0.5
        mask = trades[column].gt(threshold) if above else trades[column].lt(threshold)
        sign = ">" if above else "<"
        checks.append((f"{label} {sign} {threshold:.3g}", mask))

    print(pd.DataFrame([test_filter(trades, name, mask) for name, mask in checks]).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
