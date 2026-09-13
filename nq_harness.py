"""
NQ REVERSAL PROJECT — DATA LOADER + §4 BACKTEST HARNESS
Rebuilt 13 Sep 2026 against the re-exported CSV set (all files end 12 Sep 2026).

Implements PROJECT_MASTER_HANDOFF.md §4 exactly:
  - entry at CLOSE of signal bar (never intrabar)
  - cluster collapse: signals within N bars = ONE trade
  - dead-zone skip
  - target+stop in same bar => LOSS
  - costs in points, round turn
  - MFE tracked over the FULL window, independent of exit

Two geometry modes, never mixed in one comparison:
  'fixed' : SL = signal-bar extreme +/- 2 pts, TP = 20 pts beyond that extreme,
            CLOSE-based stop, 24-bar cap. RR varies per trade.
  'atr'   : SL = 0.8*ATR14, TP = 1.0*ATR14 (RR 1.25, breakeven 44.4%),
            WICK (hard) stop, 60-bar cap. RR constant. Use for all cross-script tables.
"""
import os
import numpy as np
import pandas as pd

UPLOADS = "/mnt/user-data/uploads"

# Longest file per timeframe — verified to strictly contain all shorter ones.
# Kept only as a fallback for sessions where files were uploaded instead of fetched.
MASTERS = {
    3:  "CME_MINI_NQ1___3__5_.csv",
    5:  "CME_MINI_NQ1___5__5_.csv",
    6:  "CME_MINI_NQ1___6__4_.csv",
    15: "CME_MINI_NQ1___15__2_.csv",
}
DATA_DIR = "/home/claude/nq/data"   # where bootstrap.py lands verified files

COST_MICRO = 1.1     # pts round turn, MNQ ($2/pt)
COST_EMINI = 0.725   # pts round turn, NQ ($20/pt)

# Session-open gap to quarantine: +513.25 pts, 15 Jun 2026 03:30 IST.
# 10x the 90th-pct gap. Either a real news gap or a continuous-contract splice.
SUSPECT_GAP_SESSIONS = ["2026-06-15"]


# ---------------------------------------------------------------- loading
def resolve(tf=5, instrument="NQ"):
    """Prefer bootstrap's verified download; fall back to a manual upload."""
    p = os.path.join(DATA_DIR, instrument.upper(), f"{tf}m.csv")
    if os.path.exists(p):
        return p
    if instrument.upper() == "NQ" and tf in MASTERS:
        q = os.path.join(UPLOADS, MASTERS[tf])
        if os.path.exists(q):
            return q
    raise FileNotFoundError(
        f"No {instrument.upper()} {tf}m data. Run bootstrap.py first, or upload the CSV.")


def load(tf=5, instrument="NQ", path=None, drop_last=True, tz="Asia/Kolkata"):
    """Load a timeframe for an instrument. Returns a tz-aware IST frame.

    NOTE: session buckets, dead-zone hours and the suspect-gap quarantine below
    were measured on NQ. They are NOT valid for another instrument until
    re-measured there — check before trusting any session-based result on ES,
    GC, CL or SI.
    """
    f = path or resolve(tf, instrument)
    df = pd.read_csv(f)
    df["time"] = pd.to_datetime(df["time"]).dt.tz_convert(tz)
    df = df.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    if drop_last:                      # last bar may be live/forming
        df = df.iloc[:-1].reset_index(drop=True)
    df["tf"] = tf
    df["instrument"] = instrument.upper()
    return add_features(df, tf, instrument)


def add_features(df, tf=5, instrument="NQ"):
    d = df.copy()
    t = d["time"]
    # CME session = 03:30 IST -> 02:30 IST next day; label by session start date
    d["session"] = (t - pd.Timedelta(hours=3, minutes=30)).dt.normalize()
    d["hf"] = t.dt.hour + t.dt.minute / 60.0
    d["bucket"] = np.select(
        [(d.hf >= 1.5) & (d.hf < 6.0), (d.hf >= 6.0) & (d.hf < 12.5),
         (d.hf >= 12.5) & (d.hf < 18.5)],
        ["deadzone", "asia", "london"], default="ny")
    d["dead"] = d["bucket"] == "deadzone"
    # refined from the 13 Sep hourly profile: 01:00-02:00 IST is the 2nd busiest
    # hour of the day (US cash close). True illiquidity is 02:00-05:00 IST.
    d["dead_refined"] = (d.hf >= 2.0) & (d.hf < 5.0)
    d["range"] = d["high"] - d["low"]
    d["atr14"] = pine_atr(d, 14)
    d["suspect"] = (d["session"].dt.strftime("%Y-%m-%d").isin(SUSPECT_GAP_SESSIONS)
                    if instrument.upper() == "NQ" else False)
    return d


