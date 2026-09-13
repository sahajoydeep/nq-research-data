#!/usr/bin/env python3
"""
NQ RESEARCH BOOTSTRAP  (v2 -- manifest-driven, multi-instrument)

Run once at the start of any session. Reads manifest.json from the repo, fetches
every listed data file plus the harness, verifies fingerprints, and lands
everything on disk under clean local names. No CSV ever needs re-uploading.

    python3 bootstrap.py [raw_base_url] [--only NQ,ES]

Adding an instrument requires NO edit to this file -- only a manifest entry.
Files without a stored fingerprint get inventoried fresh, and a paste-ready
manifest block is printed for you.
"""
import hashlib
import json
import os
import subprocess
import sys
import urllib.parse

BASE = "https://raw.githubusercontent.com/sahajoydeep/nq-research-data/main"
DEST = "/home/claude/nq"
DATA = os.path.join(DEST, "data")
CODE = ["nq_harness.py"]

REQUIRED_COLS = ["time", "open", "high", "low", "close", "Volume"]


def fetch(rel, base, out):
    """GET base/rel -> out. Percent-encodes the path, so spaces, '!', ',' and
    parentheses in TradingView filenames work untouched."""
    url = f"{base}/{urllib.parse.quote(rel)}"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    r = subprocess.run(["curl", "-sfL", "-o", out, url], capture_output=True)
    return out if r.returncode == 0 and os.path.getsize(out) > 0 else None


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--only"):
            only = {x.strip().upper() for x in a.split("=", 1)[-1].split(",")}
    base = (args[0] if args else BASE).rstrip("/")
    os.makedirs(DEST, exist_ok=True)
    import pandas as pd

    for c in CODE:
        print(f"{'ok  ' if fetch(c, base, os.path.join(DEST, c)) else 'MISS'} {c}")

    mp = fetch("manifest.json", base, os.path.join(DEST, "manifest.json"))
    if not mp:
        sys.exit("\nSTOP. manifest.json not reachable at " + base)
    man = json.load(open(mp))
    insts = man.get("instruments", {})
    print(f"ok   manifest.json  ({len(insts)} instrument(s): {', '.join(insts)})")

    ok, newblocks = True, []
    for inst, meta in insts.items():
        if only and inst.upper() not in only:
            continue
        print(f"\n--- {inst}  {meta.get('name', '')} ---")
        for tf, spec in sorted(meta.get("timeframes", {}).items(), key=lambda x: int(x[0])):
            local = os.path.join(DATA, inst.upper(), f"{tf}m.csv")
            if not fetch(spec["path"], base, local):
                print(f"  MISSING  {tf:>3}m  {spec['path']}")
                ok = False
                continue

            d = pd.read_csv(local)
            got, rows = sha(local), len(d)
            first, last = str(d["time"].iloc[0]), str(d["time"].iloc[-1])

            if "sha256" not in spec:                      # unknown -> inventory it
                d["t"] = pd.to_datetime(d["time"])
                gap = d["t"].diff().dt.total_seconds().div(60).mode()
                print(f"  NEW      {tf:>3}m  {rows:>6} bars  {first[:10]} -> {last[:10]}")
                print(f"           modal gap {gap.iloc[0] if len(gap) else '?'} min | "
                      f"dups {int(d['t'].duplicated().sum())} | "
                      f"nans {int(d[REQUIRED_COLS].isna().sum().sum())} | "
                      f"cols {'ok' if list(d.columns)[:6] == REQUIRED_COLS else list(d.columns)}")
                newblocks.append((inst, tf, spec["path"], got, rows, first, last))
                continue

            bad = []
            if got != spec["sha256"]:
                bad.append("sha256")
            if rows != spec.get("rows", rows):
                bad.append("rows")
            if first != spec.get("first", first):
                bad.append("first")
            if last != spec.get("last", last):
                bad.append("last")
            if list(d.columns)[:6] != REQUIRED_COLS:
                bad.append("cols")
            if bad:
                ok = False
                print(f"  CHANGED  {tf:>3}m  failed: {','.join(bad)}")
                print(f"           now {rows} bars {first} -> {last}")
                print(f"           sha256={got}")
            else:
                print(f"  ok       {tf:>3}m  {rows:>6} bars  {first[:10]} -> {last[:10]}")

    if newblocks:
        print("\n--- paste these into manifest.json to fingerprint the new files ---")
        for inst, tf, path, h, rows, first, last in newblocks:
            print(f'        "{tf}": {{"path": "{path}",\n'
                  f'               "sha256": "{h}",\n'
                  f'               "rows": {rows}, "first": "{first}", "last": "{last}"}},')
        print("\n  Then re-measure from scratch: session structure, dead zone, monthly regime,\n"
              "  outlier session-open gaps. Nothing established on NQ transfers to another\n"
              "  instrument until it has been measured there.")

    print("\n" + ("READY -- all fingerprinted files verified unchanged."
                  if ok else
                  "STOP -- verification failed above. Re-run the inventory before any backtest\n"
                  "and treat stored conclusions about the affected files as suspect."))
    print(f"Data at {DATA}/<INSTRUMENT>/<tf>m.csv")
    print("Load with:  import nq_harness as H;  df = H.load(5)            # NQ default")
    print("            df = H.load(5, instrument='ES')")


if __name__ == "__main__":
    main()
