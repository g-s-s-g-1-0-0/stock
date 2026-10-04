from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.final_review_20261004.run import load_data
from scripts.record_final_candidates import ARMS, ARM_RULES
from scripts.record_swing_research import replay

OUT = Path(__file__).resolve().parent
s = pd.read_pickle(OUT/"2026_signals.pkl")
t = pd.read_pickle(OUT/"2026_trades.pkl")
_, bars, days, states, arrays = load_data("2026")
sessions = {d: {"market": states[i], "bars": {ticker: {"open": float(a[i, 0]), "high": float(a[i, 1]), "low": float(a[i, 2]), "close": float(a[i, 3]), "split": 1.}
                                              for ticker, a in arrays.items() if np.isfinite(a[i]).all()}}
            for i, d in enumerate(days)}
checks = []
for arm, cfg in ARMS.items():
    source = cfg["source"]
    column = "S2_core" if source == "S2" else source
    mask = s[column] & (s.allowed if cfg["filter"] is None else s[cfg["filter"]])
    selected = s[mask]
    observations = [{"session": r.session, "ticker": r.ticker, "forwardEligible": True,
                     "market": {"recovery": r.recovery}, "features": {"close": r.close, "low": r.signal_low, "rs20": 0., "supportStop": r.support_stop},
                     "signals": {arm: True}} for r in selected.itertuples()]
    actual, _ = replay(observations, sessions, {arm: ARM_RULES[arm]})
    kind = "pattern" if cfg["filter"] is None else "filter"
    variant = cfg["filter"] or "common"
    expected = t[(t.kind == kind) & (t.name == column) & (t.variant == variant)]
    assert len(actual) == len(expected), (arm, len(actual), len(expected))
    if actual:
        a = pd.DataFrame(actual)
        if "net" not in a:
            a["net"] = np.nan
        if "exit" not in a:
            a["exit"] = None
        merged = expected.merge(a, left_on=["ticker", "session"], right_on=["ticker", "signal"], suffixes=("_test", "_paper"), validate="one_to_one")
        assert (merged.status_test == merged.status_paper).all(), arm
        closed = merged[merged.status_test == "closed"]
        assert np.allclose(closed.net_test, closed.net_paper), arm
        assert (closed.exit_test == closed.exit_paper).all(), arm
        opened = merged[merged.status_test == "open"]
        if len(opened):
            assert np.allclose(opened.net_test, opened.markNet), arm
    checks.append({"arm": arm, "trades": len(actual), "matching_recorder": True})
(OUT/"recorder_verification.json").write_text(json.dumps(checks, indent=2))
print("verified", len(checks), "final paper variants")
