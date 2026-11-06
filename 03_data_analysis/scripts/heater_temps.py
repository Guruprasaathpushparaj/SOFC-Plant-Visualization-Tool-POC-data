"""Stack temperature against the gas-line heaters ERH, EAGH, EAOH1, EAOH2 and EAOH3.

Adds the heater signals to the decided plant stages of plant_stages.py (nothing there or in operating_states.py
changes) and draws one figure per stretch of consecutive days (as in operating_states.ipynb §9.4b): stack T against the heater TCs only.
Used by heater_temperatures.ipynb.

Sensors (component_sensor_map_en.md §1.5, §1.6, §4):
    heater  control TC    safety TC     current               trip    rated
    ERH     TIRC_5_17     TIRZ_8_2_5    pi_IIR_5_1_3_ActVal   860 °C  3.3 kW
    EAGH    TIRC_3_1_1    TIRZ_8_2_1    pi_IIR_3_1_1_ActVal   950 °C  1.3 kW
    EAOH1   TIRC_5_3_1    TIRZ_8_2_2    pi_IIR_5_1_1_ActVal   950 °C  1.3 kW
    EAOH2   TIRC_5_3_2    TIRZ_8_2_3    pi_IIR_5_1_2_ActVal   950 °C  1.3 kW
    EAOH3   TIRC_6_1_1    TIRZ_8_2_4    pi_IIR_6_1_1_ActVal   950 °C  1.3 kW
The PLC_pv_rCurr* heater columns are 0 on all 39 days, so the pi_IIR_* currents are used.
"""
import sys

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

import operating_states as ops
import plant_stages as ps

OUT = ops.ROOT / "03_data_analysis" / "heater_temperatures"

HEATER_ON_A = 0.5       # A: heater current above this = heater on (off-state reads 0.0–0.1 A)

# name: control TC, safety TC, current, trip °C, rated kW, where it sits, colour (validated categorical order), line style
HEATERS = {
    "ERH":   dict(temp="TIRC_5_17", safety="TIRZ_8_2_5", current="pi_IIR_5_1_3_ActVal", trip=860, rated_kW=3.3,
                  where="reformer / burner housing heater", color="#2a78d6", ls="-"),
    "EAGH":  dict(temp="TIRC_3_1_1", safety="TIRZ_8_2_1", current="pi_IIR_3_1_1_ActVal", trip=950, rated_kW=1.3,
                  where="reformate line heater (reformer → stack anode)", color="#eb6834", ls="-"),
    "EAOH1": dict(temp="TIRC_5_3_1", safety="TIRZ_8_2_2", current="pi_IIR_5_1_1_ActVal", trip=950, rated_kW=1.3,
                  where="anode off-gas heater, TOX branch 1", color="#1baf7a", ls="-"),
    "EAOH2": dict(temp="TIRC_5_3_2", safety="TIRZ_8_2_3", current="pi_IIR_5_1_2_ActVal", trip=950, rated_kW=1.3,
                  where="anode off-gas heater, TOX branch 2", color="#eda100", ls="--"),
    "EAOH3": dict(temp="TIRC_6_1_1", safety="TIRZ_8_2_4", current="pi_IIR_6_1_1_ActVal", trip=950, rated_kW=1.3,
                  where="anode off-gas recycle heater (→ ejector)", color="#e87ba4", ls="-"),
}
FUEL_SIDE = ["ERH", "EAGH"]                 # reformer and reformate line
OFF_GAS = ["EAOH1", "EAOH2", "EAOH3"]       # anode off-gas: TOX branches and recycle
# Probes next to the heaters, for reference (not plotted in the stretch figure)
NEIGHBOURS = {"T_reformer_out_C": ["TIRC_3_17"],                 # upstream of EAGH
              "T_anode_out_C": ["TIRC_5_2_1", "TIRC_5_2_2"],     # stack anode outlet = upstream of EAOH3
              "T_recycle_in_C": ["TIR_6_01"]}                    # after EAOH3, ejector suction


def load_heaters(day):
    """Heater temperatures, safety temperatures and currents for one day, 1-min means (-1 fill values dropped)."""
    cols = [c for h in HEATERS.values() for c in (h["temp"], h["safety"], h["current"])]
    cols += [c for v in NEIGHBOURS.values() for c in v]
    d = pd.read_parquet(ops.SRC / f"{day}_10s.parquet", columns=["Date Time", *cols])
    d.index = pd.to_datetime(d.pop("Date Time"))
    d = d.apply(pd.to_numeric, errors="coerce")
    out = {}
    for n, h in HEATERS.items():
        out[f"T_{n}_C"] = d[h["temp"]].where(d[h["temp"]] > 0)
        out[f"Tsafe_{n}_C"] = d[h["safety"]].where(d[h["safety"]] > 0)
        out[f"I_{n}_A"] = d[h["current"]].where(d[h["current"]] > -1).clip(lower=0)
    for k, c in NEIGHBOURS.items():
        out[k] = d[c].where(d[c] > 0).mean(axis=1)
    return pd.DataFrame(out).resample("1min").mean()


