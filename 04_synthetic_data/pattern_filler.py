"""Fill a stage pattern with real sensor data, block by block.

For every block of a pattern (pattern_generator.py) real episodes of the same
stage are taken from library/episodes.csv and all 175 sensors are copied
minute by minute from 02_data/preprocessed/ (1-min means):

1. Pick: only episodes that were followed by the same stage as in the pattern
   (e.g. a Start-up before Hot standby must be a full heat-up), when there are
   any; these are scored on how well their temperature meets the end of the
   previous block (stack median, TIR_4_6_*), how well their length fits the
   block, whether the stage before them matches too and how close their gas /
   air supply phases (flow controllers, column phase) are to the block's
   planned phases (pattern column phases, from pattern_generator; an episode
   with forming gas but no cathode air costs AIR_MISS unless planned, rule G10); one of the
   best few (TOP_K) is drawn at random. Shut-down pieces skip the neighbour test.
2. Fit the length, by stage:
   - Hot standby, Idle: a random window of one episode; an episode that is
     too short is played forward-backward-forward (the stack is steady there).
     Natural-gas minutes at the end of a Hot standby (pre-load) are only
     copied when the plan has them, and then stay at the end of the block;
   - Shut-down: a chain of real cool-downs. Each piece is entered at the minute
     where it passes the current stack temperature (a cooling curve can be
     joined part-way), so the cooling speed stays real; when a piece ends the
     next one starts where it left off. A block with a sub_stage (Cooling /
     At ambient, from pattern_generator) only uses real minutes of that
     sub-stage; an older pattern without one uses whole Shut-downs. A Cooling
     block followed by At ambient prefers pieces that end near the stack
     temperature real At ambient stretches start at (it has to get there);
   - Start-up, Thermal adjustment, Part load: the whole episode is stretched /
     squeezed in time to the block length, within WARP_RANGE when an episode allows.
   A Start-up that starts more than ENTRY_K colder than the stack is entered
   at the minute where it passes the stack temperature.
3. Join: temperatures and pressures (TIR*, PIR*) of each piece get an offset
   that makes its first minute equal to the last minute before it and that
   fades linearly to zero over the piece, but no faster than over FADE_MIN
   (a short piece is shifted almost as a whole, so its real rates stay; the
   rest is carried into the next piece). Flows, set-points, on/off and
   electrical values are copied unchanged.
4. Check: a block whose episode had to be stretched / squeezed outside
   WARP_RANGE is flagged "outside real range" in the blocks table (the pattern
   asked for a length no real episode has from that temperature).

Usage:
    python "04_synthetic_data/pattern_filler.py" --pattern "04_synthetic_data/datasets/200h_af32pct_4hua_4hun_5hs_3fs_3pl_7afc_7sd_seed7/pattern_7.csv" --plot
    python "04_synthetic_data/pattern_filler.py" --hours 200 \
        --count "Shut-down=3, Start-up=3, Hot standby=5, Part load=3" --seed 7 --plot

Sensors: the 175 preprocessed ones plus RAW_EXTRA from the 1 s raw files
(02_data/parquet), i.e. the present FIRC 1,1,3 tag ct_FIRC_113_PV_ProcessValue
(renamed in the PLC, real values from 2026-03-17; blank before).

Writes datasets/<day_name>/synthetic_<name>.parquet (folder named by day_name(): hours, availability, stage counts, seed;
the plan's seed_<name>/ folder is renamed to it) (1-min rows: block, stage, sub_stage,
plant_stage, operation, phase, source_episode, source_time, T_stack_C and all sensors),
Planning uses the old 7 stages on purpose (2026-11-05 decision); plant_stage is the
decided 8-stage label, taken from the real minute each row was copied from.
<same folder>/synthetic_<name>_blocks.csv (which real episodes filled which block,
planned vs. copied supply phases and the share of minutes where they agree)
and, with --plot, a PNG of the main signals.
"""
import argparse
import functools
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import pattern_generator as pg  # noqa: E402
import operating_states as ops  # noqa: E402  (on sys.path via pattern_generator)
import plant_stages as ps  # noqa: E402

