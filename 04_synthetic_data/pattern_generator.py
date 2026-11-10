"""Random stage pattern for a given total time and a given number of each stage.

The order of the stages is random but every step follows an allowed arrow of
the stage map (flow_check.ALLOWED, operational-modes.md §2). The length of each
stage is random inside the range seen in the real data (library/episodes.csv)
and all lengths together add up exactly to the total time.

Shut-down is used as its two sub-stages (operating_states.sub_stage), each with
its own count and length range:
    Shut-down (Cooling)     load to zero, forced or natural cooling, stack still warm
    Shut-down (At ambient)  plant off, stack within 30 K of ambient
Shut-down is reached only from Hot standby (SD_FROM; the real-data arrows
from Idle, Part load, Rated power and Thermal adjustment are not used here)
and enters Cooling; Cooling may go on to At ambient, and both may go on to
Start-up. A Cooling block that
goes on to At ambient lasts at least as long as the fastest real cool-down from
operating temperature (> 400 °C) to ambient + 30 K (the stack has to get there). \
"Shut-down" alone in
--count / --start / --end means Shut-down (Cooling).

Gas and air supply (flow controllers FIRC 1,1,1/1,1,2 air, 1,3 N2, 1,5 H2,
1,2/1,4 natural gas, 1,1,3): every block also gets a plan of its supply
phases (operating_states.gas_phase: Air only, Forming gas (N2 + H2), N2 purge,
Natural gas, Plant off, plus Forming gas, no air: forming gas while the cathode
air FIRC 1,1,1 + 1,1,2 is off, see with_air) copied from one real stretch of the same \
step, picked
among those followed by the same next step; non-gas phases are stretched to
the block length, natural-gas runs outside Part load (pre-load, fuel
switch-over) keep their real minutes. The flows of each phase are the medians
of that real stretch (phase_table).

Gas conditions (industry permissives, GAS_RULES G1-G10): the stage itself is set by
temperature and load, but each stage may only run on the right supply - no load
without fuel, no fuel without load, hot stack always on forming gas, forming gas
on before hot in a Start-up and off before ambient in a Shut-down, nothing but air
or plant off when cold, and no anode gas without cathode air (real data: N2 purge
and natural gas always with air, forming gas 33,241 of 33,296 min). Real stretches \
that meet them are preferred; a plan that
does not is changed as little as possible (fix_gas). Column gas_check = "ok",
"fixed: ..." or the rule ids still not met. Usage:

    python "04_synthetic_data/pattern_generator.py" --hours 200 \
        --count "Shut-down (Cooling)=3, Shut-down (At ambient)=1, Start-up=3, Hot \
standby=5, Part load=3, Thermal adjustment=2"

Options:
    --start STAGE / --end STAGE   force the first / last stage
    --bounds "Part load=0.2-1.5"  override the min-max length (hours) of a stage
    --seed N                      same seed -> same pattern
    --start-time "2026-01-01 00:00"
    --out FILE.csv                default datasets/seed_<seed>/pattern_<seed>.csv
    --plot                        also save a timeline PNG next to the CSV

Writes one row per stage block: seq, step, stage, sub_stage, start, end, duration_h,
phases, phase_source, gas_check (step = the name used here, e.g. "Shut-down (Cooling)";
stage / sub_stage = the labels of operating_states.py, e.g. "Shut-down" /
"Cooling"; phases = "Air only 186 min > Forming gas (N2 + H2) 312 min") and
pattern_<seed>_phases.csv with one row per supply phase and its flows (ln/min).
GUI with the same generator: streamlit run "04_synthetic_data/pattern_app.py"
"""

import argparse
import functools
import random
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "03_data_analysis" / "scripts"))
from flow_check import ALLOWED  # noqa: E402  stage map arrows, single source of truth
from operating_states import (  # noqa: E402  needs sys.path above
    AIR_FLOW_ON,
    DT_AMBIENT,
    GAS_BLIP_MIN,
    PH_FORMING,
    PH_NG,
    PH_OFF,
    SD_AMBIENT,
    SD_COOLING,
    T_AMB_DEFAULT,
)
from operating_states import (  # noqa: E402  needs sys.path above
    PHASES as OPS_PHASES,
)

LIB = HERE / "library" / "episodes.csv"
TRACES = HERE / "library" / "traces_1min.parquet"
SENSORS = (
    HERE / "library" / "sensors_1min.parquet"
)  # pattern_filler.real_minutes() cache
OUT = HERE / "datasets"


def day_dir(seed):
    """plan folder of a made-up day; pattern_filler.day_folder renames it by \
availability + stage counts once filled"""
    return OUT / f"seed_{seed}"


