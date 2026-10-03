"""Prospective, private paired swing research; no orders or notification writes."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HISTORY = ROOT / "data/history/swing-research"
NY = ZoneInfo("America/New_York")
ETF = {"QQQ", "QLD", "USD", "SOXL", "SOXS", "HOOG"}
PROTOCOL = {
    "version": "swing-paired-v1",
    "startSession": "2026-10-05",
    "earliestReviewKST": "2026-12-08",
    "minimumCalendarMonths": 2,
    "minimumClosedFilteredTrades": 30,
    "minimumFilteredEntryDates": 15,
    "recoveryBuyCap": 14.0,
    "recoveryExit": 18.0,
    "normalBuyCap": 9.0,
    "roundTripCost": 0.004,
    "entry": "D completed daily bar, next QQQ regular session open",
    "s7Exit": "close-confirmed -8%/+10%, recovery end twice, or market peak; next open",
    "laggardExit": "close-confirmed -8%/+12%/20 sessions; next open; market block ignored only in paper",
    "arms": ["s7_base", "s7_rs_positive", "laggard_rebound"],
    "s7Priority": "independent S7 predicate, no 1-6 priority or account slot limits",
    "pairedCoverage": "both S7 arms require available rs20; missing values are not classified as negative",
    "excludedKnownETFs": sorted(ETF),
    "reentry": "new eligible signal strictly after prior exit session; no overlapping same-ticker arm positions",
    "missingPrices": "invalidate affected trade; never substitute a later entry/exit open",
    "dividends": "price returns only; cash dividends excluded",
    "purpose": "research only; no orders, public API, alerts or live trade-log writes",
}


def read_lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if not path.exists() or path.read_text() != text:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(text)
        temp.replace(path)


def write_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for r in rows)
    if not path.exists() or path.read_text() != text:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(text)
        temp.replace(path)


def number(value):
    return float(value) if value is not None and math.isfinite(float(value)) else None


def initialize(history=HISTORY):
    path = history / "protocol.json"
    if path.exists() and json.loads(path.read_text()) != PROTOCOL:
        raise RuntimeError("research protocol changed; start a new version instead of mixing rules")
    write_json(path, PROTOCOL)


def tracked_tickers(history=HISTORY):
    return sorted({r["ticker"] for r in read_lines(history / "observations.jsonl")})


def signal_flags(features, market, eligible=True):
    required = [features.get(k) for k in ("close", "open", "previousClose", "low", "ma200", "rs20")]
    if any(x is None for x in required):
        return {"s7_base": False, "s7_rs_positive": False, "laggard_rebound": False}
    close = features["close"]
    touch = any(features["low"] <= ma * 1.003 and close > ma for ma in features["movingAverages"].values())
    base = bool(eligible and market["buyAllowed"] and touch and close > features["open"] and close > features["previousClose"])
    laggard = bool(eligible and market["premium"] > 14 and close < features["ma200"]
                   and features.get("histChange") is not None and features["histChange"] > 0)
    return {"s7_base": base, "s7_rs_positive": base and features["rs20"] > 0, "laggard_rebound": laggard}


def market_rows(frame):
    from calculator.indicators import rsi
    close = frame.Close
    dist = (close / close.rolling(200).mean() - 1) * 100
    daily_rsi = rsi(close)
    hist = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    hist = hist - hist.ewm(span=9, adjust=False).mean()
    blocked = False
    result = {}
    for i, day in enumerate(frame.index):
        premium = number(dist.iloc[i])
        if premium is None:
            continue
        if premium < -3:
            blocked = True
        elif premium >= -2.5:
            blocked = False
        recovery = dist.iloc[max(0, i - 59):i + 1].min() <= -5 and premium >= 0
        weekly = close.iloc[:i + 1].copy()
        weekly.index = pd.to_datetime(weekly.index)
        wrsi = number(rsi(weekly.resample("W-FRI").last().dropna()).iloc[-1])
        drsi, prev = number(daily_rsi.iloc[i]), number(daily_rsi.iloc[i - 1])
        hot = wrsi is not None and drsi is not None and prev is not None and wrsi >= 65 and drsi >= 65 and drsi < prev
        slowing = i >= 2 and hist.iloc[i] < hist.iloc[i - 1] < hist.iloc[i - 2]
        peak = premium > 18 if recovery else hot and (premium > 16 or premium > 14 and slowing)
        cap = 14 if recovery else 9
        result[day] = {"premium": premium, "recovery": bool(recovery), "peak": bool(peak),
                       "buyAllowed": bool(not blocked and -3 <= premium <= cap and not peak),
                       "buyCap": cap, "dailyRSI": drsi, "weeklyRSI": wrsi,
                       "hist": number(hist.iloc[i]), "histChange": number(hist.diff().iloc[i])}
    return result


def extract_frames(daily, tickers):
    from scripts.record_gap_go_observations import _ohlcv_frame, _series, index_dates
    frames = {}
    for ticker in tickers:
        frame = _ohlcv_frame(daily, ticker)
        if frame.empty:
            continue
        frame.index = [d.isoformat() for d in frame.pop("_session")]
        splits = _series(daily, "Stock Splits", ticker)
        split_map = dict(zip((d.isoformat() for d in index_dates(splits.index)), splits))
        frame["split"] = [number(split_map.get(day)) or 1.0 for day in frame.index]
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        frames[ticker] = frame
    return frames


def replay(observations, sessions):
    days = sorted(sessions)
    trades = []
    last = {}
    labels = []
    for obs in sorted(observations, key=lambda r: (r["session"], r["ticker"])):
        signal, ticker = obs["session"], obs["ticker"]
        following = [d for d in days if d > signal]
        if not following or not obs["forwardEligible"]:
            continue
        entry_day = following[0]
        entry_bar = sessions[entry_day]["bars"].get(ticker)
        # All S7 signals get labels, including those rejected by relative strength.
        if entry_bar and any(obs["signals"].values()):
            factor = 1.0
            path = []
            for day in following[:20]:
                bar = sessions[day]["bars"].get(ticker)
                if bar is None:
                    break
                if path:
                    factor *= bar.get("split", 1.0)
                path.append({k: bar[k] * factor for k in ("open", "high", "low", "close")})
                horizon = len(path)
                if horizon in (5, 10, 20):
                    entry = entry_bar["open"]
                    labels.append({"signal": signal, "ticker": ticker, "entry": entry_day, "horizon": horizon,
                                   "through": day, "signals": obs["signals"],
                                   "net": path[-1]["close"] / entry - 1 - .004,
                                   "mae": min(b["low"] for b in path) / entry - 1,
                                   "mfe": max(b["high"] for b in path) / entry - 1})
        for arm, passed in obs["signals"].items():
            if not passed or signal <= last.get((arm, ticker), ""):
                continue
            trade = {"id": f"{arm}:{ticker}:{signal}", "arm": arm, "ticker": ticker,
                     "signal": signal, "entry": entry_day, "status": "open", "rs20": obs["features"]["rs20"]}
            if entry_bar is None:
                trade.update(status="invalid", reason="missing_next_session_open")
                trades.append(trade)
                continue
            entry = entry_bar["open"]
            trade.update(entryPrice=entry, entryGap=entry / (obs["features"]["close"] / entry_bar.get("split", 1.0)) - 1)
            factor, seen_recovery, nonrecovery = 1.0, bool(obs.get("market", {}).get("recovery")), 0
            pending = None
            lows, highs = [], []
            for count, day in enumerate(following, 1):
                session = sessions[day]
                bar = session["bars"].get(ticker)
                if bar is None:
                    trade.update(status="invalid", reason="missing_position_bar", missingSession=day)
                    last[arm, ticker] = day
                    break
                if count > 1:
                    factor *= bar.get("split", 1.0)
                if pending:
                    px = bar["open"] * factor
                    trade.update(status="closed", exit=day, exitPrice=bar["open"], splitFactor=factor,
                                 net=px / entry - 1 - .004, reason=pending, holdingSessions=count - 1)
                    last[arm, ticker] = day
                    break
                lows.append(bar["low"] * factor)
                highs.append(bar["high"] * factor)
                gain = bar["close"] * factor / entry - 1
                market = session["market"]
                seen_recovery |= market["recovery"]
                nonrecovery = 0 if market["recovery"] else nonrecovery + 1 if seen_recovery else 0
                if gain <= -.08:
                    pending = "stop_8_close"
                elif gain >= (.12 if arm == "laggard_rebound" else .10):
                    pending = "target_close"
                elif arm == "laggard_rebound" and count >= 20:
                    pending = "time_20"
                elif arm != "laggard_rebound" and (market["peak"] or nonrecovery >= 2):
                    pending = "market_peak" if market["peak"] else "recovery_end_2"
                trade.update(markSession=day, markNet=gain - .004, pendingExit=pending,
                             holdingSessions=count, splitFactor=factor)
                last[arm, ticker] = day
            trade.update(mae=min(lows) / entry - 1 if lows else None, mfe=max(highs) / entry - 1 if highs else None)
            trades.append(trade)
    return trades, labels


def collect(daily, tickers, now=None, history=HISTORY, event_payload=None, names=None):
    initialize(history)
    current = (now or datetime.now(timezone.utc)).astimezone(NY)
    frames = extract_frames(daily, sorted(set(tickers) | set(tracked_tickers(history)) | {"QQQ"}))
    qqq = frames.get("QQQ")
    if qqq is None or qqq.empty:
        raise RuntimeError("swing research: QQQ daily bars missing")
    complete = [d for d in qqq.index if d < current.date().isoformat() or
                d == current.date().isoformat() and current.time() >= time(16, 5)]
    complete = [d for d in complete if d >= PROTOCOL["startSession"]]
    observations = read_lines(history / "observations.jsonl")
    sessions = {r["session"]: r for r in read_lines(history / "sessions.jsonl")}
    capture = current.astimezone(timezone.utc).isoformat()
    states = market_rows(qqq.loc[:complete[-1]]) if complete else {}
    for day in complete:
        if day in sessions:
            continue
        bars = {}
        for ticker, frame in frames.items():
            if day in frame.index:
                row = frame.loc[day]
                bar = {k.lower(): number(row[k]) for k in ("Open", "High", "Low", "Close")}
                if all(v is not None and v > 0 for v in bar.values()):
                    bars[ticker] = {**bar, "split": float(row["split"])}
        sessions[day] = {"session": day, "capturedAt": capture, "market": states[day], "bars": bars}
    if complete:
        day = complete[-1]
        already = {r["ticker"] for r in observations if r["session"] == day}
        # Never backfill a signal after its entry session has started.
        later = [d for d in qqq.index if d > day and d <= current.date().isoformat()]
        forward = not later
        from calculator.pipeline import current_market_event_label
        event_known = isinstance(event_payload, dict) and "groups" in event_payload
        event = current_market_event_label(event_payload, now=datetime.fromisoformat(day + "T16:00:00").replace(tzinfo=NY)) if event_known else "unknown"
        for ticker in sorted(set(tickers) - already - {"QQQ"}):
            frame = frames.get(ticker)
            if frame is None or day not in frame.index:
                continue
            f = frame.loc[:day]
            if len(f) < 200:
                continue
            closes = f.Close
            previous_day = qqq.index[qqq.index.get_loc(day) - 20]
            rs = (closes.iloc[-1] / f.loc[previous_day, "Close"] - qqq.loc[day, "Close"] / qqq.loc[previous_day, "Close"]) * 100 if previous_day in f.index else None
            hist = closes.ewm(span=12, adjust=False).mean() - closes.ewm(span=26, adjust=False).mean()
            hist = hist - hist.ewm(span=9, adjust=False).mean()
            averages = {str(n): float(closes.iloc[-n:].mean()) for n in (20, 50, 120, 200)}
            features = {"close": float(closes.iloc[-1]), "open": float(f.Open.iloc[-1]), "low": float(f.Low.iloc[-1]),
                        "previousClose": float(closes.iloc[-2]), "ma200": averages["200"], "movingAverages": averages,
                        "rs20": number(rs), "histChange": number(hist.diff().iloc[-1])}
            name = (names or {}).get(ticker, "")
            excluded = ticker in ETF or any(word in name.upper() for word in ("ETF", "DIREXION", "PROSHARES", "LEVERAGED", "2X", "3X"))
            market = {**states[day], "event": event, "buyAllowed": states[day]["buyAllowed"] and event == "당분간 없음"}
            observations.append({"session": day, "ticker": ticker, "capturedAt": capture, "forwardEligible": forward,
                                 "excludedETF": excluded, "features": features, "market": market,
                                 "signals": signal_flags(features, market, eligible=not excluded),
                                 "source": "Yahoo completed daily OHLCV", "version": PROTOCOL["version"]})
    write_lines(history / "sessions.jsonl", [sessions[d] for d in sorted(sessions)])
    write_lines(history / "observations.jsonl", sorted(observations, key=lambda r: (r["session"], r["ticker"])))
    trades, labels = replay(observations, sessions)
    write_lines(history / "paper-trades.jsonl", trades)
    write_lines(history / "forward-outcomes.jsonl", labels)
    filtered = [r for r in trades if r["arm"] == "s7_rs_positive" and r["status"] == "closed"]
    summary = {"version": PROTOCOL["version"], "startSession": PROTOCOL["startSession"],
               "lastSession": max(sessions) if sessions else None, "observations": len(observations),
               "signalCounts": {a: sum(r["forwardEligible"] and r["signals"][a] for r in observations) for a in PROTOCOL["arms"]},
               "filteredClosed": len(filtered), "filteredEntryDates": len({r["entry"] for r in filtered}),
               "earliestReviewKST": PROTOCOL["earliestReviewKST"],
               "sampleReady": len(filtered) >= 30 and len({r["entry"] for r in filtered}) >= 15,
               "status": "collecting" if observations else "awaiting_first_session",
               "collectorHash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    write_json(history / "summary.json", summary)
    print(f"[swing-research] {summary['status']}; observations={len(observations)}, paper trades={len(trades)}")
    return summary


if __name__ == "__main__":
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import yfinance as yf
    stocks = json.loads((ROOT / "data/cache/stocks.json").read_text())["rows"]
    names = {r["ticker"]: r.get("name", "") for r in stocks if r.get("market") == "US"}
    symbols = sorted(set(names) | set(tracked_tickers()) | {"QQQ"})
    daily = yf.download(symbols, period="2y", interval="1d", auto_adjust=False, actions=True, progress=False, threads=True)
    events = json.loads((ROOT / "data/cache/market-events.json").read_text())
    collect(daily, list(names), event_payload=events, names=names)
