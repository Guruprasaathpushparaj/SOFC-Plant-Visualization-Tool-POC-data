"""Slope, bend and jerk calculations on the decided plant stages (all 39 day files).

Collects the calculations of 2026-11-03/04 that were run as loose scratchpad scripts, so they can be re-run
from the project data alone:

    1  stack_block_slopes   stack temperature slope (°C/h) of every stage block (line fit over the block)
    2  stack_rate_table     stack slope per stage x air level x 100 °C band (30-min centred rate)
       onset_lags           minutes from a stage start until the stack has moved 2 °C the right way
    3  heatup_runs          cold/warm start-ups: time to gas switch, 100/200/300/500 °C
       cooling_runs         air-flow cool-downs from > 400 °C: drop in the first 1 h / 3 h
    4  other_curve_slopes   heater and gas-path temperatures per stage (slope, first-30-min change, onset)
    5  all_column_slopes    every live logged column that changes inside a stage (units/h and % of range/h)
    6  border_table         every stage border: slope before/after (30-min fits), bend, step, peak speed,
                            acceleration and jerk within ±15 min, stack bend time (10 -> 90 %)
       border_type_curves   median curve -45..+60 min per border type, slope before/after, bend time
    7  stage_exits          leaving one stage (default Hot standby): slope 30 min / 1 h / 3 h after,
                            air level, hours to drop 50/100/200/300 °C

Definitions used throughout
    block      consecutive minutes with the same stage group and no logger gap > 2 min
    slope      least-squares line through the block (or window), in units per hour
    bend       slope after - slope before a border (each side a 30-min line fit)
    accel      change of the 1-min smoothed slope per minute (°C/h per min)
    jerk       change of accel per minute (°C/h per min²); peaks are taken within ±15 min of the border
    bend time  minutes for the 9-min smoothed slope to go from 10 % to 90 % of the way from the old to the
               new slope
    stage groups  as the plant stages, with Air-flow cooling split by air level (>= 7000 ln/min = strong);
               "Shutdown" blocks count only if the stack is still > 100 °C at the start (air-off cooling)

05_twin_2d/tools/bends.py imports border_table / border_type_curves from here (twin bend panel; app.js mirrors
border_shape for the twin's own borders). 05_twin_2d/tools/prep.py (minimum-jerk easing of sensor readings at stage changes).

Usage:
    python 03_data_analysis/scripts/slopes_jerk.py               # everything
    python 03_data_analysis/scripts/slopes_jerk.py stack borders # only some parts
    parts: stack, curves, other, columns, borders, exits;  --rebuild re-reads the raw day files
Writes to 03_data_analysis/slopes_jerk/.
"""
import contextlib
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import heater_temps as ht
import operating_states as ops
import plant_stages as ps

ROOT = ops.ROOT
OUT = ROOT / "03_data_analysis" / "slopes_jerk"
STAGE_FILE = ps.OUT / "plant_stages_1min.parquet"
FRAME_FILE = OUT / "frame_1min.parquet"
ALLCOL_FILE = OUT / "all_columns_1min.parquet"
RAW = ROOT / "02_data" / "parquet"
SENSOR_XLSX = ROOT / "01_docs" / "sensors displayed in the visualization tool - NEW.xlsx"

HEAT_AIR, HEAT_FG, HS, FS, PL, AFC, SD, PURGE = ps.STAGES
STRONG_AIR = 7000.0                 # ln/min: air-flow cooling at 8000-10000 vs normal 6000
AFC_NORMAL, AFC_STRONG = "Air-flow cooling, normal air", "Air-flow cooling, strong air"
GROUPS = [HEAT_AIR, HEAT_FG, HS, FS, PL, AFC_NORMAL, AFC_STRONG, SD, PURGE]
HOT_SHUTDOWN_C = 100.0              # Shutdown block counts only if it starts above this (air-off cooling)
ODD_HEATUP_C = 250.0                # Heat-up air block starting above this = 2026-03-22 odd block, skipped
BLOCK_GAP = pd.Timedelta("2min")    # logger gap that splits a stage block (not an episode)
BANDS = [0, 100, 200, 300, 400, 500, 600, 700]

# border analysis
FIT_W = 30          # min: line fit on each side of a border
CLEAN = 10          # min: each side must keep its stage this long for a "clean" border
CORE = 15           # min: peaks of speed, accel and jerk are searched within ±CORE
PRE, POST = 45, 60  # min: median curve window per border type
BORDER_SIGNALS = {"Stack T": "T_stack_C", "Heaters T": "T_heaters_C", "ERH T": "T_ERH_C",
                  "Cathode in T": "T_cathode_in_C", "Anode out T": "T_anode_out_C",
                  "Reformer out T": "T_reformer_out_C", "Air flow": "F_air", "N2 flow": "F_N2", "H2 flow": "F_H2",
                  "NG flow": "F_NG", "Current": "I_string_A", "Power": "P_stack_kW"}
