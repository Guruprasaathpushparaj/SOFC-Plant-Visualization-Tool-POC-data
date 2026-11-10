"""Industry stage codes S0–S8 on top of the operating stages.

The stage benchmark (2026-10-16, https://claude.ai/artifact/QWDAPd9fdpzdDmpUeebjFN)
lined our stages up with IEC 62282-3-200, the SOFC S0–S8 sequence ladder,
PackML / ISA-88 and power-plant start classes. This module adds those codes
without changing a single rule in operating_states.py:

    S0 Cold, plant off      Shut-down, sub-stage At ambient (plant off)
    S1 Warm, plant off      Idle
    S2 Start-up             Start-up        (+ start class cold / warm / hot)
    S3 Hot standby          Hot standby
    S4 Thermal adjustment   Thermal adjustment
    S5 Part load            Part load
    S6 Rated power          Rated power     (never reached)
    S7 Shut-down            Shut-down, sub-stage Cooling
    S8 Trip                 proposed: protective trip of a hot plant, from the
                            trip until the cool-down is under way

S8 is the only new stage. The trip minutes are filed under Part load / Hot
standby / Shut-down by operating_states.py; here they are taken out and also
kept as a flag column (`trip`), so either reading of benchmark decision B works.

Usage:
    python 03_data_analysis/scripts/industrial_stages.py      # all day files
Writes to 03_data_analysis/industrial_stages/.
"""

from pathlib import Path

import numpy as np
import operating_states as ops
import pandas as pd
import trip_check as tc

OUT = Path(__file__).resolve().parents[1] / "industrial_stages"
TRIP_CACHE = ops.OUT / "trip_cut_events.csv"  # written by operating_states.ipynb §11

# ---- codes, names and colours ---------------------------------------------
CODES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]
NAMES = {
    "S0": "Cold, plant off",
    "S1": "Warm, plant off",
    "S2": "Start-up",
    "S3": "Hot standby",
    "S4": "Thermal adjustment",
    "S5": "Part load",
    "S6": "Rated power",
    "S7": "Shut-down",
    "S8": "Trip",
}
LABELS = {c: f"{c} {n}" for c, n in NAMES.items()}
INDUSTRY = {
    "S0": "Cold state / Stopped / Offline cold",
    "S1": "Offline warm (power plants only)",
    "S2": "Start-up / Starting / Heat-up",
    "S3": "Pre-generation / Hot standby / Idle",
    "S4": "No standard name (PackML Holding is closest)",
    "S5": "Power generation, partial / Execute",
    "S6": "Power generation, rated",
    "S7": "Shutdown / Stopping / Normal shutdown",
    "S8": "Emergency shutdown / Aborted / Unit trip",
}
TODAY = {
    "S0": "Shut-down · At ambient",
    "S1": "Idle",
    "S2": "Start-up",
    "S3": "Hot standby",
    "S4": ops.ADJUST,
    "S5": "Part load",
    "S6": "Rated power",
    "S7": "Shut-down · Cooling",
    "S8": "(not a stage: Part load / Hot standby / Shut-down)",
}
# Benchmark page palette: cold blues → heat orange → hot red → load green → stop teal;
# trip in signal red.
COLORS = {
    "S0": "#5d6f8c",
    "S1": "#7d68a3",
    "S2": "#c47c12",
    "S3": "#b4472b",
    "S4": "#a2467f",
    "S5": "#2e8452",
    "S6": "#1d5c8c",
    "S7": "#23798a",
    "S8": "#c22d2d",
    "No data": "#ffffff",
}

# ---- trip (S8) --------------------------------------------------------------
# A protective cut of a hot plant, from trip_check.cut_events(): the S-PLC purge,
# the S-PLC stop, or power cut at a trip value with the gas left as it was.
TRIP_KINDS = [
    "EMERGENCY PURGE",
    "EMERGENCY STOP",
    "Power cut at trip value, gas unchanged",
]
# 400 °C stack (not ops.T_HOT 450): a cut below this is the end of a cool-down,
# not a trip
TRIP_T_MIN = tc.T_ANODE_HOT
TRIP_CHAIN_MIN = 30  # min: cuts this close belong to one trip (purge → stop → reset)
TRIP_HOLD_MIN = 15  # min after the last cut of a trip: cool-down taken as under way