PRE = ROOT / "02_data" / "preprocessed"
RAW = ROOT / "02_data" / "parquet"   # 1 s raw logger files
RAW_EXTRA = ["ct_FIRC_113_PV_ProcessValue"]   # not in the preprocessed set (tag renamed 2026-03-17)
LIB = HERE / "library"
CACHE = LIB / "sensors_1min.parquet"   # all preprocessed sensors on the 1-min grid + labels

AVAILABLE = {"Part load", "Hot standby", "Fuel switch"}   # as 03_data_analysis/scripts/availability.py
CODES = [("Heat-up air", "hua"), ("Heat-up N₂+H₂", "hun"), ("Hot standby", "hs"), ("Fuel switch", "fs"),
         ("Part load", "pl"), ("Air-flow cooling", "afc"), ("Shutdown", "sd"), ("Trip: purge", "trip")]


def day_name(syn, seed):
    """Folder name of a filled day: hours, availability, episodes per plant stage, seed,
    e.g. 200h_af32pct_4hua_4hun_5hs_3fs_3pl_7afc_7sd_seed7 ('No data' minutes left out, as availability.py)."""
    st = syn["plant_stage"][syn["plant_stage"] != "No data"]
    n = st[st.ne(st.shift())].value_counts()
    runs = "_".join(f"{n[k]}{c}" for k, c in CODES if n.get(k, 0))
    return f"{round(len(syn) / 60)}h_af{round(100 * st.isin(AVAILABLE).mean())}pct_{runs}_seed{seed}"


def day_folder(syn, seed, plan_dir=None):
    """datasets/<day_name>/; the plan's folder (default datasets/seed_<seed>/) is renamed to it, so plan and data stay together."""
    out = pg.OUT / day_name(syn, seed)
    plan_dir = Path(plan_dir) if plan_dir else pg.day_dir(seed)
    if plan_dir.resolve() != out.resolve() and plan_dir.parent.resolve() == pg.OUT.resolve() and plan_dir.exists() and not out.exists():
        plan_dir.rename(out)
    out.mkdir(parents=True, exist_ok=True)
    return out


HOLD = {"Hot standby", "Idle"}
CHAIN = {"Shut-down"}
BLEND_PREFIX = ("TIR", "PIR")          # temperatures and pressures: joined smoothly
TOP_K = 3                              # draw among this many best-matching episodes
T_SCALE_K = 15                         # 15 K temperature miss weighs like a factor e in length
WARP_RANGE = (0.5, 2.0)                # time stretch kept to this when a real episode allows it
FADE_MIN = 240                         # a join offset fades over the piece, but never faster than this
ENTRY_K = 30                           # a Start-up starting this much colder is entered part-way
TAIL_MIN = 15                          # last minutes of a cool-down piece left out (next stage already starting)
PREV_MISS = 1.0                        # score cost when the real stage before differs from the pattern
MIN_PIECE_MIN = 30                     # a cool-down piece entered with less than this left is skipped
DROPOUT_K = 30                         # stage_signals.DROPOUT_K: logger-dropout minute
TC_BROKEN = ["TIR_4_6_25"]             # reads ambient in every file (stage_signals.TC_BROKEN)
LABELS = ["stage", "sub_stage", "operation", "phase"]
T = "T_stack_C"                        # stack median of the working TIR_4_6_* thermocouples
PHASE_W = 2.0                          # score cost of a fully different supply-phase mix (≈ 30 K miss)
AIR_MISS = 2.0                         # score cost of copying forming gas without cathode air (rule G10)
                                       # into a block whose plan has none (≈ 30 K miss)


def real_minutes(rebuild=False):
    """All preprocessed sensors as 1-min means, with the library labels and T_stack_C (cached).

    Logger-dropout minutes (stack median > 30 K off its 5-min median, see
    03_data_analysis/scripts/stage_signals.py) are blanked and filled by time interpolation.
    """
    if not rebuild and not ops.stale(CACHE, PRE, RAW, LIB / "traces_1min.parquet"):
        return pd.read_parquet(CACHE)
    x = pd.concat(pd.read_parquet(f).resample("1min").mean()
                  for f in sorted(PRE.glob("*.parquet")))
    x = x.join(raw_extra())
    tr = pd.read_parquet(LIB / "traces_1min.parquet")
    d = x.join(tr[LABELS + ["episode_id"]], how="inner")
    tc = [c for c in x.columns if c.startswith("TIR_4_6_") and c not in TC_BROKEN]
    d[T] = d[tc].where((d[tc] > 0) & (d[tc] < 1000)).median(axis=1)
    g = d[T].asfreq("1min")
    drop = ((g - g.rolling(5, center=True, min_periods=3).median()).abs() > DROPOUT_K)
    drop = drop.reindex(d.index, fill_value=False)
    num = list(x.columns) + [T]
    d.loc[drop, num] = np.nan
    d[num] = d[num].interpolate("time", limit=10, limit_area="inside")
    d.to_parquet(CACHE)
    return d


