#!/usr/bin/env python3
"""Wait so a follow-up push to main does not overlap the previous one.

Vercel clones the repository on every push to main, before it can skip a
data-only build. Automated pushes a minute apart make those clones fail with
GitHub's secondary rate limit, and Vercel emails a failed production deploy.
The published site is unchanged. Call this only after the on-time cache push.
"""

from __future__ import annotations

import subprocess
import sys
import time

GAP_SECONDS = 180


def seconds_until_clear(commit_epoch: int, now: float, gap_seconds: int = GAP_SECONDS) -> float:
    return max(0.0, gap_seconds - (now - commit_epoch))


def latest_commit_epoch(branch: str) -> int | None:
    subprocess.check_call(["git", "fetch", "origin", branch])
    try:
        output = subprocess.check_output(
            ["git", "log", "-1", "--format=%ct", f"origin/{branch}"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except subprocess.CalledProcessError:
        return None
    if not output:
        return None
    return int(output)


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    branch = args[0] if args else "main"
    epoch = latest_commit_epoch(branch)
    if epoch is None:
        return
    wait = seconds_until_clear(epoch, time.time())
    if wait <= 0:
        print(f"Previous main commit is already {GAP_SECONDS}s old; pushing now.")
        return
    print(f"Waiting {int(wait)}s so the previous main push is not cloned at the same time.")
    time.sleep(wait)


if __name__ == "__main__":
    main()