TEMPS = {"Stack": "T_stack_C", "ERH": "T_ERH_C", "EAGH": "T_EAGH_C", "EAOH1": "T_EAOH1_C", "EAOH2": "T_EAOH2_C",
         "EAOH3": "T_EAOH3_C", "Cathode in": "T_cathode_in_C", "Reformer out": "T_reformer_out_C",
         "Anode out": "T_anode_out_C", "Recycle in": "T_recycle_in_C"}
# Note: F_NG is FIRC_14 (natural gas) as in operating_states.py.


# ---------------------------------------------------------------- data
def _days():
    return sorted(p.name[:8] for p in ops.SRC.glob("*_10s.parquet"))


def load_frame(rebuild=False):
    """1-min table: plant stages + stack, flows, current, power, heater and gas-path temperatures (39 days)."""
    if ops.stale(STAGE_FILE, *ps.RULE_SOURCES):
        ps.save()   # stage rules or inputs changed: relabel before anything reads the labels
    if not rebuild and not ops.stale(FRAME_FILE, STAGE_FILE, ht.__file__, ops.__file__, ops.SRC):
        return pd.read_parquet(FRAME_FILE)
    d = pd.read_parquet(STAGE_FILE)
    d.index = pd.to_datetime(d.index)
    extra = []
    for day in _days():
        with contextlib.redirect_stdout(io.StringIO()):
            s = ops.load_signals(day)[["P_stack_kW", "T_cathode_in_C"]]
        extra.append(s.join(ht.load_heaters(day)))
    e = pd.concat(extra)
    e = e[~e.index.duplicated()].reindex(d.index)
    d = d.join(e[[c for c in e if c not in d]])
    d["T_heaters_C"] = d[["T_EAGH_C", "T_EAOH1_C", "T_EAOH2_C"]].mean(axis=1)
    OUT.mkdir(parents=True, exist_ok=True)
    d.to_parquet(FRAME_FILE)
    return d


def load_all_columns(rebuild=False):
    """1-min means of every raw logger column (union over the day files)."""
    if not rebuild and not ops.stale(ALLCOL_FILE, RAW):
        return pd.read_parquet(ALLCOL_FILE)
    frames = []
    for f in sorted(RAW.glob("*.parquet")):
        x = pd.read_parquet(f)
        if x.empty:
            continue
        x = x.set_index("Date Time")
        frames.append(x.apply(pd.to_numeric, errors="coerce").astype("float32").resample("1min").mean())
    a = pd.concat(frames).sort_index()
    a = a[~a.index.duplicated()]
    a.columns = [str(c) for c in a.columns]
    OUT.mkdir(parents=True, exist_ok=True)
    a.to_parquet(ALLCOL_FILE)
    return a


# ---------------------------------------------------------------- helpers
def slope_group(d):
    """Plant stage per minute, Air-flow cooling split by air level."""
    g = d.plant_stage.astype(object).copy()
    afc = g == AFC
    g[afc & (d.F_air >= STRONG_AIR)] = AFC_STRONG
    g[afc & (d.F_air < STRONG_AIR)] = AFC_NORMAL
    return g


def block_ids(index, labels):
    """New block when the label changes or the log has a gap > 2 min."""
    gap = index.to_series().diff() > BLOCK_GAP
    return ((labels != labels.shift()) | gap).cumsum()


def stage_runs(d, labels, min_len=20, clean=True):
    """[(label, integer positions)] of every block. clean=True drops blocks that are not a real stage stretch:
    heat-up blocks starting at 00:00 (file cut), the odd hot Heat-up air block, cold Shutdown blocks."""
    out = []
    for _, idx in d.groupby(block_ids(d.index, labels).values).indices.items():
        s = labels.iloc[idx[0]]
        if s not in GROUPS + [AFC] or len(idx) < (5 if s == PURGE else min_len):     # skips "No data"
            continue
        if clean:
            t0, T0 = d.index[idx[0]], d.T_stack_C.iloc[idx[0]]
            if s in (HEAT_AIR, HEAT_FG) and t0.hour == 0 and t0.minute == 0:
                continue
            if s == HEAT_AIR and T0 > ODD_HEATUP_C:
                continue
            if s == SD and not T0 > HOT_SHUTDOWN_C:
                continue
        out.append((s, idx))
    return out