SD = "Shut-down"
SD_COOL, SD_AMB = "Shut-down (Cooling)", "Shut-down (At ambient)"
SUB = {SD_COOL: SD_COOLING, SD_AMB: SD_AMBIENT}  # step -> sub_stage label
ALIAS = {SD: SD_COOL}  # "Shut-down" alone = its Cooling part
STAGES = [
    "Idle",
    SD_COOL,
    SD_AMB,
    "Start-up",
    "Hot standby",
    "Thermal adjustment",
    "Part load",
    "Rated power",
]
# flow controllers, ln/min (sensor list "FIRC a,b,c" -> logger column)
FLOWS = {
    "Air 1 (FIRC 1,1,1)": "ct_FIRC_111_PV_ProcessValue",
    "Air 2 (FIRC 1,1,2)": "ct_FIRC_112_PV_ProcessValue",
    "FIRC 1,1,3": "ct_FIRC_113_PV_ProcessValue",  # present tag, logged from 2026-03-17
    "N2 (FIRC 1,3)": "ct_FIRC_13_PV_ProcessValue",
    "H2 (FIRC 1,5)": "ct_FIRC_15_PV_ProcessValue",
    "FIRC 1,2 (NG / POx air)": "ct_FIRC_12_PV_ProcessValue",
    "FIRC 1,4 (NG fuel)": "ct_FIRC_14_PV_ProcessValue",
}
AIR_COLS = [FLOWS["Air 1 (FIRC 1,1,1)"], FLOWS["Air 2 (FIRC 1,1,2)"]]
# gas_phase ranks anode gas above air, so its forming gas hides whether the cathode air
# was on. Air is implied everywhere else (N2 purge, natural gas always with air; plant
# off never); the one open case gets its own phase here: 55 of 33,296 real forming-gas
# minutes, 37 of them in Start-up 20260323_0840. Generator and filler use this split
# label; operating_states keeps the five.
PH_FORMING_DRY = "Forming gas, no air"
PHASES = [*OPS_PHASES[:3], PH_FORMING_DRY, *OPS_PHASES[3:]]
PHASE_MIN = 3  # min: a supply run shorter than this joins the run before it
STRETCH_SHARE = (
    0.10  # only runs with at least this share of their real stretch are stretched
)
PHASE_COLOR = {
    PH_OFF: "#bab0ac",
    "Air only": "#9ecae9",
    PH_FORMING: "#b279a2",
    PH_FORMING_DRY: "#e377c2",
    "N2 purge": "#4c78a8",
    PH_NG: "#f58518",
}
MAIN_PHASE = {
    "Idle": PH_OFF,
    SD_AMB: PH_OFF,
}  # filler phase when a real plan is all natural gas
SD_FROM = {"Hot standby"}  # the only stages allowed to go into Shut-down
# Industry gas conditions (permissives): the stage is set by temperature and load, but
# each stage may only run on the right supply. gas_faults() checks a block's plan
# against them.
PH_AIR = "Air only"
HOT_STEPS = {
    "Hot standby",
    "Thermal adjustment",
}  # hot stack, no load: protective gas only
COLD_STEPS = {"Idle", SD_AMB}  # cold or plant off: no fuel, no forming gas
GAS_SHORT = 30  # min: longest natural gas next to a Part load (pre-load / fuel tail)
#      and longest other-supply gap inside a hot stage
PRELOAD_MIN = (
    10  # min: natural gas added before a Part load when the copied plan has none
)
# share of a Cooling block still on forming gas (real 2025-11-13: 2286 of 6360 min)
FORMING_SHARE = 0.35
GAS_RULES = [  # (rule id, plain text) — shown in the app and the module docstring
    ("G1", "Part load runs on natural gas only (no load without fuel)"),
    (
        "G2",
        "the block before a Part load ends on natural gas, at most 30 min (pre-load)",
    ),
    (
        "G3",
        "natural gas outside Part load only right before or after one, at most 30 min "
        "(no fuel without load)",
    ),
    (
        "G4",
        "Hot standby / Thermal adjustment run on forming gas, other supply at most 30 "
        "min (hot stack protected)",
    ),
    (
        "G5",
        "a Start-up from a cold stack (after At ambient / Idle) begins on air or plant "
        "off",
    ),
    (
        "G6",
        "a Start-up into Hot standby ends on forming gas "
        "(protective gas on before hot)",
    ),
    (
        "G7",
        "a Cooling block after Hot standby begins on forming gas (stack still "
        "protected)",
    ),
    (
        "G8",
        "a Cooling block into At ambient ends without forming gas (switched off on the "
        "way down)",
    ),
    ("G9", "At ambient and Idle have no natural gas and no forming gas"),
    ("G10", "forming gas only with cathode air on (anode gas never without air)"),
]