def raw_extra():
    """RAW_EXTRA columns as 1-min means from the raw files (negative fill values blanked)."""
    import pyarrow.parquet as pq
    parts = []
    for f in sorted(RAW.glob("*.parquet")):
        cols = [c for c in RAW_EXTRA if c in pq.read_schema(f).names]
        if cols:
            r = pd.read_parquet(f, columns=["Date Time"] + cols).set_index("Date Time")
            parts.append(r.where(r >= 0).resample("1min").mean())
    out = pd.concat(parts) if parts else pd.DataFrame()
    return out.reindex(columns=RAW_EXTRA)


def phase_mix(phase):
    """Share of minutes per supply phase (blank minutes left out)."""
    v = phase[phase != ""].value_counts(normalize=True)
    return v


def mix_cost(a, b):
    """PHASE_W x half the L1 distance of two phase mixes (0 = same, PHASE_W = no overlap)."""
    if a is None or b is None or not len(a) or not len(b):
        return 0.0
    return PHASE_W * 0.5 * a.sub(b, fill_value=0).abs().sum()


def plan_mix(runs):
    if not runs:
        return None
    m = pd.Series(dict(pd.DataFrame(runs).groupby(0)[1].sum()), dtype=float)
    return m / m.sum()


def ng_tail_len(s):
    """Number of natural-gas minutes at the end of a frame."""
    ng = (s["phase"] == pg.PH_NG).to_numpy()
    return len(ng) - (np.flatnonzero(~ng)[-1] + 1) if (~ng).any() else len(ng)


class Library:
    """Real episodes and their 1-min sensor frames (built once per episode)."""

    def __init__(self, real=None):
        self.real = real_minutes() if real is None else real
        self.real = self.real.assign(phase=pg.with_air(self.real))   # forming gas split by cathode air
        self.eps = pd.read_csv(LIB / "episodes.csv", parse_dates=["usable_from", "usable_to"])
        run = self.eps.groupby("run")["stage"]
        self.eps["prev_stage"], self.eps["next_stage"] = run.shift(1), run.shift(-1)
        self.eps = self.eps[self.eps["usable_h"] > 0].set_index("episode_id", drop=False)
        self._frames = {}

    def of(self, stage, nxt=None):
        """Episodes of a stage; only those followed by `nxt` in the real record, if any."""
        c = self.eps[self.eps["stage"] == stage]
        if c.empty:
            raise ValueError(f"no real episode of '{stage}' to fill it with")
        same = c[c["next_stage"] == nxt]
        return same if nxt is not None and len(same) else c

    def frame(self, eid):
        """Usable span of one episode on a gap-free 1-min grid (gaps ≤ 60 min interpolated)."""
        if eid not in self._frames:
            ep = self.eps.loc[eid]
            s = self.real.loc[ep["usable_from"]:ep["usable_to"]]
            s = s[s["episode_id"] == eid]
            s = s.reindex(pd.date_range(s.index[0], s.index[-1], freq="1min"))
            num = s.select_dtypes("number").columns
            s[num] = s[num].interpolate("time", limit_area="inside")
            s[LABELS + ["episode_id"]] = s[LABELS + ["episode_id"]].ffill()
            self._frames[eid] = s.copy()
        return self._frames[eid]

    def dry(self, ids):
        """Episodes with forming gas but no cathode air (pg.PH_FORMING_DRY minutes), as 0 / 1."""
        return pd.Series({e: float((self.frame(e)["phase"] == pg.PH_FORMING_DRY).any()) for e in ids})

    def mixes(self, ids, sub_stage=""):
        """Supply-phase mix per episode (only one Shut-down sub-stage's minutes when given)."""
        return pd.Series({e: phase_mix(sub_frame(self, e, sub_stage)["phase"]) for e in ids}, dtype=object)


