"""유튜브 '통합 올인원 지표' 롱 전략 검증.

영상에서 설명한 매수 진입 조건(STT 기준, 숫자 오탈자는 문맥으로 보정):
  1) 종가 > MA200
  2) MA11이 MA21을 상향 돌파(골든크로스)
  3) MACD 히스토그램 > 0 (녹색)
  4) RSI가 과매수 아님 (< 70)
  + 영상 후반: ADX >= 25 일 때만 밴드 전환 신호를 신뢰

청산은 (a) 추세 반전(MA11 < MA21), (b) ATR 1:1 손익비, (c) 1:1 절반 익절 후
반전까지 홀딩 — 영상에서 권장한 세 가지를 모두 재현한다.

사용자 계좌가 롱 온리라 숏 조건은 검증하지 않는다.
조건별 기여도를 가르려고 조건을 하나씩 뺀 변형(ablation)을 같이 돌린다.
"""
from __future__ import annotations

import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calculator.indicators import add_indicators
from ma200_macd_golden import (CACHE, FEE, FWD_HORIZONS, OUT_DIR, PANEL_PATH,
                               REGIME_ORDER, build_qqq_state, dl)
from backtest_qqq_block_v2 import UNIVERSE

MA_FAST, MA_SLOW = 11, 21
RSI_MAX = 70
ADX_MIN = 25
ATR_WIN = 14
ATR_MULT = 1.5


def add_extra(df: pd.DataFrame) -> pd.DataFrame:
    d = add_indicators(df)
    c = d["Close"]
    d["MAF"] = c.rolling(MA_FAST).mean()
    d["MAS"] = c.rolling(MA_SLOW).mean()
    tr = pd.concat([d["High"] - d["Low"],
                    (d["High"] - c.shift(1)).abs(),
                    (d["Low"] - c.shift(1)).abs()], axis=1).max(axis=1)
    d["ATR"] = tr.ewm(alpha=1 / ATR_WIN, adjust=False, min_periods=ATR_WIN).mean()
    return d


