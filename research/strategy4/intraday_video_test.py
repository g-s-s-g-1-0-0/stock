"""영상 조건을 '영상과 같은 판'에서 검증 — 암호화폐 분봉 + 롱/숏 양방향.

앞선 검증(video_allinone.py)은 일봉 + 20일 수익률이었다. 영상은 이더리움
15분봉 단타에 롱/숏 양방향이므로 판이 다르다. 여기서는 조건을 그대로 두고
판만 영상에 맞춘다.

  롱  : 종가 > MA200 & MA11이 MA21 상향돌파 & MACD 히스토그램 > 0 & RSI < 70 & ADX >= 25
  숏  : 종가 < MA200 & MA11이 MA21 하향돌파 & MACD 히스토그램 < 0 & RSI > 30 & ADX >= 25
  청산: (a) 밴드 색 전환(MA11/MA21 역전)  (b) ATR 1:1 (손절 밴드폭, 익절 동일폭)

수수료가 결정적이라 총수익(gross)과 수수료 반영(net)을 나눠서 본다.
'무작위 진입' 부트스트랩을 기준선으로 둬서 신호가 타이밍을 맞추는지 본다.
"""
from __future__ import annotations

import json
import os
import subprocess
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, ".bt_cache")

CRYPTO = ["ETH-USD", "BTC-USD", "SOL-USD", "XRP-USD", "DOGE-USD"]
STOCKS = ["NVDA", "TSLA", "AMD", "AAPL", "SOXL"]
# (interval, range, 왕복 수수료+슬리피지 %, 1일치 봉 수)
SETUPS = [("15m", "60d"), ("1h", "730d")]
FEE_CRYPTO = 0.0006   # 무기한선물 테이커 0.06% 편도
FEE_STOCK = 0.0005

MA_FAST, MA_SLOW, MA_LONG = 11, 21, 200
RSI_WIN, ADX_WIN, ATR_WIN = 14, 14, 14
ADX_MIN, RSI_MAX, RSI_MIN = 25, 70, 30
BARS_PER_DAY = {"15m": 96, "1h": 24}


def fetch_binance(symbol: str, interval: str, start: str = "2019-01-01") -> pd.DataFrame | None:
    """Binance 현물 klines를 1000봉씩 이어붙여 수년치 분봉을 만든다.

    Yahoo는 15분봉을 60일까지만 준다. 영상이 15분봉 단타라 표본이 몇십 건밖에
    안 나와서 판단이 불가능하므로, 거래소 원본으로 몇 년치를 받는다.
    """
    fp = os.path.join(CACHE, f"s4_bnc_{symbol}_{interval}.pkl")
    if os.path.exists(fp):
        try:
            df = pd.read_pickle(fp)
            if len(df) > 10000:
                return df
        except Exception:
            pass
    cur = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
    chunks = []
    while cur < end:
        url = (f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}"
               f"&interval={interval}&startTime={cur}&limit=1000")
        try:
            out = subprocess.run(["curl", "-s", "-m", "30", url],
                                 capture_output=True, text=True).stdout
            rows = json.loads(out)
        except Exception:
            break
        if not isinstance(rows, list) or not rows:
            break
        chunks.append(rows)
        nxt = rows[-1][0] + 1
        if nxt <= cur:
            break
        cur = nxt
        if len(chunks) % 50 == 0:
            print(f"    {symbol} {interval}: {sum(len(c) for c in chunks):,}봉...", flush=True)
    if not chunks:
        return None
    flat = [r for c in chunks for r in c]
    df = pd.DataFrame(flat, columns=[
        "ts", "Open", "High", "Low", "Close", "Volume", "close_ts", "qv", "n",
        "tb", "tq", "ig"])
    df = df[["ts", "Open", "High", "Low", "Close", "Volume"]].astype(
        {"Open": float, "High": float, "Low": float, "Close": float, "Volume": float})
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.drop(columns="ts")
    df = df[~df.index.duplicated()].sort_index()
    df.to_pickle(fp)
    return df


