"""Segment one day of SOFC data into operating stages and operations.

Rules follow operational-modes.md §1 (stage detection criteria) and §3/§4
(sub-steps within each stage). Usage:

    python 03_data_analysis/scripts/operating_states.py 20251030

Writes to 03_data_analysis/operating_states/:
    <day>_states_1min.csv   one row per minute, with stage + operation
    <day>_segments.csv      one row per contiguous (stage, operation) block
    <day>_states.png        timeline plot
"""
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "02_data" / "downsampled"
OUT = ROOT / "03_data_analysis" / "operating_states"

# --- thresholds (operational-modes.md §1, §4) ---
I_LOAD = 1.0            # A per string: below = no load
I_RATED = 28.5          # A per string: ≈ 30 A nominal (95 %)
DTDT_HEAT = 10.0        # °C/h: heat-up / cool-down threshold
DTDT_STABLE = 5.0       # °C/h: stable threshold for Hot standby
T_HOT = 450.0           # °C: Hot standby lower bound
T_STANDBY = 550.0       # °C: below = intermediate hold (part of Start-up), §4.3
DIDT_RAMP = 0.05        # A/min: load ramp threshold, §4.4
EAPH_ON_W = 200.0       # W: EAPH heater considered on (off-state noise < 50 W)
AIR_ON = 1.0            # PIR_2_02 stack inlet pressure: air flow on
MIN_SEG_MIN = 15        # merge blocks shorter than this into neighbours
MIN_LOAD_MIN = 3        # min: current must last this long to count as load
MAX_PAUSE_MIN = 180     # min: heater pause inside a start-up, not a shut-down
MIN_HOLD_MIN = 360      # min: steady 450–550 °C hold this long = Hot standby, not Start-up
MAX_GAP_DAYS = 7        # days: a Shut-down tail is followed across missing day files (cooling τ ≈ 89 h)
DT_AMBIENT = 30.0       # K: stack within this of ambient, plant off = shut down (near ambient)
T_AMB_DEFAULT = 16.0    # °C: ambient when the proxy probes have no reading (median of the data)
# No true ambient sensor: the fuel-module supply-line probes sit on cold pipes and
# stay near room temperature whatever the stack does (cold_idle_analysis.ipynb §1).
AMB_COLS = ["TIR_1_1_1", "TIR_1_2_1", "TIR_1_3", "TIR_1_4_1"]
LOW_HOLD = "Low-temperature hold (~510 °C)"
AT_AMBIENT = "Plant off at ambient"
TAIL = "Natural cooling (air off)"
# Hot standby is a constant temperature only (user decision 2026-10-14): with no
# load, a rise or fall of a hot stack is the Thermal adjustment stage (user
# decision 2026-10-14, later), since Start-up only follows a Shut-down and Part
# load only follows Hot standby. Re-heats and cool-backs are first labelled
# Start-up / Shut-down so the context rules can see them, then moved by
# thermal_adjustment().
ADJUST = "Thermal adjustment"
REHEAT = "Re-heat (no load)"
COOL_BACK = "Cool-back (no load)"
REHEAT_OPS = (REHEAT, "Re-heat to operating temperature", "Re-heat to hold")
COOL_BACK_OPS = (COOL_BACK, "Temperature dip during hold")
PRE_LOAD = "Pre-load (ready for load)"
PAUSED = "Heat-up interrupted (plant off)"
# Gas and air supply (user decision 2026-10-15: use the other sensors for
# sub-phases and fixes; the six stages and the stage map stay). Mass-flow
# controllers: FIRC_13 N2 and FIRC_15 H2 (forming gas, 1200 + 60 ln/min),
# FIRC_14 natural gas (FIRC_12 is POx air, not gas), FIRC_111/112 cathode air blowers.
N2_ON = 100.0           # ln/min FIRC_13
H2_ON = 5.0             # ln/min FIRC_15
NG_ON = 20.0            # ln/min FIRC_14
AIR_FLOW_ON = 100.0     # ln/min FIRC_111 + FIRC_112
GAS_GAP_MIN = 10        # min: supply gap this short inside one gas state is bridged
GAS_BLIP_MIN = 3        # min: any gas state shorter than this takes its neighbours' state
PH_OFF, PH_AIR, PH_FORMING, PH_N2, PH_NG = \
    "Plant off", "Air only", "Forming gas (N2 + H2)", "N2 purge", "Natural gas"
PHASES = [PH_OFF, PH_AIR, PH_FORMING, PH_N2, PH_NG]
FUEL_SWITCH = "Fuel switch-over (NG on, no load)"
FALSE_START = "Heater on without air (false start)"
STAGES = ["Idle", "Start-up", "Hot standby", ADJUST, "Part load", "Rated power", "Shut-down"]


def num(d, cols):
    return d[cols].apply(pd.to_numeric, errors="coerce")


def stale(out, *sources):
    """True when saved file `out` is missing or older than any source (a file, or the files in a folder)."""
    if not out.exists():
        return True
    t = out.stat().st_mtime
    files = (f for s in map(Path, sources) for f in (s.iterdir() if s.is_dir() else [s]))
    return any(f.is_file() and f.stat().st_mtime > t for f in files)


