"""Shared loader for the per-stage analysis notebooks (start-up, shut-down, part load).

Joins the stage / operation labels of the episode library with the extra signals
the labels do not carry (flows, BOP temperatures, string voltages, controller
setpoints), all on the library's 1-min grid. Usage from a notebook:

    import stage_signals as ss
    d = ss.load()                 # one row per labelled minute, all 39 days
    ep = ss.episodes()            # library episode table (one row per stage episode)

The ambient proxy is built exactly as in operating_states.load_signals, so
"near ambient" means the same thing as in the labels.
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

import operating_states as ops

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "04_synthetic_data" / "library"
SRC = ROOT / "02_data" / "downsampled"
TRIPS = ROOT / "03_data_analysis" / "operating_states" / "trip_cut_events.csv"

BOP = {"EAPH inlet (TIR_2_05)": "TIR_2_05", "EAPH outlet / cathode inlet (TIRC_2_06)": "TIRC_2_06",
       "EAPH element, safety (TIRZ_8_1_1)": "TIRZ_8_1_1", "Stack module, safety (TIRZ_8_1_3)": "TIRZ_8_1_3",
       "Reformer catalyst in (TIRC_3_07)": "TIRC_3_07", "Reformer catalyst out (TIRC_3_15)": "TIRC_3_15",
       "Afterburner (TIRC_5_09)": "TIRC_5_09", "ERH housing heater (TIRC_5_17)": "TIRC_5_17",
       "Recycle gas (TIR_6_01)": "TIR_6_01", "APH exhaust outlet (TIR_7_04)": "TIR_7_04",
       "Exhaust outlet, safety (TIRZ_8_1_10)": "TIRZ_8_1_10", "Roof exhaust (TIR_7_05)": "TIR_7_05"}
FLOW = {"air_1": "ct_FIRC_111_PV_ProcessValue", "air_2": "ct_FIRC_112_PV_ProcessValue",
        "pox_air": "ct_FIRC_12_PV_ProcessValue", "N2": "ct_FIRC_13_PV_ProcessValue",
        "fuel": "ct_FIRC_14_PV_ProcessValue", "H2": "ct_FIRC_15_PV_ProcessValue"}
PRESS = {"p_air_supply_bar": "PIR_1_1_1", "p_N2_purge_bar": "PIR_1_3_2", "p_H2_supply_bar": "PIR_1_5"}
SETP = {"eaph_sp_C": "ct_TIRC_206_SP_TargetValue", "eaph_sp_slew": "ct_TIRC_206_SP_SlewRateAbs",
        "eaph_sp_use_ramp": "ct_TIRC_206_SP_UseSP_Ramp", "eaph_out_pct": "ct_TIRC_206_OUT_OutputValue",
        "reformer_sp_C": "ct_TIRC_311_SP_TargetValue", "erh_sp_C": "ct_TIRC_517_SP_TargetValue"}
PLANT = {"FU_worst": [f"PLC_pv_rFU_Worst_{i}" for i in range(1, 6)],
         "FU_best": [f"PLC_pv_rFU_best_{i}" for i in range(1, 6)]}
OTHER = {"P_system_out": "PLC_pv_rSystemOutPower", "afsr": "PLC_pv_rActAfsr", "pox": "PLC_pv_rActPoxValue",
         "I_ERH_A": "PLC_pv_rCurrERH"}
STRINGS = range(1, 6)
VOLT = [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rVoltMonitor" for i in STRINGS]
CURR = [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rCurrMonitor" for i in STRINGS]
VMIN = [f"String_{i}_ActMinVoltage" for i in STRINGS]
CELL = [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rVoltCellMin_ActV" for i in STRINGS]      # lowest cell voltage per string, V
CELL_SP = [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rVoltCellMin_Setp" for i in STRINGS]   # its protection limit, V
TC = [f"TIR_4_6_{i}" for i in range(1, 37)]
TC_BROKEN = ["TIR_4_6_25"]        # reads ambient in every file, whatever the stack does
TC_OUTLIER_K = 150                # a TC this far from the module median in a minute is dropped (TIR_4_6_19 on 03-13)
DROPOUT_K = 30                    # a stack median this far from its 5-min median = logger dropout minute
TC_INLET =[f"TIR_4_6_{i}" for i in range(1, 9)]   # the group that leads on heat-up and lags on cool-down


def _columns():
    cols = ops.AMB_COLS + list(BOP.values()) + list(FLOW.values()) + list(PRESS.values()) \
        + list(SETP.values()) + list(OTHER.values()) + PLANT["FU_worst"] + PLANT["FU_best"] + VOLT + CURR + VMIN + CELL + CELL_SP + TC
    return list(dict.fromkeys(cols))


def load():
    """Library labels + extra signals on the 1-min grid, with derived columns."""
    import pyarrow.parquet as pq
    tr = pd.read_parquet(LIB / "traces_1min.parquet")
    cols = _columns()
    parts = []
    for f in sorted(glob.glob(str(SRC / "*_10s.parquet"))):
        have = set(pq.read_schema(f).names)
        r = pd.read_parquet(f, columns=["Date Time"] + [c for c in cols if c in have])
        r.index = pd.to_datetime(r.pop("Date Time"))
        r = r.apply(pd.to_numeric, errors="coerce")
        r["T_amb_C"] = r[ops.AMB_COLS].where((r[ops.AMB_COLS] != -1) & (r[ops.AMB_COLS] < 60)).median(axis=1)
        r = r.resample("1min").mean()
        r["T_amb_C"] = r["T_amb_C"].rolling(60, center=True, min_periods=1).median().fillna(ops.T_AMB_DEFAULT)
        parts.append(r)
    sig = pd.concat(parts).reindex(columns=cols + ["T_amb_C"])
    d = tr.join(sig)
    # Logger dropouts: the raw file writes -1 for a few seconds, and the 10 s average turns
    # that into a one-minute drop of the whole plant (2026-03-13 10:15 and 10:34, 03-23 08:43).
    # Those minutes are blanked, so they do not show up as fake 200 °C/h rates.
    T = d["T_stack_C"].asfreq("1min")
    drop = ((T - T.rolling(5, center=True, min_periods=3).median()).abs() > DROPOUT_K).reindex(d.index, fill_value=False)
    num_cols = d.select_dtypes("number").columns
    d.loc[drop, num_cols] = np.nan
    d["logger_dropout"] = drop
    for k, c in {**FLOW, **PRESS, **SETP, **OTHER}.items():
        d[k] = d[c]
    d["air_flow"] = d["air_1"] + d["air_2"]
    d["FU_worst"] = d[PLANT["FU_worst"]].mean(axis=1)
    d["FU_best"] = d[PLANT["FU_best"]].mean(axis=1)
    d["V_string_mean"] = d[VOLT].mean(axis=1)
    d["V_cell_min"] = d[CELL].where((d[CELL] > 0) & (d[CELL] < 1.5)).min(axis=1)   # a cell above 1.5 V is a glitch
    d["V_cell_min_sp"] = d[CELL_SP].where(d[CELL_SP] > 0).median(axis=1)
    # Robust thermocouple spread. The library's T_stack_min/max keep TIR_4_6_25 on days
    # that start cold (its per-day exclusion test only sees a cold median), which makes the
    # spread jump to ~450 K during a heat-up and drop at midnight.
    t = d[TC].where((d[TC] > 0) & (d[TC] < 1000)).drop(columns=TC_BROKEN)
    t = t.where(t.sub(t.median(axis=1), axis=0).abs() <= TC_OUTLIER_K)
    d["T_tc_max_C"], d["T_tc_min_C"] = t.max(axis=1), t.min(axis=1)
    d["T_spread_K"] = d["T_tc_max_C"] - d["T_tc_min_C"]
    inlet = [c for c in TC_INLET if c in t]
    d["T_inlet_group_C"] = t[inlet].mean(axis=1)
    d["T_inlet_lead_K"] = d["T_inlet_group_C"] - t.drop(columns=inlet).mean(axis=1)
    d["excess_K"] = d["T_stack_C"] - d["T_amb_C"]
    # rates on a gap-free minute grid, so differences never jump across a missing day
    g = d["T_stack_C"].asfreq("1min")
    d["dTdt_C_per_h"] = (g.shift(-30) - g.shift(30)).reindex(d.index)
    d["dTdt_20min_C_per_h"] = ((g.shift(-10) - g.shift(10)) * 3).reindex(d.index)
    for c, n in (("T_tc_max_C", "dTmaxdt_C_per_h"), ("T_tc_min_C", "dTmindt_C_per_h")):
        g = d[c].asfreq("1min")
        d[n] = (g.shift(-30) - g.shift(30)).reindex(d.index)
    i = d["I_string_A"].asfreq("1min")
    d["dIdt_A_per_min"] = ((i.shift(-2) - i.shift(2)) / 4).reindex(d.index)
    return d


def episodes():
    e = pd.read_csv(LIB / "episodes.csv", parse_dates=["start", "end", "usable_from", "usable_to"])
    return e


def all_cuts():
    """Every logged cut, unfiltered (the CSV industrial_stages.trip_events() filters to hot protective trips)."""
    return pd.read_csv(TRIPS, parse_dates=[0]) if TRIPS.exists() else pd.DataFrame()


def neighbours(e):
    """Previous / next stage of each library episode, with the gap in between (min)."""
    e = e.sort_values("start").reset_index(drop=True)
    e["prev_stage"] = e.stage.shift()
    e["prev_ops"] = e.operations.shift()
    e["next_stage"] = e.stage.shift(-1)
    e["gap_before_min"] = (e.start - e.end.shift()).dt.total_seconds() / 60
    e["gap_after_min"] = (e.start.shift(-1) - e.end).dt.total_seconds() / 60
    e.loc[e.starts_at_run_edge, ["prev_stage", "prev_ops"]] = "file edge"
    e.loc[e.ends_at_run_edge, "next_stage"] = "file edge"
    return e


def band_rates(T, t, bands, rising=True):
    """°C/h across each band: first upward crossings (rising) or last downward crossings (falling)."""
    out = {}
    h = (t - t[0]).total_seconds().values / 3600
    v = T.values
    for lo, hi in bands:
        if rising:
            a, b = np.argmax(v >= lo), np.argmax(v >= hi)
            ok = (v >= lo).any() and (v >= hi).any() and b > a and v[0] < lo
        else:
            a = len(v) - 1 - np.argmax(v[::-1] >= hi)
            b = len(v) - 1 - np.argmax(v[::-1] >= lo) + 1 if (v >= lo).any() else 0
            ok = (v >= hi).any() and v[-1] < lo and b > a and b < len(v)
        out[f"{lo}->{hi}" if rising else f"{hi}->{lo}"] = \
            ((hi - lo) if rising else (lo - hi)) / (h[b] - h[a]) if ok and h[b] > h[a] else np.nan
    return out


def robust_sigma(x):
    dx = x.diff()[x.index.to_series().diff() == pd.Timedelta("1min")]
    return 1.4826 * (dx - dx.median()).abs().median() / np.sqrt(2)