def best(c, score, rng):
    top = c.assign(score=score).nsmallest(TOP_K, "score")
    return top.iloc[rng.randrange(len(top))]


def take(s, i0, n):
    """n rows of s from row i0, bouncing forward / backward when s runs out."""
    period = 2 * (len(s) - 1) or 1
    k = (i0 + np.arange(n)) % period
    idx = np.where(k < len(s), k, period - k)
    out = s.iloc[idx].copy()
    out["source_time"] = out.index
    return out.reset_index(drop=True)


def warp(s, n):
    """Stretch / squeeze an episode to n minutes (numbers linear, labels nearest)."""
    pos = np.linspace(0, len(s) - 1, n)
    num = s.select_dtypes("number").columns
    near = np.rint(pos).astype(int)
    out = {c: np.interp(pos, np.arange(len(s)), s[c].to_numpy(float)) if c in num else s[c].to_numpy()[near]
           for c in s.columns}
    return pd.DataFrame({**out, "source_time": s.index[near]})


def neighbour_cost(c, prev):
    return 0 if prev is None else PREV_MISS * (c["prev_stage"] != prev)


def air_cost(lib, c, plan):
    """AIR_MISS for episodes with forming gas without air when the plan has none (rule G10)."""
    if any(p == pg.PH_FORMING_DRY for p, _ in plan):
        return 0.0
    return AIR_MISS * lib.dry(c.index)


def hold(lib, stage, n, T_prev, rng, prev=None, nxt=None, plan=()):
    c = lib.of(stage, nxt)
    score = 0.5 * np.log(n / (c["usable_h"] * 60)).clip(lower=0)   # only a too-short episode costs
    score = score + neighbour_cost(c, prev)
    if T_prev is not None:
        score = score + (c["T_start_C"] - T_prev).abs() / T_SCALE_K
    pm = plan_mix(plan)
    if pm is not None:
        score = score + lib.mixes(c.index).map(lambda m: mix_cost(m, pm))
    score = score + air_cost(lib, c, plan)
    want_ng = plan[-1][1] if plan and plan[-1][0] == pg.PH_NG else 0
    if n > want_ng:                         # natural gas is never looped: needs non-NG minutes to repeat
        ok = [e for e in c.index if (lib.frame(e)["phase"] != pg.PH_NG).sum() >= MIN_PIECE_MIN]
        c, score = (c.loc[ok], score.loc[ok]) if ok else (c, score)
    ep = best(c, score, rng)
    s = lib.frame(ep["episode_id"])
    tail = ng_tail_len(s)
    k = min(want_ng, tail, n)                                       # pre-load minutes copied at the end
    body = s[s["phase"] != pg.PH_NG] if tail < len(s) else s
    m = n - k
    how = "window" if len(body) >= m else "forward-backward"
    out = [take(body, rng.randrange(max(1, len(body) - m + 1)), m)] if m else []
    if k:
        out.append(take(s, len(s) - k, k))
        how += f" + {k} min natural gas (pre-load) at the end"
    return [(pd.concat(out, ignore_index=True), ep["episode_id"], how)]


def path(lib, stage, n, T_prev, rng, prev=None, nxt=None, plan=()):
    c = lib.of(stage, nxt)
    ratio = n / (c["usable_h"] * 60)
    score = np.abs(np.log(ratio)) + neighbour_cost(c, prev)
    if T_prev is not None:
        score = score + (c["T_start_C"] - T_prev).abs() / T_SCALE_K
    pm = plan_mix(plan)
    if pm is not None:
        score = score + lib.mixes(c.index).map(lambda m: mix_cost(m, pm))
    score = score + air_cost(lib, c, plan)
    ep = best(c, score, rng)
    s = lib.frame(ep["episode_id"])
    how = ""
    if stage == "Start-up" and T_prev is not None and s[T].iat[0] < T_prev - ENTRY_K:
        i = int(np.argmax(s[T].to_numpy() >= T_prev))
        s, how = s.iloc[i:], f"entered at {s[T].iat[i]:.0f} C, "
    f = n / len(s)
    how += f"time x{f:.2f}" + ("" if WARP_RANGE[0] <= f <= WARP_RANGE[1] else " (outside real range)")
    return [(warp(s, n), ep["episode_id"], how)]