def load_signals(day):
    d = pd.read_parquet(SRC / f"{day}_10s.parquet")
    d.index = pd.to_datetime(d.pop("Date Time"))

    st = [c for c in d.columns if c.startswith("TIR_4_6_")]
    t = num(d, st)
    # drop fill values (-1 °C) and broken/saturated thermocouples (e.g. 1300 °C)
    t = t.where((t > 0) & (t < 1000))
    # Drop thermocouples that sit far from the module median all day
    # (e.g. TIR_4_6_25 reading ambient while the stack is at 150 °C).
    dev = (t.sub(t.median(axis=1), axis=0)).abs().median()
    bad = dev[(dev > 75) | t.isna().all()].index.tolist()
    if bad:
        print(f"Excluded stack thermocouples: {sorted(bad + [c for c in st if c not in t.columns])}")
    t = t.drop(columns=bad)

    # String current and voltage from the PLC monitor columns: present on every
    # day and unaffected by the mid-day column shift that corrupts the
    # EIRC_4X_* columns (e.g. 2026-03-20 from ~11:00, OpMode = 150).
    cur = num(d, [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rCurrMonitor" for i in range(1, 6)]).clip(lower=0)
    v = num(d, [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rVoltMonitor" for i in range(1, 6)]).clip(lower=0)
    p_stack = pd.Series((v.values * cur.values).sum(axis=1) / 1000.0, index=d.index)

    s = pd.DataFrame({
        "T_stack_C": t.median(axis=1),
        "T_stack_min_C": t.min(axis=1),
        "T_stack_max_C": t.max(axis=1),
        "I_string_A": cur.sum(axis=1) / 5,
        "P_stack_kW": p_stack,
        "P_EAPH_kW": num(d, ["EIRC_2_01_ActV_In_ThreePhasePower"]).iloc[:, 0] / 1000,
        "T_cathode_in_C": num(d, ["TIRC_2_06"]).iloc[:, 0],
        "P_air_in": num(d, ["PIR_2_02"]).iloc[:, 0],
        "T_amb_C": num(d, AMB_COLS).where(lambda a: (a != -1) & (a < 60)).median(axis=1),
        "F_N2": num(d, ["ct_FIRC_13_PV_ProcessValue"]).iloc[:, 0],
        "F_H2": num(d, ["ct_FIRC_15_PV_ProcessValue"]).iloc[:, 0],
        "F_NG": num(d, ["ct_FIRC_14_PV_ProcessValue"]).iloc[:, 0],
        "F_air": num(d, ["ct_FIRC_111_PV_ProcessValue", "ct_FIRC_112_PV_ProcessValue"]).sum(axis=1, min_count=1),
    })
    s = s.resample("1min").mean()
    s["T_amb_C"] = s["T_amb_C"].rolling(60, center=True, min_periods=1).median().fillna(T_AMB_DEFAULT)
    # 1-hour centred difference for reported rates (§4.1); a 20-min centred
    # difference for classification so stage boundaries are not smeared.
    T = s["T_stack_C"]
    s["dTdt_C_per_h"] = (T.shift(-30) - T.shift(30))
    s["dTdt_20min_C_per_h"] = ((T.shift(-10) - T.shift(10)) * 3).fillna(
        T.diff(5).rolling(5, center=True, min_periods=1).mean() * 12)
    s["dIdt_A_per_min"] = (s["I_string_A"].shift(-2) - s["I_string_A"].shift(2)) / 4
    # Load = current above I_LOAD for at least MIN_LOAD_MIN consecutive minutes;
    # shorter blips (e.g. 1 min at 1.15 A on 2026-03-04) are not a load stage.
    on = s["I_string_A"] >= I_LOAD
    run = (on != on.shift()).cumsum()
    s["load_on"] = on & (run.map(run.value_counts()) >= MIN_LOAD_MIN)
    return s


def steady_hold(s):
    return ~s["load_on"] & s["T_stack_C"].between(T_HOT, T_STANDBY, inclusive="neither") \
        & (s["dTdt_20min_C_per_h"].abs() < DTDT_STABLE)


def long_hold(day, s):
    """Minutes inside a steady 450–550 °C hold lasting ≥ MIN_HOLD_MIN.

    Holds often span midnight (2026-01-31 → 02-04), so the run length is
    measured over the neighbouring calendar-day files too. Breaks shorter than
    MIN_SEG_MIN inside a hold, and logger gaps of any length, are bridged.
    """
    import contextlib
    import io
    parts = [s]
    for off in (-1, 1):
        d = (pd.Timestamp(day) + pd.Timedelta(days=off)).strftime("%Y%m%d")
        if (SRC / f"{d}_10s.parquet").exists():
            with contextlib.redirect_stdout(io.StringIO()):
                parts.append(load_signals(d))
    a = pd.concat(parts).sort_index()
    h = steady_hold(a)
    # minutes known to break the hold (logger gaps and their blank slope edges do not)
    breaks = ~h & a[["T_stack_C", "dTdt_20min_C_per_h"]].notna().all(axis=1)
    run = (h != h.shift()).cumsum()
    runs = pd.DataFrame({"hold": h.groupby(run).first(), "breaks": breaks.groupby(run).sum()})
    gap = ~runs["hold"] & (runs["breaks"] < MIN_SEG_MIN) \
        & runs["hold"].shift(1, fill_value=False) & runs["hold"].shift(-1, fill_value=False)
    h = h | run.map(gap)
    run = (h != h.shift()).cumsum()
    long = h & (run.map(run.value_counts()) >= MIN_HOLD_MIN)
    return long.reindex(s.index, fill_value=False)


def classify_row(r):
    T, dT, I, dI = r.T_stack_C, r.dTdt_20min_C_per_h, r.I_string_A, r.dIdt_A_per_min
    air_on = r.P_air_in > AIR_ON
    # The heater only heats the stack with air flowing through it; heater power
    # with the blowers off is not a heat-up (2026-02-06, ~0.4 kW all afternoon).
    eaph_on = r.P_EAPH_kW * 1000 > EAPH_ON_W and (air_on or r.F_air > AIR_FLOW_ON)

    if pd.isna(T):
        return "No data", "Logger gap"
    if r.load_on:
        stage = "Rated power" if I >= I_RATED else "Part load"
        if dI > DIDT_RAMP:
            op = "Load ramp-up"
        elif dI < -DIDT_RAMP:
            op = "Load ramp-down"
        else:
            op = "Steady load"
        return stage, op

    # Steady 450–550 °C: a long hold (e.g. 2026-02-01…03 at ~510 °C for days,
    # heater trimming) is the plant parked hot = Hot standby; a short one is
    # the Start-up intermediate hold (§4.3). Checked before the heater rule,
    # because the EAPH stays on to hold the temperature.
    if r.long_hold:
        return "Hot standby", LOW_HOLD
    if T_HOT < T < T_STANDBY and abs(dT) < DTDT_STABLE:
        return "Start-up", "Intermediate hold (~510 °C)"
    # Heater on below the operating window = active heat-up, whatever the
    # momentary slope (the stack lags the EAPH ramp by tens of minutes).
    if eaph_on and T < T_STANDBY and dT > -DTDT_HEAT:
        return "Start-up", "Heat-up (EAPH on)"
    if air_on and not eaph_on and T < T_HOT and dT > -DTDT_HEAT and dT < DTDT_HEAT:
        return "Shut-down", "Cool-down (air flow on)"  # re-labelled by apply_context
    if dT > DTDT_HEAT:
        if T >= T_STANDBY:
            return "Start-up", "Final heat-up to Hot standby"
        return "Start-up", "Heat-up (EAPH on)" if eaph_on else "Heat-up (EAPH off)"
    if dT < -DTDT_HEAT:
        return "Shut-down", "Cool-down (air flow on)" if air_on else "Cool-down (natural)"
    if T >= T_STANDBY and abs(dT) < DTDT_STABLE:
        return "Hot standby", "Temperature hold"
    if T > T_HOT:  # drifting 5–10 °C/h: not constant, so not Hot standby
        return ("Shut-down", "Slow cool-down") if dT < 0 else ("Start-up", "Slow heat-up")
    # Plant off (no current, heater off, air off, slow drift). Near ambient the
    # plant is shut down; a warm stack is Idle, or the natural-cooling tail of a
    # Shut-down (re-labelled by apply_context when a Shut-down comes before it).
    if T <= r.T_amb_C + DT_AMBIENT:
        return "Shut-down", AT_AMBIENT
    return "Idle", ("Natural cooling (heater off, no air)" if dT < -0.5 else "Stable / settling")


def gas_phase(s):
    """Supply state of each minute from the gas and air flow controllers.

    Natural gas (or load) > forming gas (N2 + H2) > N2 only (purge) > air only >
    plant off. A gap of up to GAS_GAP_MIN in the forming-gas or natural-gas
    supply (e.g. 2026-03-24/25, 1–10 min with no flow) is bridged, and any state
    shorter than GAS_BLIP_MIN takes the state on both sides of it.
    """
    air = (s["F_air"] > AIR_FLOW_ON) | (s["P_air_in"] > AIR_ON)
    n2, h2, ng = s["F_N2"] > N2_ON, s["F_H2"] > H2_ON, s["F_NG"] > NG_ON
    ph = pd.Series(np.select([ng | s["load_on"], n2 & h2, n2, air], [PH_NG, PH_FORMING, PH_N2, PH_AIR], PH_OFF),
                   index=s.index)
    for limit, gap_states in ((GAS_GAP_MIN, (PH_OFF, PH_AIR, PH_N2)), (GAS_BLIP_MIN - 1, tuple(PHASES))):
        for _ in range(3):
            run = (ph != ph.shift()).cumsum()
            r = ph.groupby(run).agg(state="first", n="size")
            prv, nxt = r["state"].shift(), r["state"].shift(-1)
            fill = (r["n"] <= limit) & r["state"].isin(gap_states) & (prv == nxt) & prv.notna()
            if limit == GAS_GAP_MIN:
                fill &= prv.isin([PH_FORMING, PH_NG])
            if not fill.any():
                break
            ph = run.map(prv.where(fill)).fillna(ph)
    return ph.where(s["T_stack_C"].notna(), "")


def fuel_rules(s):
    """Natural-gas rules (user decision 2026-10-15).

    The no-load natural-gas minutes that run straight into load are Hot standby
    pre-load (fuel switched over, ready for load). Natural gas on without load
    following, in Hot standby or Thermal adjustment, is operation Fuel
    switch-over (e.g. 2026-03-04, 03-19, 03-30), inside its stage.
    """
    ng = (s["phase"] == PH_NG) & ~s["load_on"]
    run = (ng != ng.shift()).cumsum()
    for k in run[ng].unique():
        idx = s.index[run == k]
        nxt = s.index[s.index > idx[-1]]
        if len(nxt) and s.at[nxt[0], "load_on"] and s.loc[idx, "stage"].isin(["Hot standby", ADJUST]).all():
            s.loc[idx, ["stage", "operation"]] = ["Hot standby", PRE_LOAD]
    sw = ng & s["stage"].isin(["Hot standby", ADJUST]) & (s["operation"] != PRE_LOAD)
    s.loc[sw, "operation"] = FUEL_SWITCH
    # a sliver shorter than GAS_BLIP_MIN left between two operations of the same
    # no-load stage takes the operation of its longer same-stage neighbour
    b = blocks(s)
    seg = s.groupby(b).agg(stage=("stage", "first"), op=("operation", "first"), n=("stage", "size"))
    ids = list(seg.index)
    for i, k in enumerate(ids):
        if seg.at[k, "n"] >= GAS_BLIP_MIN or seg.at[k, "stage"] not in ("Hot standby", ADJUST):
            continue
        nb = [j for j in (ids[i - 1] if i else None, ids[i + 1] if i + 1 < len(ids) else None)
              if j is not None and seg.at[j, "stage"] == seg.at[k, "stage"]]
        if nb:
            j = max(nb, key=lambda j: seg.at[j, "n"])
            s.loc[b == k, "operation"] = seg.at[j, "op"]
    return s


def ng_tail(s, idx):
    """Trailing natural-gas minutes of a block (empty when it ends without NG)."""
    ng = (s.loc[idx, "phase"] == PH_NG).to_numpy()
    n = len(ng) - (np.flatnonzero(~ng)[-1] + 1) if (~ng).any() else len(ng)
    return idx[len(idx) - n:]


def plant_off_cold(stage, op):
    """Idle, or shut down at ambient: the plant is off and nothing runs."""
    return stage == "Idle" or op == AT_AMBIENT


def blocks(s):
    key = s["stage"] + " | " + s["operation"]
    return (key != key.shift()).cumsum()


def merge_short(s):
    """Absorb blocks shorter than MIN_SEG_MIN into the preceding block.

    Merging never crosses a load / no-load edge: minutes with current flowing
    stay load minutes even when the load pulse is short (e.g. 2026-03-19).
    """
    run = (s["load_on"] != s["load_on"].shift()).cumsum()
    for _ in range(5):
        b = blocks(s)
        size = b.map(b.value_counts())
        short = size < MIN_SEG_MIN
        if not short.any():
            break
        lab = s[["stage", "operation"]].where(~short)
        prev = lab.groupby(run).ffill()
        prev = prev.fillna(lab.groupby(run).bfill())
        fill = short & prev["stage"].notna()
        if not fill.any():
            break
        s.loc[fill, ["stage", "operation"]] = prev.loc[fill].values
    return s


def apply_context(s, prev_stage=None):
    """Context rules that a single row cannot see.

    prev_stage is the last stage of the previous day file, so a Shut-down tail
    that crosses midnight stays Shut-down.
    """
    # Cooling that levels off inside the operating window (e.g. after a load
    # pause) stays Shut-down, since Hot standby is a constant temperature only,
    # but is marked as a cool-back, not a cool-down towards room temperature.
    b = blocks(s)
    for k in b[s["stage"] == "Shut-down"].unique():
        idx = s.index[b == k]
        if s.loc[idx[-1], "T_stack_C"] >= T_STANDBY:
            s.loc[idx, "operation"] = COOL_BACK
    # Heater on during a cool-down without net warming = heater-controlled
    # cool-down (e.g. 2026-03-20 evening, ~9 kW at ~290 °C), not a new start-up.
    b = blocks(s)
    prv_st = prv_op = None
    for k in b.unique():
        idx = s.index[b == k]
        st, op = s.loc[idx[0], ["stage", "operation"]]
        T0, T1 = s.loc[idx, "T_stack_C"].dropna().iloc[[0, -1]] if s.loc[idx, "T_stack_C"].notna().any() else (0, 0)
        if st == "Start-up" and prv_st == "Shut-down" and prv_op != AT_AMBIENT and T1 < T0 + 5:
            s.loc[idx, ["stage", "operation"]] = ["Shut-down", "Controlled cool-down (heater trim)"]
            st, op = "Shut-down", "Controlled cool-down (heater trim)"
        if st != "No data":
            prv_st, prv_op = st, op
    b = blocks(s)
    seg = s.groupby(b).agg(stage=("stage", "first"), op=("operation", "first"),
                           start=("stage", lambda x: x.index[0]))
    seg_ids = list(seg.index)
    reached_hot = False
    for i, k in enumerate(seg_ids):
        st = seg.at[k, "stage"]
        # A ~510 °C low-temperature hold is below the operating window: the
        # heat-up that follows it is still a Start-up, not a re-heat.
        if st in ("Hot standby", "Part load", "Rated power") and seg.at[k, "op"] != LOW_HOLD:
            reached_hot = True
        nxt = seg.at[seg_ids[i + 1], "stage"] if i + 1 < len(seg_ids) else None
        # Warming after the stack has already been hot (between load periods) is
        # a Start-up re-heat, not a new Start-up from cold.
        if st == "Start-up" and reached_hot:
            s.loc[b == k, "operation"] = REHEAT
        # Temperature rising with the heater off right after a cool-down is not a
        # start-up (no EAPH); seen on 2026-03-30, a leakage symptom per §6.6.
        elif st == "Start-up" and seg.at[k, "op"] == "Heat-up (EAPH off)" and i > 0 \
                and seg.at[seg_ids[i - 1], "stage"] == "Shut-down" and seg.at[seg_ids[i - 1], "op"] != AT_AMBIENT:
            s.loc[b == k, ["stage", "operation"]] = ["Shut-down", "Temperature rise, heater off"]
            st = "Shut-down"
        # Cooling with air on, right before an EAPH heat-up and with no load or
        # Hot standby since the plant was last off = start-up purge, not shut-down.
        prv = seg.at[seg_ids[i - 1], "stage"] if i > 0 else None
        prv_off = prv in (None, "No data") or plant_off_cold(prv, seg.at[seg_ids[i - 1], "op"])
        if st == "Shut-down" and not reached_hot and nxt == "Start-up" and prv_off \
                and seg.at[k, "op"].startswith("Cool-down") and seg.at[k, "op"] != COOL_BACK:
            s.loc[b == k, ["stage", "operation"]] = ["Start-up", "Air flow start (purge, heater off)"]
        # Load dropping to zero right before cool-down = Shut-down step 1 (§3.3)
        if st in ("Part load", "Rated power") and seg.at[k, "op"] == "Load ramp-down" \
                and nxt == "Shut-down":
            s.loc[b == k, ["stage", "operation"]] = ["Shut-down", "Load ramp-down to zero"]
        # Heat-up that stops below Hot standby = aborted start-up
        if st == "Idle" and i > 0 and seg.at[seg_ids[i - 1], "stage"] == "Start-up" \
                and not reached_hot:
            s.loc[b == k, "operation"] = "Heat-up stopped - settling / natural cooling"
        # a cool-back to Hot standby leaves the stack hot
        if st == "Idle" or (st == "Shut-down" and seg.at[k, "op"] != COOL_BACK):
            reached_hot = False

    # A Shut-down episode sandwiched between Start-up and Start-up / Hot standby
    # is part of the same start-up, not a separate shut-down: either a dip with
    # the EAPH still on (e.g. 2026-03-23 13:18–14:12 at ~20 kW) or a heater
    # pause of up to MAX_PAUSE_MIN (e.g. 2025-11-13 16:19–17:04). Not for a
    # cool-back between two re-heats of a hot stack.
    st = s["stage"]
    ep = (st != st.shift()).cumsum()
    eps = list(ep.unique())
    for i in range(1, len(eps) - 1):
        idx = s.index[ep == eps[i]]
        if st.loc[idx[0]] != "Shut-down" or (s.loc[idx, "operation"] == COOL_BACK).any() \
                or (s.loc[ep == eps[i - 1], "operation"] == REHEAT).any():
            continue
        prv = st[ep == eps[i - 1]].iloc[0]
        nxt = st[ep == eps[i + 1]].iloc[0]
        heater_on = (s.loc[idx, "P_EAPH_kW"] * 1000 > EAPH_ON_W).mean() > 0.5
        if prv == "Start-up" and nxt in ("Start-up", "Hot standby"):
            if heater_on:
                s.loc[idx, ["stage", "operation"]] = ["Start-up", "Temperature dip during heat-up (heater on)"]
            elif len(idx) <= MAX_PAUSE_MIN:
                s.loc[idx, ["stage", "operation"]] = ["Start-up", "Heat-up paused (heater off)"]

    # A short excursion between two low-temperature holds (e.g. 2026-02-02
    # 13:46, dip to 492 °C and back with the heater on): the fall is Shut-down,
    # the climb back Start-up, as Hot standby is a constant temperature only.
    b = blocks(s)
    seg = s.groupby(b).agg(stage=("stage", "first"), op=("operation", "first"),
                           T_max=("T_stack_C", "max"), load=("load_on", "any"), n=("stage", "size"))
    ids = list(seg.index)
    holds = [i for i, k in enumerate(ids) if seg.at[k, "op"] == LOW_HOLD]
    for a, z in zip(holds, holds[1:]):
        mid = ids[a + 1:z]
        if mid and not seg.loc[mid, "load"].any() and seg.loc[mid, "T_max"].max() < T_STANDBY \
                and seg.loc[mid, "n"].sum() <= MAX_PAUSE_MIN:
            for k in mid:
                warming = s.loc[b == k, "dTdt_20min_C_per_h"].mean() > 0
                s.loc[b == k, ["stage", "operation"]] = \
                    ["Start-up", "Re-heat to hold"] if warming else ["Shut-down", "Temperature dip during hold"]

    # The climb from a low-temperature hold to the operating window (e.g.
    # 2026-03-03 511 → 576 °C) is a Start-up re-heat, and a cool-down from Hot
    # standby that levels off in a low-temperature hold (2026-01-31 570 → 520 °C)
    # is a Shut-down cool-back, not a cool-down towards room temperature.
    b = blocks(s)
    seg = s.groupby(b).agg(stage=("stage", "first"), op=("operation", "first"))
    seg = seg[seg["stage"] != "No data"]
    ids = list(seg.index)
    after_hold = False
    for i, k in enumerate(ids):
        st, op = seg.at[k, "stage"], seg.at[k, "op"]
        if op == LOW_HOLD:
            after_hold = True
        elif st == "Start-up" and after_hold:
            s.loc[b == k, "operation"] = "Re-heat to operating temperature"
        else:
            after_hold = False
    st = s["stage"].where(s["stage"] != "No data").ffill()
    ep = (st != st.shift()).cumsum()
    eps = list(ep.unique())
    for i in range(1, len(eps) - 1):
        idx = s.index[(ep == eps[i]) & (s["stage"] != "No data")]
        nxt = s.index[ep == eps[i + 1]][0]
        if st.loc[idx[0]] == "Shut-down" and st[ep == eps[i - 1]].iloc[0] == "Hot standby" \
                and s.at[nxt, "operation"] == LOW_HOLD:
            s.loc[idx, "operation"] = COOL_BACK

    # A warm, plant-off stack right after a Shut-down is its natural-cooling tail
    # (operational-modes.md §1): Shut-down lasts until the stack is near ambient.
    # Only a warm stack with no Shut-down before it stays Idle (e.g. 2025-10-30,
    # or cooling after a heat-up that stopped below Hot standby).
    st = s["stage"].where(s["stage"] != "No data").ffill()
    ep = (st != st.shift()).cumsum()
    prv = prev_stage
    for e in ep.unique():
        cur = st[ep == e].iloc[0]
        if pd.isna(cur):
            continue
        if cur == "Idle" and prv == "Shut-down":
            s.loc[(ep == e) & (s["stage"] == "Idle"), ["stage", "operation"]] = ["Shut-down", TAIL]
            cur = "Shut-down"
        prv = cur
    return s


def restarts_next_day(day):
    """True when the next calendar-day file starts with the plant still off and
    the stack still warm, and the plant then comes back without load (a heat-up
    stopped overnight, e.g. 2026-03-17 → 18)."""
    import contextlib
    import io
    nxt = (pd.Timestamp(day) + pd.Timedelta(days=1)).strftime("%Y%m%d")
    if not (SRC / f"{nxt}_10s.parquet").exists():
        return False
    with contextlib.redirect_stdout(io.StringIO()):
        a = load_signals(nxt)
    active = a["load_on"] | (a["P_EAPH_kW"] * 1000 > EAPH_ON_W) | (a["P_air_in"] > AIR_ON)
    if not active.any():
        return False
    first = active.idxmax()
    before = a.loc[:first].iloc[:-1]
    warm = (before["T_stack_C"] > before["T_amb_C"] + DT_AMBIENT).all()
    return bool(warm and not a.at[first, "load_on"])


def thermal_adjustment(s, day, prev_stage=None):
    """Final stage rules (user decisions 2026-10-14, later).

    - A re-heat or cool-back of a hot stack with no load is Thermal adjustment.
      A cool-back that runs straight into a cool-down is the start of that
      Shut-down, and a load ramp-down into a Thermal adjustment stays load.
    - Part load only follows Hot standby: the last MIN_SEG_MIN minutes of a
      Thermal adjustment right before load are Hot standby, pre-load (the whole
      block when it is shorter than twice that).
    - Start-up only follows a Shut-down: an Idle stretch between two parts of a
      heat-up (heat-up stopped, plant off, heat-up resumed) is that Start-up,
      interrupted (user confirmed 2026-10-14 for 2026-03-17/18). Other Idle
      stays Idle (2025-10-30).
    """
    adj = s["operation"].isin(REHEAT_OPS + COOL_BACK_OPS)
    s.loc[adj, "stage"] = ADJUST

    def labelled_blocks():
        b = blocks(s)
        v = s["stage"] != "No data"
        seg = s[v].groupby(b[v]).agg(stage=("stage", "first"), op=("operation", "first"))
        return b, seg, list(seg.index)

    b, seg, ids = labelled_blocks()
    nxt_stage = None
    for k in reversed(ids):
        st, op = seg.at[k, "stage"], seg.at[k, "op"]
        if st == ADJUST and op in COOL_BACK_OPS and nxt_stage == "Shut-down":
            idx = s.index[b == k]
            air = (s.loc[idx, "P_air_in"] > AIR_ON).mean() > 0.5
            s.loc[idx, ["stage", "operation"]] = ["Shut-down", "Cool-down (air flow on)" if air else "Cool-down (natural)"]
            st = "Shut-down"
        elif st == "Shut-down" and op == "Load ramp-down to zero" and nxt_stage == ADJUST:
            idx = s.index[b == k]
            load = "Rated power" if s.loc[idx, "I_string_A"].max() >= I_RATED else "Part load"
            s.loc[idx, ["stage", "operation"]] = [load, "Load ramp-down"]
            st = load
        nxt_stage = st

    b, seg, ids = labelled_blocks()
    for i, k in enumerate(ids[:-1]):
        if seg.at[k, "stage"] == ADJUST and seg.at[ids[i + 1], "stage"] in ("Part load", "Rated power"):
            idx = s.index[b == k]
            # pre-load = natural gas on until load starts; without a fuel
            # switch-over in the data, the last MIN_SEG_MIN minutes
            tail = ng_tail(s, idx)
            if not len(tail):
                tail = idx if len(idx) < 2 * MIN_SEG_MIN else idx[-MIN_SEG_MIN:]
            s.loc[tail, ["stage", "operation"]] = ["Hot standby", PRE_LOAD]

    st = s["stage"].where(s["stage"] != "No data").ffill()
    ep = (st != st.shift()).cumsum()
    eps = [e for e in ep.unique() if st[ep == e].notna().any()]
    for i, e in enumerate(eps):
        if st[ep == e].iloc[0] != "Idle":
            continue
        prv = st[ep == eps[i - 1]].iloc[0] if i > 0 else prev_stage
        nxt = st[ep == eps[i + 1]].iloc[0] if i + 1 < len(eps) else \
            ("Start-up" if restarts_next_day(day) else None)
        if prv == "Start-up" and nxt == "Start-up":
            s.loc[(ep == e) & (s["stage"] == "Idle"), ["stage", "operation"]] = ["Start-up", PAUSED]
    return s


SD_COOLING = "Cooling"
SD_AMBIENT = "At ambient (plant off)"


def sub_stage(stage, op):
    """Shut-down sub-name (user decision 2026-10-14): Cooling (load to zero,
    forced or natural cooling, stack still warm) or At ambient (plant off,
    within DT_AMBIENT of ambient, waiting for the next Start-up). Empty for
    other stages."""
    return pd.Series(np.where(stage != "Shut-down", "",
                              np.where(op == AT_AMBIENT, SD_AMBIENT, SD_COOLING)), index=stage.index)


def prev_day(day):
    """Latest earlier day file within MAX_GAP_DAYS (days can be missing), or None."""
    for n in range(1, MAX_GAP_DAYS + 1):
        d = (pd.Timestamp(day) - pd.Timedelta(days=n)).strftime("%Y%m%d")
        if (SRC / f"{d}_10s.parquet").exists():
            return d
    return None


@lru_cache(maxsize=None)
def last_stage(day):
    """Stage at the end of a day file (None without a file), for rules that cross midnight."""
    if day is None:
        return None
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        st = segment(day)[0]["stage"]
    st = st[st != "No data"]
    return st.iloc[-1] if len(st) else last_stage(prev_day(day))


def segment(day):
    s = load_signals(day)
    s["phase"] = gas_phase(s)
    s["long_hold"] = long_hold(day, s)
    lab = s.apply(classify_row, axis=1, result_type="expand")
    s["stage"], s["operation"] = lab[0], lab[1]
    s = merge_short(s)
    s = apply_context(s, last_stage(prev_day(day)))
    s = merge_short(s)
    # A heat-up block ends at the last minute the EAPH is on; the tail that
    # merge_short absorbed takes the label of the following block.
    eaph_on = s["P_EAPH_kW"] * 1000 > EAPH_ON_W
    b = blocks(s)
    for k in b[s["operation"] == "Heat-up (EAPH on)"].unique():
        idx = s.index[b == k]
        on = idx[eaph_on.loc[idx].values]
        nxt = s.index[s.index > idx[-1]]
        if len(on) and len(nxt) and on[-1] < idx[-1]:
            tail = idx[idx > on[-1]]
            s.loc[tail, ["stage", "operation"]] = s.loc[nxt[0], ["stage", "operation"]].values
    s = thermal_adjustment(s, day, last_stage(prev_day(day)))
    s = fuel_rules(s)
    s["sub_stage"] = sub_stage(s["stage"], s["operation"])
    # Heater power with the blowers off while the plant is otherwise off
    # (2026-02-06): named, so it is not mistaken for a start-up.
    off = (s["P_EAPH_kW"] * 1000 > EAPH_ON_W) & (s["phase"] == PH_OFF) & ~s["load_on"] \
        & (s["stage"].isin(["Idle"]) | s["operation"].isin([AT_AMBIENT, TAIL]))
    gap = s["T_stack_C"].isna() & (s["stage"] != "No data") & off.shift().fillna(False).astype(bool)
    off = off | gap  # a lone logger-gap minute does not end it
    run = (off != off.shift()).cumsum()
    s.loc[off & (run.map(run.value_counts()) >= MIN_SEG_MIN), "operation"] = FALSE_START

    b = blocks(s)
    seg = s.groupby(b).agg(
        stage=("stage", "first"), sub_stage=("sub_stage", "first"), operation=("operation", "first"),
        phases=("phase", lambda x: " > ".join(v for v in dict.fromkeys(x) if v)),
        start=("T_stack_C", lambda x: x.index[0]),
        end=("T_stack_C", lambda x: x.index[-1] + pd.Timedelta("1min")),
        T_start_C=("T_stack_C", "first"), T_end_C=("T_stack_C", "last"),
        T_min_C=("T_stack_C", "min"), T_max_C=("T_stack_C", "max"),
        dTdt_mean_C_per_h=("dTdt_C_per_h", "mean"),
        I_max_A=("I_string_A", "max"), P_stack_max_kW=("P_stack_kW", "max"),
        P_EAPH_mean_kW=("P_EAPH_kW", "mean"), P_EAPH_max_kW=("P_EAPH_kW", "max"),
    ).reset_index(drop=True)
    seg[seg.select_dtypes("number").columns] = seg.select_dtypes("number").round(2)
    seg.insert(4, "duration_min", ((seg.end - seg.start).dt.total_seconds() / 60).astype(int))
    return s, seg


def count_episodes(s):
    """Number of separate times each stage occurs in one day's minute table.

    An episode is a contiguous run of minutes with the same stage (operations
    inside it are not counted separately). 'No data' gaps are skipped, so a
    stage interrupted only by a logger gap counts once. Episodes that cross
    midnight are counted on both days.
    """
    st = s["stage"][s["stage"] != "No data"]
    ep = (st != st.shift()).cumsum()
    return st.groupby(ep).first().value_counts().reindex(STAGES, fill_value=0)


def stage_minutes(s):
    return s["stage"].value_counts().reindex(STAGES + ["No data"], fill_value=0)


def segment_all(days=None):
    """Segment every day; returns {day: (states, segments)}."""
    days = days or sorted(p.name[:8] for p in SRC.glob("*_10s.parquet"))
    return {d: segment(d) for d in days}


# One clearly different hue per stage (Okabe-Ito, colour-blind safe): warming = orange,
# hot = vermilion, cooling = sky blue, load = green/blue. Signal lines in plot() stay neutral
# so they are never mistaken for a stage.
STAGE_COLORS = {"Idle": "#999999", "Start-up": "#E69F00", "Hot standby": "#D55E00", ADJUST: "#CC79A7",
                "Part load": "#009E73", "Rated power": "#0072B2", "Shut-down": "#56B4E9"}
STAGE_TINT = 0.22  # background shading behind the signal panels
# Flow lines (dark) and gas-phase band (light version of the same hue), kept apart from the stage hues.
GAS_COLORS = {"N2": "#1F3A93", "H2": "#C0392B", "NG": "#542788", "air": "#333333"}
PHASE_COLORS = {PH_OFF: "#FFFFFF", PH_AIR: "#D9D9D9", PH_FORMING: "#F2B8B0", PH_N2: "#A9B8E0", PH_NG: "#B2A1CF"}


def plot_flows(s, ax_fuel, ax_air, legend=True):
    """Anode-side flows (N2, NG left axis; H2 right axis) and cathode air, in ln/min."""
    c = GAS_COLORS
    ax_fuel.plot(s.index, s.F_N2, color=c["N2"], lw=1.1, label="N2  FIRC_13")
    ax_fuel.plot(s.index, s.F_NG, color=c["NG"], lw=1.1, label="Natural gas  FIRC_14")
    ax_fuel.set_ylabel("ln/min")
    h2 = ax_fuel.twinx()
    h2.plot(s.index, s.F_H2, color=c["H2"], lw=1.1, ls="--", label="H2  FIRC_15 (right axis)")
    h2.set_ylabel("H2 ln/min", color=c["H2"]); h2.set_ylim(0, max(100, s.F_H2.max() * 1.6))  # H2 sits lower than N2, not on top of it
    ax_fuel.set_ylim(0, max(1400, s[["F_N2", "F_NG"]].max().max() * 1.15))
    ax_air.plot(s.index, s.F_air, color=c["air"], lw=1.1, label="Cathode air  FIRC_111 + FIRC_112")
    ax_air.set_ylabel("ln/min"); ax_air.set_ylim(bottom=0)
    if legend:
        lines = ax_fuel.get_lines() + h2.get_lines()
        ax_fuel.legend(lines, [l.get_label() for l in lines], loc="upper left", fontsize=8, ncol=3)
        ax_air.legend(loc="upper left", fontsize=8)
    return h2


def phase_band(s, ax):
    """One coloured span per contiguous gas/air supply phase (column `phase`)."""
    ph = s["phase"]
    run = (ph != ph.shift()).cumsum()
    step = pd.Timedelta("1min")
    for _, g in ph.groupby(run):
        if g.iloc[0]:
            ax.axvspan(g.index[0], g.index[-1] + step, color=PHASE_COLORS[g.iloc[0]], lw=0)
    ax.set_yticks([])


def plot(day, s, seg, path=None):
    """Timeline figure. With a path it is saved and closed; without, it is returned (notebooks)."""
    import matplotlib.pyplot as plt
    colors = STAGE_COLORS
    fig, ax = plt.subplots(6, 1, figsize=(13, 12), sharex=True,
                           gridspec_kw={"height_ratios": [3, 2, 1.8, 1.3, 0.5, 0.5]})
    ax[0].plot(s.index, s.T_stack_C, color="k", lw=1.2, label="Stack T (median of valid TIR_4_6_* TCs)")
    ax[0].plot(s.index, s.T_cathode_in_C, color="#555555", lw=0.9, ls="--", label="Cathode inlet TIRC2.06")
    ax[0].set_ylabel("°C"); ax[0].legend(loc="upper left", fontsize=8)
    ax[1].plot(s.index, s.P_EAPH_kW, color="k", lw=1.1, label="EAPH heater power (kW)")
    ax[1].plot(s.index, s.P_stack_kW.fillna(0), color="#555555", lw=1, ls="--", label="Stack DC power (kW)")
    ax1b = ax[1].twinx()
    ax1b.plot(s.index, s.I_string_A, color="#888888", lw=0.8, ls=":", label="I per string (A)")
    ax1b.set_ylabel("A")
    ax[1].set_ylabel("kW"); ax[1].legend(loc="upper left", fontsize=8)
    plot_flows(s, ax[2], ax[3])
    for _, r in seg.iterrows():
        ax[4].axvspan(r.start, r.end, color=colors.get(r.stage, "#ccc"))
        for a in ax[:4]:
            a.axvspan(r.start, r.end, color=colors.get(r.stage, "#ccc"), alpha=STAGE_TINT, lw=0)
    ax[4].set_yticks([]); ax[4].set_ylabel("stage", rotation=0, ha="right", va="center", fontsize=9)
    phase_band(s, ax[5]); ax[5].set_ylabel("gas", rotation=0, ha="right", va="center", fontsize=9)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors.values()]
    handles.append(plt.Rectangle((0, 0), 1, 1, fc="white", ec="#999"))
    leg = ax[5].legend(handles, [*colors.keys(), "No data"], ncol=8, fontsize=8, loc="upper center",
                       bbox_to_anchor=(.5, -0.7), title="Stage", title_fontsize=8)
    ax[5].add_artist(leg)
    ax[5].legend([plt.Rectangle((0, 0), 1, 1, fc=c, ec="#999") for c in PHASE_COLORS.values()], PHASE_COLORS.keys(),
                 ncol=5, fontsize=8, loc="upper center", bbox_to_anchor=(.5, -2.0),
                 title="Gas / air supply (column phase)", title_fontsize=8)
    fig.suptitle(f"{day} — operating stages and gas / air supply")
    fig.tight_layout()
    if path is None:
        return fig
    fig.savefig(path, dpi=130); plt.close(fig)


if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    day = sys.argv[1] if len(sys.argv) > 1 else sorted(SRC.glob("*_10s.parquet"))[0].name[:8]
    OUT.mkdir(parents=True, exist_ok=True)
    s, seg = segment(day)
    s.to_csv(OUT / f"{day}_states_1min.csv", float_format="%.3f")
    seg.to_csv(OUT / f"{day}_segments.csv", index=False)
    plot(day, s, seg, OUT / f"{day}_states.png")
    pd.set_option("display.width", 250)
    print(seg[["stage", "operation", "start", "end", "duration_min", "T_start_C",
               "T_end_C", "dTdt_mean_C_per_h", "I_max_A", "P_EAPH_max_kW"]].to_string())
    print("\nMinutes per stage:\n", s.stage.value_counts().to_string())
