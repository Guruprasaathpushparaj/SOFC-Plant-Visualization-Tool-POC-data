"""Check the S-PLC trip conditions and find emergency shutdowns in the 1 s raw data.

Trip values follow component_sensor_map_en.md §4 (Safety Functions, S-PLC 0xB9E8,
2026-03-27). Emergency shutdowns are recognised by the actions the S-PLC takes
(§4.1 SPLC_EMERGENCYPURGE, §4.2 SPLC_EMERGENCYSTOP), since the logger has no
S-PLC state or trip-cause column. Usage from the notebook:

    import trip_check as tc
    margins = tc.trip_margins()        # one row per day: max/min of each trip sensor \
vs limit
    events = tc.cut_events()           # every abrupt cut of current / heater / gas, \
classified
    crossings = tc.exhaust_crossings(events)
"""

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "02_data" / "parquet"  # 1 s raw files

# --- trip conditions (component_sensor_map_en.md §4.1); each acts after > 50 ms ---
TEMP_TRIPS = {  # sensor: (component, trip above °C)
    "TIRZ_8_1_1": ("EAPH", 1050),
    "TIRZ_8_1_3": ("Stack module", 720),
    "TIRZ_8_1_9": ("Afterburner (TOX)", 930),
    "TIRZ_8_1_10": (
        "Exhaust outlet",
        None,
    ),  # limit changed over time, see exhaust_limit()
    "TIRZ_8_2_1": ("EAGH", 950),
    "TIRZ_8_2_2": ("EAOH1", 950),
    "TIRZ_8_2_3": ("EAOH2", 950),
    "TIRZ_8_2_4": ("EAOH3", 950),
    "TIRZ_8_2_5": ("ERH", 860),
}
P_TRIP = 0.750  # PIRZ_8_1_2 below this (bar a)
# BE s.1 below 2 kΩ; unit of the logged Riso column unresolved (CONFLICT-RISO-01)
RISO_TRIP = 2.0


def exhaust_limit(day):
    """Exhaust trip value in force on that day: 100 °C, 200 °C from 2026-01-28, 300 °C \
from 2026-03-27."""
    return 100 if day < "20260128" else (200 if day < "20260327" else 300)


