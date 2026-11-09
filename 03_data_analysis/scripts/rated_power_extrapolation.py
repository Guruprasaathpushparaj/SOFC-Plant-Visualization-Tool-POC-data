"""Every logged sensor stretched from part load to rated power (30 A per string = 52 kW DC) and on to 60 kW.

Part load never went above ~34 kW. For each numeric sensor we fit a straight line
    sensor = a + b * P_dc        (P_dc = sum over 5 strings of V * I, kW)
on the part-load minutes (plant_stages.py label "Part load") and read it at 0..60 kW.
Fit quality is checked by leaving one part-load run out at a time and predicting
the run's top-power minutes (error at the far end = how far we can trust the line).
The values used at each step (use_<p>kW) then come from each sensor's best-fitting curve
(rated_power_curves.py: line, quadratic or power lag, picked by leave-one-run-out MAE; column
"model"), except string V, I and gas, which stay on the electrical solution so sum V*I = P.

shortcut: straight line in power only, minutes are not steady (temperatures still
rising when the run ends), so heat-driven sensors are under-read; upgrade = twin
heat balance (05_twin_2d) for stack/BOP temperatures.

Usage:  python 03_data_analysis/scripts/rated_power_extrapolation.py
Writes: 03_data_analysis/rated_power/sensor_extrapolation.csv (+ .xlsx), pl_minutes.parquet,
        electrical_60kW.csv, string_vi_fit.csv, curve_fits.csv
"""
import glob
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "02_data" / "downsampled"
STAGES = ROOT / "03_data_analysis" / "plant_stages" / "plant_stages_1min.parquet"
OUT = ROOT / "03_data_analysis" / "rated_power"
# rated power = 30 A on every string (user, 2026-11-06; was 60 kW = 40.18 A): 52.0 kW on the string V-I lines
# (electrical() checks the solved current); the table still runs to 60 kW
RATED_A, RATED_KW = 30.0, 52
CELLS = 476                     # per string: 4 stacks x 119 cells
STEPS = [0, 10, 20, 30, 34, 40, 50, RATED_KW, 60]
VOLT = [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rVoltMonitor" for i in range(1, 6)]
CURR = [f"PLC_hostSetp_ctrl_ctEIRC4{i}_rCurrMonitor" for i in range(1, 6)]
# known limits a straight line can run through (from trip_causes / rated-power work)
LIMITS = {"TIRZ_8_1_3": 720.0, "TIRZ_8_1_10": 200.0}
HEAT_NOTE = {"TIRZ_8_1_3": "heat balance (rated-power work 2026-11-05): no steady point under the 720 trip; trips at 40-52 kW",
             "TIRZ_8_1_10": "heat balance: exhaust 200 trip reached in 3 of 4 rated-power cases"}


def pl_minutes():
    s = pd.read_parquet(STAGES)
    pl = s.index[s.plant_stage == "Part load"]
    parts = []
    for day in sorted(pl.normalize().unique()):
        f = SRC / f"{day:%Y%m%d}_10s.parquet"
        r = pd.read_parquet(f)
        r.index = pd.to_datetime(r.pop("Date Time"))
        r = r.apply(pd.to_numeric, errors="coerce").resample("1min").mean()
        parts.append(r.reindex(pl[pl.normalize() == day]))
    d = pd.concat(parts)
    d = d.where(d != -1)                                    # logger writes -1 on dropouts
    d["P_dc_kW"] = sum(d[v] * d[i] for v, i in zip(VOLT, CURR)) / 1000
    d["run"] = (d.index.to_series().diff() != pd.Timedelta("1min")).cumsum().values
    return d[d["P_dc_kW"] > 0.5]


def fit(x, y):
    b, a = np.polyfit(x, y, 1)
    return a, b


def robust_keep(x, y):
    """Drop glitch minutes (> 4 robust sigma off the first line), e.g. 93 V strings, 28 V cells."""
    a, b = fit(x, y)
    r = y - (a + b * x)
    sig = 1.4826 * np.median(np.abs(r - np.median(r)))
    return np.abs(r - np.median(r)) <= 4 * sig if sig > 0 else np.ones(len(x), bool)


def extrapolate(d):
    rows = []
    P = d["P_dc_kW"]
    for c in d.columns.drop(["P_dc_kW", "run"]):
        y = d[c]
        ok = y.notna() & P.notna()
        if ok.sum() < 60 or y[ok].std() < 1e-6:
            continue
        x, yy, run = P[ok].values, y[ok].values, d.loc[ok, "run"].values
        keep = robust_keep(x, yy)
        n_out = int((~keep).sum())
        x, yy, run = x[keep], yy[keep], run[keep]
        if np.ptp(yy) < 1e-6:
            continue
        a, b = fit(x, yy)
        r2 = 1 - np.var(yy - (a + b * x)) / np.var(yy)
        # leave-one-run-out: predict the held-out run's minutes above its 75th power percentile
        errs = []
        for k in np.unique(run):
            tr, te = run != k, (run == k) & (x >= np.percentile(x[run == k], 75))
            if tr.sum() < 30 or te.sum() == 0 or np.ptp(x[tr]) < 1:
                continue
            a2, b2 = fit(x[tr], yy[tr])
            errs.append(np.abs(a2 + b2 * x[te] - yy[te]).mean())
        span = np.ptp(yy) or 1.0
        loro = float(np.mean(errs)) if errs else np.nan
        row = {"sensor": c, "n_min": int(keep.sum()), "n_glitch": n_out, "slope_per_kW": b, "r2": r2, "loro_err": loro,
               "loro_err_pct_of_range": 100 * loro / span, "seen_min": yy.min(), "seen_max": yy.max(),
               "pl_mean": yy.mean(), "at_max_seen_P": a + b * x.max()}
        row.update({f"at_{p}kW": a + b * p for p in STEPS})
        rows.append(row)
    t = pd.DataFrame(rows)
    t["power_driven"] = (t.r2 >= 0.5) & (t.loro_err_pct_of_range <= 25)
    t["group"] = np.where(t.power_driven, "follows power",
                          np.where(t.sensor.str.match(r"(ct_)?TI|.*VoltCellMin_ActV"), "temperature / cell (lags power)",
                                   "operator-set / no link"))
    # operator-set values keep their part-load level; physical ones take their line even when weak (low trust)
    for p in STEPS:
        t[f"use_{p}kW"] = np.where(t.group == "operator-set / no link", t.pl_mean, t[f"at_{p}kW"])
    t["model"] = np.where(t.group == "operator-set / no link", "part-load mean", "line")
    add_notes(t)
    return t.sort_values(["power_driven", "r2"], ascending=False)


def add_notes(t):
    """Notes from the use_* values (call again after they change): trips crossed, cell protection, actuators past 0/100 %."""
    t["note"] = ""
    t.loc[t.sensor.str.contains("VoltCellMin_ActV"), "note"] += "plant cell protection (0.72 V) stops load before this; "
    for s, lim in LIMITS.items():
        m = t.sensor == s
        if not m.any():
            continue
        v = t.loc[m, [f"use_{p}kW" for p in STEPS]].values[0]
        k = int(np.argmax(v >= lim)) if (v >= lim).any() else None
        if k is not None:                                  # first step at or over the trip, straight between steps
            p_hit = STEPS[0] if k == 0 else STEPS[k - 1] + (lim - v[k - 1]) / (v[k] - v[k - 1]) * (STEPS[k] - STEPS[k - 1])
            t.loc[m, "note"] = f"crosses trip {lim:.0f} at {p_hit:.0f} kW; "
    for k, v in HEAT_NOTE.items():
        t.loc[t.sensor == k, "note"] += v
    pct = t.sensor.str.contains("Valve|_OP|Out", case=False) & (t.seen_max <= 100) & (t.seen_min >= 0)
    t.loc[pct & (t.use_60kW > 100), "note"] += " >100 % (actuator saturates)"
    t.loc[pct & (t.use_60kW < 0), "note"] += " <0 % (actuator saturates)"


def ng_faraday(I, fu_pct):
    """NG ln/min as CH4 (8 e-/molecule) for string currents I (A) at fuel use fu_pct; 476 cells/string."""
    return float(np.sum(I) * CELLS / 96485 / 8 * 22.414 * 60 / (fu_pct / 100)) if fu_pct > 0 else 0.0


def electrical(d, t):
    """Make the string V and I agree with P = sum V*I: separate straight lines in P give only ~50 kW at 60.
    Per string V = a + b*I (robust); every string carries the same current (user, 2026-11-06: the part-load
    split, string 4.4 at ~73 %, was an operator setting, and it put four strings above the 42 A El.Load rating);
    solve the common current u. Rated point = the twin's (05_twin_2d/app.js): RATED_A on every string = RATED_KW.
    Also writes t.use_rated = t.use_<RATED_KW>kW (read by 05_twin_2d/tools/prep.py)."""
    rows = []
    share = np.ones(len(CURR))
    ab, r2 = [], []
    for v, i in zip(VOLT, CURR):
        ok = d[v].notna() & d[i].notna() & (d[i] > 0.5)
        x, y = d.loc[ok, i].values, d.loc[ok, v].values
        keep = robust_keep(x, y)
        ab.append(fit(x[keep], y[keep]))
        r2.append(1 - np.var(y[keep] - (ab[-1][0] + ab[-1][1] * x[keep])) / np.var(y[keep]))
    a, b = np.array(ab).T
    # fuel use follows power well (r2 0.9); the mean of its used values (best curve) sets how much gas each step burns
    fu = t.set_index("sensor").loc[[f"PLC_pv_rFU_Worst_{k}" for k in range(1, 6)], [f"use_{p}kW" for p in STEPS]].mean()
    fu = {p: fu[f"use_{p}kW"] for p in STEPS}
    for p in STEPS:
        # sum_k (a_k + b_k s_k u) s_k u = 1000 P  ->  (sum b s^2) u^2 + (sum a s) u - 1000 P = 0
        A, B = (b * share ** 2).sum(), (a * share).sum()
        disc = B * B + 4 * A * 1000 * p
        u = (-B + np.sqrt(disc)) / (2 * A) if disc >= 0 else np.nan
        I, V = share * u, a + b * share * u
        if p == RATED_KW:
            assert abs(u - RATED_A) < 0.05, f"{RATED_KW} kW solves to {u:.2f} A, not the rated {RATED_A} A: update RATED_KW"
        rows.append({"P_kW": p, **{f"I_{k + 1}_A": I[k] for k in range(5)}, **{f"V_{k + 1}_V": V[k] for k in range(5)},
                     "V_cell_avg": float((V / CELLS).mean()), "P_check_kW": float((V * I).sum() / 1000),
                     "FU_pct": fu[p], "NG_lnmin": ng_faraday(I, fu[p])})
        t.loc[t.sensor == "ct_FIRC_14_PV_ProcessValue", f"use_{p}kW"] = rows[-1]["NG_lnmin"]
        for k in range(5):
            for col, val in ((CURR[k], I[k]), (VOLT[k], V[k])):
                t.loc[t.sensor == col, f"use_{p}kW"] = val
    t.loc[t.sensor == "ct_FIRC_14_PV_ProcessValue", "model"] = "Faraday from solved current"
    t.loc[t.sensor.isin(CURR + VOLT), "model"] = "V-I solved"
    t["use_rated"] = t[f"use_{RATED_KW}kW"]
    t.loc[t.sensor == "ct_FIRC_14_PV_ProcessValue", "note"] += "gas by Faraday from solved currents at the fuel-use trend (operator steps hide the link)"
    for col in CURR + VOLT:
        t.loc[t.sensor == col, "note"] += "V-I solved so sum V*I = P (electrical_60kW.csv)"
    e = pd.DataFrame(rows)
    e.attrs["VI"] = pd.DataFrame({"string": range(1, 6), "V_at_0A": a, "V_per_A": b, "r2": r2, "current_share": share})
    return e


def self_check():
    x = np.arange(10.0)
    assert np.allclose(fit(x, 3 + 2 * x), (3, 2))
    y = 3 + 2 * x + np.r_[0.1, -0.1] .repeat(5)
    y[4] = 500                                        # one glitch minute
    assert robust_keep(x, y).sum() == 9 and not robust_keep(x, y)[4]
    assert abs(ng_faraday(np.full(5, 16.0), 100) - 66.4) < 0.5     # 80 A total -> 66 ln/min CH4 at 100 %


if __name__ == "__main__":
    self_check()
    OUT.mkdir(exist_ok=True)
    d = pl_minutes()
    d.to_parquet(OUT / "pl_minutes.parquet")
    t = extrapolate(d)
    import rated_power_curves as rc                    # here, not at the top: it imports this module
    res, fits = rc.fit_all(d, t)
    res.to_csv(OUT / "curve_fits.csv", index=False)
    rc.apply_best(t, fits)
    add_notes(t)
    e = electrical(d, t)
    assert np.allclose(e.P_check_kW, e.P_kW, atol=0.01)
    e.to_csv(OUT / "electrical_60kW.csv", index=False)
    e.attrs["VI"].to_csv(OUT / "string_vi_fit.csv", index=False)
    print(e.round(2).to_string(index=False))
    t.to_csv(OUT / "sensor_extrapolation.csv", index=False)
    t.round(4).to_excel(OUT / "sensor_extrapolation.xlsx", index=False)
    print(f"{len(d)} part-load minutes, {d.run.nunique()} runs, P max {d.P_dc_kW.max():.1f} kW")
    print(f"{len(t)} changing sensors:", t.group.value_counts().to_dict())