def with_air(d):
    """Phase column of a frame with forming gas split by cathode air: minutes of \
forming gas
    with FIRC 1,1,1 + 1,1,2 at or below AIR_FLOW_ON become PH_FORMING_DRY. Air dips \
shorter
    than GAS_BLIP_MIN stay forming gas (same blip rule as \
operating_states.gas_phase)."""
    ph = d["phase"].astype(object)
    if not set(AIR_COLS) <= set(d.columns):
        return ph
    dry = (ph == PH_FORMING) & (d[AIR_COLS].fillna(0).sum(axis=1) <= AIR_FLOW_ON)
    run = (dry != dry.shift()).cumsum()
    dry &= dry.groupby(run).transform("size") >= GAS_BLIP_MIN
    return ph.where(~dry, PH_FORMING_DRY)


def split_arrows(allowed):
    """Stage-map arrows with Shut-down replaced by its two sub-stages, entered only \
from SD_FROM."""
    out = {(SD_COOL, SD_AMB)}
    for a, b in allowed:
        if b == SD and a not in SD_FROM:
            continue
        src = [SD_COOL, SD_AMB] if a == SD else [a]
        dst = ([SD_COOL, SD_AMB] if a == "Idle" else [SD_COOL]) if b == SD else [b]
        out |= {(x, y) for x in src for y in dst}
    return out


ARROWS = split_arrows(ALLOWED)
NEXT = {s: sorted(b for a, b in ARROWS if a == s) for s in STAGES}


def step_name(stage, sub_stage=""):
    """Generator step for an operating_states stage / sub_stage pair."""
    if stage != SD:
        return stage
    return {v: k for k, v in SUB.items()}.get(sub_stage, SD_COOL)


def labels(step):
    """(stage, sub_stage) labels of a generator step."""
    return (SD, SUB[step]) if step in SUB else (step, "")


def canon(name):
    name = ALIAS.get(name, name)
    if name is not None and name not in STAGES:
        raise ValueError(f"unknown stage '{name}', choose from {STAGES}")
    return name


def parse_pairs(text, conv):
    out = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        name, val = (x.strip() for x in part.split("="))
        try:
            out[canon(name)] = conv(val)
        except ValueError as err:
            sys.exit(str(err))
    return out


def sub_pieces():
    """Real Shut-down stretches split by sub-stage: one row per (episode, sub-stage), \
length in h."""
    t = pd.read_parquet(TRACES, columns=["stage", "sub_stage", "episode_id"])
    t = t[t["stage"] == SD]
    p = (
        t.groupby(["episode_id", "sub_stage"])
        .size()
        .div(60)
        .rename("duration_h")
        .reset_index()
    )
    p["step"] = p["sub_stage"].map({v: k for k, v in SUB.items()})
    return p


def library_bounds():
    """Min-max length (h) per step from the real episodes, complete ones preferred.

    The Shut-down sub-stages use every real stretch of that sub-stage: an episode's
    'complete' flag says nothing about where inside it Cooling turns into At ambient.
    """
    e = pd.read_csv(LIB)
    b = {}
    for s, g in e[e["stage"] != SD].groupby("stage"):
        d = (
            g.loc[g["complete"], "duration_h"]
            if g["complete"].any()
            else g["duration_h"]
        )
        b[s] = (float(d.min()), float(d.max()))
    for s, g in sub_pieces().groupby("step"):
        b[s] = (float(g["duration_h"].min()), float(g["duration_h"].max()))
    return b


def to_ambient_min_h(T_hot=400.0):
    """Fastest real cool-down (h) from above T_hot to ambient + DT_AMBIENT, None \
without one.

    Only Shut-down episodes that start hot count (one cut at a file edge can start
    already cold). Uses the stack median of library/traces_1min.parquet.
    """
    t = pd.read_parquet(TRACES, columns=["stage", "episode_id", "T_stack_C"])
    t = t[t["stage"] == SD]
    hours = []
    for _, g in t.groupby("episode_id"):
        T = g["T_stack_C"].dropna()
        if len(T) and T.iat[0] > T_hot:
            cold = T.index[T <= T_AMB_DEFAULT + DT_AMBIENT]
            if len(cold):
                hours.append((cold[0] - T.index[0]).total_seconds() / 3600)
    return min(hours) if hours else None


def library_counts():
    """Number of real stretches per step (the data the default lengths come from)."""
    e = pd.read_csv(LIB)
    n = e.loc[e["stage"] != SD, "stage"].value_counts().to_dict()
    return {**n, **sub_pieces()["step"].value_counts().to_dict()}