def sub_frame(lib, eid, sub_stage):
    """Episode frame, only the minutes of one Shut-down sub-stage when given."""
    s = lib.frame(eid)
    return s[s["sub_stage"] == sub_stage] if sub_stage else s


def ambient_start_T(lib):
    """Median stack temperature at the first minute of the real At ambient stretches."""
    if not hasattr(lib, "_ambient_T"):
        c = lib.of(pg.SD)
        t = [f[T].iat[0] for f in (sub_frame(lib, e, pg.SUB[pg.SD_AMB]) for e in c.index) if len(f)]
        lib._ambient_T = float(np.median(t))
    return lib._ambient_T


def chain(lib, stage, n, T_prev, rng, prev=None, nxt=None, sub_stage="", goal_T=None, plan=()):
    """Real cool-down pieces, each entered where it passes the current temperature.

    goal_T: stack temperature the block should end at (pieces whose end is close are preferred).
    plan: planned supply runs; a piece whose phases agree with the plan minutes it covers is preferred.
    """
    want = np.concatenate([[p] * m for p, m in plan]) if plan else None
    c = lib.of(stage)
    if sub_stage:
        c = c[[(lib.frame(e)["sub_stage"] == sub_stage).any() for e in c.index]]
        if c.empty:
            raise ValueError(f"no real '{stage} / {sub_stage}' minutes to fill it with")
    pieces, left, Tc = [], n, T_prev
    while left > 0:
        rows = []
        for eid in c.index:
            s = sub_frame(lib, eid, sub_stage)
            s = s.iloc[:max(1, len(s) - TAIL_MIN)]
            tt = s[T].to_numpy()
            if Tc is None:
                i = 0
            else:
                below = np.flatnonzero(tt <= Tc)
                if not len(below):
                    continue
                i = int(below[0])
            room = len(s) - i
            if room < min(MIN_PIECE_MIN, left):
                continue
            miss = 0 if Tc is None else abs(tt[i] - Tc)
            if goal_T is not None:                         # where this piece leaves the stack
                miss += abs(tt[i + min(room, left) - 1] - goal_T)
            ph_cost = 0.0
            if want is not None:                           # planned phases over the minutes this piece covers
                k0, k = n - left, min(room, left)
                w = want[k0:k0 + k]
                got = s["phase"].to_numpy()[i:i + len(w)]
                ph_cost = PHASE_W * float(np.mean(got != w)) if len(w) else 0.0
                if pg.PH_FORMING_DRY in got and pg.PH_FORMING_DRY not in w:
                    ph_cost += AIR_MISS
            # prefer a close entry and a piece that covers what is left
            rows.append(dict(eid=eid, i=i, room=room,
                             score=miss / T_SCALE_K + 0.5 * max(0.0, np.log(left / room)) + ph_cost))
        if not rows and not pieces and Tc is not None:      # colder than every piece from the start:
            Tc = None                                       # take one from its first minute
            continue
        if not rows:                                       # colder than every piece: hold the last one
            s, eid = sub_frame(lib, pieces[-1][1], sub_stage), pieces[-1][1]
            i = max(0, len(s) - 120)
            pieces.append((take(s, i, left), eid, "hold cold end"))
            break
        top = 1 if goal_T is not None else TOP_K           # few real cool-downs reach ambient: take the best
        r = pd.DataFrame(rows).nsmallest(top, "score").iloc[rng.randrange(min(top, len(rows)))]
        s = sub_frame(lib, r["eid"], sub_stage)
        s = s.iloc[:max(1, len(s) - TAIL_MIN)]
        k = int(min(left, r["room"]))
        piece = take(s, int(r["i"]), k)
        pieces.append((piece, r["eid"], f"from {s[T].iat[int(r['i'])]:.0f} C, {k} min"))
        left -= k
        Tc = float(piece[T].iat[-1])
    return pieces