def fetch(symbol: str, interval: str, rng: str) -> pd.DataFrame | None:
    fp = os.path.join(CACHE, f"s4_intra_{symbol}_{interval}.pkl")
    if os.path.exists(fp):
        try:
            df = pd.read_pickle(fp)
            if len(df) > 1000:
                return df
        except Exception:
            pass
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?range={rng}&interval={interval}")
    for attempt in range(3):
        try:
            out = subprocess.run(["curl", "-s", "-m", "90", "-A", "Mozilla/5.0", url],
                                 capture_output=True, text=True).stdout
            res = json.loads(out)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            df = pd.DataFrame(
                {"Open": q["open"], "High": q["high"], "Low": q["low"],
                 "Close": q["close"], "Volume": q["volume"]},
                index=pd.to_datetime(res["timestamp"], unit="s", utc=True))
            df = df.dropna()
            if len(df) > 1000:
                df.to_pickle(fp)
                return df
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return None


def indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    c, h, lo = d["Close"], d["High"], d["Low"]
    d["MAF"] = c.rolling(MA_FAST).mean()
    d["MAS"] = c.rolling(MA_SLOW).mean()
    d["MAL"] = c.rolling(MA_LONG).mean()

    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    d["Hist"] = macd - macd.ewm(span=9, adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / RSI_WIN, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / RSI_WIN, adjust=False).mean()
    d["RSI"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))

    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / ATR_WIN, adjust=False).mean()
    d["ATR"] = atr
    up, dn = h.diff(), -lo.diff()
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    pdi = 100 * pd.Series(plus, index=d.index).ewm(alpha=1 / ADX_WIN, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus, index=d.index).ewm(alpha=1 / ADX_WIN, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    d["ADX"] = dx.ewm(alpha=1 / ADX_WIN, adjust=False).mean()
    return d.dropna()


def signals(d: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    maf, mas = d["MAF"].to_numpy(), d["MAS"].to_numpy()
    cl, mal = d["Close"].to_numpy(), d["MAL"].to_numpy()
    hist, rsi, adx = d["Hist"].to_numpy(), d["RSI"].to_numpy(), d["ADX"].to_numpy()
    gc, dc = np.zeros(len(d), bool), np.zeros(len(d), bool)
    gc[1:] = (maf[1:] > mas[1:]) & (maf[:-1] <= mas[:-1])
    dc[1:] = (maf[1:] < mas[1:]) & (maf[:-1] >= mas[:-1])
    long_ = (cl > mal) & gc & (hist > 0) & (rsi < RSI_MAX) & (adx >= ADX_MIN)
    short = (cl < mal) & dc & (hist < 0) & (rsi > RSI_MIN) & (adx >= ADX_MIN)
    return long_, short


def fwd_table(d: pd.DataFrame, long_: np.ndarray, short: np.ndarray,
              interval: str) -> pd.DataFrame:
    """신호 후 N봉 수익률(수수료 제외)과, 같은 구간 전체 봉의 평균을 비교."""
    cl = d["Close"].to_numpy()
    op = d["Open"].to_numpy()
    n = len(cl)
    entry = np.full(n, np.nan)
    entry[:-1] = op[1:]
    bpd = BARS_PER_DAY[interval]
    horizons = [1, 4, bpd // 4, bpd // 2, bpd] if interval == "15m" else [1, 2, 4, 12, 24]
    rows = []
    for h in horizons:
        fut = np.full(n, np.nan)
        fut[: n - h] = cl[h:]
        r = (fut / entry - 1) * 100
        base = np.nanmean(r)
        for name, m, sign in [("롱", long_, 1), ("숏", short, -1)]:
            v = r[m] * sign
            v = v[np.isfinite(v)]
            if len(v) < 5:
                continue
            rows.append({"방향": name, "봉": h,
                         "시간": f"{h * (15 if interval == '15m' else 60) / 60:.1f}h",
                         "신호": len(v), "평균%": round(v.mean(), 3),
                         "승률%": round((v > 0).mean() * 100, 1),
                         "전체봉평균%": round(base * sign, 3),
                         "차이%p": round(v.mean() - base * sign, 3)})
    return pd.DataFrame(rows)


def trades(d: pd.DataFrame, sig: np.ndarray, side: int, mode: str,
           fee: float, max_bars: int) -> pd.DataFrame:
    """side=+1 롱 / -1 숏. mode='flip'(밴드 전환) 또는 'atr'(1:1)."""
    op, cl = d["Open"].to_numpy(), d["Close"].to_numpy()
    maf, mas, atr = d["MAF"].to_numpy(), d["MAS"].to_numpy(), d["ATR"].to_numpy()
    n = len(cl)
    out, busy = [], -1
    for i0 in np.flatnonzero(sig):
        if i0 <= busy or i0 + 1 >= n:
            continue  # 영상 규칙: 보유 중 중복 진입 금지
        ep = op[i0 + 1]
        a = atr[i0]
        if not np.isfinite(ep) or ep <= 0 or not np.isfinite(a):
            continue
        stop, target = ep - side * 1.5 * a, ep + side * 1.5 * a
        gross, bars, why = None, 0, "time"
        for j in range(i0 + 1, min(i0 + 1 + max_bars, n)):
            bars = j - i0
            px = cl[j]
            if mode == "flip":
                flipped = (maf[j] < mas[j]) if side > 0 else (maf[j] > mas[j])
                if flipped:
                    gross, why = side * (px / ep - 1), "flip"
                    break
            else:
                if (side > 0 and px <= stop) or (side < 0 and px >= stop):
                    gross, why = side * (px / ep - 1), "stop"
                    break
                if (side > 0 and px >= target) or (side < 0 and px <= target):
                    gross, why = side * (px / ep - 1), "target"
                    break
        if gross is None:
            gross = side * (cl[min(i0 + max_bars, n - 1)] / ep - 1)
        busy = i0 + bars
        out.append({"gross": gross * 100, "net": (gross - 2 * fee) * 100,
                    "bars": bars, "why": why})
    return pd.DataFrame(out)


def random_baseline(d: pd.DataFrame, side: int, bar_dist: np.ndarray,
                    fee: float, draws: int = 2000) -> float:
    """같은 방향·같은 보유기간으로 아무 때나 들어갔을 때의 평균 수익(수수료 반영)."""
    cl = d["Close"].to_numpy()
    op = d["Open"].to_numpy()
    n = len(cl)
    rng = np.random.default_rng(0)
    means = []
    for _ in range(draws):
        i0 = rng.integers(0, n - 2, len(bar_dist))
        b = rng.choice(bar_dist, len(bar_dist))
        j = np.minimum(i0 + b, n - 1)
        r = side * (cl[j] / op[i0 + 1] - 1) - 2 * fee
        means.append(np.nanmean(r) * 100)
    return float(np.mean(means))


def summarize(tr: pd.DataFrame, label: str) -> dict:
    if tr.empty or len(tr) < 5:
        return {}
    g, nt = tr["gross"].to_numpy(), tr["net"].to_numpy()
    gains, losses = nt[nt > 0].sum(), -nt[nt < 0].sum()
    se = nt.std(ddof=1) / np.sqrt(len(nt))
    return {"구분": label, "거래": len(tr), "승률%": round((nt > 0).mean() * 100, 1),
            "총평균%": round(g.mean(), 3), "순평균%": round(nt.mean(), 3),
            "t값": round(nt.mean() / se, 2) if se > 0 else np.nan,
            "PF": round(gains / losses, 2) if losses > 0 else np.inf,
            "평균봉": round(tr["bars"].mean(), 1)}


def run_asset(symbol: str, interval: str, rng: str, fee: float,
              source: str = "yahoo") -> list[dict]:
    raw = fetch_binance(symbol, interval) if source == "binance" else fetch(symbol, interval, rng)
    if raw is None:
        print(f"  {symbol} {interval}: 수집 실패")
        return []
    d = indicators(raw)
    long_, short = signals(d)
    bpd = BARS_PER_DAY[interval]
    print(f"\n▸ {symbol} {interval}  {d.index.min():%Y-%m-%d} ~ {d.index.max():%Y-%m-%d}  "
          f"{len(d):,}봉 | 롱신호 {int(long_.sum())} · 숏신호 {int(short.sum())}")
    ft = fwd_table(d, long_, short, interval)
    if not ft.empty:
        print("  [신호 후 N봉 수익률 — 수수료 제외, 전체 봉 평균과 비교]")
        print("  " + ft.to_string(index=False).replace("\n", "\n  "))

    rows = []
    for mode, desc in [("flip", "밴드전환 청산"), ("atr", "ATR 1:1")]:
        for side, sname, sig in [(1, "롱", long_), (-1, "숏", short)]:
            tr = trades(d, sig, side, mode, fee, max_bars=bpd * 3)
            s = summarize(tr, f"{sname} · {desc}")
            if not s:
                continue
            s["무작위진입%"] = round(random_baseline(d, side, tr["bars"].to_numpy(), fee), 3)
            s["초과%"] = round(s["순평균%"] - s["무작위진입%"], 3)
            s.update({"종목": symbol, "봉": interval})
            rows.append(s)
    if rows:
        cols = ["구분", "거래", "승률%", "총평균%", "순평균%", "t값", "PF", "평균봉",
                "무작위진입%", "초과%"]
        print("  [거래 시뮬레이션 — 순평균은 왕복 수수료 반영]")
        print("  " + pd.DataFrame(rows)[cols].to_string(index=False).replace("\n", "\n  "))
    return rows


BINANCE = ["ETHUSDT", "BTCUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "SOLUSDT"]


def main():
    pd.set_option("display.width", 300)
    os.makedirs(CACHE, exist_ok=True)
    allrows = []

    print("#" * 130)
    print(f"# 영상과 동일 조건: 암호화폐 15분봉 (거래소 원본, 2019~) "
          f"왕복 수수료 {FEE_CRYPTO * 200:.2f}%")
    print("#" * 130)
    deep = []
    for sym in BINANCE:
        deep += run_asset(sym, "15m", "", FEE_CRYPTO, source="binance")
    if deep:
        dd = pd.DataFrame(deep)
        print("\n[15분봉 심층 — 종합]")
        print(dd.groupby("구분").apply(lambda x: pd.Series({
            "종목수": x["종목"].nunique(), "거래합": int(x["거래"].sum()),
            "가중 총평균%": round(np.average(x["총평균%"], weights=x["거래"]), 4),
            "가중 순평균%": round(np.average(x["순평균%"], weights=x["거래"]), 4),
            "가중 초과%": round(np.average(x["초과%"], weights=x["거래"]), 4),
            "순평균>0": f"{int((x['순평균%'] > 0).sum())}/{len(x)}",
        }), include_groups=False).to_string())
        dd.to_csv(os.path.join(ROOT, "research/strategy4/out/intraday_15m_deep.csv"),
                  index=False)

    for interval, rng in SETUPS:
        print("\n" + "#" * 130)
        print(f"# {interval} 봉 ({rng})   암호화폐 왕복 {FEE_CRYPTO * 200:.2f}% / "
              f"주식 왕복 {FEE_STOCK * 200:.2f}% 가정")
        print("#" * 130)
        for sym in CRYPTO:
            allrows += run_asset(sym, interval, rng, FEE_CRYPTO)
        for sym in STOCKS:
            allrows += run_asset(sym, interval, rng, FEE_STOCK)

    df = pd.DataFrame(allrows)
    if df.empty:
        return
    print("\n" + "#" * 130)
    print("# 전체 종합")
    print("#" * 130)
    for key in ("구분", "봉"):
        g = df.groupby(key).apply(
            lambda x: pd.Series({
                "종목수": x["종목"].nunique(), "거래합": int(x["거래"].sum()),
                "가중 총평균%": round(np.average(x["총평균%"], weights=x["거래"]), 3),
                "가중 순평균%": round(np.average(x["순평균%"], weights=x["거래"]), 3),
                "가중 초과%": round(np.average(x["초과%"], weights=x["거래"]), 3),
                "순평균>0 비율": f"{int((x['순평균%'] > 0).sum())}/{len(x)}",
            }), include_groups=False)
        print(f"\n[{key}별]")
        print(g.to_string())
    df.to_csv(os.path.join(ROOT, "research/strategy4/out/intraday_video.csv"), index=False)


if __name__ == "__main__":
    main()