# --- signals used to recognise the S-PLC actions ---
MV = [
    "MV_1_1_2_SetVal_1",
    "MV_1_1_3_SetVal_1",
    "MV_1_2_SetVal",
    "MV_1_3_2_SetVal",
    "MV_1_4_3_SetVal",
    "MV_1_4_4_SetVal",
    "MV_1_4_5_SetVal",
    "MV_1_5_3_SetVal",
]
MV_SHORT = ["1.1.2", "1.1.3", "1.2", "1.3.2", "1.4.3", "1.4.4", "1.4.5", "1.5.3"]
CUR = [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rCurrMonitor" for i in range(1, 6)]
RISO = [f"B{i}_0x1011_Riso/[Ohm]" for i in range(5)]
EAPH = "EIRC_2_01_ActV_In_ThreePhasePower"
AIR = "PIR_2_02"  # stack inlet air pressure: collapses when the compressor stops
T_ANODE_HOT = 400.0  # °C: an all-gas stop above this leaves a hot anode unprotected
CORRUPT_FROM = {"20260320": "11:00"}  # mid-day column shift (see operating_states.py)
P = pd.Timedelta


def days():
    return [p.stem for p in sorted(RAW.glob("*.parquet")) if p.stat().st_size > 0]


def load(day, cols):
    f = RAW / f"{day}.parquet"
    have = set(pq.read_schema(f).names)
    cols = list(dict.fromkeys(c for c in cols if c in have))
    d = pd.read_parquet(f, columns=["Date Time"] + cols)
    d.index = pd.to_datetime(d.pop("Date Time"))
    d = d[~d.index.duplicated()].apply(pd.to_numeric, errors="coerce")
    if day in CORRUPT_FROM:
        d = d.loc[: f"{day[:4]}-{day[4:6]}-{day[6:]} {CORRUPT_FROM[day]}"]
    return d


def trip_margins():
    """Per day: worst value of each trip sensor and its distance to the trip value."""
    rows = []
    for day in days():
        d = load(day, list(TEMP_TRIPS) + ["PIRZ_8_1_2", "TIRZ_8_1_3"] + RISO)
        valid = d["TIRZ_8_1_3"] > 0  # -1 = logger dropout, 0 = instruments off
        r = {"day": day}
        for c, (_, lim) in TEMP_TRIPS.items():
            lim = lim or exhaust_limit(day)
            x = d.loc[valid, c].where(lambda v: v > 0)
            r[c] = round(x.max(), 1)
            r[c + " margin"] = round(lim - x.max(), 1)
        p = d.loc[valid, "PIRZ_8_1_2"]
        r["PIRZ_8_1_2 min"] = round(p[p > 0].min(), 3)
        ri = d.loc[valid, [c for c in RISO if c in d]]
        r["Riso min (logged value)"] = (
            ri[ri > 0].min().min() if len(ri.columns) else None
        )
        rows.append(r)
    o = pd.DataFrame(rows).set_index("day")
    o.index = pd.to_datetime(o.index, format="%Y%m%d").date
    return o


def _valves(x):
    return "".join("?" if pd.isna(v) else str(int(round(v))) for v in x[MV].median())


def _classify(vb, va, I_b, H_b, H_a, air_b, air_a):
    """Match the valve / power change against the S-PLC actions in \
component_sensor_map_en.md §4."""
    supply_closed = va[0] == va[1] == va[2] == va[3] == va[4] == va[6] == va[7] == "0"
    if supply_closed and air_b > 5 and air_a < 1:
        if va[5] == "1":
            # all supply closed, only NG vent MV1.4.4 open, compressor off
            return "EMERGENCY STOP"
        # close to EMERGENCYSTOP, but MV1.4.4 stays shut
        return "All gas + compressor off (vent shut)"
    purge = va[0] == va[1] == va[3] == va[7] == "1" and va[2] == va[4] == "0"
    if purge and vb != va and (I_b > 1 or H_b > 5):
        if H_a < 0.2:
            # purge valves open, NG/POx closed, heater + stack cut
            return "EMERGENCY PURGE"
        # not the S-PLC pattern (heater would be cut)
        return "Gas to purge, heater kept on"
    if vb == va:
        return "Load / heater off, valves unchanged"
    return "Valve change only"


def cut_events(day_list=None):
    """Every abrupt cut of stack current, heater power, NG supply or compressor, \
classified."""
    rows = []
    for day in day_list or days():
        d = load(day, MV + CUR + list(TEMP_TRIPS) + [EAPH, AIR])
        current = d[CUR].clip(lower=0).mean(axis=1)
        H = d[EAPH] / 1000
        cand = (
            ((current.rolling(3).max().shift(1) > 2) & (current < 0.2))
            | ((H.rolling(3).max().shift(1) > 5) & (H < 0.2))
            | ((d[AIR].rolling(3).max().shift(1) > 5) & (d[AIR] < 1))
            | ((d["MV_1_4_3_SetVal"] == 0) & (d["MV_1_4_3_SetVal"].shift() == 1))
        )
        last = None
        for t in d.index[cand.fillna(False)]:
            if last is not None and t - last < P("60s"):
                continue
            last = t
            b, a = d.loc[t - P("20s") : t - P("2s")], d.loc[t + P("3s") : t + P("12s")]
            vb, va = _valves(b), _valves(a)
            if "?" in vb + va:
                continue
            kind = _classify(
                vb,
                va,
                current[b.index].mean(),
                H[b.index].mean(),
                H[a.index].mean(),
                b[AIR].mean(),
                a[AIR].mean(),
            )
            T = (
                b["TIRZ_8_1_3"].where(lambda v: v > 0).mean()
            )  # -1 dropout / 0 off would drag a hot stop below T_ANODE_HOT
            pre = d.loc[t - P("60s") : t]
            over = [
                f"{c} {pre[c].max():.0f} > {lim or exhaust_limit(day)}"
                for c, (_, lim) in TEMP_TRIPS.items()
                if pre[c].max() > (lim or exhaust_limit(day))
            ]
            # after an all-gas stop: how long until N2 or H2 purge is back
            gap = None
            if kind == "EMERGENCY STOP" or kind.startswith("All gas"):
                back = d.loc[t + P("2s") :]
                back = back[
                    (back["MV_1_3_2_SetVal"] == 1) | (back["MV_1_5_3_SetVal"] == 1)
                ]
                gap = (
                    round((back.index[0] - t).total_seconds() / 60, 1)
                    if len(back)
                    else None
                )
            if kind.startswith("Load / heater off") and over:
                kind = "Power cut at trip value, gas unchanged"
            if kind == "EMERGENCY STOP" and T < T_ANODE_HOT:
                kind = "EMERGENCY STOP (cold: end of cool-down)"
            rows.append(
                {
                    "time": t,
                    "kind": kind,
                    "valves before": vb,
                    "valves after": va,
                    "I string A": round(current[b.index].mean(), 1),
                    "EAPH kW": round(H[b.index].mean(), 1),
                    "air before→after": f"{b[AIR].mean():.1f}→{a[AIR].mean():.1f}",
                    "T stack °C": round(T) if pd.notna(T) else None,
                    "trip value exceeded (60 s before)": "; ".join(over) or "-",
                    "purge back after (min)": gap,
                }
            )
    return pd.DataFrame(rows)


def exhaust_crossings(events, day_list=None):
    """Each time TIRZ_8_1_10 first exceeds the limit in force, and what happened in \
the next 5 min."""
    ev = events.set_index("time").sort_index()
    rows = []
    for day in day_list or days():
        lim = exhaust_limit(day)
        d = load(day, ["TIRZ_8_1_10", EAPH] + CUR)
        running = (d[CUR].clip(lower=0).mean(axis=1) > 1) | (d[EAPH] > 5000)
        over = d["TIRZ_8_1_10"] > lim
        last = None
        for t in d.index[over & ~over.shift(1, fill_value=False)]:
            if last is not None and t - last < P("5min"):
                continue
            last = t
            nxt = ev.loc[t - P("2s") : t + P("5min")]
            rows.append(
                {
                    "first above limit": t,
                    "limit °C": lim,
                    "peak in next 60 s": round(
                        d["TIRZ_8_1_10"].loc[t : t + P("60s")].max(), 1
                    ),
                    "running (I > 1 A or EAPH > 5 kW)": bool(running.loc[t]),
                    "next cut": "-"
                    if nxt.empty
                    else f"{(nxt.index[0] - t).total_seconds():.0f} s later: "
                    f"{nxt.kind.iloc[0]}",
                }
            )
    return pd.DataFrame(rows)


def window(t, before="3min", after="3min"):
    t = pd.Timestamp(t)
    d = load(t.strftime("%Y%m%d"), MV + CUR + [EAPH, AIR, "TIRZ_8_1_10", "TIRZ_8_1_3"])
    w = d.loc[t - P(before) : t + P(after)].copy()
    w["I_string_A"] = w[CUR].clip(lower=0).mean(axis=1)
    w["EAPH_kW"] = w[EAPH] / 1000
    return w


def plot_event(t, ax, title, before="3min", after="3min", exh_limit=None):
    """Three stacked panels for one event: current + heater, air + exhaust T, valve \
states."""
    w = window(t, before, after)
    ax[0].plot(w.index, w.I_string_A, "k", lw=1, label="string current (A, mean of 5)")
    ax[0].plot(w.index, w.EAPH_kW, color="#d1495b", lw=1, label="EAPH power (kW)")
    ax[0].legend(loc="upper right", fontsize=8)
    ax[0].set_title(title, fontsize=10, loc="left")
    ax[1].plot(w.index, w[AIR], color="#3d7ea6", lw=1, label="stack inlet air PIR_2_02")
    a2 = ax[1].twinx()
    a2.plot(
        w.index,
        w["TIRZ_8_1_10"],
        color="#e8a33d",
        lw=1,
        label="exhaust TIRZ_8_1_10 (°C)",
    )
    if exh_limit:
        a2.axhline(exh_limit, color="#e8a33d", ls="--", lw=0.8)
    ax[1].legend(loc="lower left", fontsize=8)
    a2.legend(loc="upper right", fontsize=8)
    for i, c in enumerate(MV):
        ax[2].fill_between(
            w.index, i, i + 0.8 * w[c].fillna(0), step="post", color="#5c946e", lw=0
        )
    ax[2].set_yticks(
        [i + 0.4 for i in range(len(MV))], ["MV" + s for s in MV_SHORT], fontsize=7
    )
    ax[2].set_ylim(0, len(MV))
    ax[0].axvline(pd.Timestamp(t), color="grey", ls=":", lw=0.8)
    ax[1].axvline(pd.Timestamp(t), color="grey", ls=":", lw=0.8)
    ax[2].axvline(pd.Timestamp(t), color="grey", ls=":", lw=0.8)