def line_slope(t_h, y):
    """Least-squares slope (units/h); NaN if fewer than 5 points."""
    ok = ~np.isnan(y)
    return np.polyfit(t_h[ok], y[ok], 1)[0] if ok.sum() >= 5 else np.nan


def window_slope(s, t0, t1):
    """Slope (units/h) of a time series between two timestamps."""
    x = s[t0:t1].dropna()
    if len(x) < 5:
        return np.nan
    return line_slope(((x.index - x.index[0]).total_seconds() / 3600).values, x.values)


def centred_rate(T, win=30):
    """°C/h from a centred difference over `win` minutes, NaN where the window is not continuous."""
    h = win // 2
    full = T.index.to_series().diff(win).eq(pd.Timedelta(minutes=win)).shift(-h, fill_value=False)
    r = (T.shift(-h) - T.shift(h)) * (60 / win)
    return r.where(full.values)


def band(T):
    return pd.cut(T, BANDS)


# ---------------------------------------------------------------- 1, 2  stack slopes
def stack_block_slopes(d):
    """One row per stage block (>= 20 min): line-fit slope, net slope, start/end T, air level."""
    g = slope_group(d)
    rows = []
    for s, idx in stage_runs(d, g, clean=False):
        x = d.iloc[idx]
        T = x.T_stack_C.values
        ok = ~np.isnan(T)
        if ok.sum() < 20:
            continue
        t = (x.index - x.index[0]).total_seconds().values / 3600
        rows.append(dict(group=s, stage=x.plant_stage.iloc[0], start=x.index[0], minutes=len(x),
                         T_start_C=T[ok][0], T_end_C=T[ok][-1], T_max_C=np.nanmax(T),
                         slope_fit_C_per_h=line_slope(t, T), slope_net_C_per_h=(T[ok][-1] - T[ok][0]) / (len(x) / 60),
                         air_median=x.F_air.median(), operation=x.operation.mode().iloc[0]))
    r = pd.DataFrame(rows)
    keep = {(s, d.index[i[0]]) for s, i in stage_runs(d, g)}
    r["clean"] = [(a, b) in keep for a, b in zip(r.group, r.start)]
    return r


def summarise_blocks(r):
    """Median / range of the stack block slope per stage group (clean blocks only)."""
    x = r[r.clean]
    t = x.groupby("group").slope_fit_C_per_h.agg(runs="count", median="median", low="min", high="max")
    return t.reindex([g for g in GROUPS if g in t.index]).round(1)


def stack_rate_table(d, min_minutes=30):
    """Median stack slope (30-min centred rate) per stage group x 100 °C band; cells with >= min_minutes."""
    x = d.assign(rate=centred_rate(d.T_stack_C), group=slope_group(d), band=band(d.T_stack_C))
    t = x.dropna(subset=["rate"]).groupby(["group", "band"], observed=True).rate.agg(["median", "count"])
    t = t[t["count"] >= min_minutes].reset_index()
    t = t[t.group.isin(GROUPS)]
    t["band"] = t.band.astype(str)
    t["group"] = pd.Categorical(t.group, GROUPS, ordered=True)
    return t.sort_values(["group", "band"]).round(1)


def onset_lags(d, cases=((HEAT_AIR, 1), (HEAT_FG, 1), (AFC, -1)), move=2.0, min_len=60):
    """Minutes from a stage start until the stack has moved `move` °C in the expected direction."""
    rows = []
    for s, sign in cases:
        for st, idx in stage_runs(d, d.plant_stage.astype(object), min_len=min_len):
            if st != s:
                continue
            x = d.T_stack_C.iloc[idx]
            t0 = x.index[0]
            if t0.hour == 0 and t0.minute == 0:
                continue
            mv = sign * (x - x.iloc[0]) >= move
            rows.append(dict(stage=s, start=t0, T_start_C=x.iloc[0], onset_min=int(mv.values.argmax()) if mv.any() else np.nan))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3  heat-up and cooling runs
def _cut_at_gap(g, t):
    jump = np.diff(t) > 0.1
    if jump.any():
        k = int(np.argmax(jump))
        return g.iloc[:k + 1], t[:k + 1]
    return g, t