def blend(piece, prev_last, cols):
    """Offset that meets the minute before and fades to zero over this piece."""
    off = (prev_last[cols] - piece[cols].iloc[0]).fillna(0).to_numpy(float)
    fade = np.clip(1 - np.arange(len(piece)) / max(len(piece) - 1, FADE_MIN), 0, 1)[:, None]
    piece[cols] = piece[cols].to_numpy(float) + fade * off[None, :]
    return piece.copy()                    # one block again (column-wise assignment fragments it)


def sub_of(b):
    """sub_stage of a pattern block ('' when the pattern has none, e.g. an older CSV)."""
    v = b.get("sub_stage", "")
    return "" if pd.isna(v) else str(v)


@functools.cache
def plant_stage_of():
    """Real minute -> decided plant stage (03_data_analysis/plant_stages, run plant_stages.py to refresh)."""
    s = pd.read_parquet(ps.STAGE_FILE, columns=["plant_stage"])["plant_stage"]
    return s[~s.index.duplicated()]


def fill(pattern, seed=None, lib=None):
    """Synthetic 1-min sensor table for a pattern + a table of the real episodes used."""
    rng = random.Random(seed)
    lib = lib or Library()
    blend_cols = [c for c in lib.real.columns if c.startswith(BLEND_PREFIX)] + [T]

    parts, used, prev = [], [], None
    stages = pattern["stage"].tolist()
    for k, (_, b) in enumerate(pattern.iterrows()):
        t0 = pd.Timestamp(b["start"])
        n = int(round((pd.Timestamp(b["end"]) - t0).total_seconds() / 60))
        if n <= 0:
            continue
        T_prev = None if prev is None else float(prev[T])
        nb = (stages[k - 1] if k else None, stages[k + 1] if k + 1 < len(stages) else None)
        plan = pg.parse_phases(b.get("phases", ""))
        if b["stage"] in CHAIN:
            nxt_sub = sub_of(pattern.iloc[k + 1]) if k + 1 < len(pattern) else ""
            goal = (ambient_start_T(lib) if sub_of(b) == pg.SUB[pg.SD_COOL]
                    and nxt_sub == pg.SUB[pg.SD_AMB] else None)
            pieces = chain(lib, b["stage"], n, T_prev, rng, *nb, sub_stage=sub_of(b), goal_T=goal,
                           plan=plan)
        else:
            pieces = (hold if b["stage"] in HOLD else path)(lib, b["stage"], n, T_prev, rng, *nb,
                                                              plan=plan)
        jumps = []
        for piece, _, _ in pieces:
            if prev is not None:
                jumps.append(float(prev[T] - piece[T].iat[0]))
                piece = blend(piece, prev, blend_cols)
            parts.append(piece.assign(block=b["seq"], stage=b["stage"]))
            prev = piece.iloc[-1]
        blk = pd.concat(parts[-len(pieces):])
        real = pg.runs_of(blk["phase"].fillna("").reset_index(drop=True))
        want = np.concatenate([[p] * m for p, m in plan]) if plan else None
        got = blk["phase"].fillna("").to_numpy()
        match = (round(100 * float(np.mean(got[:len(want)] == want[:len(got)])), 1)
                 if want is not None and len(want) else None)
        used.append(dict(seq=b["seq"], step=pg.step_name(b["stage"], sub_of(b)), stage=b["stage"],
                         sub_stage=sub_of(b), minutes=n,
                         source_episodes=" + ".join(e for _, e, _ in pieces),
                         fit=" | ".join(h for _, _, h in pieces),
                         phases_plan=pg.phases_text(plan), phases_copied=pg.phases_text(real),
                         phase_match_pct=match,
                         max_join_offset_K=round(max(jumps, key=abs), 1) if jumps else None,
                         T_start_C=round(float(blk[T].iat[0]), 1),
                         T_end_C=round(float(blk[T].iat[-1]), 1)))
    out = pd.concat(parts, ignore_index=True)
    out.index = pd.date_range(pd.Timestamp(pattern["start"].iat[0]), periods=len(out), freq="1min",
                              name="Date Time")
    out = out.rename(columns={"episode_id": "source_episode"})
    # decided 8 plant stages: the label of the real minute each row was copied from
    out["plant_stage"] = out["source_time"].map(plant_stage_of())
    first = ["block", "stage", "sub_stage", "plant_stage", "operation", "phase", "source_episode", "source_time", T]
    return out[first + [c for c in out.columns if c not in first]], pd.DataFrame(used)


