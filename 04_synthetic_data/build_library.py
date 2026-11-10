"""Synthetic data, step 1 → 2 hand-over: the learning material from the real record.

Builds, from the approved stage segmentation \
(03_data_analysis/scripts/operating_states.py):
1. Episode library: every stage episode, stitched across midnight within a
   recording run, with its 1-min key-signal trace (episodes.csv, traces.parquet).
2. Stage transition table (decision D2): which stage followed which, counted
   from the data and compared with the design flow in operational-modes.md §2.
3. Held-out day groups (decision D8): 5 folds of whole recording runs.
4. Rebuild check (decision D6, D7): how well the 8 key signals predict every
   kept sensor, by component group, scored on held-out folds; and how many
   shared shapes the stack thermocouples need.

Run from anywhere:  python "04_synthetic_data/build_library.py"
"""

import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "03_data_analysis" / "scripts"))
import operating_states as ops  # noqa: E402

PRE = ROOT / "02_data" / "preprocessed"
TRIPS = ROOT / "03_data_analysis" / "operating_states" / "trip_cut_events.csv"
GROUPS = ROOT / "03_data_analysis" / "preprocessing" / "column_groups.json"
OUT = Path(__file__).resolve().parent / "library"

KEY = [
    "T_stack_C",
    "T_stack_min_C",
    "T_stack_max_C",
    "I_string_A",
    "P_stack_kW",
    "P_EAPH_kW",
    "T_cathode_in_C",
    "P_air_in",
]
# a logger gap up to this long inside a run does not split a library episode (one stage
# run; plant episodes use industrial_stages.EPISODE_GAP_H)
MAX_BRIDGE_MIN = 60
R2_REBUILD = 0.8  # D6 default: key-signal route when the group R² reaches this
PCA_VAR = 0.95  # D7 default: shapes needed to explain this share of variance
# Safety events that make an episode a fault example (D19: kept out of training)
FAULT_KINDS = ("EMERGENCY STOP", "EMERGENCY PURGE", "Power cut at trip value")
FAULT_MARGIN = pd.Timedelta(
    "10min"
)  # minutes before a safety event that are left out too
MIN_USABLE_H = {"Part load": 0.1}  # h; an episode cut shorter than this is not used
MIN_USABLE_H_DEFAULT = 0.5  # (load runs last only 8–44 min, so Part load gets 6 min)
TRIP_AFTER = pd.Timedelta(
    "15min"
)  # a safety event this soon after the end = episode ended in a trip

# D8: 5 folds of ~8 days, each made of whole recording runs (runs are listed by first
# day)
FOLDS = {
    "F1": ["2026-01-30"],
    "F2": ["2025-10-30", "2025-11-13"],
    "F3": ["2026-02-13", "2026-03-12"],
    "F4": ["2026-03-01", "2026-03-17"],
    "F5": ["2026-03-22", "2026-03-28"],
}

# Design stage flow, operational-modes.md §1–§2 (Shut-down ends with the plant
# off at ambient; Idle = a warm, plant-off stack with no Shut-down before it)
DESIGN = {
    ("Shut-down", "Start-up"),
    ("Idle", "Start-up"),
    ("Idle", "Shut-down"),
    ("Start-up", "Hot standby"),
    ("Hot standby", "Part load"),
    ("Part load", "Rated power"),
    ("Rated power", "Part load"),
    ("Part load", "Hot standby"),
    ("Rated power", "Hot standby"),
    ("Part load", "Shut-down"),
    ("Rated power", "Shut-down"),
    ("Hot standby", "Shut-down"),
    # a re-heat / cool-back of a hot stack with no load (operational-modes.md §1,
    # 2026-10-14): Start-up only follows a Shut-down, Part load only Hot standby
    ("Hot standby", ops.ADJUST),
    (ops.ADJUST, "Hot standby"),
    ("Part load", ops.ADJUST),
    ("Rated power", ops.ADJUST),
    (ops.ADJUST, "Shut-down"),
}

