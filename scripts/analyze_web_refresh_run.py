"""Diagnose a Web data refresh GitHub Actions run.

The script correlates three signals:
- GitHub Actions log output for notification steps
- the cache commit produced by the run
- stock/opinion and trade-log diffs inside that commit

Usage:
    python3 scripts/analyze_web_refresh_run.py 25578358385
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any


STOCKS_PATH = "web/public/api/stocks.json"
TRADE_LOGS_PATH = "web/public/api/trade-logs.json"
WORKFLOW = "web-data-refresh.yml"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class OpinionChange:
    ticker: str
    old: str
    new: str


@dataclass(frozen=True)
class TradeLogAddition:
    ticker: str
    buy_date: str
    strategy: str


def run(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)


def fetch_origin() -> None:
    try:
        run(["git", "fetch", "origin", "main"])
    except subprocess.CalledProcessError as exc:
        print(f"[warn] git fetch failed; continuing with local refs: {exc.output.strip()}")


def latest_run_id() -> str:
    payload = run([
        "gh",
        "run",
        "list",
        "--workflow",
        WORKFLOW,
        "--limit",
        "1",
        "--json",
        "databaseId",
    ])
    runs = json.loads(payload)
    if not runs:
        raise RuntimeError(f"No recent runs found for {WORKFLOW}.")
    return str(runs[0]["databaseId"])


def run_metadata(run_id: str) -> dict[str, Any]:
    payload = run([
        "gh",
        "run",
        "view",
        run_id,
        "--json",
        "databaseId,event,status,conclusion,createdAt,updatedAt,headSha,headBranch,url",
    ])
    return json.loads(payload)


def run_log(run_id: str) -> str:
    return run(["gh", "run", "view", run_id, "--log"])


def cache_commit_from_log(log: str) -> str | None:
    matches = re.findall(r"\[main ([0-9a-f]{6,40})\] Update scheduled web data caches", log)
    return matches[-1] if matches else None


def load_git_json(ref: str, path: str) -> Any:
    return json.loads(run(["git", "show", f"{ref}:{path}"]))


def stock_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("rows") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("ticker", "")).strip(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("ticker", "")).strip()
    }


def opinion_changes(commit: str) -> list[OpinionChange]:
    previous = stock_rows(load_git_json(f"{commit}^", STOCKS_PATH))
    current = stock_rows(load_git_json(commit, STOCKS_PATH))
    changes: list[OpinionChange] = []
    for ticker, current_row in current.items():
        previous_row = previous.get(ticker)
        if not previous_row:
            continue
        old = str(previous_row.get("opinion") or "").strip()
        new = str(current_row.get("opinion") or "").strip()
        if old and new and old != new:
            changes.append(OpinionChange(ticker=ticker, old=old, new=new))
    return changes


def trade_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("ticker") or ""),
        str(row.get("buyDate") or ""),
        str(row.get("strategy") or ""),
    )


def trade_log_additions(commit: str) -> list[TradeLogAddition]:
    previous = load_git_json(f"{commit}^", TRADE_LOGS_PATH)
    current = load_git_json(commit, TRADE_LOGS_PATH)
    previous_rows = previous.get("rows") if isinstance(previous, dict) else []
    current_rows = current.get("rows") if isinstance(current, dict) else []
    if not isinstance(previous_rows, list) or not isinstance(current_rows, list):
        return []
    previous_keys = {trade_key(row) for row in previous_rows if isinstance(row, dict)}
    additions: list[TradeLogAddition] = []
    for row in current_rows:
        if not isinstance(row, dict):
            continue
        key = trade_key(row)
        if key not in previous_keys:
            additions.append(TradeLogAddition(ticker=key[0], buy_date=key[1], strategy=key[2]))
    return additions


def extract_line(log: str, pattern: str) -> str | None:
    fallback: str | None = None
    for line in log.splitlines():
        if pattern in line:
            clean = ANSI_RE.sub("", line)
            if "echo " not in clean:
                return clean
            fallback = clean
    return fallback


def print_section(title: str) -> None:
    print(f"\n## {title}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id", nargs="?", default="latest", help="GitHub Actions run id, or 'latest'.")
    parser.add_argument("--no-fetch", action="store_true", help="Do not fetch origin/main before analysis.")
    args = parser.parse_args()

    if not args.no_fetch:
        fetch_origin()

    run_id = latest_run_id() if args.run_id == "latest" else str(args.run_id)
    meta = run_metadata(run_id)
    log = run_log(run_id)
    commit = cache_commit_from_log(log)

    print_section("Run")
    print(f"id: {run_id}")
    print(f"event: {meta.get('event')}")
    print(f"status: {meta.get('status')} / {meta.get('conclusion')}")
    print(f"createdAt: {meta.get('createdAt')}")
    print(f"url: {meta.get('url')}")

    print_section("Workflow Signals")
    for marker in [
        "Resolved refresh tasks:",
        "Send notifications:",
        "[api_logs] recorded",
        "No opinion changes.",
        "Sent opinion notifications:",
        "Nasdaq peak state reset.",
        "Nasdaq peak notification already sent.",
        "Sent nasdaq peak notifications:",
    ]:
        line = extract_line(log, marker)
        if line:
            print(line)

    if not commit:
        print_section("Diff")
        print("No cache commit found in this run log.")
        return 0

    print_section("Diff")
    print(f"cache_commit: {commit}")
    try:
        changes = opinion_changes(commit)
        trade_additions = trade_log_additions(commit)
    except subprocess.CalledProcessError as exc:
        print(f"[error] Could not inspect commit diff: {exc.output.strip()}")
        return 1

    print(f"opinion_changes: {len(changes)}")
    for change in changes:
        print(f"- {change.ticker}: {change.old} -> {change.new}")

    print(f"trade_log_additions: {len(trade_additions)}")
    for addition in trade_additions:
        print(f"- {addition.ticker}: {addition.buy_date} / {addition.strategy}")

    print_section("Diagnosis")
    if changes and "No opinion changes." in log:
        print("Finding: opinion changes existed in the cache commit, but the notification step reported none.")
        print("Likely cause: the previous stocks snapshot was unavailable or stale when the opinion email step ran.")
        print("Check that the workflow passes a preserved previous snapshot to web_refresh_notifications.py opinion.")
    elif changes and "Sent opinion notifications:" in log:
        print("Finding: opinion changes existed and the notification step reported a send.")
    elif not changes and "No opinion changes." in log:
        print("Finding: no opinion changes existed in the cache commit, so no opinion email was expected.")
    else:
        print("Finding: no definitive opinion-email mismatch detected from available logs.")

    if "Nasdaq peak state reset." in log:
        print("Note: Nasdaq peak was reset, not sent, in this run.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
