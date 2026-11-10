"""Trace every tag in 'sensors displayed in the visualization tool.xlsx' to a logged
column and score how useful each one is.  Output: sensors/out/*.csv"""

import glob
import os
import re

import numpy as np
import openpyxl
import pandas as pd

ROOT = r"C:/Users/mrgur/Guru_prasaath/06_Projects/01_POC"
OUT = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(OUT, exist_ok=True)

# ---------- 1. Excel tags --------------------------------------------------
ws = openpyxl.load_workbook(
    f"{ROOT}/01_docs/sensors displayed in the visualization tool.xlsx"
).active
rows = []
for r in ws.iter_rows(min_row=4):
    sno, name = r[0].value, r[1].value
    if sno is None:
        continue
    red = (
        r[1].font.color is not None
        and r[1].font.color.type == "rgb"
        and r[1].font.color.rgb == "FFFF0000"
    )
    rows.append(dict(sno=sno, tag=(name or "").strip(), red=red))
tags = pd.DataFrame(rows)
tags["tag_n"] = tags.tag.str.replace(r"\s+", " ", regex=True)
tags["duplicate_of"] = (
    tags.groupby("tag_n").sno.transform("first").where(lambda s: s != tags.sno)
)

cols = set()
for f in sorted(glob.glob(f"{ROOT}/02_data/downsampled/*_10s.parquet")):
    import pyarrow.parquet as pq

    cols |= set(pq.read_schema(f).names)

# EIRC 4,s,k  (ICA rows per string load; .1/.2/.4–.8 from component_sensor_map_en.md
# §3.2)
EIRC4 = {
    1: (
        "PLC_hostSetp_ctrl_ctEIRC4{s}_rVoltMonitor",
        "map doc",
        "Load voltage monitor (twin EIRC_4s_VoltageMon, 03-17 on)",
    ),
    2: (
        "PLC_hostSetp_ctrl_ctEIRC4{s}_rCurrMonitor",
        "map doc",
        "Load current monitor (twin EIRC_4s_CurrentMon, 03-17 on)",
    ),
    3: (
        "EIRC_4{s}_Actual_Power",
        "assumed",
        "Load power (assumed); only from 03-17, 3e37 glitches",
    ),
    4: (
        "PLC_hostSetp_ctrl_ctEIRC4{s}_SP_TargetValue_Value",
        "map doc",
        "Load set input (current set-point)",
    ),
    5: (
        "PLC_hostSetp_ctrl_ctEIRC4{s}_SP_SlewRateAbs",
        "map doc",
        "Load slew-rate setting",
    ),
    6: ("PLC_hostSetp_ctrl_ctEIRC4{s}_OpMode", "map doc", "Load basic mode"),
    7: ("EIRC_4{s}_OUT_Enable", "map doc", "Load ON/OFF; only from 03-17"),
    8: (
        "EIRC_4{s}_OUT_StackCon_OnOff)",
        "assumed",
        "Load device status (assumed); only from 03-17, shifted values on some days",
    ),
    9: (
        "PLC_hostSetp_ctrl_ctEIRC4{s}_rVoltCellMin_ActV",
        "assumed",
        "Min. voltage reported by load (assumed)",
    ),
}
EIR_STACK = {12: 1, 15: 2, 18: 3, 21: 4}


def trace(tag):
    """-> (column, how, note)"""
    m = re.match(r"^([A-Z]+)\s*([\d,]*)$", tag)
    if not m or not m.group(2):
        return None, "none", "blank tag name"
    fam, nums = m.group(1), [n for n in m.group(2).split(",") if n]
    us = "_".join(nums)
    if fam == "FIRC":
        c = f"ct_FIRC_{''.join(nums)}_PV_ProcessValue"
        return (c, "direct", "flow actual value") if c in cols else (None, "none", "")
    if fam == "QIR":
        return "PLC_pi_QIR_1_4_ActVal_Value", "map doc", "NG quality (PLC)"
    if fam == "EIRC" and us == "2_01":
        return "EIRC_2_01_ActV_In_ThreePhasePower", "map doc", "EAPH 3-phase power"
    if fam == "EIRC" and nums[0] in ("3", "5"):
        return (
            f"pi_IIR_{us}_ActVal",
            "assumed",
            "heater current IIR (EIRC output itself not logged)",
        )
    if fam == "EIRC" and nums[0] == "4":
        s, k = int(nums[1]), int(nums[2])
        c, how, note = EIRC4[k]
        return c.format(s=s), how, note
    if fam == "EIR":
        k = int(nums[2])
        note = (
            f"stack {EIR_STACK[k]} total voltage"
            if k in EIR_STACK
            else "package voltage"
        )
        return f"pi_EIR_{us}", "direct", note
    if fam == "TIRC" and us.startswith("3_19"):
        return f"TIR_{us}", "renamed", "logged as TIR"
    c = f"{fam}_{us}"
    return (
        (c, "direct", "")
        if c in cols
        else (None, "none", "not in any of the 836 logged columns")
    )


