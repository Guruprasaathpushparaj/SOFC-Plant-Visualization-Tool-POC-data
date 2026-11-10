"""Ladder logic for the operating stage, scanned once per minute.

Inputs are the plant signals only (stack temperature, gas/air flows, stack inlet
pressure, string current, EAPH heater power). Like a PLC, every scan sees only
the present minute and the past: no look-ahead, no context rules over future
blocks. Rungs are tested top to bottom and the first one that closes drives its
output coil; when none closes, the last output is held (seal-in).

Thresholds are those of operating_states.py so the two can be compared.
"""

import numpy as np
import operating_states as ops
import pandas as pd

# ---- timers (minutes) ----
TON_GAS, TOF_FG, TOF_NG = 2, 10, 3  # gas on-delay; forming-gas gaps ≤ 10 min bridged
TON_AIR, TOF_AIR = 2, 5
TON_HEAT, TOF_HEAT = 2, 15  # heater thermostat pauses ≤ 15 min bridged
TON_LOAD = ops.MIN_LOAD_MIN  # 3 min of current before it counts as load
SLOPE_MIN = 20  # trailing window for dT/dt (a PLC can't look ahead)
T_COLD_RESET = ops.T_HOT  # 450 °C: below this the "been hot" memory resets

OUT_FILTER_MIN = 10  # a new output must hold this long before it is shown
FAST_RUNGS = (
    "R01",
    "R02",
    "R03",
    "R04",
)  # data gap, load and fuel switch on the minute, unfiltered

# ---- output coils: (stage as used today, ladder name) ----
# Ladder names marked NEW have no exact counterpart in today's stage list,
# because naming them today needs the future (see the notes in scan()).
Y = {
    "R01": ("No data", "No data"),
    "R02": ("Rated power", "Rated power"),
    "R03": ("Part load", "Load on"),
    "R04": ("Hot standby", "Fuel on, waiting for load"),
    "R05a": ("Hot standby", "Hot hold"),
    "R05b": ("Start-up", "Warm hold"),  # NEW: becomes Hot hold once it has lasted 6 h
    "R06": (ops.ADJUST, "Re-heat"),
    "R07": (ops.ADJUST, "Cool-back, heater on"),
    "R08a": ("Start-up", "Heat-up in air"),
    "R08b": ("Start-up", "Heat-up under forming gas"),
    "R09": ("Heater only", "Heater only"),  # NEW: today Shut-down, false start
    "R10": ("Shut-down", "Cool-down under forming gas"),
    "R11a": ("Start-up", "Air purge"),
    "R11b": ("Shut-down", "Cool-down in air"),
    "R12": ("Shut-down", "Cold, plant off"),
    "R13": ("Shut-down", "Cooling, plant off"),
    "R14": ("Idle", "Warm, plant off"),  # NEW: Idle, or a heat-up paused overnight
    "HOLD": (None, None),  # no rung closed: keep the last output
}


def ton(x, n):
    """On-delay timer: true once x has been true for n consecutive scans."""
    run = (x != x.shift()).cumsum()
    return x & (x.groupby(run).cumcount() + 1 >= n)


def tof(x, n):
    """Off-delay timer: stays true for n scans after x drops."""
    return x.astype(float).rolling(n + 1, min_periods=1).max().astype(bool)


def contacts(s):
    """Boolean input contacts, one column per contact, from the 1-min signals."""
    s = s.asfreq("1min")
    T = s["T_stack_C"]
    dT = (T - T.shift(SLOPE_MIN)) * 60 / SLOPE_MIN
    c = pd.DataFrame(index=s.index)
    c["DATA"] = T.notna()
    c["LOAD"] = ton((s["I_string_A"] >= ops.I_LOAD).fillna(False), TON_LOAD)
    c["RATED"] = (s["I_string_A"] >= ops.I_RATED).fillna(False)
    c["NG"] = tof(ton((s["F_NG"] > ops.NG_ON).fillna(False), TON_GAS), TOF_NG)
    c["FG"] = tof(
        ton(((s["F_N2"] > ops.N2_ON) & (s["F_H2"] > ops.H2_ON)).fillna(False), TON_GAS),
        TOF_FG,
    )
    c["AIR"] = tof(
        ton(
            ((s["F_air"] > ops.AIR_FLOW_ON) | (s["P_air_in"] > ops.AIR_ON)).fillna(
                False
            ),
            TON_AIR,
        ),
        TOF_AIR,
    )
    c["HEAT"] = tof(
        ton((s["P_EAPH_kW"] * 1000 > ops.EAPH_ON_W).fillna(False), TON_HEAT), TOF_HEAT
    )
    c["HOT"] = T >= ops.T_STANDBY
    c["BAND"] = (T >= ops.T_HOT) & (T < ops.T_STANDBY)
    c["AMB"] = T <= s["T_amb_C"].fillna(ops.T_AMB_DEFAULT) + ops.DT_AMBIENT
    c["UP"] = dT > ops.DTDT_HEAT
    c["DOWN"] = dT < -ops.DTDT_HEAT
    c["STEADY"] = dT.abs() < ops.DTDT_STABLE
    c["COLD"] = T < T_COLD_RESET
    return c


