"""Fixed final candidate review, with a separate capacity-limited S7 experiment."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from scripts.swing_final_features import PATTERNS, FILTERS, final_feature_frame
from scripts.record_swing_research import market_rows

PROTOCOL = {
    "patterns": PATTERNS, "filters": FILTERS,
    "entry": "D completed close, D+1 regular open; same-name reentry requires signal strictly after prior exit",
    "exit": "close -8/+12/20 sessions plus QQQ14/18 market exits; next open; .4% roundtrip cost",
    "portfolio": "S7 only, not operating1..7; initial1, max5 names, each entry budget<=20% open equity, no leverage; .2% buy/.2% sell cost; uninvested cash0%; fractional shares; daily liquidation-value NAV including open positions",
    "portfolio_variants": ["S7", "S7_QQQ", "S7_watchlist", "S7_both"],
    "portfolio_order": "SHA256(seed,entry date,ticker), seeds0..19 all reported; independent of future returns, no winning-seed selection",
    "coverage": "same prior2026 observed48-name panel and2021..2025 current29-survivor panel; no untouched holdout, actual event history or historical S2 season",
    "decision": "record plausible candidates, no operating changes; report all fixed trials; repeated years/dates and incremental unique signals matter",
}


def load_data(label):
    s = pd.read_pickle(ROOT / "research/extended_review_20261004" / f"{label}_signals.pkl")
    bars = {}
    if label == "2026":
        w = pd.read_pickle(ROOT / "research/observed_signals_20261003/phase2/results/warmup_bars.pkl")
        for ticker, group in w[w.market == "US"].groupby("ticker"):
            if ticker == "QQQ" or ticker in set(s.ticker):
                bars[ticker] = group.drop_duplicates("session").set_index("session").sort_index()[["open", "high", "low", "close", "volume"]]
    else:
        for ticker in ["QQQ", *s.ticker.unique()]:
            b = pd.read_pickle(ROOT / ".bt_cache" / f"{ticker}.pkl").rename(columns=str.lower)
            b.index = pd.to_datetime(b.index).strftime("%Y-%m-%d")
            bars[ticker] = b.loc[:"2025-12-31"]
    start, end = ("2026-05-01", "2026-10-02") if label == "2026" else ("2021-01-01", "2025-12-31")
    q = bars["QQQ"]
    days = [d for d in q.index if start <= d <= end]
    states = market_rows(q.rename(columns=str.title))
    arrays = {t: b.reindex(days)[["open", "high", "low", "close"]].to_numpy() for t, b in bars.items()}
    return s, bars, days, [states[d] for d in days], arrays


def simulate(selected, days, states, arrays):
    idx = {d: i for i, d in enumerate(days)}
    result, last = [], {}
    for r in selected.sort_values(["entry", "ticker"]).to_dict("records"):
        ticker = r["ticker"]
        if r["session"] <= last.get(ticker, ""):
            continue
        i = idx[r["entry"]]
        a = arrays[ticker]
        ep = a[i, 0]
        if not np.isfinite(ep) or ep <= 0:
            continue
        if r.get("strategy_eval") in ["S5", "S6"]:
            if ep > r["close"] * 1.03:
                continue
            if r["strategy_eval"] == "S6" and not 0 < (ep-r["support_stop"])/ep <= .08:
                continue
        seen, nonrec, pending = r["recovery"], 0, None
        status, reason, mae, mfe = "open", "end", 0., 0.
        xp = ep
        for j in range(i, len(days)):
            op, hi, lo, c = a[j]
            if not np.isfinite([op, hi, lo, c]).all():
                status, reason = "invalid", "missing_bar"
                break
            if pending:
                xp, status, reason = op, "closed", pending
                break
            mae, mfe = min(mae, lo/ep-1), max(mfe, hi/ep-1)
            seen |= states[j]["recovery"]
            nonrec = 0 if states[j]["recovery"] else nonrec+1 if seen else 0
            gain = c/ep-1
            if gain <= -.08:
                pending = "stop"
            elif gain >= .12:
                pending = "target"
            elif j-i+1 >= 20:
                pending = "time"
            elif states[j]["peak"] or nonrec >= 2:
                pending = "market"
            xp = c
        net = xp/ep-1-.004
        bench = arrays["QQQ"][j, 0 if status == "closed" else 3]/arrays["QQQ"][i, 0]-1
        result.append({"ticker": ticker, "session": r["session"], "entry": days[i], "exit": days[j], "status": status,
                       "net": net, "excess": net-bench, "mae": mae, "mfe": mfe, "reason": reason})
        last[ticker] = days[j]
    return pd.DataFrame(result, columns=["ticker", "session", "entry", "exit", "status", "net", "excess", "mae", "mfe", "reason"])


def metrics(t):
    x = t[t.status == "closed"]
    o = t[t.status == "open"]
    result = {"n": len(x), "dates": x.entry.nunique(), "open_n": len(o), "invalid_n": int((t.status == "invalid").sum()), "open_mark": o.net.mean()}
    if x.empty:
        return result
    by = x.groupby("entry").net.mean()
    best_name_removed = [x[x.ticker != name].net.mean() for name in x.ticker.unique()]
    return {**result, "mean": x.net.mean(), "median": x.net.median(), "win": (x.net > 0).mean(), "worst": x.net.min(),
            "excess": x.excess.mean(), "date_mean": by.mean(), "cost1_mean": x.net.mean()-.006,
            "no_best_ticker": min(best_name_removed) if len(best_name_removed) > 1 else np.nan,
            "no_best_date": (by.sum()-by.max())/(len(by)-1) if len(by) > 1 else np.nan}


def portfolio(selected, days, states, arrays, seed=0, slots=5):
    candidates = {d: g.to_dict("records") for d, g in selected.groupby("entry")}
    cash, held, last_exit, curve, fills = 1., {}, {}, [], []
    for i, day in enumerate(days):
        for ticker in list(held):
            p = held[ticker]
            if not np.isfinite(arrays[ticker][i]).all():
                return {"status": "invalid", "missing": ticker+":"+day}, curve, fills
            if p["pending"]:
                cash += p["qty"]*arrays[ticker][i, 0]*.998
                fills.append({"ticker": ticker, "signal": p["signal"], "entry": p["entry"], "exit": day})
                last_exit[ticker] = day
                del held[ticker]
        open_equity = cash + sum(p["qty"]*arrays[t][i, 0] for t, p in held.items())
        ordered = sorted(candidates.get(day, []), key=lambda r: hashlib.sha256(f"{seed}:{day}:{r['ticker']}".encode()).digest())
        for r in ordered:
            ticker = r["ticker"]
            if len(held) >= slots or cash < 1e-10:
                break
            if ticker in held or r["session"] <= last_exit.get(ticker, ""):
                continue
            op = arrays[ticker][i, 0]
            if not np.isfinite(op) or op <= 0:
                continue
            budget = min(cash, open_equity/slots)
            cash -= budget
            held[ticker] = {"qty": budget/(op*1.002), "price": op, "entry": day, "signal": r["session"],
                            "days": 0, "seen": r["recovery"], "nonrec": 0, "pending": None}
        for ticker, p in held.items():
            c = arrays[ticker][i, 3]
            if not np.isfinite(c):
                return {"status": "invalid", "missing": ticker+":"+day}, curve, fills
            p["days"] += 1
            p["seen"] |= states[i]["recovery"]
            p["nonrec"] = 0 if states[i]["recovery"] else p["nonrec"]+1 if p["seen"] else 0
            gain = c/p["price"]-1
            if gain <= -.08:
                p["pending"] = "stop"
            elif gain >= .12:
                p["pending"] = "target"
            elif p["days"] >= 20:
                p["pending"] = "time"
            elif states[i]["peak"] or p["nonrec"] >= 2:
                p["pending"] = "market"
        equity = cash + sum(p["qty"]*arrays[t][i, 3]*.998 for t, p in held.items())
        assert cash >= -1e-10 and len(held) <= slots
        curve.append({"day": day, "equity": equity, "cash": cash, "positions": len(held)})
    eq = pd.Series([1., *[p["equity"] for p in curve]])
    elapsed = (pd.Timestamp(days[-1])-pd.Timestamp(days[0])).days/365.25
    result = {"status": "ok", "final": eq.iloc[-1], "return": eq.iloc[-1]-1, "mdd": (eq/eq.cummax()-1).min(),
              "closed": len(fills), "open": len(held), "mean_exposure": np.mean([1-p["cash"]/p["equity"] for p in curve]),
              "cagr": eq.iloc[-1]**(1/elapsed)-1 if elapsed >= 1 else np.nan}
    return result, curve, fills


def run_dataset(label):
    s, bars, days, states, arrays = load_data(label)
    q = bars["QQQ"].rename(columns=str.title)
    fs = {t: final_feature_frame(b.rename(columns=str.title), q) for t, b in bars.items() if t != "QQQ"}
    extra = []
    for r in s.itertuples():
        f = fs[r.ticker].loc[r.session]
        extra.append({"ticker": r.ticker, "session": r.session, **{k: bool(f[k]) for k in [*PATTERNS, *FILTERS]}})
    s = s.merge(pd.DataFrame(extra), on=["ticker", "session"], validate="one_to_one")
    s.to_pickle(OUT / f"{label}_signals.pkl")
    scores, trades = [], []
    def add(selected, kind, name, variant="common"):
        t = simulate(selected, days, states, arrays)
        if not t.empty:
            trades.append(t.assign(kind=kind, name=name, variant=variant))
        periods = [("all", t)]
        if not t.empty:
            periods += list(t.groupby(t.entry.str[:4])) if label != "2026" else [("early", t[t.entry < "2026-07-01"]), ("late", t[t.entry >= "2026-07-01"])]
        for period, g in periods:
            scores.append({"dataset": label, "kind": kind, "name": name, "variant": variant, "period": period, **metrics(g)})
    existing = ["S1", "S2_core", "S3", "S4", "S5", "S6", "S7"]
    for name in PATTERNS:
        chosen = s[s[name] & s.allowed]
        add(chosen, "pattern", name)
        unique = ~chosen[[*existing, "narrow_range_breakout", "squeeze_breakout"]].any(axis=1)
        add(chosen[unique], "unique_pattern", name)
    for name in existing:
        chosen = s[s[name]].assign(strategy_eval=name)
        add(chosen, "existing", name)
        for filt in FILTERS:
            if filt == "fresh_ma_support" and name not in {"S2_core", "S7"}:
                continue
            add(chosen[chosen[filt]], "filter", name, filt)
    variants = {"S7": s.S7, "S7_QQQ": s.S7 & s.rs20_positive,
                "S7_watchlist": s.S7 & s.rs_vs_watchlist, "S7_both": s.S7 & s.rs20_positive & s.rs_vs_watchlist}
    portfolio_rows, curves = [], []
    for variant, mask in variants.items():
        for seed in range(20):
            p, curve, fills = portfolio(s[mask], days, states, arrays, seed)
            portfolio_rows.append({"dataset": label, "variant": variant, "seed": seed, **p})
            if seed == 0:
                curves.extend({"variant": variant, **row} for row in curve)
    score = pd.DataFrame(scores)
    score.to_csv(OUT / f"{label}_scorecard.csv", index=False)
    pd.concat(trades).to_pickle(OUT / f"{label}_trades.pkl")
    pd.DataFrame(portfolio_rows).to_csv(OUT / f"{label}_portfolios.csv", index=False)
    pd.DataFrame(curves).to_csv(OUT / f"{label}_portfolio_curves.csv", index=False)
    prior = pd.read_csv(ROOT / "research/extended_review_20261004" / f"{label}_scorecard.csv")
    validation = []
    for name in existing:
        a = prior[(prior.kind == "existing") & (prior.name == name) & (prior.period == "all")].iloc[0]
        b = score[(score.kind == "existing") & (score.name == name) & (score.period == "all")].iloc[0]
        assert a.n == b.n and (a.n == 0 or np.isclose(a["mean"], b["mean"])), (label, name, a.n, b.n)
        validation.append({"base": name, "matching_prior_n_and_mean": True})
    for ticker in list(fs)[:3]:
        b = bars[ticker].iloc[:-13]
        prefix = final_feature_frame(b.rename(columns=str.title), q.loc[:b.index[-1]])
        columns = [*PATTERNS, *FILTERS]
        assert prefix[columns].iloc[-1].equals(fs[ticker][columns].loc[b.index[-1]]), ticker
        validation.append({"ticker": ticker, "prefix_invariant": True})
    (OUT / f"{label}_validation.json").write_text(json.dumps(validation, indent=2))
    print(label, "complete", len(score), "scores; portfolio status", pd.DataFrame(portfolio_rows).status.value_counts().to_dict(), flush=True)


if __name__ == "__main__":
    (OUT / "protocol.json").write_text(json.dumps(PROTOCOL, ensure_ascii=False, indent=2))
    run_dataset("2026")
    run_dataset("2021_2025")