# ------------------------------------------------- Pine-faithful primitives
def pine_rma(s, length):
    """ta.rma — Wilder. Seeds with SMA of first `length`."""
    s = pd.Series(s).astype(float)
    out = np.full(len(s), np.nan)
    if len(s) < length:
        return pd.Series(out, index=s.index)
    out[length - 1] = s.iloc[:length].mean()
    a = 1.0 / length
    v = s.to_numpy()
    for i in range(length, len(s)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return pd.Series(out, index=s.index)


def pine_atr(df, length=14):
    """ta.atr = rma(TR). TR uses previous close."""
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return pine_rma(tr, length)


def pine_ema(s, length):
    """ta.ema — seeds with SMA of first `length`, NOT x[0]."""
    s = pd.Series(s).astype(float)
    out = np.full(len(s), np.nan)
    if len(s) < length:
        return pd.Series(out, index=s.index)
    out[length - 1] = s.iloc[:length].mean()
    a = 2.0 / (length + 1)
    v = s.to_numpy()
    for i in range(length, len(s)):
        out[i] = a * v[i] + (1 - a) * out[i - 1]
    return pd.Series(out, index=s.index)


def pine_stdev(s, length):
    """ta.stdev is POPULATION (ddof=0)."""
    return pd.Series(s).rolling(length).std(ddof=0)


def pine_rsi(s, length=14):
    d = pd.Series(s).astype(float).diff()
    up = pine_rma(d.clip(lower=0), length)
    dn = pine_rma((-d).clip(lower=0), length)
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def pine_pivothigh(h, left, right):
    """ta.pivothigh — value appears at the CONFIRMATION bar (right bars later)."""
    h = pd.Series(h).astype(float)
    out = pd.Series(np.nan, index=h.index)
    v = h.to_numpy()
    for i in range(left, len(h) - right):
        c = v[i]
        if c >= v[i - left:i].max() and c > v[i + 1:i + right + 1].max():
            out.iloc[i + right] = c
    return out


def pine_pivotlow(l, left, right):
    l = pd.Series(l).astype(float)
    out = pd.Series(np.nan, index=l.index)
    v = l.to_numpy()
    for i in range(left, len(l) - right):
        c = v[i]
        if c <= v[i - left:i].min() and c < v[i + 1:i + right + 1].min():
            out.iloc[i + right] = c
    return out


# ------------------------------------------------------------ trade builder
def collapse_clusters(idx, side, max_gap=2):
    """Signals within max_gap bars on the same side => keep the first only."""
    keep, last = [], {}
    for i, s in zip(idx, side):
        if s in last and i - last[s] <= max_gap:
            continue
        last[s] = i
        keep.append((i, s))
    return keep


def simulate(df, signals, mode="atr", skip_dead=True, dead_col="dead",
             cluster=2, cost=COST_MICRO, drop_suspect=True,
             atr_stop=0.8, atr_tgt=1.0, cap_atr=60,
             fixed_pad=2.0, fixed_tgt=20.0, cap_fixed=24,
             mfe_window=None):
    """
    signals: list of (bar_index, 'long'|'short') OR a pd.Series of
             +1/-1/0 aligned to df's index.
    Returns a per-trade DataFrame.
    """
    if isinstance(signals, pd.Series):
        s = signals.fillna(0)
        idx = list(np.where(s.to_numpy() != 0)[0])
        side = ["long" if s.iloc[i] > 0 else "short" for i in idx]
    else:
        idx = [i for i, _ in signals]
        side = [s for _, s in signals]

    pairs = collapse_clusters(idx, side, cluster) if cluster else list(zip(idx, side))

    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    atr = df["atr14"].to_numpy()
    dead = df[dead_col].to_numpy() if skip_dead else np.zeros(len(df), bool)
    susp = df["suspect"].to_numpy() if drop_suspect else np.zeros(len(df), bool)
    n = len(df)
    cap = cap_atr if mode == "atr" else cap_fixed
    mfe_win = mfe_window or cap

    out = []
    for i, sd in pairs:
        if i + 1 >= n or dead[i] or susp[i] or not np.isfinite(atr[i]):
            continue
        entry = c[i]
        if mode == "atr":
            sdist, tdist = atr_stop * atr[i], atr_tgt * atr[i]
            hard = True
        else:
            # SL = signal-bar extreme +/- pad (close-based stop).
            # TP = fixed_tgt points from ENTRY. This reading reproduces the
            # handoff's reported RR band of 0.53-0.87 (gives 0.68 on a
            # reference RSI engine); reading it as "20 pts beyond the extreme"
            # gives RR 0.43, outside the band. See DATA_CONTEXT note C4.
            ext = h[i] if sd == "short" else l[i]
            sdist = abs(entry - (ext + fixed_pad if sd == "short" else ext - fixed_pad))
            tdist = fixed_tgt
            hard = False
        if sdist <= 0 or tdist <= 0:
            continue
        sl = entry + sdist if sd == "short" else entry - sdist
        tp = entry - tdist if sd == "short" else entry + tdist

        res, bars_held, exitp = "cap", cap, None
        for k in range(i + 1, min(i + cap + 1, n)):
            if sd == "long":
                hit_t = h[k] >= tp
                hit_s = (l[k] <= sl) if hard else (c[k] <= sl)
            else:
                hit_t = l[k] <= tp
                hit_s = (h[k] >= sl) if hard else (c[k] >= sl)
            if hit_t and hit_s:                 # rule 4: unresolvable => LOSS
                res, bars_held, exitp = "loss", k - i, sl
                break
            if hit_s:
                res, bars_held, exitp = "loss", k - i, sl
                break
            if hit_t:
                res, bars_held, exitp = "win", k - i, tp
                break
        if exitp is None:
            exitp = c[min(i + cap, n - 1)]
            bars_held = min(i + cap, n - 1) - i

        # MFE over the FULL window, independent of exit (lesson #3)
        j = min(i + mfe_win + 1, n)
        mfe = (h[i + 1:j].max() - entry) if sd == "long" else (entry - l[i + 1:j].min())
        mfe = float(mfe) if j > i + 1 else 0.0

        gross = (exitp - entry) if sd == "long" else (entry - exitp)
        out.append(dict(
            bar=i, time=df["time"].iloc[i], side=sd, bucket=df["bucket"].iloc[i],
            session=df["session"].iloc[i], entry=entry, sl=sl, tp=tp,
            stop_pts=sdist, tgt_pts=tdist, rr=tdist / sdist,
            result=res, bars_held=bars_held, exit=exitp,
            pts_gross=gross, pts_net=gross - cost, mfe=mfe,
            legendary=mfe >= 50,
            leg_tier=("150+" if mfe >= 150 else "100-150" if mfe >= 100
                      else "50-100" if mfe >= 50 else "-"),
            r_mult=(gross - cost) / sdist))
    return pd.DataFrame(out)


# ------------------------------------------------------------------ metrics
def metrics(tr, label=""):
    if len(tr) == 0:
        return {"label": label, "n": 0}
    w = (tr.result == "win").sum()
    lo = (tr.result == "loss").sum()
    dec = w + lo
    wr = 100 * w / dec if dec else np.nan
    rr = tr.rr.median()
    be = 100 / (1 + rr)
    eq = tr.r_mult.cumsum()
    dd = (eq - eq.cummax()).min()
    st, mx = 0, 0
    for r in tr.result:
        st = st + 1 if r == "loss" else 0
        mx = max(mx, st)
    lo95, hi95 = _wilson(w, dec)
    return {
        "label": label, "n": len(tr), "decided": dec, "W": int(w), "L": int(lo),
        "win_%": round(wr, 1), "RR": round(rr, 3), "breakeven_%": round(be, 1),
        "MARGIN": round(wr - be, 1), "ci95": f"{lo95:.0f}-{hi95:.0f}%",
        "R_per_trade": round(tr.r_mult.mean(), 3), "net_pts": round(tr.pts_net.sum(), 1),
        "maxDD_R": round(dd, 2), "loss_streak": mx,
        "legendary": int(tr.legendary.sum()),
        "leg_%": round(100 * tr.legendary.mean(), 1),
        "med_bars_held": int(tr.bars_held.median()),
    }


def _wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z**2 / n
    c = (p + z**2 / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return (100 * (c - h), 100 * (c + h))


# -------------------------------------------------------- validation battery
def rr_sweep(df, signals, rrs=(0.75, 1.0, 1.25, 1.5, 2.0), **kw):
    rows = []
    for rr in rrs:
        t = simulate(df, signals, mode="atr", atr_stop=0.8, atr_tgt=0.8 * rr, **kw)
        rows.append(metrics(t, f"RR {rr:.2f}"))
    return pd.DataFrame(rows)


def period_split(df, signals, by="M", **kw):
    tr = simulate(df, signals, **kw)
    if len(tr) == 0:
        return pd.DataFrame()
    rows = [metrics(tr, "ALL")]
    for k, g in tr.groupby(pd.PeriodIndex(tr.time.dt.tz_localize(None), freq=by)):
        rows.append(metrics(g, str(k)))
    return pd.DataFrame(rows)


def cost_sensitivity(df, signals, costs=(0.0, 0.725, 1.1, 2.0), **kw):
    rows = []
    for cst in costs:
        t = simulate(df, signals, cost=cst, **kw)
        rows.append(metrics(t, f"cost {cst} pt"))
    return pd.DataFrame(rows)


def holdout(df, signals, split="2026-08-01", **kw):
    tr = simulate(df, signals, **kw)
    if len(tr) == 0:
        return pd.DataFrame()
    cut = pd.Timestamp(split, tz=df["time"].dt.tz)
    return pd.DataFrame([metrics(tr[tr.time < cut], f"design <{split}"),
                         metrics(tr[tr.time >= cut], f"holdout >={split}")])