def scan(c):
    """Run the rungs once per minute. Returns a frame with rung, stage, detail and \
memory bits."""
    cols = list(c.columns)
    A = c.to_numpy()
    k = {n: i for i, n in enumerate(cols)}
    n = len(A)
    rung = np.empty(n, dtype=object)
    m_hot = np.zeros(n, bool)
    m_sd = np.zeros(n, bool)
    m_su = np.zeros(n, bool)
    hold_t = np.zeros(n, int)
    HOT_M = SD_M = SU_M = (
        False  # memory bits (latched coils): been hot, shutting down, heat-up begun
    )
    hold = 0  # TON accumulator for a steady 450–550 °C hold
    last = "R01"
    for i in range(n):
        x = {name: A[i, j] for name, j in k.items()}
        steady_band = x["STEADY"] and x["BAND"] and (x["FG"] or x["HEAT"])
        hold = hold + 1 if steady_band else 0
        no_flow = not (x["FG"] or x["AIR"] or x["NG"])

        if not x["DATA"]:
            r = "R01"
        elif x["LOAD"] and x["RATED"]:
            r = "R02"
        elif x["LOAD"]:
            r = "R03"
        elif x["NG"]:
            r = "R04"
        elif x["STEADY"] and (x["HOT"] or x["BAND"]) and (x["FG"] or x["HEAT"]):
            r = "R05a" if (x["HOT"] or HOT_M or hold >= ops.MIN_HOLD_MIN) else "R05b"
        elif x["UP"] and HOT_M:
            r = "R06"
        elif x["DOWN"] and HOT_M and x["HEAT"]:
            r = "R07"
        elif x["HEAT"] and (x["AIR"] or x["FG"]) and not HOT_M:
            r = "R08b" if x["FG"] else "R08a"
        elif x["HEAT"] and no_flow:
            r = "R09"
        elif x["FG"] and not x["HEAT"]:
            r = "R10"
        elif x["AIR"] and not x["HEAT"] and not x["AMB"]:
            r = "R11b" if (SD_M or SU_M) else "R11a"
        elif x["AMB"] and no_flow and not x["HEAT"]:
            r = "R12"
        elif no_flow and not x["HEAT"] and SD_M:
            r = "R13"
        elif no_flow and not x["HEAT"]:
            r = "R14"
        else:
            r = "HOLD"
        if r == "HOLD":
            r = last
        # memory coils
        if r in ("R02", "R03", "R04", "R05a", "R06", "R07"):
            HOT_M = True
        if x["DATA"] and (x["COLD"] or x["AMB"]):
            HOT_M = False
        if r in ("R10", "R11b", "R13"):
            SD_M = True
        if r in ("R08a", "R08b", "R11a", "R12"):
            SD_M = False
        if r in ("R08a", "R08b"):
            SU_M = True
        if r in ("R05a", "R05b", "R12") or HOT_M:
            SU_M = False
        rung[i] = r
        m_hot[i] = HOT_M
        m_sd[i] = SD_M
        m_su[i] = SU_M
        hold_t[i] = hold
        if r != "R01":
            last = r
    out = pd.DataFrame(
        {"rung": rung, "M_HOT": m_hot, "M_SD": m_sd, "M_SU": m_su, "hold_min": hold_t},
        index=c.index,
    )
    out["stage"] = out["rung"].map(lambda r: Y[r][0])
    out["detail"] = out["rung"].map(lambda r: Y[r][1])
    return out


def output_filter(rung, n=OUT_FILTER_MIN):
    """A new rung output replaces the shown one only after it has closed for n scans \
in a row.

    Load, fuel and data-gap rungs (FAST_RUNGS) are sharp switches and pass straight \
through.
    """
    r = rung.to_numpy()
    out = r.copy()
    cur, cand, cnt = r[0], None, 0
    for i, x in enumerate(r):
        if x == cur:
            cand, cnt = None, 0
        elif x in FAST_RUNGS or cur in FAST_RUNGS:
            cur, cand, cnt = x, None, 0
        else:
            cnt = cnt + 1 if x == cand else 1
            cand = x
            if cnt >= n:
                cur, cand, cnt = x, None, 0
        out[i] = cur
    return pd.Series(out, index=rung.index)


def run(signals, filter_min=OUT_FILTER_MIN):
    """signals: 1-min frame from operating_states.load_signals, one or more days \
concatenated.

    Returns the contacts, memory bits, the raw rung of each scan (rung_raw) and
    the filtered rung with its stage and ladder name.
    """
    c = contacts(signals)
    out = scan(c).rename(
        columns={"rung": "rung_raw", "stage": "stage_raw", "detail": "name_raw"}
    )
    out["rung"] = (
        output_filter(out["rung_raw"], filter_min) if filter_min else out["rung_raw"]
    )
    out["stage"] = out["rung"].map(lambda r: Y[r][0])
    out["name"] = out["rung"].map(lambda r: Y[r][1])
    return pd.concat([c, out], axis=1)


if __name__ == "__main__":
    import contextlib
    import io

    days = sorted(p.name[:8] for p in ops.SRC.glob("*_10s.parquet"))
    with contextlib.redirect_stdout(io.StringIO()):
        sig = pd.concat([ops.load_signals(d) for d in days])
    res = run(sig)
    res.to_parquet(ops.OUT / "ladder_states.parquet")
    print(res["name"].value_counts().div(60).round(1).to_string())