# Component per tag section, component_sensor_map_en.md §1–§4
COMPONENT = {
    "1": "FPM supply (air, POx, N2, H2, NG)",
    "2": "Air preheating (APH, EAPH)",
    "3": "Fuel and reforming",
    "4": "Stack module",
    "5": "Stack outlet, AOG heaters, TOX",
    "6": "Anode recycle (EAOH3)",
    "7": "Exhaust and APH flue side",
    "8": "Safety monitors",
}


def quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a)


def label_all():
    days = sorted(p.name[:8] for p in ops.SRC.glob("*_10s.parquet"))
    parts = []
    for d in days:
        s, _ = quiet(ops.segment, d)
        s["day"] = pd.Timestamp(d)
        parts.append(s)
    s = pd.concat(parts).sort_index()
    s = s[~s.index.duplicated()]
    # a run = consecutive calendar days with a labelled file
    dd = pd.Series(sorted(s["day"].unique()))
    run_start = dd.where(dd.diff() != pd.Timedelta(days=1)).ffill()
    s["run"] = s["day"].map(dict(zip(dd, run_start.dt.strftime("%Y-%m-%d"))))
    return s


def episodes(s):
    """Contiguous same-stage minutes within a run; short logger gaps are bridged."""
    rows, trace = [], []
    for run, r in s.groupby("run", sort=True):
        # full minute grid, so minutes missing between two files (e.g. a day ending
        # early) count as gap
        r = r.reindex(pd.date_range(r.index[0], r.index[-1], freq="1min"))
        st = r["stage"].where(r["stage"] != "No data")
        gap = st.isna()
        gap_len = gap.groupby((~gap).cumsum()).transform("sum")
        filled = st.ffill()
        # a long gap breaks the episode even when the stage is the same on both sides
        brk = (gap & (gap_len > MAX_BRIDGE_MIN)).astype(int).diff().fillna(0).eq(-1)
        ep = ((filled != filled.shift()) | brk).cumsum()
        ids = [k for k in ep.unique() if filled[ep == k].notna().any()]
        prev_last = None  # last logged minute of the previous episode
        for i, k in enumerate(ids):
            m = r[(ep == k) & ~gap]
            if m.empty:
                continue
            eid = (
                f"{m.index[0]:%Y%m%d_%H%M}_"
                f"{m['stage'].iloc[0].split()[0].replace('/', '')}"
            )
            T = m["T_stack_C"]
            # unlogged minutes between the previous episode and this one
            prev_gap = prev_last is not None and (
                m.index[0] - prev_last
            ) > pd.Timedelta(minutes=MAX_BRIDGE_MIN + 1)
            prev_last = m.index[-1]
            rows.append(
                dict(
                    episode_id=eid,
                    run=run,
                    stage=m["stage"].iloc[0],
                    start=m.index[0],
                    end=m.index[-1] + pd.Timedelta("1min"),
                    duration_h=round(len(m) / 60, 2),
                    gap_min=int(gap[ep == k].sum()),
                    sub_stages=" > ".join(
                        x for x in dict.fromkeys(m["sub_stage"]) if x
                    ),
                    operations=" > ".join(dict.fromkeys(m["operation"])),
                    phases=" > ".join(x for x in dict.fromkeys(m["phase"]) if x),
                    T_start_C=T.iloc[0],
                    T_end_C=T.iloc[-1],
                    T_min_C=T.min(),
                    T_max_C=T.max(),
                    T_spread_max_K=(m["T_stack_max_C"] - m["T_stack_min_C"]).max(),
                    dTdt_mean_C_per_h=m["dTdt_C_per_h"].mean(),
                    I_max_A=m["I_string_A"].max(),
                    P_stack_max_kW=m["P_stack_kW"].max(),
                    P_EAPH_mean_kW=m["P_EAPH_kW"].mean(),
                    starts_at_run_edge=i == 0,
                    ends_at_run_edge=i == len(ids) - 1,
                    after_long_gap=bool(prev_gap),
                )
            )
            trace.append(
                m[KEY + ["sub_stage", "operation", "phase"]].assign(
                    episode_id=eid, stage=m["stage"].iloc[0]
                )
            )
    e = pd.DataFrame(rows)
    # a Shut-down that has reached ambient before the data ends is complete
    # (e.g. 2026-02-04 → 06, whose end is no longer cut by the 02-06 false start)
    at_amb = (e["stage"] == "Shut-down") & e["sub_stages"].str.contains(
        ops.SD_AMBIENT, regex=False
    )
    e["complete"] = ~e["starts_at_run_edge"] & (~e["ends_at_run_edge"] | at_amb)
    return e, pd.concat(trace)