tr = tags.tag_n.apply(trace)
tags["column"] = [t[0] for t in tr]
tags["how"] = [t[1] for t in tr]
tags["note"] = [t[2] for t in tr]
tags.loc[tags.column.notna() & ~tags.column.isin(cols), ["how", "note"]] = [
    "none",
    "candidate column not logged",
]
tags.loc[tags.how == "none", "column"] = None

# ---------- 2. load data as 1-min means -------------------------------------
use = sorted(set(tags.column.dropna()) | {"TIR_4_6_25"})
frames = []
for f in sorted(glob.glob(f"{ROOT}/02_data/downsampled/*_10s.parquet")):
    have = [c for c in use if c in pq.read_schema(f).names]
    d = pd.read_parquet(f, columns=["Date Time"] + have).set_index("Date Time")
    d = d.apply(pd.to_numeric, errors="coerce")
    d = d.mask(d.abs() > 1e30)  # 3e37 invalids
    frames.append(d.resample("1min").mean())
X = pd.concat(frames).reindex(columns=use)
lab = pd.read_parquet(f"{ROOT}/04_synthetic_data/library/traces_1min.parquet")[
    ["stage", "phase"]
]
X = X.join(lab, how="left")
X.to_parquet(os.path.join(OUT, "x1min.parquet"))
print("data", X.shape)

# ---------- 3. per-column metrics ------------------------------------------
num = X[use]
days = num.index.normalize()
labelled = X.stage.notna()
res = {}
for c in use:
    s = num[c]
    cov = s.notna().mean()
    neg1 = (s == -1).mean()
    v = s.where(s != -1)
    rng = (v.quantile(0.01), v.quantile(0.99)) if v.notna().any() else (np.nan, np.nan)
    span = rng[1] - rng[0]
    # days on which the sensor actually moves (p99-p1 within day > 1 % of global span)
    dspan = v.groupby(days).quantile(0.99) - v.groupby(days).quantile(0.01)
    days_alive = (
        int((dspan > max(1e-6, 0.01 * span)).sum()) if span and np.isfinite(span) else 0
    )
    # eta^2: share of variance explained by stage
    g = v[labelled].groupby(X.stage[labelled])
    tot = v[labelled].var(ddof=0)
    eta = (
        float(
            ((g.mean() - v[labelled].mean()) ** 2 * g.count()).sum()
            / (tot * g.count().sum())
        )
        if tot and tot > 0
        else 0.0
    )
    med = g.median()
    res[c] = dict(
        coverage=cov,
        minus1_share=neg1,
        p01=rng[0],
        p99=rng[1],
        span=span,
        days_alive=days_alive,
        eta2_stage=eta,
        **{
            f"med_{k}": med.get(k, np.nan)
            for k in [
                "Shut-down",
                "Start-up",
                "Hot standby",
                "Thermal adjustment",
                "Part load",
                "Idle",
            ]
        },
    )
M = pd.DataFrame(res).T

# redundancy (Spearman on 10-min sample, alive columns)
alive = M.index[(M.span > 0) & (M.coverage > 0.3) & (M.days_alive >= 3)]
S = num[alive].iloc[::10].rank().corr().copy()
S = S.mask(np.eye(len(S), dtype=bool))

M["max_r"] = S.abs().max()
M["most_like"] = S.abs().idxmax()
S.to_csv(os.path.join(OUT, "spearman.csv"))

T = tags.merge(M, left_on="column", right_index=True, how="left")
T.to_csv(os.path.join(OUT, "trace_metrics.csv"), index=False)
print(T.how.value_counts())
