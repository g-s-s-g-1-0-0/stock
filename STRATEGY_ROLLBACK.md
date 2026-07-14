# Strategy Rollback

## Web A–H rollback (before Strategy 1/2)

- Tag: `rollback/pre-strategy-1-2-20260714`
- Restore:

```bash
git fetch --tags
git checkout rollback/pre-strategy-1-2-20260714
```

## GAS A–H rollback (before GAS Strategy 1/2 sync)

- Tag: `rollback/pre-gas-strategy-1-2-20260714`
- At this tag: **web already Strategy 1/2**, **GAS still A–H**
- Restore GAS files only:

```bash
git fetch --tags
git checkout rollback/pre-gas-strategy-1-2-20260714 -- '*.gs'
```

## What Strategy 1/2 means

- **1 공황 저점**: former B entry; opens buy season
- **2 이평선 눌림**: MA20/60/144/200 touch while season open + recovery
- Exit: recovery end (2-day confirm) full sell, or -30% stop