# ---- start class (benchmark decision C) ----------------------------------------
# Power plants class starts by metal temperature. Our edges: within DT_AMBIENT of
# ambient = cold (the S0 test), at or above T_HOT (450 °C, Hot standby lower bound) =
# hot.
START_CLASSES = ["cold", "warm", "hot"]
EPISODE_GAP_H = 6  # h: a logger gap longer than this ends an episode


def trip_events(recompute=False):
    """Protective cuts with a hot stack, one row per cut (1 s raw data)."""
    if recompute or ops.stale(TRIP_CACHE, tc.__file__, tc.RAW):
        ev = tc.cut_events()
        TRIP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        ev.to_csv(TRIP_CACHE, index=False)
    else:
        ev = pd.read_csv(TRIP_CACHE, parse_dates=["time"])
    return (
        ev[ev.kind.isin(TRIP_KINDS) & (ev["T stack °C"] >= TRIP_T_MIN)]
        .sort_values("time")
        .reset_index(drop=True)
    )


def trip_windows(events):
    """Chain cuts closer than TRIP_CHAIN_MIN into one trip. The one trip window every \
script uses:
    minutes `start` <= t < `end`, start = first whole minute after the first cut (the \
minute holding the cut
    keeps its old stage), end = first whole minute after the last cut + \
TRIP_HOLD_MIN."""
    rows = []
    for t, kind in zip(events.time, events.kind):
        if rows and t - rows[-1]["last cut"] <= pd.Timedelta(minutes=TRIP_CHAIN_MIN):
            rows[-1]["last cut"] = t
            rows[-1]["cuts"].append(kind)
        else:
            rows.append({"first cut": t, "last cut": t, "cuts": [kind]})
    w = pd.DataFrame(rows)
    if w.empty:
        return pd.DataFrame(
            columns=["trip", "start", "end", "first cut", "last cut", "n cuts", "cuts"]
        )
    w["start"] = w["first cut"].dt.floor("1min") + pd.Timedelta(minutes=1)
    w["end"] = w["last cut"].dt.floor("1min") + pd.Timedelta(minutes=1 + TRIP_HOLD_MIN)
    w["n cuts"] = w.cuts.str.len()
    w["cuts"] = w.cuts.map(lambda k: " → ".join(k))
    w.insert(0, "trip", range(1, len(w) + 1))
    return w[["trip", "start", "end", "first cut", "last cut", "n cuts", "cuts"]]


# ---- mapping ------------------------------------------------------------------
def code_of(stage, sub_stage):
    """Today's stage (+ Shut-down sub-stage) → industry code. 'No data' stays 'No \
data'."""
    m = {
        "Idle": "S1",
        "Start-up": "S2",
        "Hot standby": "S3",
        ops.ADJUST: "S4",
        "Part load": "S5",
        "Rated power": "S6",
        "Shut-down": "S7",
    }
    code = stage.map(m).fillna("No data")
    return code.mask((stage == "Shut-down") & (sub_stage == ops.SD_AMBIENT), "S0")


def add_codes(s, windows):
    """Add `trip`, `code`, `ind_stage` to one minute table (states from ops.segment)."""
    s = s.copy()
    s["trip"] = False
    for w in windows.itertuples():
        s.loc[
            (s.index >= w.start) & (s.index < w.end) & (s.stage != "No data"), "trip"
        ] = True
    s["code"] = code_of(s["stage"], s["sub_stage"]).mask(s["trip"], "S8")
    s["ind_stage"] = s["code"].map(LABELS).fillna("No data")
    return s


