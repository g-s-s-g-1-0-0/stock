"""전략 4 백테스트용 전체 기간 일봉 수집 (QQQ 상장 1999-03 ~ 현재).

yfinance(curl_cffi 세션)는 이 환경에서 계속 실패하는데 Yahoo 차트 API 자체는
살아 있다. 그래서 curl로 chart API를 직접 호출한다. auto_adjust=True와 맞추려고
adjclose/close 비율을 OHLC에 곱해 배당·분할을 반영한다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from backtest_qqq_block_v2 import UNIVERSE

CACHE = os.path.join(ROOT, ".bt_cache")
PERIOD1 = int(pd.Timestamp("1999-01-01").timestamp())
PERIOD2 = int(pd.Timestamp.today().timestamp()) + 86400
MAX_RETRY = 3
PAUSE = 0.4


def path_for(ticker: str) -> str:
    return os.path.join(CACHE, f"s4_{ticker.replace('^', '_')}.pkl")


def cached(ticker: str) -> bool:
    fp = path_for(ticker)
    if not os.path.exists(fp):
        return False
    try:
        df = pd.read_pickle(fp)
        return len(df) > 50 and df.index.max() >= pd.Timestamp.today() - pd.Timedelta(days=7)
    except Exception:
        return False


def fetch(ticker: str) -> pd.DataFrame | None:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={PERIOD1}&period2={PERIOD2}&interval=1d&events=div%2Csplit")
    for attempt in range(MAX_RETRY):
        try:
            out = subprocess.run(["curl", "-s", "-m", "60", "-A", "Mozilla/5.0", url],
                                 capture_output=True, text=True).stdout
            res = json.loads(out)["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            idx = (pd.to_datetime(res["timestamp"], unit="s", utc=True)
                   .tz_convert("America/New_York").normalize().tz_localize(None))
            df = pd.DataFrame({"Open": q["open"], "High": q["high"], "Low": q["low"],
                               "Close": q["close"], "Volume": q["volume"]}, index=idx)
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
            if adj is not None:
                ratio = (pd.Series(adj, index=idx) / df["Close"]).fillna(1.0)
                for c in ("Open", "High", "Low", "Close"):
                    df[c] = df[c] * ratio
            df = df.dropna()
            df.index.name = "Date"
            if len(df) > 50:
                return df
        except Exception:
            pass
        time.sleep(1.0 * (attempt + 1))
    return None


def watchlist_symbols() -> dict[str, str]:
    """스냅샷에 등장한 관심종목 → Yahoo 심볼. KR은 .KS → .KQ 순으로 시도한다."""
    import glob

    seen = {}
    for fp in sorted(glob.glob(os.path.join(ROOT, "data/history/*.jsonl"))):
        for line in open(fp):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            seen[r["ticker"]] = r.get("market")
    mapping = {}
    for t, mkt in sorted(seen.items()):
        for cand in ([f"{t}.KS", f"{t}.KQ"] if mkt == "KR" else [t]):
            if cached(cand):
                mapping[t] = cand
                break
            df = fetch(cand)
            if df is not None:
                df.to_pickle(path_for(cand))
                mapping[t] = cand
                print(f"  관심종목 {t} -> {cand}: {len(df)}행 "
                      f"{df.index.min().date()}~{df.index.max().date()}", flush=True)
                break
            time.sleep(PAUSE)
    return mapping


def main():
    targets = ["QQQ", "^VIX"] + UNIVERSE
    todo = [t for t in targets if not cached(t)]
    print(f"대상 {len(targets)}종목 중 수집 필요 {len(todo)}종목", flush=True)
    failed = []
    for i, t in enumerate(todo, 1):
        df = fetch(t)
        if df is None:
            failed.append(t)
            print(f"[{i}/{len(todo)}] {t}: 실패", flush=True)
        else:
            df.to_pickle(path_for(t))
            print(f"[{i}/{len(todo)}] {t}: {len(df)}행 "
                  f"{df.index.min().date()}~{df.index.max().date()}", flush=True)
        time.sleep(PAUSE)

    done = [t for t in targets if cached(t)]
    print(f"\n유니버스 완료 {len(done)}/{len(targets)} | 실패 {len(failed)}", flush=True)
    if failed:
        print("  실패:", ", ".join(failed), flush=True)

    print("\n관심종목 수집...", flush=True)
    mapping = watchlist_symbols()
    with open(os.path.join(CACHE, "s4_watchlist_map.json"), "w") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1)
    print(f"관심종목 {len(mapping)}종목 매핑 저장", flush=True)


if __name__ == "__main__":
    main()