def plot(syn, path_png):
    import matplotlib.pyplot as plt
    sig = [(T, "stack median, °C"), ("TIRC_2_06", "EAPH outlet, °C"),
           ("EIRC_2_01_ActV_In_ThreePhasePower", "EAPH power"),
           ("ct_FIRC_111_PV_ProcessValue", "air 1 FIRC 1,1,1, ln/min"),
           ("ct_FIRC_13_PV_ProcessValue", "N2 FIRC 1,3, ln/min"),
           ("ct_FIRC_113_PV_ProcessValue", "FIRC 1,1,3, ln/min"),
           ("PLC_hostSetp_ctrl_ctEIRC41_rCurrMonitor", "string 1 current, A")]
    sig = [(c, lab) for c, lab in sig if c in syn]
    h = np.asarray((syn.index - syn.index[0]).total_seconds() / 3600)
    fig, ax = plt.subplots(len(sig), 1, figsize=(22, 4 * len(sig) + 1), sharex=True)
    ax = np.atleast_1d(ax)
    edges = np.flatnonzero(np.r_[True, syn["block"].to_numpy()[1:] != syn["block"].to_numpy()[:-1]])
    step = [pg.step_name(a, "" if pd.isna(b) else b) for a, b in zip(syn["stage"], syn["sub_stage"])]
    for a, (c, lab) in zip(ax, sig):
        for i0, i1 in zip(edges, np.r_[edges[1:], len(syn)]):
            a.plot(h[i0:i1 + 1], syn[c].iloc[i0:i1 + 1], lw=1.4,
                   color=f"C{pg.STAGES.index(step[i0])}")
        for i0 in edges:
            a.axvline(h[i0], color="0.85", lw=0.6, zorder=0)
        a.set_ylabel(lab, fontsize=13)
        a.tick_params(labelsize=12)
    ax[0].legend(handles=[plt.Line2D([], [], color=f"C{pg.STAGES.index(s)}", label=s)
                          for s in pg.STAGES if s in set(step)], ncol=6, fontsize=12, loc="upper right")
    ax[-1].set_xlabel("hours from start", fontsize=13)
    fig.suptitle("Synthetic run filled with real episodes (colour = stage, grey line = block start)", fontsize=17)
    fig.tight_layout()
    fig.savefig(path_png, dpi=130)


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--pattern", help="pattern CSV from pattern_generator.py")
    p.add_argument("--hours", type=float)
    p.add_argument("--count")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--seed", type=int)
    p.add_argument("--out")
    p.add_argument("--plot", action="store_true")
    p.add_argument("--rebuild-cache", action="store_true",
                   help="re-read the sensor files (needed once to add RAW_EXTRA, e.g. FIRC 1,1,3)")
    a = p.parse_args()

    seed = a.seed if a.seed is not None else random.randrange(10**6)
    if a.pattern:
        pat = pd.read_csv(a.pattern, parse_dates=["start", "end"], keep_default_na=False)
        name = Path(a.pattern).stem.replace("pattern_", "")
    elif a.hours and a.count:
        try:
            pat = pg.generate(a.hours, pg.parse_pairs(a.count, int), None, a.start, a.end, seed)
        except ValueError as err:
            sys.exit(str(err))
        name = str(seed)
    else:
        sys.exit("give --pattern FILE or --hours and --count")

    syn, used = fill(pat, seed, Library(real_minutes(a.rebuild_cache)))
    out = Path(a.out) if a.out else day_folder(syn, name, Path(a.pattern).parent if a.pattern else None) / f"synthetic_{name}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    syn.to_parquet(out)
    used.to_csv(out.with_name(out.stem + "_blocks.csv"), index=False)
    bad = used[used["fit"].str.contains("outside")]
    if len(bad):
        print(f"note: {len(bad)} block(s) needed a length no real episode has: "
              f"{', '.join(f'{r.seq} {r.step}' for r in bad.itertuples())}")
    print(f"seed {seed}\n{used.drop(columns=['phases_plan', 'phases_copied']).to_string(index=False)}\n"
          f"wrote {out} ({len(syn)} min x {syn.shape[1]} columns)")
    if a.plot:
        plot(syn, out.with_suffix(".png"))
        print(f"wrote {out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