def order(counts, start=None, end=None, rng=random, extra=0, fillers=STAGES):
    """Random stage sequence using each stage exactly counts[s] times along allowed \
arrows.

    Depth-first search that tries the next stages in random order; dead ends
    (last stage, counts left, extras left) are remembered so they are never
    searched twice. Up to `extra` blocks of the `fillers` stages may be added
    on top of the counts to bridge steps the stage map does not allow.
    """
    left = {s: counts.get(s, 0) for s in STAGES}
    seq, dead = [], set()

    def step(prev, spare):
        if not any(left.values()) and (end is None or prev == end):
            return True
        key = prev, tuple(left[s] for s in STAGES), spare
        if key in dead:
            return False
        nxt = NEXT[prev] if prev else [start] if start else STAGES
        counted = [s for s in nxt if left[s] > 0]
        added = [s for s in nxt if left[s] == 0 and s in fillers] if spare else []
        rng.shuffle(counted)
        rng.shuffle(added)
        for s in counted + added:  # counted stages first, extras only when needed
            seq.append(s)
            use = left[s] > 0
            left[s] -= use
            if step(s, spare - (not use)):
                return True
            left[s] += use
            seq.pop()
        dead.add(key)
        return False

    return seq if step(None, extra) else None


def order_closest(
    counts, start=None, end=None, rng=random, fillers=STAGES, max_extra=40
):
    """`order` with the fewest extra blocks needed (0 if the counts follow the map as \
they are)."""
    for extra in range(max_extra + 1):
        seq = order(counts, start, end, rng, extra, fillers)
        if seq is not None:
            return seq
    return None


def durations(seq, hours, bounds, rng, cool_min=None):
    """Random length per block inside its bounds, summing exactly to `hours`.

    Each block gets lo + min(hi - lo, lam * g * (hi - lo)) with a random weight
    g ~ Exp(1); lam is found by bisection so the sum hits the total. A Cooling
    block followed by At ambient is at least `cool_min` hours (within its max).
    """
    lo = np.array([bounds[s][0] for s in seq])
    hi = np.array([bounds[s][1] for s in seq])
    if cool_min is not None:
        for i, (a, b) in enumerate(zip(seq[:-1], seq[1:])):
            if (a, b) == (SD_COOL, SD_AMB):
                lo[i] = min(max(lo[i], cool_min), hi[i])
    if not lo.sum() <= hours <= hi.sum():
        raise ValueError(
            f"{hours:g} h does not fit: these stages need between "
            f"{lo.sum():.1f} and {hi.sum():.1f} h (change the total time, counts or "
            "lengths)"
        )
    g = rng.exponential(1.0, len(seq))
    cap = hi - lo
    a, b = 0.0, 1.0
    while (lo + np.minimum(cap, b * g * cap)).sum() < hours:
        b *= 2
    for _ in range(100):
        m = (a + b) / 2
        a, b = (m, b) if (lo + np.minimum(cap, m * g * cap)).sum() < hours else (a, m)
    d = lo + np.minimum(cap, b * g * cap)
    return d * hours / d.sum()  # remove the last bisection rounding


def runs_of(phase):
    """Supply runs [(phase, minutes)] of a 1-min phase series; blanks and runs < \
PHASE_MIN absorbed."""
    ph = phase.replace("", np.nan).ffill().bfill().fillna(PH_OFF).to_numpy()
    out = []
    for p in ph:
        if out and out[-1][0] == p:
            out[-1][1] += 1
        else:
            out.append([p, 1])
    merged = []
    for p, m in out:
        if merged and (m < PHASE_MIN or merged[-1][0] == p):
            merged[-1][1] += m
        else:
            merged.append([p, m])
    if len(merged) > 1 and merged[0][1] < PHASE_MIN:
        merged[1][1] += merged.pop(0)[1]
    return [(p, int(m)) for p, m in merged]


@functools.lru_cache(maxsize=1)
def phase_profiles():
    """Real supply runs per step: one row per (episode, Shut-down sub-stage) with \
next_step and runs."""
    t = pd.read_parquet(TRACES, columns=["stage", "sub_stage", "phase", "episode_id"])
    if SENSORS.exists():  # cathode air, to split forming gas (with_air)
        t = t.join(pd.read_parquet(SENSORS, columns=AIR_COLS))
        t["phase"] = with_air(t)
    t = t[t["episode_id"].notna()]
    e = pd.read_csv(LIB)
    nxt = dict(zip(e["episode_id"], e.groupby("run")["stage"].shift(-1)))
    has_amb = set(t.loc[t["sub_stage"] == SUB[SD_AMB], "episode_id"])
    rows = []
    for (eid, sub), g in t.groupby(["episode_id", "sub_stage"], sort=False):
        step = step_name(g["stage"].iat[0], sub)
        if step == SD_COOL and eid in has_amb:
            after = SD_AMB
        else:
            n = nxt.get(eid)
            after = None if pd.isna(n) else step_name(n)
        rows.append(
            dict(step=step, episode_id=eid, next_step=after, runs=runs_of(g["phase"]))
        )
    return pd.DataFrame(rows)