def flag_faults(e, tr):
    """D19: each episode is used only on its longest stretch clear of safety events.

    Minutes within FAULT_MARGIN of a safety event are left out. A Shut-down whose
    first event falls in its first 30 min is marked trip-initiated: its cooling
    curve after the trip is kept as an example of `emergency_shutdown`
    (operational-modes.md §5.1).
    """
    t = pd.read_csv(TRIPS, parse_dates=["time"])
    t = t[t["kind"].str.startswith(FAULT_KINDS)]
    hits, lo, hi, trip0 = {}, {}, {}, {}
    for i, row in e.iterrows():
        x = t[
            (t["time"] >= row.start - FAULT_MARGIN)
            & (t["time"] < row.end + FAULT_MARGIN)
        ]["time"]
        hits[i] = "; ".join(
            f"{a:%m-%d %H:%M} {k}"
            for a, k in zip(x, t.loc[x.index, "kind"])
            if row.start <= a < row.end
        )
        # merge overlapping danger zones first, else events < 2*margin apart yield a
        # "clean" span inside the trip
        zones = []
        for a in sorted(x):
            if zones and a - FAULT_MARGIN <= zones[-1][1]:
                zones[-1][1] = a + FAULT_MARGIN
            else:
                zones.append([a - FAULT_MARGIN, a + FAULT_MARGIN])
        cuts = [
            min(max(c, row.start), row.end)
            for c in [row.start] + [c for z in zones for c in z] + [row.end]
        ]
        spans = list(zip(cuts[::2], cuts[1::2]))
        lo[i], hi[i] = max(spans, key=lambda ab: ab[1] - ab[0])
        trip0[i] = row.stage == "Shut-down" and any(
            a < row.start + pd.Timedelta("30min") for a in x
        )
    e["fault_events"] = pd.Series(hits)
    e["trip_initiated"] = pd.Series(trip0)
    e["usable_from"], e["usable_to"] = pd.Series(lo), pd.Series(hi)
    e["usable_h"] = (
        (e["usable_to"] - e["usable_from"]).dt.total_seconds() / 3600
    ).round(2)
    e["ends_in_trip"] = [
        ((t["time"] >= r.end - FAULT_MARGIN) & (t["time"] < r.end + TRIP_AFTER)).any()
        for r in e.itertuples()
    ]
    need = e["stage"].map(MIN_USABLE_H).fillna(MIN_USABLE_H_DEFAULT)
    e["use_for_training"] = e["complete"] & (e["usable_h"] >= need)
    w = e.set_index("episode_id")
    tr["usable"] = (tr.index >= tr["episode_id"].map(w["usable_from"])) & (
        tr.index < tr["episode_id"].map(w["usable_to"])
    )
    return e, tr


