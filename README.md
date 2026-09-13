# NQ Reversal Research — data & harness

Static store so chart data never has to be re-uploaded to a chat session.
Sandbox sessions fetch from here with `curl`; GitHub raw is reachable, Drive/Dropbox are not.

## Layout

```
├── README.md
├── bootstrap.py        # run first in any session: fetches + verifies everything
├── nq_harness.py       # §4-compliant backtest harness, Pine-faithful primitives
├── manifest.json       # list of data files (so new instruments need no code edit)
└── data/
    ├── CME_MINI_NQ1___3__5_.csv     3m  master  20,620 bars  13 Jul → 12 Sep 2026
    ├── CME_MINI_NQ1___5__5_.csv     5m  master  20,556 bars   1 Jun → 12 Sep 2026
    ├── CME_MINI_NQ1___6__4_.csv     6m  master  18,848 bars  20 May → 12 Sep 2026
    └── CME_MINI_NQ1___15__2_.csv   15m  master   8,368 bars   7 May → 12 Sep 2026
```

Only the four masters are stored. The other twelve files in the original export were verified
byte-identical trailing windows of these — redundant.

## What does NOT belong here

Indicator source code, if it is proprietary. This repo is public. Paste `.pine` files directly
into the chat instead; they are small and need no persistence.

## Adding a new instrument or timeframe

1. Drop the CSV in `data/`.
2. Add the filename to the `data` array in `manifest.json`.

`bootstrap.py` will flag it as NEW and print a fresh inventory rather than assuming it matches
the NQ files. Nothing measured on NQ — session buckets, dead zone, ATR levels, the confluence
result — transfers to another instrument without being re-measured.

## Integrity

`bootstrap.py` carries hard-coded sha256 hashes for the four masters, measured 13 Sep 2026.
This is deliberate: a previous TradingView re-export **reused filenames while changing the
contents**, which silently invalidated a file named as "master" in the project handoff. A
filename is not an identity. If bootstrap prints `CHANGED`, the stored conclusions about that
file no longer apply and the inventory must be re-run.

Known data defect carried in the set: the **15 Jun 2026** session opens +513.25 pts, ten times
the 90th-percentile session gap, consistent across all four timeframes. Real news gap or an
NQ1! continuous-contract splice — unresolved. The harness quarantines that session by default.
