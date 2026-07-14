# Strategy Rollback

## Current rollback tag (pre Strategy 1/2)

- Tag: `rollback/pre-strategy-1-2-20260714`
- Commit: `e638a35` (A–H multi-strategy system)
- Restore:

```bash
git fetch --tags
git checkout rollback/pre-strategy-1-2-20260714
# or hard reset main (destructive):
# git reset --hard rollback/pre-strategy-1-2-20260714 && git push --force
```

## What changed after this tag

- Active strategies: **1 (공황 저점)**, **2 (이평선 눌림)** only
- Season opens on strategy 1 signal; strategy 2 only while season open + recovery
- Exit: recovery end (2-day confirm) full sell, or -30% hard stop
- Trade logs: retired A/C/D/E/F/G/H rows cleared; B migrated to 1