def heatup_runs(d, levels=(100, 200, 300, 500)):
    """Each Heat-up air start followed until the plant leaves the heat-up stages (max 20 h).
    Returns (milestones table, {start: [[h, °C], ...] every 10 min})."""
    st = d.plant_stage
    rows, curves = [], {}
    for s in d.index[(st == HEAT_AIR) & (st.shift() != HEAT_AIR)]:
        g = d.loc[s:s + pd.Timedelta("20h")]
        out = ~g.plant_stage.isin([HEAT_AIR, HEAT_FG])
        if out.any():
            g = g.loc[:out.idxmax()]
        if len(g) < 120:
            continue
        g, t = _cut_at_gap(g, (g.index - s).total_seconds().values / 3600)
        T = g.T_stack_C.values
        fg = g.index[g.plant_stage == HEAT_FG]
        r = dict(start=s, T_start_C=T[0], hours=t[-1], T_end_C=T[-1],
                 h_to_gas_switch=(fg[0] - s).total_seconds() / 3600 if len(fg) else np.nan,
                 slope_C_per_h=line_slope(t, T))
        for lvl in levels:
            hit = np.where(T >= lvl)[0]
            r[f"h_to_{lvl}C"] = t[hit[0]] if len(hit) and T[0] < lvl - 20 else np.nan
        rows.append(r)
        curves[str(s)] = [[round(t[i], 2), round(float(T[i]), 1)] for i in range(0, len(g), 10)]
    return pd.DataFrame(rows), curves


def cooling_runs(d, min_start_C=400):
    """Each Air-flow cooling start above min_start_C followed while it lasts (max 12 h)."""
    st = d.plant_stage
    rows, curves = [], {}
    for s in d.index[(st == AFC) & (st.shift() != AFC)]:
        g = d.loc[s:s + pd.Timedelta("12h")]
        out = g.plant_stage != AFC
        if out.any():
            g = g.loc[:out.idxmax()]
        if len(g) < 60 or g.T_stack_C.iloc[0] < min_start_C:
            continue
        g, t = _cut_at_gap(g, (g.index - s).total_seconds().values / 3600)
        T = g.T_stack_C.values
        rows.append(dict(start=s, T_start_C=T[0], air=g.F_air.median(), hours=t[-1], T_end_C=T[-1],
                         slope_C_per_h=line_slope(t, T),
                         drop_first_h_C=T[0] - T[min(60, len(T) - 1)],
                         drop_3h_C=T[0] - T[180] if len(T) > 180 else np.nan))
        curves[str(s)] = [[round(t[i], 2), round(float(T[i]), 1)] for i in range(0, len(g), 10)]
    return pd.DataFrame(rows), curves


# ---------------------------------------------------------------- 4  heater / gas-path curves
def other_curve_slopes(d, groups=(HEAT_AIR, HEAT_FG, HS, AFC_NORMAL, AFC_STRONG, SD), min_len=60):
    """Per block (>= 60 min): slope, change in the first 30 min and onset (2 °C move) of every temperature in TEMPS.
    Returns (per-block table, summary: median/min/max per group x curve)."""
    lab = slope_group(d)
    rows = []
    for s, idx in stage_runs(d, lab, min_len=min_len):
        if s not in groups:
            continue
        g = d.iloc[idx]
        t = (g.index - g.index[0]).total_seconds().values / 3600
        sign = -1 if s in (AFC_NORMAL, AFC_STRONG, SD) else 1
        for name, c in TEMPS.items():
            y = g[c].values.astype(float)
            ok = ~np.isnan(y)
            if ok.sum() < 40:
                continue
            y0 = y[ok][0]
            mv = sign * (y - y0) >= 2
            rows.append(dict(group=s, start=g.index[0], minutes=len(g), curve=name, slope_C_per_h=line_slope(t, y),
                             change_first_30min_C=np.nanmean(y[25:35]) - y0 if len(y) > 35 else np.nan,
                             onset_min=int(np.argmax(mv)) if mv.any() else np.nan))
    r = pd.DataFrame(rows)
    summ = (r.groupby(["group", "curve"])
            .agg(runs=("slope_C_per_h", "count"), median=("slope_C_per_h", "median"), low=("slope_C_per_h", "min"),
                 high=("slope_C_per_h", "max"), change_first_30min=("change_first_30min_C", "median"),
                 onset_min=("onset_min", "median")).reset_index())
    summ["group"] = pd.Categorical(summ.group, GROUPS, ordered=True)
    summ["curve"] = pd.Categorical(summ.curve, list(TEMPS), ordered=True)
    return r, summ.sort_values(["group", "curve"]).round(1)


# ---------------------------------------------------------------- 5  every logged column
def column_kind(c):
    if re.match(r"B\d_", c):
        return "insulation monitor"
    if re.search(r"SetVal|_SP_|Setp|TargetValue|SetPoint|SetV_", c):
        return "command/setpoint"
    if re.search(r"Enable|bool|BOOL|State|Status|Alarm|Toggle|Error|Aktiv", c, re.I):
        return "status/bit"
    if re.search(r"_OUT_|OutputValue|SO_|_DO_", c):
        return "controller output"
    return "measurement"