def transitions(e):
    rows = []
    for _, r in e.sort_values("start").groupby("run"):
        r = r.reset_index(drop=True)
        for a, b in zip(r.itertuples(), r.iloc[1:].itertuples()):
            if not b.after_long_gap:
                ok = (a.stage, b.stage) in DESIGN
                rows.append((a.stage, b.stage, a.episode_id, b.episode_id, ok))
    t = pd.DataFrame(rows, columns=["from", "to", "from_episode", "to_episode", "ok"])
    n = t.groupby(["from", "to"]).agg(
        count=("to", "size"),
        in_design=("ok", "sum"),
        examples=("to_episode", lambda x: ", ".join(list(x)[:3])),
    )
    n = n.reset_index()
    obs = set(zip(n["from"], n["to"]))
    n["status"] = np.where(
        n["in_design"] == n["count"], "observed, in design", "observed, not in design"
    )
    n = n.drop(columns="in_design")
    miss = pd.DataFrame(
        [
            dict(
                zip(["from", "to"], k),
                count=0,
                examples="",
                status="design, not observed",
            )
            for k in sorted(DESIGN - obs)
        ]
    )
    n = pd.concat([n, miss], ignore_index=True)
    mat = (
        n.pivot_table(index="from", columns="to", values="count", aggfunc="sum")
        .reindex(index=ops.STAGES, columns=ops.STAGES)
        .fillna(0)
        .astype(int)
    )
    return n, mat