def build_panel(symbols: dict[str, str], qstate: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    frames, prices = [], {}
    for name, sym in symbols.items():
        raw = dl(sym)
        if raw is None or len(raw) < 400:
            continue
        d = add_extra(raw).join(qstate, how="inner").dropna(subset=["premium"])
        d = d.dropna(subset=["MA200", "MAF", "MAS", "ADX", "ATR"])
        if len(d) < 100:
            continue
        d["trendUp"] = d["MAF"] > d["MAS"]
        prices[name] = d
        cl = d["Close"].to_numpy()
        op = d["Open"].to_numpy()
        maf, mas = d["MAF"].to_numpy(), d["MAS"].to_numpy()
        n = len(d)
        entry = np.full(n, np.nan)
        entry[:-1] = op[1:]
        cross = np.zeros(n, dtype=bool)
        cross[1:] = (maf[1:] > mas[1:]) & (maf[:-1] <= mas[:-1])
        out = pd.DataFrame({
            "ticker": name, "date": d.index, "regime": d["regime"].to_numpy(),
            "close": cl, "entryPrice": entry, "atr": d["ATR"].to_numpy(),
            "above200": cl > d["MA200"].to_numpy(),
            "cross": cross,
            "macdPos": d["MACD_Hist"].to_numpy() > 0,
            "rsiOk": d["RSI"].to_numpy() < RSI_MAX,
            "adxOk": d["ADX"].to_numpy() >= ADX_MIN,
            "trendUp": maf > mas,
        })
        for h in FWD_HORIZONS:
            fut = np.full(n, np.nan)
            fut[: n - h] = cl[h:]
            out[f"fwd{h}"] = (fut / entry - 1) * 100
        frames.append(out)
    return pd.concat(frames, ignore_index=True), prices


VARIANTS = {
    "영상 그대로 (MA200↑ + 11/21골든 + MACD>0 + RSI<70 + ADX≥25)":
        ["above200", "cross", "macdPos", "rsiOk", "adxOk"],
    "ADX 제외": ["above200", "cross", "macdPos", "rsiOk"],
    "RSI 제외": ["above200", "cross", "macdPos", "adxOk"],
    "MACD 제외": ["above200", "cross", "rsiOk", "adxOk"],
    "MA200 제외": ["cross", "macdPos", "rsiOk", "adxOk"],
    "골든크로스만": ["cross"],
    "MA200↑ + 골든크로스": ["above200", "cross"],
    "비교군: MA200 위 전체": ["above200"],
    "비교군: 전체": [],
}


def mask_of(panel: pd.DataFrame, conds: list[str]) -> pd.Series:
    m = pd.Series(True, index=panel.index)
    for c in conds:
        m &= panel[c]
    return m


def add_excess(panel: pd.DataFrame) -> pd.DataFrame:
    """같은 날 유니버스 평균 / MA200 위 종목 평균 대비 초과수익."""
    p = panel.copy()
    for h in FWD_HORIZONS:
        col = f"fwd{h}"
        p[f"exAll{h}"] = p[col] - p.groupby("date")[col].transform("mean")
        above = p[col].where(p["above200"])
        p[f"exAbove{h}"] = p[col] - above.groupby(p["date"]).transform("mean")
    return p


def ablation_table(p: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, conds in VARIANTS.items():
        sub = p[mask_of(p, conds)]
        if sub.empty:
            continue
        rec = {"조건": name, "신호수": len(sub), "종목": sub["ticker"].nunique()}
        for h in (5, 10, 20, 60):
            v = sub[f"fwd{h}"].dropna()
            rec[f"fwd{h}%"] = round(v.mean(), 2) if len(v) else np.nan
            rec[f"승률{h}%"] = round((v > 0).mean() * 100, 1) if len(v) else np.nan
        for h in (20, 60):
            e = sub[f"exAbove{h}"].dropna()
            rec[f"MA200↑대비{h}"] = round(e.mean(), 2) if len(e) else np.nan
            rec[f"초과승률{h}%"] = round((e > 0).mean() * 100, 1) if len(e) else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def significance(p: pd.DataFrame, conds: list[str]) -> None:
    """초과수익이 0과 구분되는지. 같은 날 신호가 뭉치므로 날짜 단위 블록 부트스트랩."""
    sig = p[mask_of(p, conds)]
    rng = np.random.default_rng(0)
    for h in (20, 60):
        e = sig[["date", f"exAbove{h}"]].dropna()
        if len(e) < 30:
            continue
        daily = e.groupby("date")[f"exAbove{h}"].mean().to_numpy()
        obs = daily.mean()
        boot = np.array([rng.choice(daily, len(daily), replace=True).mean()
                         for _ in range(5000)])
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"  {h}일 MA200↑ 대비 초과수익 {obs:+.2f}% "
              f"(95% 신뢰구간 {lo:+.2f}% ~ {hi:+.2f}%, 신호일 {len(daily)}일) "
              f"→ {'0을 포함, 통계적으로 무의미' if lo <= 0 <= hi else '유의'}")


def regime_table(p: pd.DataFrame, conds: list[str]) -> pd.DataFrame:
    sig = p[mask_of(p, conds)]
    base = p[p["above200"]]
    rows = []
    for regime in REGIME_ORDER + ["전체"]:
        sm = pd.Series(True, index=sig.index) if regime == "전체" else (sig["regime"] == regime)
        bm = pd.Series(True, index=base.index) if regime == "전체" else (base["regime"] == regime)
        s, b = sig[sm], base[bm]
        if s.empty:
            continue
        rows.append({
            "국면": regime, "신호수": len(s),
            "fwd20%": round(s["fwd20"].mean(), 2),
            "승률20%": round((s["fwd20"] > 0).mean() * 100, 1),
            "fwd60%": round(s["fwd60"].mean(), 2),
            "MA200↑기저20%": round(b["fwd20"].mean(), 2),
            "차이%p": round(s["fwd20"].mean() - b["fwd20"].mean(), 2),
            "초과승률20%": round((s["exAbove20"] > 0).mean() * 100, 1),
        })
    return pd.DataFrame(rows)


def simulate(p: pd.DataFrame, conds: list[str], prices: dict, mode: str,
             max_hold: int = 120) -> pd.DataFrame:
    """mode: 'trend'(반전 청산) / 'atr'(ATR 1:1) / 'half'(1:1 절반 후 반전)."""
    trades = []
    sig = p[mask_of(p, conds) & p["entryPrice"].notna()]
    for t, grp in sig.groupby("ticker"):
        px = prices[t]
        idx = px.index
        op, cl = px["Open"].to_numpy(), px["Close"].to_numpy()
        up = px["trendUp"].to_numpy()
        pos = {d: i for i, d in enumerate(idx)}
        busy_until = -1
        for _, r in grp.sort_values("date").iterrows():
            i0 = pos.get(r["date"])
            if i0 is None or i0 <= busy_until or i0 + 1 >= len(idx):
                continue  # 영상 규칙: 보유 중이면 중복 진입 안 함
            ep = op[i0 + 1] * (1 + FEE)
            atr = r["atr"]
            if not np.isfinite(ep) or ep <= 0 or not np.isfinite(atr):
                continue
            stop, target = ep - ATR_MULT * atr, ep + ATR_MULT * atr
            ret, days, reason, half_done, realized = None, 0, "open_end", False, 0.0
            for j in range(i0 + 1, min(i0 + 1 + max_hold, len(idx))):
                days = j - i0
                price = cl[j]
                if mode == "trend":
                    if not up[j]:
                        ret, reason = price * (1 - FEE) / ep - 1, "reversal"; break
                elif mode == "atr":
                    if price <= stop:
                        ret, reason = price * (1 - FEE) / ep - 1, "stop"; break
                    if price >= target:
                        ret, reason = price * (1 - FEE) / ep - 1, "target"; break
                else:  # half
                    if not half_done and price <= stop:
                        ret, reason = price * (1 - FEE) / ep - 1, "stop"; break
                    if not half_done and price >= target:
                        realized = 0.5 * (price * (1 - FEE) / ep - 1)
                        half_done = True
                    if half_done and not up[j]:
                        ret = realized + 0.5 * (price * (1 - FEE) / ep - 1)
                        reason = "half+reversal"; break
                if days >= max_hold:
                    ret, reason = price * (1 - FEE) / ep - 1, "time"; break
            if ret is None:
                last = cl[min(i0 + max_hold, len(idx) - 1)]
                ret = (realized + 0.5 * (last * (1 - FEE) / ep - 1)) if half_done \
                    else last * (1 - FEE) / ep - 1
            busy_until = i0 + days
            trades.append({"ticker": t, "date": r["date"], "regime": r["regime"],
                           "ret": ret * 100, "days": days, "reason": reason})
    return pd.DataFrame(trades)


def summarize(tr: pd.DataFrame, label: str) -> dict:
    if tr.empty:
        return {"구분": label, "거래": 0}
    r = tr["ret"].to_numpy()
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"구분": label, "거래": len(tr), "승률%": round((r > 0).mean() * 100, 1),
            "평균%": round(r.mean(), 2), "중앙%": round(np.median(r), 2),
            "PF": round(gains / losses, 2) if losses > 0 else np.inf,
            "최악%": round(r.min(), 1), "평균일": round(tr["days"].mean(), 1)}


