"""Plant stages as decided on 2026-11-02 (plant walkthrough + devices-on check).

These eight stages are named after what the plant is doing (which supplies and
devices are on), not after the stack temperature alone:

    Heat-up air       Start-up, cathode air only (EAPH heats the air)
    Heat-up N₂+H₂     Start-up, forming gas on (stack > ~210 °C)
    Hot standby       Hot standby + Thermal adjustment, forming gas, no load
    Fuel switch       natural gas on, no current yet
    Part load         stack current flowing (Rated power never reached)
    Air-flow cooling  Shut-down with cathode air still blowing (> 20 ln/min)
    Shutdown          everything off except control: air-off cooling, plant
                      off (cold or warm) and the emergency stop until the air
                      is switched back on
    Trip: purge       emergency purge: air, N₂, H₂ and control on, all else off

The stage is built on top of operating_states.py (stage, phase, F_air,
I_string_A) and industrial_stages.py (trip windows); no rule there changes.
Rule of thumb from the data: forming gas is on ⇔ stack > 210 °C and no natural
gas (`rule_210_check`), except right after an emergency stop.

Usage:
    python 03_data_analysis/scripts/plant_stages.py      # all day files
Writes to 03_data_analysis/plant_stages/.
"""

from pathlib import Path

import industrial_stages as ins
import operating_states as ops
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "plant_stages"

HEAT_AIR, HEAT_FG, HS, FS, PL, AFC, SD, PURGE = (
    "Heat-up air",
    "Heat-up N₂+H₂",
    "Hot standby",
    "Fuel switch",
    "Part load",
    "Air-flow cooling",
    "Shutdown",
    "Trip: purge",
)
STAGES = [HEAT_AIR, HEAT_FG, HS, FS, PL, AFC, SD, PURGE]
COLORS = {
    HEAT_AIR: "#E8B04A",
    HEAT_FG: "#C46A12",
    HS: "#B4472B",
    FS: "#7B4FA0",
    PL: "#2E8B57",
    AFC: "#3A7CA5",
    SD: "#8C96A3",
    PURGE: "#C2185B",
    "No data": "#FFFFFF",
}

AIR_COOL = 20.0  # ln/min FIRC_111 + FIRC_112: above this the cool-down is forced by air
I_POWER = 1.0  # A string current: below this natural gas on = fuel switch, not power
# °C stack: forming gas on above this (rule of thumb, checked in rule_210_check)
T_FORMING = 210.0
FORMING = ["Forming gas (N2 + H2)", "N2 purge"]


def base_stage(s):
    """Stage of each minute without the trips. s: minute table from ops.segment (all \
days may be joined)."""
    st, ph = s["stage"], s["phase"]
    air = s["F_air"].fillna(0) > AIR_COOL
    lab = pd.Series(
        SD, index=s.index, dtype=object
    )  # Idle, plant off, anything unpowered
    su, hot = st == "Start-up", st.isin(["Hot standby", ops.ADJUST])
    lab[su & (ph == "Air only")] = HEAT_AIR
    lab[su & ph.isin(FORMING)] = HEAT_FG
    lab[hot & (ph != "Plant off")] = HS
    lab[(st == "Shut-down") & air] = AFC
    lab[
        (ph == "Natural gas")
        & (s["I_string_A"].fillna(0) < I_POWER)
        & (st != "Shut-down")
    ] = FS
    lab[st.isin(["Part load", "Rated power"])] = PL
    lab[st == "No data"] = "No data"
    return lab


def trip_kind(cut):
    """component_sensor_map_en.md §4: an emergency stop closes every supply; the other \
cuts are followed by purge."""
    return SD if "STOP" in cut else PURGE


def add_trips(s, lab, windows):
    """Overwrite the trip windows: purge until the last cut's kind takes over; an \
emergency stop lasts until the
    air comes back on, after that the cool-down follows the normal rules. Minutes \
before the first cut stay as they are."""
    lab = lab.copy()
    air = s["F_air"].fillna(0) > AIR_COOL
    for _, w in windows.iterrows():
        cuts = [c.strip() for c in w["cuts"].split("→")]
        t1, t3 = (
            pd.Timestamp(w["start"]),
            pd.Timestamp(w["end"]),
        )  # window from ins.trip_windows
        t2 = t3 - pd.Timedelta(
            minutes=ins.TRIP_HOLD_MIN
        )  # first minute after the last cut
        win = (s.index >= t1) & (s.index < t3) & (lab != "No data").to_numpy()
        lab[win & (s.index < t2)] = trip_kind(cuts[0])
        after = win & (s.index >= t2)
        lab[after] = trip_kind(cuts[-1])
        if trip_kind(cuts[-1]) == SD:
            back = s.index[after & air.to_numpy()]
            if len(back):
                lab[after & (s.index >= back[0])] = base_stage(
                    s.loc[after & (s.index >= back[0])]
                )
    return lab


def label(s, windows):
    """Add column `plant_stage` to a minute table (one day or all days joined)."""
    s = s.copy()
    s["plant_stage"] = add_trips(s, base_stage(s), windows)
    return s


