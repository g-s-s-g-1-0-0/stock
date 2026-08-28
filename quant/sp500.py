"""Point-in-time S&P 500 membership, rebuilt from Wikipedia.

The `.bt_cache` universe is a thematic watchlist written in 2026, which makes
any cross-sectional excess return meaningless near the end of the sample (see
`quant/universe_bias.py`). This module replaces it with membership that was
knowable at the time.

Two Wikipedia pages are used: the current constituent list, and the table of
index additions and removals. Walking the changes backward from today's list
reconstructs who was in the index on any past date.

The reconstruction is only as complete as the changes table, and it says
nothing about whether price data exists for a past member -- delisted names
are still missing. `coverage_report` measures that gap instead of hiding it.
"""

from __future__ import annotations

import io
import os
import urllib.request

import pandas as pd

CURRENT_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
CHANGES_URL = "https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500"
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
UA = {"User-Agent": "Mozilla/5.0 (research; backtest universe reconstruction)"}


def _fetch(url: str, cache_name: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    request = urllib.request.Request(url, headers=UA)
    html = urllib.request.urlopen(request, timeout=60).read().decode("utf-8")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return html


def _yahoo(ticker: str) -> str:
    """Wikipedia writes share classes as BRK.B; Yahoo wants BRK-B.

    Some cells carry a trailing pipe left over from wiki table markup.
    """
    cleaned = str(ticker).strip().upper().replace(".", "-")
    return cleaned.split("|")[0].strip()


def current_members() -> tuple[set[str], pd.DataFrame]:
    table = pd.read_html(io.StringIO(_fetch(CURRENT_URL, "sp500_current.html")))[0]
    table["Symbol"] = table["Symbol"].map(_yahoo)
    return set(table["Symbol"]), table


def changes() -> pd.DataFrame:
    table = pd.read_html(io.StringIO(_fetch(CHANGES_URL, "sp500_changes.html")))[0]
    table.columns = ["_".join(str(p) for p in col) for col in table.columns]
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(table.iloc[:, 0], errors="coerce"),
            "added": table.iloc[:, 1],
            "removed": table.iloc[:, 3],
        }
    ).dropna(subset=["date"])
    for column in ("added", "removed"):
        frame[column] = frame[column].map(
            lambda v: _yahoo(v) if isinstance(v, str) and v.strip() else None
        )
    return frame.sort_values("date").reset_index(drop=True)


def membership() -> pd.DataFrame:
    """Boolean membership frame: rows are change dates, columns are tickers.

    Row ``d`` describes who was in the index from ``d`` until the next row.
    """
    current, _ = current_members()
    events = changes()

    # Walk backward from today's list to recover the earliest known roster.
    roster = set(current)
    for _, event in events[::-1].iterrows():
        if event["added"]:
            roster.discard(event["added"])
        if event["removed"]:
            roster.add(event["removed"])

    # Then walk forward, snapshotting after each change.
    dates = [events["date"].iloc[0] - pd.Timedelta(days=1)]
    snapshots = [set(roster)]
    for _, event in events.iterrows():
        if event["added"]:
            roster.add(event["added"])
        if event["removed"]:
            roster.discard(event["removed"])
        dates.append(event["date"])
        snapshots.append(set(roster))

    tickers = sorted(set().union(*snapshots))
    frame = pd.DataFrame(
        [[t in snap for t in tickers] for snap in snapshots],
        index=pd.DatetimeIndex(dates, name="date"),
        columns=tickers,
    )
    return frame[~frame.index.duplicated(keep="last")].sort_index()


def daily_membership(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Expand the change-date frame onto a trading calendar."""
    frame = membership()
    return frame.reindex(frame.index.union(index)).ffill().reindex(index).fillna(False)


def summary() -> None:
    current, table = current_members()
    events = changes()
    frame = membership()

    print(f"current members: {len(current)}")
    print(f"change events: {len(events)}  ({events['date'].min().date()} .. {events['date'].max().date()})")
    print(f"unique tickers ever seen: {frame.shape[1]}")
    print(f"ever left the index: {len(set(frame.columns) - current)}")

    print("\n--- reconstructed roster size at year start ---")
    rows = {}
    for year in range(2000, 2027):
        stamp = pd.Timestamp(f"{year}-01-01")
        window = frame.loc[frame.index <= stamp]
        rows[year] = int(window.iloc[-1].sum()) if len(window) else 0
    print(pd.Series(rows).to_string())

    print("\n--- change events per year ---")
    print(events.groupby(events["date"].dt.year).size().to_string())


if __name__ == "__main__":
    summary()