def overlap(p: pd.DataFrame, conds: list[str]) -> None:
    if not os.path.exists(PANEL_PATH):
        print("  (s4_panel.pkl 없음 — 중복 분석 생략)")
        return
    base = pd.read_pickle(PANEL_PATH)[["ticker", "date", "ahCode", "liveCode", "signal"]]
    m = p[mask_of(p, conds)][["ticker", "date"]].merge(base, on=["ticker", "date"], how="left")
    total = len(m)
    print(f"  영상전략 신호 {total:,}건 중 동시 발동:")
    rows = []
    for code in list("ABCDEFGH"):
        n = int((m["ahCode"] == code).sum())
        if n:
            rows.append({"상대": code, "동시발동": n, "비율%": round(n / total * 100, 2)})
    for code in ("1", "2"):
        n = int((m["liveCode"] == code).sum())
        if n:
            rows.append({"상대": f"전략{code}", "동시발동": n, "비율%": round(n / total * 100, 2)})
    n4 = int(m["signal"].fillna(False).sum())
    rows.append({"상대": "전략4(MA200↓&MACD골든)", "동시발동": n4, "비율%": round(n4 / total * 100, 2)})
    print(pd.DataFrame(rows).to_string(index=False) if rows else "  없음")


def run(label: str, symbols: dict[str, str], qstate: pd.DataFrame, do_overlap: bool):
    print("\n" + "#" * 150)
    print(f"# {label}")
    print("#" * 150)
    panel, prices = build_panel(symbols, qstate)
    p = add_excess(panel)
    print(f"기간 {p['date'].min().date()} ~ {p['date'].max().date()} / "
          f"{p['ticker'].nunique()}종목 / {len(p):,} 종목·일")

    full = VARIANTS[list(VARIANTS)[0]]
    print("\n[조건별 기여도 — 하나씩 빼면서 비교]")
    at = ablation_table(p)
    print(at.to_string(index=False))
    at.to_csv(os.path.join(OUT_DIR, f"video_ablation_{label}.csv"), index=False)

    print("\n[영상 그대로 조건 · 통계적 유의성]")
    significance(p, full)

    print("\n[영상 그대로 조건 · 국면별]")
    rt = regime_table(p, full)
    print(rt.to_string(index=False))
    rt.to_csv(os.path.join(OUT_DIR, f"video_regime_{label}.csv"), index=False)

    print("\n[청산 방식별 성과 — 영상이 제시한 세 가지]")
    rows = []
    for mode, desc in [("trend", "추세반전(MA11<MA21) 청산"),
                       ("atr", "ATR 1:1 (손절 -1.5ATR / 익절 +1.5ATR)"),
                       ("half", "1:1 절반익절 후 반전까지 홀딩")]:
        tr = simulate(p, full, prices, mode)
        rows.append(summarize(tr, desc))
        if mode == "half" and not tr.empty:
            for regime in REGIME_ORDER:
                sub = tr[tr["regime"] == regime]
                if len(sub) >= 20:
                    rows.append(summarize(sub, f"   └ {regime}"))
    print(pd.DataFrame(rows).to_string(index=False))

    if do_overlap:
        print("\n[기존 전략과의 중복]")
        overlap(p, full)


def main():
    pd.set_option("display.width", 300)
    pd.set_option("display.max_columns", 50)
    os.makedirs(OUT_DIR, exist_ok=True)
    qstate = build_qqq_state()

    run("미국주요137", {t: t for t in UNIVERSE}, qstate, do_overlap=True)

    map_fp = os.path.join(CACHE, "s4_watchlist_map.json")
    if os.path.exists(map_fp):
        run("관심종목57", json.load(open(map_fp)), qstate, do_overlap=False)


if __name__ == "__main__":
    main()
