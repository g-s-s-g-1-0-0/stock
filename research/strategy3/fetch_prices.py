"""스냅샷에 등장한 전 종목 일봉을 yfinance로 받아 analysis_tmp/prices.pkl 생성.

재검증 시 가장 먼저 실행. START를 스냅샷 시작 한 달 전쯤으로 넉넉히 잡을 것.
KR 티커는 .KS → .KQ 순서로 시도한다.
"""
import json
import pickle
from pathlib import Path

import yfinance as yf

ROOT = Path(__file__).resolve().parents[2]
START = "2026-04-01"   # 재검증 시 스냅샷 범위에 맞게 조정
END = None             # None이면 오늘까지

rows = []
for f in sorted((ROOT / "data/history").glob("*.jsonl")):
    for line in open(f):
        line = line.strip()
        if line:
            rows.append(json.loads(line))
tickers = sorted({(r["ticker"], r["market"]) for r in rows})
print(f"tickers: {len(tickers)}")

out = {}
fails = []
for t, mkt in tickers:
    cands = [t + ".KS", t + ".KQ"] if mkt == "KR" else [t]
    got = None
    for c in cands:
        try:
            df = yf.download(c, start=START, end=END, progress=False, auto_adjust=False)
            if df is not None and len(df) > 20:
                got = (c, df)
                break
        except Exception:
            pass
    if got:
        out[t] = got[1]
    else:
        fails.append(t)
print(f"ok: {len(out)} | fails: {fails}")

target = ROOT / "analysis_tmp"
target.mkdir(exist_ok=True)
pickle.dump(out, open(target / "prices.pkl", "wb"))
print(f"saved -> {target / 'prices.pkl'}")