def plant_days(all_days):
    """Label every day file with the decided plant stages. all_days: ops.segment_all(). `stage` becomes the plant
    stage, the operating_states stage is kept as `old_stage`. Returns ({day: minutes}, {day: stage blocks})."""
    windows = ps.ins.trip_windows(ps.ins.trip_events())
    s = ps.label(pd.concat(m for m, _ in all_days.values()), windows)     # all days at once: trips may cross midnight
    states, segs = {}, {}
    for d, (m, _) in all_days.items():
        x = s.loc[m.index]
        segs[d] = ps.blocks(x)
        states[d] = x.rename(columns={"stage": "old_stage"}).rename(columns={"plant_stage": "stage"})
    return states, segs


def heater_states(day, states):
    """Plant-stage minutes (stage, operation, stack signals) joined with the heater signals."""
    s = states.join(load_heaters(day))
    for n in HEATERS:
        s[f"dT_{n}_K"] = s[f"T_{n}_C"] - s["T_stack_C"]        # heater TC minus stack median
        s[f"{n}_on"] = s[f"I_{n}_A"] > HEATER_ON_A
    return s


def stage_table(s, value, how="median"):
    """One row per stage, one column per heater: `value` is a format with {n}, e.g. 'T_{n}_C'."""
    st = s[s.stage != "No data"]
    t = pd.DataFrame({n: st.groupby("stage")[value.format(n=n)].agg(how) for n in HEATERS})
    return t.reindex([x for x in ps.STAGES if x in t.index])


SHORT = {ps.HEAT_AIR: "HU-air", ps.HEAT_FG: "HU-fg", ps.HS: "HS", ps.FS: "FS", ps.PL: "PL", ps.AFC: "AFC",
         ps.SD: "SD", ps.PURGE: "Purge", "No data": "–"}


def stretches(days):
    """Split day files into stretches of consecutive days."""
    groups = []
    for d in days:
        if groups and pd.Timestamp(d) - pd.Timestamp(groups[-1][-1]) == pd.Timedelta("1D"):
            groups[-1].append(d)
        else:
            groups.append([d])
    return groups


def heater_panels(axs, s):
    """Stack T against the fuel-side and the off-gas heater TCs."""
    for a, group, title in ((axs[0], FUEL_SIDE, "fuel side"), (axs[1], OFF_GAS, "anode off-gas")):
        a.plot(s.index, s.T_stack_C, color="k", lw=1.6, label="Stack T (median TIR_4_6_*)")
        for n in group:
            h = HEATERS[n]
            a.plot(s.index, s[f"T_{n}_C"], color=h["color"], ls=h["ls"], lw=1.1, label=f"{n}  {h['temp']}")
        a.set_ylabel("°C"); a.set_ylim(0, 850)
        a.text(0.995, 0.96, f"Heaters, {title}", transform=a.transAxes, ha="right", va="top", fontsize=8, color="#555")
        a.legend(loc="upper left", fontsize=7.5, ncol=4)
        a.spines["top"].set_visible(False)
        a.grid(axis="x", color="#e3e3e3", lw=.6)


def plot_stretch(gi, n_groups, grp, hs, segs, path=None):
    """One figure per stretch: stack T vs heater TCs (shaded by stage) and a stage band. hs/segs: {day: frame}."""
    t0, t1 = pd.Timestamp(grp[0]), pd.Timestamp(grp[-1]) + pd.Timedelta("1D")
    fig, axs = plt.subplots(3, 1, figsize=(16, 8.5), sharex=True, gridspec_kw={"height_ratios": [2.4, 2.4, .35]})
    s = pd.concat([hs[d] for d in grp])
    s = s.reindex(pd.date_range(t0, t1, freq="1min", inclusive="left"))   # logger gaps -> breaks in the lines
    seg = pd.concat([segs[d] for d in grp])
    heater_panels(axs[:2], s)
    num = mdates.date2num
    for r in seg.itertuples():
        c = ps.COLORS.get(r.stage, "#fff")
        for a in axs[:2]:
            a.axvspan(r.start, r.end, color=c, alpha=ops.STAGE_TINT, lw=0)
        axs[2].broken_barh([(num(r.start), num(r.end) - num(r.start))], (0, 1), color=c, lw=0)
    for d in grp[1:]:
        for a in axs:
            a.axvline(num(pd.Timestamp(d)), color="#888", lw=.8)
    ax = axs[-1]
    ax.set_yticks([.5], ["Stage"], fontsize=9); ax.set_ylim(0, 1)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.set_xlim(num(t0), num(t1))
    hours = (t1 - t0) / pd.Timedelta("1h")
    ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 3 if hours <= 48 else 6 if hours <= 120 else 12)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d\n%H:%M"))
    ax.tick_params(axis="x", labelsize=8)
    title = f"{t0:%Y-%m-%d}" + (f" → {pd.Timestamp(grp[-1]):%Y-%m-%d}" if len(grp) > 1 else "")
    axs[0].set_title(f"Stretch {gi} of {n_groups}:  {title}  ({len(grp)} day{'s' if len(grp) > 1 else ''})",
                     loc="left", fontsize=11)
    axs[0].add_artist(axs[0].get_legend())             # keep the sensor legend next to the stage legend
    axs[0].legend(handles=ps.legend_handles(), ncol=8,
                  fontsize=8, loc="lower left", bbox_to_anchor=(0, 1.08), frameon=False)
    fig.tight_layout()
    if path:
        fig.savefig(path, dpi=110, bbox_inches="tight")
    return fig


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else "20260324"
    states, _ = plant_days({day: ops.segment(day)})
    s = heater_states(day, states[day])
    print(stage_table(s, "T_{n}_C").round(0))
    print(stage_table(s, "dT_{n}_K").round(0))