def scale_runs(runs, n, step):
    """Fit real supply runs to n minutes. Natural gas outside Part load (pre-load, fuel
    switch-over) and short runs (< STRETCH_SHARE of the real stretch, e.g. a 4-min \
supply
    blip) keep their real minutes (together at most half the block); the other runs \
share
    the rest in proportion."""
    total = sum(m for _, m in runs)
    longest = max(range(len(runs)), key=lambda i: runs[i][1])
    keep = {
        i: m
        for i, (p, m) in enumerate(runs)
        if (p == PH_NG and step != "Part load")
        or (m < STRETCH_SHARE * total and i != longest)
    }
    if sum(keep.values()) > n // 2:
        keep = {i: m * (n // 2) // sum(keep.values()) for i, m in keep.items()}
    free = [i for i in range(len(runs)) if i not in keep]
    if not free:  # a real plan of natural gas only (e.g. 8 min pre-load)
        runs = [(MAIN_PHASE.get(step, PH_FORMING), 1)] + list(runs)
        keep = {i + 1: m for i, m in keep.items()}
        free = [0]
    rest = max(n - sum(keep.values()), 0)
    w = np.array([runs[i][1] for i in free], float)
    m = np.floor(rest * w / w.sum()).astype(int)
    m[np.argmax(w)] += rest - m.sum()
    mins = {**keep, **dict(zip(free, m))}
    out = []
    for i, (p, _) in enumerate(runs):
        if mins[i] <= 0:
            continue
        if out and out[-1][0] == p:
            out[-1][1] += int(mins[i])
        else:
            out.append([p, int(mins[i])])
    return [tuple(r) for r in out]


def phases_text(runs):
    return " > ".join(f"{p} {m} min" for p, m in runs)


def parse_phases(text):
    """'Air only 186 min > Forming gas (N2 + H2) 312 min' -> [(phase, minutes)]."""
    if not isinstance(text, str) or not text.strip():
        return []
    return [
        (m.group(1), int(m.group(2)))
        for m in (
            re.fullmatch(r"\s*(.+?) (\d+) min\s*", part) for part in text.split(" > ")
        )
        if m
    ]


def gas_faults(step, runs, prev=None, nxt=None):
    """Ids of the GAS_RULES a block's supply plan breaks ([] = all met)."""
    if not runs:
        return []
    ph = [p for p, _ in runs]
    bad = []
    if step == "Part load":
        if any(p != PH_NG for p in ph):
            bad.append("G1")
    else:
        if nxt == "Part load" and not (ph[-1] == PH_NG and runs[-1][1] <= GAS_SHORT):
            bad.append("G2")
        edge = {0} if prev == "Part load" else set()
        edge |= {len(runs) - 1} if nxt == "Part load" else set()
        if any(
            p == PH_NG and (i not in edge or m > GAS_SHORT)
            for i, (p, m) in enumerate(runs)
        ):
            bad.append("G3")
    if step in HOT_STEPS:
        core = [(p, m) for p, m in runs if p != PH_NG]
        if (
            not core
            or max(core, key=lambda r: r[1])[0] != PH_FORMING
            or any(p != PH_FORMING and m > GAS_SHORT for p, m in core)
        ):
            bad.append("G4")
    if step == "Start-up":
        if prev in COLD_STEPS and ph[0] not in (PH_AIR, PH_OFF):
            bad.append("G5")
        if nxt == "Hot standby" and ph[-1] != PH_FORMING:
            bad.append("G6")
    if step == SD_COOL:
        first = next((p for p in ph if p != PH_NG), None)
        if prev in HOT_STEPS and first != PH_FORMING:
            bad.append("G7")
        if nxt == SD_AMB and ph[-1] == PH_FORMING:
            bad.append("G8")
    if step in COLD_STEPS and any(p in (PH_NG, PH_FORMING, PH_FORMING_DRY) for p in ph):
        bad.append("G9")
    if PH_FORMING_DRY in ph:
        bad.append("G10")
    return bad


def _merge(runs):
    out = []
    for p, m in runs:
        if m <= 0:
            continue
        if out and out[-1][0] == p:
            out[-1][1] += m
        else:
            out.append([p, m])
    return [tuple(r) for r in out]


def _take(runs, m, at_end):
    """Cut m minutes off the start or end of runs (for a run added there)."""
    runs = [list(r) for r in runs]
    idx = range(len(runs) - 1, -1, -1) if at_end else range(len(runs))
    for i in idx:
        cut = min(m, runs[i][1] - 1 if len(runs) == 1 else runs[i][1])
        runs[i][1] -= cut
        m -= cut
        if m <= 0:
            break
    return [tuple(r) for r in runs]


def fix_gas(step, runs, prev, nxt):
    """Make a plan meet GAS_RULES with the smallest change, keeping the block length.
    Returns (runs, short notes of what was changed)."""
    n = sum(m for _, m in runs)
    notes = []
    for _ in range(3):  # one fix can open another rule; few passes
        bad = gas_faults(step, runs, prev, nxt)
        if not bad:
            break
        if "G1" in bad:
            runs, notes = [(PH_NG, n)], notes + ["all natural gas"]
            continue
        if "G9" in bad:
            runs = _merge(
                [
                    (PH_OFF if p in (PH_NG, PH_FORMING, PH_FORMING_DRY) else p, m)
                    for p, m in runs
                ]
            )
            notes.append("fuel / forming gas -> plant off")
            continue
        if "G10" in bad:
            runs = _merge(
                [(PH_FORMING if p == PH_FORMING_DRY else p, m) for p, m in runs]
            )
            notes.append("air on under forming gas")
            continue
        if "G3" in bad:  # natural gas away from a Part load
            keep = MAIN_PHASE.get(step, PH_AIR if step in COLD_STEPS else PH_FORMING)
            last = len(runs) - 1
            runs = _merge(
                [
                    (
                        keep
                        if p == PH_NG
                        and not (
                            (i == 0 and prev == "Part load")
                            or (i == last and nxt == "Part load")
                        )
                        else p,
                        min(m, GAS_SHORT) if p == PH_NG else m,
                    )
                    for i, (p, m) in enumerate(runs)
                ]
            )
            runs = [
                list(r) for r in runs
            ]  # minutes cut off the fuel go to the longest other run
            j = max(
                (i for i, r in enumerate(runs) if r[0] != PH_NG),
                key=lambda i: runs[i][1],
                default=None,
            )
            if j is None:
                runs.insert(0, [keep, 0])
                j = 0
            runs[j][1] += n - sum(m for _, m in runs)
            runs = _merge(runs)
            notes.append("natural gas trimmed to next to the load, max 30 min")
            continue
        if "G4" in bad:
            runs = _merge([(PH_FORMING if p != PH_NG else p, m) for p, m in runs])
            notes.append("gaps in a hot stage -> forming gas")
            continue
        if "G7" in bad:
            runs = _merge(
                [(PH_FORMING, max(1, int(n * FORMING_SHARE)))]
                + _take(runs, max(1, int(n * FORMING_SHARE)), at_end=False)
            )
            notes.append("forming gas at start of cool-down")
            continue
        if "G8" in bad:
            m = runs[-1][1] - max(1, int(runs[-1][1] * FORMING_SHARE))
            runs = _merge(runs[:-1] + [(PH_FORMING, runs[-1][1] - m), (PH_AIR, m)])
            notes.append("forming gas off before ambient")
            continue
        if "G5" in bad:
            m = max(1, runs[0][1] // 3)
            runs = _merge([(PH_AIR, m)] + _take(runs, m, at_end=False))
            notes.append("cold start begins on air")
            continue
        if "G6" in bad:
            m = max(1, n // 2)
            runs = _merge(_take(runs, m, at_end=True) + [(PH_FORMING, m)])
            notes.append("forming gas on before hot")
            continue
        if "G2" in bad:
            m = min(PRELOAD_MIN, max(1, n // 2))
            if runs[-1][0] == PH_NG:  # pre-load too long: shorten it
                runs = _merge(
                    runs[:-1]
                    + [(MAIN_PHASE.get(step, PH_FORMING), runs[-1][1] - m), (PH_NG, m)]
                )
            else:
                runs = _merge(_take(runs, m, at_end=True) + [(PH_NG, m)])
            notes.append(f"pre-load natural gas {m} min")
    return runs, notes


def plan_phases(steps, minutes, rng):
    """Supply-phase plan per block: (runs, source episode, gas_check); a real stretch of
    the same step followed by the same next step when there is one, preferring stretches
    that already meet GAS_RULES; a plan that does not is fixed with fix_gas.
    gas_check = "ok", "fixed: ..." or the rule ids still broken."""
    prof = phase_profiles()
    out = []
    for i, (s, n) in enumerate(zip(steps, minutes)):
        c = prof[prof["step"] == s]
        if c.empty:
            out.append(([], "", "no real supply data"))
            continue
        before = steps[i - 1] if i else None
        after = steps[i + 1] if i + 1 < len(steps) else None
        fits = [scale_runs(r, int(n), s) for r in c["runs"]]
        ok = np.array([not gas_faults(s, f, before, after) for f in fits])
        same = (
            (c["next_step"] == after).to_numpy()
            if after is not None
            else np.zeros(len(c), bool)
        )
        for pick in (same & ok, ok, same, np.ones(len(c), bool)):
            if pick.any():
                break
        j = rng.choice(np.flatnonzero(pick).tolist())
        runs, notes = fix_gas(s, fits[j], before, after)
        left = gas_faults(s, runs, before, after)
        check = (
            (", ".join(left) + " not met")
            if left
            else ("fixed: " + "; ".join(notes))
            if notes
            else "ok"
        )
        out.append((runs, c["episode_id"].iat[j], check))
    return out


@functools.lru_cache(maxsize=1)
def flow_medians():
    """Median flow (ln/min) per (episode, phase) and per phase over all real minutes."""
    if not SENSORS.exists():
        return pd.DataFrame(), pd.DataFrame()
    import pyarrow.parquet as pq

    have = set(pq.read_schema(SENSORS).names)
    cols = [c for c in FLOWS.values() if c in have]
    d = pd.read_parquet(SENSORS, columns=cols + ["phase", "episode_id"])
    d["phase"] = with_air(d)
    d = d[d["phase"] != ""]
    d[cols] = d[cols].where(d[cols] >= 0)
    name = {v: k for k, v in FLOWS.items()}
    per_ep = d.groupby(["episode_id", "phase"])[cols].median().rename(columns=name)
    per_ph = d.groupby("phase")[cols].median().rename(columns=name).reindex(PHASES)
    return per_ep, per_ph


def flow_levels():
    """Real flows per supply phase: median ln/min and minutes seen (for the app)."""
    per_ph = flow_medians()[1]
    t = pd.read_parquet(SENSORS if SENSORS.exists() else TRACES, columns=["phase"])
    if SENSORS.exists():
        t["phase"] = with_air(pd.read_parquet(SENSORS, columns=["phase", *AIR_COLS]))
    n = t.loc[t["phase"] != "", "phase"].value_counts().rename("minutes")
    return per_ph.join(n).rename_axis("phase").reset_index()


def phase_table(df):
    """One row per planned supply phase: seq, step, phase, start, end, duration_h,
    source_episode and the median flows of that phase in its source episode."""
    per_ep, per_ph = flow_medians()
    rows = []
    for _, b in df.iterrows():
        t = pd.Timestamp(b["start"])
        for p, m in parse_phases(b.get("phases", "")):
            row = dict(
                seq=b["seq"],
                step=b["step"],
                phase=p,
                start=t,
                end=t + pd.Timedelta(minutes=m),
                duration_h=round(m / 60, 3),
                source_episode=b.get("phase_source", ""),
            )
            if len(per_ph):
                key = (row["source_episode"], p)
                f = per_ep.loc[key] if key in per_ep.index else per_ph.loc[p]
                row.update(f.round(1).to_dict())
            rows.append(row)
            t = row["end"]
    return pd.DataFrame(rows)


def plot(df, path):
    import matplotlib.pyplot as plt

    rows = [s for s in STAGES if s in set(df["step"])]
    ph = phase_table(df) if "phases" in df else pd.DataFrame(columns=["phase"])
    fig, (ax, axp) = plt.subplots(
        2,
        1,
        figsize=(22, 0.9 * len(rows) + 4),
        sharex=True,
        gridspec_kw=dict(height_ratios=[len(rows), 1.4]),
    )
    t0 = df["start"].iat[0]
    for _, r in ph.iterrows():
        axp.barh(
            0,
            r["duration_h"],
            left=(r["start"] - t0).total_seconds() / 3600,
            height=0.8,
            color=PHASE_COLOR[r["phase"]],
        )
    axp.set_yticks([0], ["supply"], fontsize=14)
    axp.legend(
        handles=[
            plt.Rectangle((0, 0), 1, 1, color=PHASE_COLOR[p], label=p)
            for p in PHASES
            if p in set(ph["phase"])
        ],
        ncol=6,
        fontsize=13,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.9),
    )
    for _, r in df.iterrows():
        x = (r["start"] - t0).total_seconds() / 3600
        ax.barh(
            rows.index(r["step"]),
            r["duration_h"],
            left=x,
            height=0.6,
            color=f"C{STAGES.index(r['step'])}",
        )
    ax.step(
        [(t - t0).total_seconds() / 3600 for t in df["start"]],
        [rows.index(s) for s in df["step"]],
        where="post",
        color="0.6",
        lw=0.8,
    )
    ax.set_yticks(range(len(rows)), rows, fontsize=14)
    ax.invert_yaxis()
    axp.set_xlabel("hours from start", fontsize=14)
    axp.tick_params(axis="x", labelsize=13)
    ax.set_title(
        f"Synthetic stage pattern, {df['duration_h'].sum():.0f} h, {len(df)} blocks",
        fontsize=17,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)


def generate(
    hours,
    counts,
    bounds=None,
    start=None,
    end=None,
    seed=None,
    start_time="2026-01-01 00:00",
    phases=True,
):
    """One random pattern as a table: seq, step, stage, sub_stage, start, end, \
duration_h
    (+ phases, phase_source: the planned gas / air supply of each block, see \
plan_phases).

    counts / bounds / start / end use the step names (STAGES; "Shut-down" alone
    = Shut-down (Cooling)). When the counts cannot follow the stage map as given
    (e.g. more Start-ups than Shut-downs), the fewest extra blocks needed are
    added; they are listed in df.attrs["added"] as {step: n}. Raises ValueError
    with a plain message when the total time does not fit the stage lengths.
    """
    counts = {canon(s): n for s, n in counts.items() if n > 0}
    if not counts:
        raise ValueError("give at least one stage a count above 0")
    start, end = canon(start), canon(end)
    bounds = {**library_bounds(), **{canon(s): v for s, v in (bounds or {}).items()}}
    missing = [s for s in counts if s not in bounds]
    if missing:
        raise ValueError(f"no real data for {missing}: give its min-max length")
    fillers = [s for s in STAGES if s in bounds and s != "Idle"]
    seq = order_closest(counts, start, end, random.Random(seed), fillers)
    if seq is None:
        raise ValueError(
            "no order of these stage counts follows the stage map, even with "
            "extra blocks added (e.g. each Start-up needs a Shut-down or Idle "
            "before it, each Shut-down and Part load a Hot standby)"
        )
    added = {
        s: seq.count(s) - counts.get(s, 0)
        for s in STAGES
        if seq.count(s) > counts.get(s, 0)
    }
    try:
        d = durations(
            seq, hours, bounds, np.random.default_rng(seed), to_ambient_min_h()
        )
    except ValueError as err:
        if added:
            err = ValueError(
                f"{err}; this includes the added blocks "
                + ", ".join(f"{n} {s}" for s, n in added.items())
            )
        raise err from None

    t0 = pd.Timestamp(start_time)
    begin = t0 + pd.to_timedelta(np.r_[0, np.cumsum(d)[:-1]], unit="h")
    lab = [labels(s) for s in seq]
    df = pd.DataFrame(
        {
            "seq": range(1, len(seq) + 1),
            "step": seq,
            "stage": [a for a, _ in lab],
            "sub_stage": [b for _, b in lab],
            "start": begin.round("1min"),
            "duration_h": d.round(3),
        }
    )
    df["end"] = df["start"].shift(-1).fillna(t0 + pd.Timedelta(hours=hours))
    df = df[["seq", "step", "stage", "sub_stage", "start", "end", "duration_h"]]
    if phases:
        mins = ((df["end"] - df["start"]).dt.total_seconds() // 60).astype(int)
        plan = plan_phases(seq, mins, random.Random(seed))
        df["phases"] = [phases_text(r) for r, _, _ in plan]
        df["phase_source"] = [e for _, e, _ in plan]
        df["gas_check"] = [g for _, _, g in plan]
    df.attrs["added"] = added
    return df


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--hours", type=float, required=True)
    p.add_argument("--count", required=True)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--bounds", default="")
    p.add_argument("--seed", type=int)
    p.add_argument("--start-time", default="2026-01-01 00:00")
    p.add_argument("--out")
    p.add_argument("--plot", action="store_true")
    a = p.parse_args()

    seed = a.seed if a.seed is not None else random.randrange(10**6)
    try:
        df = generate(
            a.hours,
            parse_pairs(a.count, int),
            parse_pairs(a.bounds, lambda v: tuple(map(float, v.split("-")))),
            a.start,
            a.end,
            seed,
            a.start_time,
        )
    except ValueError as err:
        sys.exit(str(err))

    out = Path(a.out) if a.out else day_dir(seed) / f"pattern_{seed}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    ph = phase_table(df)
    ph.to_csv(out.with_name(out.stem + "_phases.csv"), index=False)
    if df.attrs["added"]:
        print(
            "counts do not follow the stage map as given, added "
            + ", ".join(f"{n} {s}" for s, n in df.attrs["added"].items())
        )
    print(f"seed {seed}\n{df.drop(columns=['phases']).to_string(index=False)}\n")
    print("gas / air supply plan (flows = median ln/min of the source stretch)")
    print(ph.drop(columns=["start", "end"]).to_string(index=False))
    print(f"wrote {out} and {out.stem}_phases.csv")
    if a.plot:
        plot(df, out.with_suffix(".png"))
        print(f"wrote {out.with_suffix('.png')}")


if __name__ == "__main__":
    main()