def folds(s, e):
    run_fold = {r: f for f, rs in FOLDS.items() for r in rs}
    missing = set(s["run"].unique()) - set(run_fold)
    assert not missing, f"runs without a fold: {missing}"
    days = s.groupby("day")["run"].first().map(run_fold).rename("fold")
    e["fold"] = e["run"].map(run_fold)
    cov = (
        e[e["use_for_training"]]
        .groupby(["fold", "stage"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=ops.STAGES, fill_value=0)
    )
    cov.insert(0, "days", days.value_counts().sort_index())
    cov.insert(1, "runs", [", ".join(FOLDS[f]) for f in cov.index])
    return days, cov


def load_sensors(days):
    parts = []
    for d in days:
        x = pd.read_parquet(PRE / f"{d:%Y%m%d}.parquet")
        parts.append(x.resample("1min").mean())
    return pd.concat(parts)


def rebuild_check(s, days):
    """Out-of-fold R² of each kept sensor from the 8 key signals (linear + squares)."""
    groups = json.load(open(GROUPS))
    x = load_sensors(days.index)
    k = s[KEY]
    feats = pd.concat([k, (k**2).add_suffix("^2")], axis=1)
    fold = s["day"].map(days)
    stage_ok = s["stage"] != "No data"
    rows = []
    for g, cols in groups.items():
        for c in cols:
            if c not in x.columns:
                continue
            y = x[c].reindex(s.index)
            ok = stage_ok & y.notna() & feats.notna().all(axis=1)
            pred = pd.Series(np.nan, index=s.index)
            for f in FOLDS:
                tr, te = ok & (fold != f), ok & (fold == f)
                if tr.sum() < 500 or te.sum() == 0:
                    continue
                mu, sd = feats[tr].mean(), feats[tr].std().replace(0, 1)
                A = np.c_[np.ones(tr.sum()), ((feats[tr] - mu) / sd).values]
                beta = np.linalg.lstsq(A, y[tr].values, rcond=None)[0]
                B = np.c_[np.ones(te.sum()), ((feats[te] - mu) / sd).values]
                pred[te] = B @ beta
            m = pred.notna()
            if m.sum() < 500 or y[m].var() == 0:
                continue
            r2 = 1 - ((y[m] - pred[m]) ** 2).sum() / ((y[m] - y[m].mean()) ** 2).sum()
            sec = g.split("_")[1] if "_" in g and g.split("_")[1].isdigit() else ""
            comp = COMPONENT.get(
                sec,
                "Flow controllers (FIRC)"
                if g == "FIRC"
                else "EAPH power controller"
                if g.startswith("EIRC_2")
                else "String loads (EIRC4)"
                if g.startswith("EIRC_4")
                else g,
            )
            rows.append(
                dict(group=g, component=comp, sensor=c, r2_out_of_fold=round(r2, 3))
            )
    per = pd.DataFrame(rows)
    grp = (
        per.groupby(["component", "group"])
        .agg(
            sensors=("sensor", "size"),
            r2_median=("r2_out_of_fold", "median"),
            r2_min=("r2_out_of_fold", "min"),
            share_ge_0_8=(
                "r2_out_of_fold",
                lambda v: round((v >= R2_REBUILD).mean(), 2),
            ),
        )
        .reset_index()
    )
    grp["route_D6"] = np.where(
        grp["r2_median"] >= R2_REBUILD,
        "from key signals",
        "joint model / own generator",
    )
    grp = grp.sort_values("r2_median", ascending=False)
    return per, grp.round(3), x


def stack_shapes(x, s):
    """D7: shared shapes (principal components) of the stack thermocouples."""
    tc = [c for c in x.columns if c.startswith("TIR_4_6_")]
    t = x[tc].reindex(s.index).where(lambda v: (v > 0) & (v < 1000))
    dev = t.sub(t.median(axis=1), axis=0).abs().median()
    t = t.drop(columns=dev[dev > 75].index).dropna()
    z = t - t.mean()
    sv = np.linalg.svd(z.values, compute_uv=False)
    var = sv**2 / (sv**2).sum()
    cum = np.cumsum(var)
    n95 = int(np.searchsorted(cum, PCA_VAR) + 1)
    return dict(
        thermocouples_used=len(t.columns),
        dropped=sorted(set(tc) - set(t.columns)),
        minutes=len(t),
        variance_first_5=[round(v, 4) for v in var[:5]],
        cumulative_first_5=[round(v, 4) for v in cum[:5]],
        shapes_for_95pct=n95,
        D7_choice=max(3, n95),
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("Labelling all days ...")
    s = label_all()
    e, tr = episodes(s)
    e, tr = flag_faults(e, tr)
    days, cov = folds(s, e)
    t, mat = transitions(e)

    num = e.select_dtypes("float").columns
    e[num] = e[num].round(2)
    e.to_csv(OUT / "episodes.csv", index=False)
    tr.to_parquet(OUT / "traces_1min.parquet")
    t.to_csv(OUT / "transitions.csv", index=False)
    mat.to_csv(OUT / "transition_matrix.csv")
    days.to_frame().to_csv(OUT / "folds_days.csv")
    cov.to_csv(OUT / "folds_coverage.csv")

    print("Rebuild check ...")
    per, grp, x = rebuild_check(s, days)
    per.to_csv(OUT / "rebuild_r2_per_sensor.csv", index=False)
    grp.to_csv(OUT / "rebuild_r2_per_group.csv", index=False)
    shapes = stack_shapes(x, s)
    json.dump(shapes, open(OUT / "stack_shapes.json", "w"), indent=2)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print("\nEpisodes per stage (all / complete / usable for training):")
    print(
        pd.DataFrame(
            {
                "all": e["stage"].value_counts(),
                "complete": e[e["complete"]]["stage"].value_counts(),
                "usable": e[e["use_for_training"]]["stage"].value_counts(),
            }
        )
        .reindex(ops.STAGES)
        .fillna(0)
        .astype(int)
        .to_string()
    )
    print(
        "\nFault-flagged episodes:\n",
        e.loc[
            e["fault_events"] != "",
            [
                "episode_id",
                "duration_h",
                "usable_h",
                "trip_initiated",
                "ends_in_trip",
                "use_for_training",
            ],
        ].to_string(),
    )
    print(
        "\nAll episodes:\n",
        e[
            [
                "episode_id",
                "fold",
                "duration_h",
                "T_start_C",
                "T_end_C",
                "I_max_A",
                "complete",
                "use_for_training",
                "operations",
            ]
        ].to_string(max_colwidth=70),
    )
    print("\nTransition matrix (from → to):\n", mat.to_string())
    print("\nTransitions:\n", t[["from", "to", "count", "status"]].to_string())
    print("\nFold coverage (usable episodes):\n", cov.to_string())
    print("\nRebuild R² per group:\n", grp.to_string())
    print("\nStack shapes:", json.dumps(shapes))


if __name__ == "__main__":
    main()