def column_area(c, kind):
    """Plant area and unit of a logged column."""
    u = c.replace("pi_", "").replace("PLC_hostSetp_", "").replace("hostSetp_", "")
    if kind == "command/setpoint": return "Commands & setpoints", ""
    if kind == "controller output": return "Controller outputs", "%"
    if kind == "insulation monitor": return "Insulation monitors", "see name"
    if re.match(r"TIR_4_6_|TIR_4_1$", u): return "Stack temperatures", "°C"
    if re.match(r"TotalVoltage|String_\d_ActMinVoltage|EIR_4_|EIRC_4\d", u): return "Stack electrical", "V / A / W"
    if re.match(r"EIRC_2_01|IIR_", u):
        return ("Heater power controller", "°C") if "DeviceTemp" in u else ("Heater power controller", "V / A / W / %")
    if re.match(r"TIRZ_", u): return "Safety temperatures", "°C"
    if re.match(r"TIR_1_", u): return "Supply temperatures (air, gas)", "°C"
    if re.match(r"TIRC?_|ct_TIRC|PLC_ctrl_ct_FIRC_113|ctrl_ct_Reformer", u): return "Heater & gas-path temperatures", "°C"
    if re.match(r"PLC_pv_r(ActAfsr|ActPox|FU_|RejectionRatio)", u): return "Fuel control values (PLC)", ""
    if re.match(r"PIR|PT02|PLC_pv_r(PressEjector|DeltaPressEjec)", u): return "Pressures", "bar / mbar"
    if re.match(r".*FIR|.*FI_", u): return "Flows", "ln/min"
    if re.match(r"QIR", u): return "Gas analysis", "%"
    return "Other", ""


DROP_COLS = re.compile(r"OpMode|bOffStatus|ModulWithMinVoltage|CycleCounter|Alarm|TestStatus", re.I)
NOISE_COLS = {"PLC_ctrl_ct_FIRC_113_OUT_Analog"}       # old PLC copy, noise only


def sensor_descriptions(columns):
    """{column: (tag, property, measurement, group)} from the Excel sensor list, if it is there."""
    if not SENSOR_XLSX.exists():
        return {}
    xl = pd.read_excel(SENSOR_XLSX, sheet_name="Sensor list", header=3)
    xl = xl[xl["Name in the dataset"].notna()]
    out = {}
    for _, r in xl.iterrows():
        for n in re.split(r"[,;\s]+", str(r["Name in the dataset"])):
            if n in columns and n not in out:
                out[n] = (str(r["Sensor tag"]), str(r["What it measures (property)"]), str(r["Measurement"]),
                          str(r["Group"]) if pd.notna(r["Group"]) else "")
    return out