def blocks(s, col="plant_stage"):
    """One row per contiguous run of `col`; a logger gap > 6 h also ends a block."""
    g = s.groupby(ins.runs(s[col]))
    b = pd.DataFrame(
        {
            "stage": g[col].first(),
            "start": g.apply(lambda x: x.index[0]),
            "end": g.apply(lambda x: x.index[-1] + pd.Timedelta("1min")),
            "minutes": g.size(),
            "T_start_C": g.T_stack_C.first(),
            "T_end_C": g.T_stack_C.last(),
            "air_median": g.F_air.median(),
            "I_max_A": g.I_string_A.max(),
            "old_stages": g.stage.agg(lambda x: " / ".join(dict.fromkeys(x))),
        }
    ).reset_index(drop=True)
    num = ["T_start_C", "T_end_C", "air_median", "I_max_A"]
    b[num] = b[num].round(1)
    return b


def episodes(b):
    """Blocks without 'No data' (one stage split only by a short gap is joined), with \
the stage before and after
    (a gap > 6 h = unknown '–')."""
    e = b[b.stage != "No data"].reset_index(drop=True)
    gap = (e.start - e.end.shift()) > pd.Timedelta(hours=ins.EPISODE_GAP_H)
    g = e.groupby(((e.stage != e.stage.shift()) | gap).cumsum())
    e = pd.DataFrame(
        {
            "stage": g.stage.first(),
            "start": g.start.first(),
            "end": g.end.last(),
            "minutes": g.minutes.sum(),
            "T_start_C": g.T_start_C.first(),
            "T_end_C": g.T_end_C.last(),
            "I_max_A": g.I_max_A.max(),
        }
    ).reset_index(drop=True)
    gap = (e.start - e.end.shift()) > pd.Timedelta(hours=ins.EPISODE_GAP_H)
    e["prev"] = e.stage.shift().where(~gap, "–").fillna("–")
    e["next"] = (
        e.stage.shift(-1).where(~gap.shift(-1, fill_value=False), "–").fillna("–")
    )
    return e


def transitions(e):
    """How often each stage was followed by each other stage."""
    t = pd.crosstab(e.stage, e.next).reindex(index=STAGES, columns=STAGES, fill_value=0)
    return t.rename_axis("from \\ to", axis=0).rename_axis(None, axis=1)


def rule_210_check(s):
    """Share of labelled minutes where 'forming gas on' equals 'stack > 210 °C and no \
natural gas'."""
    m = s[s.plant_stage != "No data"]
    fg = (m.F_N2.fillna(0) > ops.N2_ON) & (m.F_H2.fillna(0) > ops.H2_ON)
    pred = (m.T_stack_C > T_FORMING) & (m.phase != "Natural gas")
    per = pd.DataFrame(
        {
            "stage": m.plant_stage,
            "agree": fg == pred,
            "fg_on": fg,
            "hot": m.T_stack_C > T_FORMING,
        }
    )
    tab = per.groupby("stage").agg(
        minutes=("agree", "size"),
        agree_pct=("agree", "mean"),
        forming_gas_on_pct=("fg_on", "mean"),
        above_210_pct=("hot", "mean"),
    )
    tab[["agree_pct", "forming_gas_on_pct", "above_210_pct"]] *= 100
    return float((fg == pred).mean() * 100), tab.reindex(
        [x for x in STAGES if x in tab.index]
    ).round(1)


def per_day(s, how="minutes"):
    """Minutes (or block starts) per day file and stage."""
    if how == "minutes":
        x = pd.crosstab(s.index.date, s.plant_stage)
    else:
        st = s.plant_stage
        x = pd.crosstab(
            s.index.date[(st != st.shift()).to_numpy()], st[st != st.shift()]
        )
    x = x.reindex(
        columns=STAGES + (["No data"] if how == "minutes" else []), fill_value=0
    )
    x.index.name = "day"
    return x


def plot_band(ax, b, y=0, h=0.8):
    """Stage band from a blocks() table on a date axis."""
    import matplotlib.dates as mdates

    for r in b.itertuples():
        ax.broken_barh(
            [
                (
                    mdates.date2num(r.start),
                    mdates.date2num(r.end) - mdates.date2num(r.start),
                )
            ],
            (y - h / 2, h),
            color=COLORS.get(r.stage, "#fff"),
            lw=0,
        )


def legend_handles(stages=STAGES):
    import matplotlib.patches as mpatches

    return [mpatches.Patch(color=COLORS[k], label=k) for k in stages]


def run_all():
    """Segment every day file and label it. Returns (all minutes joined, trip \
windows)."""
    import contextlib
    import io

    windows = ins.trip_windows(ins.trip_events())
    with contextlib.redirect_stdout(io.StringIO()):
        days = ops.segment_all()
    s = pd.concat(d for d, _ in days.values())
    return label(s, windows), windows


STAGE_FILE = OUT / "plant_stages_1min.parquet"
# files whose change alters the stage labels in STAGE_FILE
RULE_SOURCES = [
    __file__,
    ins.__file__,
    ops.__file__,
    ins.tc.__file__,
    ins.TRIP_CACHE,
    ops.SRC,
]


def save():
    """Label all days and write STAGE_FILE + the blocks table. Returns the labelled \
minutes."""
    allst, _ = run_all()
    OUT.mkdir(exist_ok=True)
    allst[
        [
            "T_stack_C",
            "I_string_A",
            "F_air",
            "phase",
            "stage",
            "sub_stage",
            "operation",
            "plant_stage",
        ]
    ].to_parquet(STAGE_FILE)
    blocks(allst).to_csv(OUT / "plant_stage_blocks.csv", index=False)
    return allst


if __name__ == "__main__":
    allst = save()
    print(allst.plant_stage.value_counts().reindex(STAGES + ["No data"], fill_value=0))