def blocks(s, col="code"):
    """One row per contiguous run of `col` within one day's minute table."""
    b = (s[col] != s[col].shift()).cumsum()
    g = s.groupby(b)
    seg = pd.DataFrame(
        {
            "code": g[col].first(),
            "stage_today": g["stage"].agg(lambda x: " / ".join(dict.fromkeys(x))),
            "operations": g["operation"].agg(lambda x: " > ".join(dict.fromkeys(x))),
            "start": g.apply(lambda x: x.index[0]),
            "end": g.apply(lambda x: x.index[-1] + pd.Timedelta("1min")),
            "T_start_C": g["T_stack_C"].first(),
            "T_end_C": g["T_stack_C"].last(),
            "I_max_A": g["I_string_A"].max(),
            "P_EAPH_mean_kW": g["P_EAPH_kW"].mean(),
        }
    ).reset_index(drop=True)
    seg.insert(1, "name", seg.code.map(NAMES).fillna("No data"))
    seg.insert(
        4, "duration_min", ((seg.end - seg.start).dt.total_seconds() / 60).astype(int)
    )
    seg[["T_start_C", "T_end_C", "I_max_A", "P_EAPH_mean_kW"]] = seg[
        ["T_start_C", "T_end_C", "I_max_A", "P_EAPH_mean_kW"]
    ].round(1)
    return seg


def runs(label):
    """Run id per row: a new run starts when `label` changes or the logger gap to the \
previous row is > EPISODE_GAP_H."""
    return (
        (label != label.shift())
        | (label.index.to_series().diff() > pd.Timedelta(hours=EPISODE_GAP_H))
    ).cumsum()


def episodes(all_states):
    """Episodes over all days joined: contiguous runs of one code, 'No data' skipped, \
broken by gaps > EPISODE_GAP_H."""
    s = all_states[all_states.code != "No data"]
    g = s.groupby(runs(s.code))
    e = pd.DataFrame(
        {
            "code": g.code.first(),
            "start": g.apply(lambda x: x.index[0]),
            "end": g.apply(lambda x: x.index[-1] + pd.Timedelta("1min")),
            "minutes": g.size(),
            "T_start_C": g.T_stack_C.agg(
                lambda x: x.dropna().iloc[0] if x.notna().any() else np.nan
            ),
            "T_end_C": g.T_stack_C.agg(
                lambda x: x.dropna().iloc[-1] if x.notna().any() else np.nan
            ),
            "T_amb_C": g.T_amb_C.first(),
            "I_max_A": g.I_string_A.max(),
        }
    ).reset_index(drop=True)
    e["prev"] = e.code.shift().fillna("–")
    e["next"] = e.code.shift(-1).fillna("–")
    joined = (e.start - e.end.shift()) > pd.Timedelta(hours=EPISODE_GAP_H)
    e.loc[joined, "prev"] = "–"  # a long logger gap: the previous episode is unknown
    e.loc[joined.shift(-1, fill_value=False), "next"] = "–"
    e["start_class"] = ""
    su = e.code == "S2"
    e.loc[su, "start_class"] = np.select(
        [
            e.T_start_C[su] <= e.T_amb_C[su].fillna(ops.T_AMB_DEFAULT) + ops.DT_AMBIENT,
            e.T_start_C[su] >= ops.T_HOT,
        ],
        ["cold", "hot"],
        "warm",
    )
    return e


def run_all(recompute_trips=False):
    """Segment every day file and add the codes. Returns (all_days, windows) with \
all_days = {day: (states, blocks)}."""
    import contextlib
    import io

    windows = trip_windows(trip_events(recompute_trips))
    with contextlib.redirect_stdout(io.StringIO()):
        raw = ops.segment_all()
    out = {}
    for d, (s, _) in raw.items():
        s = add_codes(s, windows)
        out[d] = (s, blocks(s))
    return out, windows


def plot_band(ax, seg, y=0, h=0.8):
    """Industry-stage band from a blocks() table on a date axis."""
    import matplotlib.dates as mdates

    for r in seg.itertuples():
        ax.broken_barh(
            [
                (
                    mdates.date2num(r.start),
                    mdates.date2num(r.end) - mdates.date2num(r.start),
                )
            ],
            (y - h / 2, h),
            color=COLORS.get(r.code, "#fff"),
            lw=0,
        )


def legend_handles(codes=CODES):
    import matplotlib.patches as mpatches

    return [mpatches.Patch(color=COLORS[c], label=LABELS[c]) for c in codes]


if __name__ == "__main__":
    all_days, windows = run_all()
    OUT.mkdir(exist_ok=True)
    allst = pd.concat(s for s, _ in all_days.values())
    episodes(allst).to_csv(OUT / "industrial_episodes.csv", index=False)
    windows.to_csv(OUT / "trip_windows.csv", index=False)
    print(allst.code.value_counts().reindex(CODES + ["No data"], fill_value=0))
