#!/usr/bin/env python3
"""
NQ PROJECT BOOTSTRAP
Run this at the start of any session. It pulls the dataset + harness from GitHub
onto the sandbox disk and VERIFIES them, so no CSV ever needs re-uploading.

Usage:
    python3 bootstrap.py                      # uses BASE below
    python3 bootstrap.py <raw_base_url>       # or pass it in

The verification step exists because of a real defect already seen on this
project: TradingView re-exports REUSE FILENAMES while changing contents. A
filename is not an identity. Hashes are.
"""
import hashlib
import json
import os
import subprocess
import sys

# ---- EDIT THIS ONCE: your repo's raw base URL, no trailing slash -------------
BASE = "https://raw.githubusercontent.com/sahajoydeep/nq-research-data/main"
# -----------------------------------------------------------------------------

DEST = "/home/claude/nq"

# Known-good fingerprints, measured 13 Sep 2026. Independent of the repo, so a
# tampered or stale manifest cannot make a bad file look good.
KNOWN = {
    "CME_MINI_NQ1___3__5_.csv": dict(
        sha256="ebd0b30495ca302377a7d9d580eaacf6c4d6ec918ca0880f02eac95dce4655b6",
        rows=20620, tf=3, first="2026-07-13T03:30:00+05:30", last="2026-09-12T02:27:00+05:30"),
    "CME_MINI_NQ1___5__5_.csv": dict(
        sha256="2b495a105d99a426ffccad8bd50ff779b25c7f8b414a21acaa4c5903a049227a",
        rows=20556, tf=5, first="2026-06-01T03:30:00+05:30", last="2026-09-12T02:25:00+05:30"),
    "CME_MINI_NQ1___6__4_.csv": dict(
        sha256="cac01d3386a33678310ab3a708fc1bb7b90f07b976cc83eb4ddd5ee487a876ec",
        rows=18848, tf=6, first="2026-05-20T11:42:00+05:30", last="2026-09-12T02:24:00+05:30"),
    "CME_MINI_NQ1___15__2_.csv": dict(
        sha256="052b4fce9ec5404e317a5efe77884f99467f7168476b2531a0ca302eb53ebad8",
        rows=8368, tf=15, first="2026-05-07T11:30:00+05:30", last="2026-09-12T02:15:00+05:30"),
}

CODE = ["nq_harness.py"]


def fetch(rel, base):
    out = os.path.join(DEST, os.path.basename(rel))
    r = subprocess.run(["curl", "-sfL", "-o", out, f"{base}/{rel}"], capture_output=True)
    return out if r.returncode == 0 else None


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else BASE).rstrip("/")
    if "USERNAME/REPO" in base:
        sys.exit("Set BASE at the top of this file, or pass the raw base URL as an argument.")
    os.makedirs(DEST, exist_ok=True)

    import pandas as pd

    # 1. code first, so the harness is importable
    for c in CODE:
        p = fetch(c, base)
        print(f"{'ok  ' if p else 'MISS'} {c}")

    # 2. manifest is optional; it lets you add instruments without editing this file
    man, extra = fetch("manifest.json", base), []
    if man:
        try:
            extra = [f for f in json.load(open(man)).get("data", []) if f not in KNOWN]
        except Exception:
            extra = []

    # 3. known data files: fetch + verify
    print("\n--- verifying known files ---")
    ok = True
    for name, exp in KNOWN.items():
        p = fetch(f"data/{name}", base) or fetch(name, base)
        if not p:
            print(f"MISSING  {name}")
            ok = False
            continue
        got = sha(p)
        d = pd.read_csv(p)
        checks = {
            "sha256": got == exp["sha256"],
            "rows": len(d) == exp["rows"],
            "first": str(d["time"].iloc[0]) == exp["first"],
            "last": str(d["time"].iloc[-1]) == exp["last"],
            "cols": list(d.columns) == ["time", "open", "high", "low", "close", "Volume"],
        }
        bad = [k for k, v in checks.items() if not v]
        if bad:
            ok = False
            print(f"CHANGED  {name}  failed: {','.join(bad)}")
            print(f"         rows={len(d)} (exp {exp['rows']})  "
                  f"{d['time'].iloc[0]} -> {d['time'].iloc[-1]}")
            print(f"         sha256={got}")
        else:
            print(f"ok       {name}  {exp['tf']:>2}m  {len(d):>6} bars  "
                  f"{exp['first'][:10]} -> {exp['last'][:10]}")

    # 4. anything new: do NOT assume, inventory it fresh
    if extra:
        print("\n--- NEW files, not yet fingerprinted: full inventory required ---")
        for name in extra:
            p = fetch(f"data/{name}", base) or fetch(name, base)
            if not p:
                print(f"MISSING  {name}")
                continue
            d = pd.read_csv(p)
            d["time"] = pd.to_datetime(d["time"])
            gap = d["time"].diff().dt.total_seconds().div(60).mode()
            print(f"NEW      {name}")
            print(f"         {len(d)} rows | {d['time'].min()} -> {d['time'].max()}")
            print(f"         modal gap {gap.iloc[0] if len(gap) else '?'} min | "
                  f"cols {list(d.columns)} | dups {d['time'].duplicated().sum()} | "
                  f"nans {int(d.isna().sum().sum())}")
            print(f"         sha256={sha(p)}")
        print("\n  -> Run the standard inventory on these before backtesting: nesting vs the\n"
              "     masters, cross-timeframe consistency, session gaps, monthly regime,\n"
              "     outlier session-open gaps. Do not reuse NQ conclusions on a new instrument.")

    print("\n" + ("READY. Data verified unchanged since 13 Sep 2026."
                  if ok else
                  "STOP. Verification failed above. Re-run the full inventory before any\n"
                  "backtest, and treat every stored conclusion about these files as suspect."))
    print("Load with:  import nq_harness as H;  df = H.load(5)")


if __name__ == "__main__":
    main()