def all_column_slopes(d, X, move_pct=2.0):
    """Slope of every live logged column in every clean stage block, then median over blocks.
    A column 'changes with time' if, in at least one stage group, it moves more than move_pct % of its full range
    (5-95 % spread inside the block). Returns (long table: column x group, column info)."""
    X = X.reindex(d.index)
    cols = []
    for c in X.columns:
        v = X[c].to_numpy(dtype="float64")
        ok = ~np.isnan(v)
        if ok.mean() < 0.05 or column_kind(c) == "status/bit" or DROP_COLS.search(c) or c in NOISE_COLS:
            continue
        vv = v[ok]
        if len(np.unique(np.round(vv, 6))) > 2 and np.std(vv) > 0:
            cols.append(c)
    V = X[cols].to_numpy(dtype="float64", copy=True)
    V[np.abs(V) > 1e7] = np.nan                         # logger junk (e.g. 1e34 heater-controller resistance)
    lo, hi = np.nanpercentile(V, 0.5, axis=0), np.nanpercentile(V, 99.5, axis=0)
    full = np.nanmax(V, 0) - np.nanmin(V, 0)
    span = np.where(hi - lo > 0, hi - lo, full)          # 0.5-99.5 % spread; signals that are almost always one value use the full range
    span[span == 0] = np.nan
    rows = []
    for s, idx in stage_runs(d, slope_group(d)):
        t = (idx - idx[0]) / 60.0
        Y = V[idx]
        ok = ~np.isnan(Y)
        tm = np.where(ok, t[:, None], np.nan)
        tc, yc = tm - np.nanmean(tm, 0), Y - np.nanmean(Y, 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            slope = np.nansum(tc * yc, 0) / np.nansum(tc * tc, 0)
            mv = np.nanpercentile(Y, 95, 0) - np.nanpercentile(Y, 5, 0)
        slope[ok.sum(0) < 0.8 * len(idx)] = np.nan
        rows.append(pd.DataFrame(dict(group=s, start=d.index[idx[0]], col=cols, slope=slope, move=mv)))
    B = pd.concat(rows)
    g = B.groupby(["col", "group"])
    L = g.slope.agg(median_per_h="median", low="min", high="max", runs="count").join(g.move.median().rename("move"))
    L = L.reset_index()
    L["span"] = L.col.map(dict(zip(cols, span)))
    L["pct_of_range_per_h"] = 100 * L.median_per_h / L.span
    L.loc[L.pct_of_range_per_h.abs() > 2000, "pct_of_range_per_h"] = np.nan    # range too small to scale
    L["moves"] = L.move > move_pct / 100 * L.span
    changing = L.groupby("col").moves.any()
    desc = sensor_descriptions(set(cols))
    info = pd.DataFrame({"col": cols, "span": span})
    info["kind"] = info.col.map(column_kind)
    info["area"], info["unit"] = zip(*[column_area(c, k) for c, k in zip(info.col, info.kind)])
    for i, k in enumerate(("tag", "property", "measurement", "sensor_group")):
        info[k] = info.col.map(lambda c, i=i: desc.get(c, ("", "", "", ""))[i])
    info["changes"] = info.col.map(changing).fillna(False)
    L = L[L.col.isin(changing[changing].index)].merge(info.drop(columns="span"), on="col")
    return L, info


# ---------------------------------------------------------------- 6  stage borders: bend and jerk
def _smooth(v, n):
    return pd.Series(v).rolling(n, center=True, min_periods=3).mean().values


def border_shape(y, tm):
    """y: 1-min values on minutes tm (0 = border). Slope before/after (units/h, 30-min fits), step (mean +5..+15 min
    minus mean -15..-5 min), and peak |speed| (units/h), |accel| (units/h per min), |jerk| (units/h per min²)
    within ±15 min, with the minute of the accel peak."""
    pre, post = (tm >= -FIT_W) & (tm < 0), (tm >= 0) & (tm < FIT_W)
    sm = pd.Series(y).rolling(5, center=True, min_periods=3).median().rolling(5, center=True, min_periods=3).mean().values
    v = np.gradient(sm) * 60
    acc = np.gradient(_smooth(v, 5))
    jrk = np.gradient(_smooth(acc, 5))
    core = (tm >= -CORE) & (tm < CORE)
    s1, s2 = line_slope(tm[pre] / 60, y[pre]), line_slope(tm[post] / 60, y[post])
    k = np.nanargmax(np.abs(acc[core]))
    return dict(before=s1, after=s2, bend=s2 - s1,
                step=np.nanmean(y[(tm >= 5) & (tm < 15)]) - np.nanmean(y[(tm >= -15) & (tm < -5)]),
                speed_max=float(np.nanmax(np.abs(v[core]))), accel_max=float(np.nanmax(np.abs(acc[core]))),
                accel_at_min=int(tm[core][k]), jerk_max=float(np.nanmax(np.abs(jrk[core]))))


def bend_time(slope, i, pre=(-25, -5), post=(25, 45), min_change=5.0):
    """Stack bend time at border position i: minutes for the 9-min smoothed slope (°C/h) to go 10 % -> 90 % of the
    way from the old slope (median -25..-5 min) to the new one (median +25..+45 min). NaN if the change < 5 °C/h."""
    a = np.nanmedian(slope[i + pre[0]:i + pre[1]])
    b = np.nanmedian(slope[i + post[0]:i + post[1]])
    ch = b - a
    if not np.isfinite(ch) or abs(ch) < min_change:
        return np.nan
    w = (slope[i - 10:i + 60] - a) / ch
    if not (w >= 0.9).any():
        return np.nan
    return float(np.argmax(w >= 0.9) - np.argmax(w >= 0.1))


def _grid(d):
    full = pd.date_range(d.index[0], d.index[-1], freq="1min")
    return full, d.reindex(full)


def border_table(d):
    """One row per stage border x signal (borders with ±40 min of stack data). `clean` = both sides last >= 10 min."""
    full, x = _grid(d)
    st = x.plant_stage.where(x.plant_stage != "No data")
    stack_slope = _smooth(np.diff(_smooth(x.T_stack_C.values, 9), prepend=np.nan), 9) * 60
    tm = np.arange(-FIT_W - 10, FIT_W + 10)
    rows = []
    for t in st.index[st.ne(st.shift()) & st.notna() & st.shift().notna()]:
        i = full.get_loc(t)
        if i < FIT_W + 10 or i + FIT_W + 10 > len(full):
            continue
        win = x.iloc[i - FIT_W - 10:i + FIT_W + 10]
        if win.T_stack_C.isna().sum() > 5:
            continue                                     # file gap at the border
        a, b = st.iloc[i - 1], st.iloc[i]
        clean = not ((st.iloc[i - CLEAN:i] != a).any() or (st.iloc[i:i + CLEAN] != b).any())
        bt = bend_time(stack_slope, i) if i + 60 <= len(full) else np.nan
        for name, c in BORDER_SIGNALS.items():
            if c not in win:
                continue
            y = win[c].astype(float).interpolate(limit=5).values
            if np.isnan(y).sum() > 5:
                continue
            rows.append(dict(time=t, frm=a, to=b, clean=clean, signal=name, **border_shape(y, tm),
                             stack_bend_time_min=bt if name == "Stack T" else np.nan))
    return pd.DataFrame(rows)


def border_type_curves(d, signals=("T_stack_C", "T_heaters_C", "T_anode_out_C", "F_air", "F_H2", "F_NG", "I_string_A")):
    """Per border type (clean borders): median curve -45..+60 min (temperatures as change from the border value),
    slope before/after (30-min fits on the median curve), bend time 10 -> 90 % (temperatures, change > 5 °C/h)."""
    full, x = _grid(d)
    st = x.plant_stage.where(x.plant_stage != "No data")
    tm = np.arange(-PRE, POST + 1)
    types = {}
    for t in st.index[st.ne(st.shift()) & st.notna() & st.shift().notna()]:
        i = full.get_loc(t)
        if i < PRE or i + POST >= len(full):
            continue
        a, b = st.iloc[i - 1], st.iloc[i]
        if (st.iloc[i - CLEAN:i] != a).any() or (st.iloc[i:i + CLEAN] != b).any():
            continue
        types.setdefault((a, b), []).append(i)
    rows, curves = [], {}
    for (a, b), idx in types.items():
        for c in signals:
            M = []
            for i in idx:
                y = x[c].iloc[i - PRE:i + POST + 1].astype(float).interpolate(limit=5).values
                if np.isnan(y).sum() < 5:
                    M.append(y - (y[PRE] if c.startswith("T_") else 0))
            if not M:
                continue
            m = np.nanmedian(np.array(M), axis=0)
            v = np.gradient(_smooth(m, 9)) * 60
            pre = line_slope(tm[PRE - FIT_W:PRE] / 60, m[PRE - FIT_W:PRE])
            post = line_slope(tm[PRE:PRE + FIT_W] / 60, m[PRE:PRE + FIT_W])
            t10 = t90 = np.nan
            if c.startswith("T_") and abs(post - pre) > 5:
                f = (v - pre) / (post - pre)
                zone = (tm >= -20) & (tm <= 40)
                if (f[zone] >= 0.9).any():
                    t10, t90 = tm[zone][np.argmax(f[zone] >= 0.1)], tm[zone][np.argmax(f[zone] >= 0.9)]
            rows.append(dict(frm=a, to=b, borders=len(M), signal=c, before=pre, after=post, bend=post - pre,
                             bend_t10_min=t10, bend_t90_min=t90, bend_time_min=t90 - t10))
            curves.setdefault(f"{a} > {b}", {})[c] = [None if np.isnan(z) else round(float(z), 2) for z in m]
    return pd.DataFrame(rows), dict(minutes=tm.tolist(), curves=curves)


# ---------------------------------------------------------------- 7  leaving a stage
def stage_exits(d, frm=HS, skip_to=(FS,), windows=(30, 60, 180), drops=(50, 100, 200, 300)):
    """Every exit from stage `frm` (default Hot standby) to another stage (Fuel switch skipped: that is the way to load).
    Slope before (last hour) and after (first 30 min / 1 h / 3 h), air level, hours until the stack has dropped
    50/100/200/300 °C (within 48 h), the next block's length and slope, and whether it is a real cool-down
    (stack below the start after 1 h and the next stage lasts >= 20 min)."""
    b = ps.blocks(d)
    T, A = d.T_stack_C, d.F_air
    rows = []
    for i in range(len(b) - 1):
        cur, nxt = b.iloc[i], b.iloc[i + 1]
        if cur.stage != frm or nxt.stage in skip_to:
            continue
        t = pd.Timestamp(nxt.start)
        T0 = T.asof(t)
        r = dict(time=t, to=nxt.stage, next_minutes=nxt.minutes, T_start_C=T0,
                 slope_last_1h=window_slope(T, t - pd.Timedelta("60min"), t))
        for w in windows:
            r[f"slope_first_{w}min"] = window_slope(T, t, t + pd.Timedelta(minutes=w))
        for h in (0, 1, 2, 4):
            r[f"air_h{h}"] = A[t + pd.Timedelta(hours=h):t + pd.Timedelta(hours=h + 1)].median()
        seg = T[t:t + pd.Timedelta("48h")]
        for dr in drops:
            hit = seg[seg <= T0 - dr]
            r[f"h_to_drop_{dr}C"] = (hit.index[0] - t).total_seconds() / 3600 if len(hit) else np.nan
        r["next_stage_slope"] = window_slope(T, t, pd.Timestamp(nxt.end))
        r["real_cooldown"] = bool(nxt.minutes >= 20 and T.asof(t + pd.Timedelta("60min")) < T0 - 5)
        rows.append(r)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- run
PARTS = ("stack", "curves", "other", "columns", "borders", "exits")


def run_all(parts=PARTS, rebuild=False):
    OUT.mkdir(parents=True, exist_ok=True)
    d = load_frame(rebuild)
    print("frame", d.shape)
    if "stack" in parts:
        r = stack_block_slopes(d)
        r.to_csv(OUT / "stack_block_slopes.csv", index=False)
        s = summarise_blocks(r)
        s.to_csv(OUT / "stack_slope_summary.csv")
        stack_rate_table(d).to_csv(OUT / "stack_rate_by_band.csv", index=False)
        o = onset_lags(d)
        o.to_csv(OUT / "stack_onset_lags.csv", index=False)
        print("\nStack slope per stage (°C/h, clean blocks)\n", s.to_string())
        print("\nOnset (min, median)", o.groupby("stage").onset_min.median().round(0).to_dict())
    if "curves" in parts:
        h, hc = heatup_runs(d)
        c, cc = cooling_runs(d)
        h.to_csv(OUT / "heatup_runs.csv", index=False)
        c.to_csv(OUT / "cooling_runs.csv", index=False)
        json.dump(dict(heatup=hc, cooling=cc), open(OUT / "run_curves.json", "w", encoding="utf-8"))
        print(f"\nHeat-up runs {len(h)}; cold starts (< 50 °C):",
              h[h.T_start_C < 50][["h_to_gas_switch", "h_to_300C", "h_to_500C"]].median().round(1).to_dict())
        print("Cooling runs", len(c), "first-hour drop median", round(c.drop_first_h_C.median(), 1), "°C")
    if "other" in parts:
        r, s = other_curve_slopes(d)
        r.to_csv(OUT / "temperature_block_slopes.csv", index=False)
        s.to_csv(OUT / "temperature_slope_summary.csv", index=False)
        print("\nHeater / gas-path slopes (°C/h, median)\n",
              s.pivot(index="curve", columns="group", values="median").to_string())
    if "columns" in parts:
        L, info = all_column_slopes(d, load_all_columns(rebuild))
        L.to_csv(OUT / "all_column_slopes_long.csv", index=False)
        info.to_csv(OUT / "all_column_info.csv", index=False)
        try:
            with pd.ExcelWriter(OUT / "all_column_slopes.xlsx") as w:
                L.pivot_table(index=["area", "col"], columns="group", values="median_per_h").to_excel(w, sheet_name="units per h")
                L.pivot_table(index=["area", "col"], columns="group",
                              values="pct_of_range_per_h").to_excel(w, sheet_name="pct of range per h")
                L.to_excel(w, sheet_name="long", index=False)
        except ImportError:
            pass
        print(f"\nColumns: {len(info)} live, {int(info.changes.sum())} change inside a stage")
    if "borders" in parts:
        bt = border_table(d)
        bt.to_csv(OUT / "border_bends.csv", index=False)
        ty, curves = border_type_curves(d)
        ty.to_csv(OUT / "border_type_bends.csv", index=False)
        json.dump(curves, open(OUT / "border_type_curves.json", "w", encoding="utf-8"), ensure_ascii=False)
        st = bt[(bt.signal == "Stack T") & bt.clean]
        print(f"\nBorders {bt.time.nunique()} ({st.time.nunique()} clean). Stack °C/h before -> after (median, clean):")
        print(st.groupby(["frm", "to"]).agg(n=("bend", "size"), before=("before", "median"), after=("after", "median"),
                                            bend_time=("stack_bend_time_min", "median")).round(1).to_string())
    if "exits" in parts:
        e = stage_exits(d)
        e.to_csv(OUT / "hot_standby_exits.csv", index=False)
        print("\nHot standby exits\n", e.round(1).to_string(index=False) if len(e) else "none")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run_all(tuple(args) or PARTS, rebuild="--rebuild" in sys.argv)
