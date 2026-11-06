"""Fitted numbers of the 2D twin (05_twin_2d/app.js), re-calculated from the project data.

Collects the fits of 2026-11-03/04 that were run as loose scratchpad scripts, so every "amber" number in app.js
can be re-made from the project alone:

    heat     stack heat balance  dT/dt = k·(air/6000)^1.5·(Tin − T) + heaters + fuel + current − loss
             K_UP / K_DOWN (air warms / cools the stack), Q_HEAT, LOSS, Q_NG, Q_PER_A
    eaph     ETA_EAPH (share of air-heater power that goes into the air) and RISE_6000 (max air-in lift at 6000 ln/min)
    targets  SP_FS / SP_PL (plant median air-heater target in fuel switch / part load, heater on)
    tin      E_REC / E_REC_HI (recuperator effectiveness used for the air-in temperature, 6000 / 8000+ ln/min)
    rec      REC_E6 / REC_E9 / REC_TAU / REC_G / REC_TG (EAPH inlet TIR 2.05: lagged recuperator + gas gain)
    hsc      HSC_C6 / HSC_N / HSC_TAU (hot standby → air-flow cooling law, HSC_Q fixed at 0.5)

Held out of every fit: the 8 replay stretches the twin is scored on (REPLAYS below).
Chosen values that are NOT fitted here (app.js "violet"): air exponent 1.5, HSC_Q 0.5, 10-min air-in lag, 60 °C/h ramp.

Usage:
    python 03_data_analysis/scripts/twin_fits.py            # all parts
    python 03_data_analysis/scripts/twin_fits.py heat rec   # only some parts
Writes 03_data_analysis/twin_fits/twin_fits.json (+ twin_fits.csv: fitted vs app.js value).
Notebook with explanations and charts: 03_data_analysis/twin_fits.ipynb (calls these functions, then save()).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize, nnls

import plant_stages as ps

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "03_data_analysis" / "twin_fits"
STAGE_FILE = ROOT / "03_data_analysis" / "plant_stages" / "plant_stages_1min.parquet"
ALLCOL_FILE = ROOT / "03_data_analysis" / "slopes_jerk" / "all_columns_1min.parquet"   # made by slopes_jerk.py
APP = ROOT / "05_twin_2d" / "app.js"

# The 8 replay stretches (start, minutes) the twin is checked against; kept out of all fits.
REPLAYS = {"cold1": ("2026-03-01 09:05", 1436), "cold2": ("2026-02-13 14:32", 1289), "fs_pl1": ("2026-03-24 08:00", 87),
           "fs_pl2": ("2026-03-25 13:45", 90), "fs_pl3": ("2026-03-30 09:30", 62), "afc1": ("2026-03-25 15:35", 1091),
           "afc2": ("2026-02-16 10:37", 1263), "sd1": ("2026-02-17 07:40", 526)}
COLS = {"ng": "ct_FIRC_14_PV_ProcessValue", "pox": "ct_FIRC_12_PV_ProcessValue", "sp": "ct_TIRC_206_SP_TargetValue",
        "tin": "TIRC_2_06", "t205": "TIR_2_05", "peaph": "EIRC_2_01_ActV_In_ThreePhasePower",
        "eaph_A": "EIRC_2_01_ActV_rMas_Current", "air1": "ct_FIRC_111_PV_ProcessValue", "air2": "ct_FIRC_112_PV_ProcessValue"}
NOFUEL = ["Heat-up air", "Heat-up N₂+H₂", "Hot standby", "Air-flow cooling", "Shutdown"]
AIR_EXP = 1.5          # chosen (app.js AIR_EXP), not fitted
MCP6000 = 6000 / 60 * 1.293 * 1.005   # W/K of 6000 ln/min air
EAPH_KW = 40.0         # rated air heater


def frame():
    """1-min frame: plant stages + the air-path columns, replay stretches flagged as held."""
    st = pd.read_parquet(STAGE_FILE)
    a = pd.read_parquet(ALLCOL_FILE, columns=list(COLS.values())).rename(columns={v: k for k, v in COLS.items()})
    F = st.join(a.apply(pd.to_numeric, errors="coerce"), how="inner")
    for c in COLS:
        if c != "eaph_A":
            F.loc[F[c] < 0, c] = np.nan       # logger fill values
    F["held"] = False
    for t0, n in REPLAYS.values():
        t0 = pd.Timestamp(t0); F.loc[t0:t0 + pd.Timedelta(minutes=n - 1), "held"] = True
    F["heat"] = (F.peaph > 500).astype(float)
    F["day"] = F.index.date
    return F


def mode10(s):
    return s.resample("10min").agg(lambda x: x.mode().iat[0] if len(x.dropna()) else None)


def fit_heat(F):
    """Stack heat balance. Step A (no-fuel stages, 10-min windows): loss from air-off shutdown, then warming / cooling
    air exchange + heater heat. Step B (fuel switch + part load minutes): natural-gas heat + current heat."""
    W = F.resample("10min").mean(numeric_only=True)
    W["st"] = mode10(F.plant_stage)
    W["n"] = F.T_stack_C.resample("10min").count()
    W["dT"] = (W.T_stack_C.shift(-1) - W.T_stack_C.shift(1)) / 20 * 60
    keep = ((W.n >= 9) & W.dT.notna() & W.tin.notna() & W.st.isin(NOFUEL) & (W.T_stack_C > 40)
            & (W.st.shift(1) == W.st) & (W.st.shift(-1) == W.st) & (W.held.fillna(0) == 0))
    D = W[keep].copy()
    sd = D[(D.st == "Shutdown") & (D.F_air <= 20) & (D.heat == 0)]
    L = float(-(sd.dT * (sd.T_stack_C - 25)).sum() / ((sd.T_stack_C - 25) ** 2).sum())
    D = D[D.F_air > 20]
    sw = np.sqrt(1 / D.st.map(D.st.value_counts()).values)     # each stage counts equally
    a = (D.F_air / 6000) ** AIR_EXP; g = D.tin - D.T_stack_C
    X = np.c_[a * np.maximum(g, 0), a * np.minimum(g, 0), D.heat]; y = D.dT + L * (D.T_stack_C - 25)
    (kup, kdn, qh), _ = nnls(X * sw[:, None], y.values * sw)
    D["fit"] = X @ np.array([kup, kdn, qh]) - L * (D.T_stack_C - 25)
    by = D.groupby("st").apply(lambda q: (q.dT - q.fit).abs().median()).round(1).to_dict()

    M = F.copy(); M["Ts"] = M.T_stack_C.rolling(5, center=True).mean(); M["dT"] = (M.Ts.shift(-5) - M.Ts.shift(5)) / 10 * 60
    aa = np.where(M.F_air > 20, (np.maximum(M.F_air, 0) / 6000) ** AIR_EXP, 0); gg = M.tin - M.T_stack_C
    M["r"] = M.dT - (kup * aa * np.maximum(gg, 0) + kdn * aa * np.minimum(gg, 0) + qh * M.heat - L * (M.T_stack_C - 25))
    same = (M.plant_stage.shift(5) == M.plant_stage) & (M.plant_stage.shift(-5) == M.plant_stage)
    J = M[M.plant_stage.isin(["Fuel switch", "Part load"]) & same & ~M.held & M.r.notna() & M.ng.notna()]
    wj = np.sqrt(1 / J.plant_stage.map(J.plant_stage.value_counts()).values)
    (ang, bI), _ = nnls(J[["ng", "I_string_A"]].values * wj[:, None], J.r.values * wj)
    return {"K_UP": kup, "K_DOWN": kdn, "Q_HEAT": qh, "LOSS": L, "Q_NG": ang, "Q_PER_A": bI}, \
           {"windows_10min": len(D), "shutdown_windows": len(sd), "fuel_minutes": len(J), "median_miss_C_per_h_by_stage": by}


def fit_eaph(F):
    """Air-heater efficiency = air heat ÷ electric power (10-min windows, heater > 3 kW), air heat with the same
    cp = 1003 + 0.1·T as app.js eaphPower. RISE_6000 = max lift at 6000 ln/min (cp cancels: same as with cp 1.005)."""
    W = F.resample("10min").mean(numeric_only=True)
    ok = W[(W.T_stack_C > 60) & (W.F_air > 20) & (W.peaph > 3000)]
    rise, mdot = ok.tin - ok.t205, ok.F_air / 60 * 1.293          # K, g/s
    eta = float((rise * mdot * (1003 + 0.1 * (ok.tin + ok.t205) / 2) / 1000 / ok.peaph).median())
    rise_6000 = float(EAPH_KW * 1000 * (rise * mdot * 1.005 / ok.peaph).median() / MCP6000)
    return {"ETA_EAPH": eta, "RISE_6000": rise_6000}, {"windows_10min": len(ok)}


def fit_targets(F):
    """Plant median air-heater target with the heater on, in fuel switch and part load."""
    on = F[(F.heat > 0) & F.sp.notna()]
    return {"SP_FS": float(on[on.plant_stage == "Fuel switch"].sp.median()), "SP_PL": float(on[on.plant_stage == "Part load"].sp.median())}, \
           {"minutes_FS": int((on.plant_stage == "Fuel switch").sum()), "minutes_PL": int((on.plant_stage == "Part load").sum())}


def tin_sim(F, e6, ehi):
    """app.js air-in model on the plant's own stack T: recuperator 25 + e·(T − 25), heater lifts towards the target
    at 60 °C/h (cap RISE_6000), otherwise a 10-min lag."""
    run = (F.index.to_series().diff() != pd.Timedelta("1min")).cumsum().values
    T, air, sp, heat, tin = (F[c].values for c in ("T_stack_C", "F_air", "sp", "heat", "tin"))
    sp = np.nan_to_num(sp)
    e = e6 - (e6 - ehi) * np.clip((air - 6000) / 2000, 0, 1); rec = 25 + e * (T - 25)
    cap = rec + 268 * 6000 / np.maximum(air, 1000)
    tg = np.where(heat > 0, np.maximum(rec, np.minimum(np.where(sp > 0, sp, rec), cap)), rec)
    a = 1 - np.exp(-1 / 10); out = np.empty_like(T); x = tin[0]
    for i in range(len(T)):
        if i == 0 or run[i] != run[i - 1]:
            x = tin[i]
        else:
            x += (min(tg[i], max(rec[i], x)) - x) * a
            if heat[i] and tg[i] > x:
                x = min(tg[i], x + 1.0)
        out[i] = x
    return out


def fit_tin(F):
    """E_REC / E_REC_HI: grid search of the air-in model against measured TIRC 2.06 (non-held minutes, each stage equal)."""
    G = F[F.T_stack_C.notna() & F.tin.notna() & F.F_air.notna()]
    use = (~G.held & (G.F_air > 20) & (G.T_stack_C > 40)).values
    w = 1 / G.plant_stage.map(G.plant_stage.value_counts()).values
    best = None
    for e6 in np.arange(0.80, 0.925, 0.01):
        for ehi in np.arange(0.76, e6 + 0.001, 0.01):
            err = np.abs(tin_sim(G, e6, ehi) - G.tin.values)
            s = float(np.nansum((err * w)[use]) / np.sum(w[use]))
            if best is None or s < best[0]:
                best = (s, e6, ehi)
    s, e6, ehi = best
    hold = (G.held & (G.F_air > 20)).values
    held_miss = lambda a, b: round(float(np.nanmean(np.abs(tin_sim(G, a, b) - G.tin.values)[hold])), 1)
    # 2026-11-05: best fit 0.91/0.86 misses the replays by 7.6 °C, app.js 0.88/0.83 by 4.8 °C -> app keeps 0.88/0.83
    return {"E_REC": e6, "E_REC_HI": ehi}, {"weighted_mean_miss_C": round(s, 1), "held_out_miss_C": held_miss(e6, ehi),
                                            "app_0.88_0.83_held_out_miss_C": held_miss(0.88, 0.83)}


def fit_rec(F):
    """EAPH inlet TIR 2.05 = lagged recuperator 25 + e·(T − 25) (e 6000 → 9000 ln/min) + lagged gas gain. Nelder-Mead."""
    d = F.copy()
    air = (d.air1 + d.air2).fillna(0).values; ng = d.ng.fillna(0).clip(lower=0).values
    T = d.T_stack_C.ffill().values; y = d.t205.values
    seg = (d.index.to_series().diff() != pd.Timedelta("1min")).cumsum().values

    def sim(p):
        e6, ehi, g, tau, tg = p
        base = 25 + (e6 - (e6 - ehi) * np.clip((air - 6000) / 3000, 0, 1)) * (T - 25)
        a, ag = 1 - np.exp(-1 / max(tau, 0.5)), 1 - np.exp(-1 / max(tg, 0.5))
        out = np.empty(len(T)); R = G = 0.0
        for i in range(len(T)):
            if i == 0 or seg[i] != seg[i - 1]:
                R = y[i] if not np.isnan(y[i]) else base[i]; G = 0.0
            G += (g * ng[i] - G) * ag; R += (base[i] - R) * a; out[i] = R + G
        return out
    m = (air > 3000) & ~np.isnan(y)
    tr, te = m & ~d.held.values, m & d.held.values
    loss = lambda p, k: float(np.nanmean(np.abs(sim(p) - y)[k]))
    r = minimize(lambda p: loss(p, tr), [0.87, 0.87, 0.3, 40, 20], method="Nelder-Mead",
                 options=dict(maxiter=400, xatol=1e-3, fatol=1e-3))
    e6, ehi, g, tau, tg = r.x
    return {"REC_E6": e6, "REC_E9": ehi, "REC_G": g, "REC_TAU": tau, "REC_TG": tg}, \
           {"train_miss_C": round(float(r.fun), 1), "held_out_miss_C": round(loss(r.x, te), 1)}


def hs_exits(F):
    """Hot standby → air-flow cooling exits: stack + air per minute from the border until the stage ends,
    12 h, or the air heater comes back on (current > 1 A for 15 min, 20 min after it went off)."""
    b = ps.blocks(F)
    runs = {}
    for i in range(len(b) - 1):
        cur, nxt = b.iloc[i], b.iloc[i + 1]
        if cur.stage != "Hot standby" or nxt.stage != "Air-flow cooling":
            continue
        t0 = pd.Timestamp(nxt.start)
        post = F.loc[t0:t0 + pd.Timedelta("12h")]
        bad = ~post.plant_stage.isin(["Air-flow cooling", "No data"])
        if bad.any():
            post = post.loc[:bad.idxmax() - pd.Timedelta("1min")]
        post = post.asfreq("1min")
        cur_A = post.eaph_A.values
        off = np.where(cur_A < 1)[0]; t_off = int(off[0]) if len(off) else -1
        on = pd.Series(cur_A > 1).rolling(15).sum().values >= 15
        back = np.where((np.arange(len(post)) > t_off + 20) & on)[0] - 14 if t_off >= 0 else []
        n = min(len(post), 12 * 60 + 1, int(back[0]) if len(back) else 10 ** 9)
        runs[str(t0)] = (post.T_stack_C.values[:n].astype(float), post.F_air.ffill().values[:n].astype(float))
    return runs


def fit_hsc(F, q=0.5):
    """Cooling law slope = −f·C6·(air/6000)^N·u·(u/475)^q, u = T − 25, f = 1 − e^(−t/TAU); q fixed (chosen).
    Fitted on the settled exits (2026-03-30 left out: only 14 min hot standby straight after part load)."""
    R = hs_exits(F)

    def sim(c6, n, tau, P, A):
        M = np.full(len(P), np.nan); T = P[0]
        for i in range(len(P)):
            if i > 0:
                if np.isnan(P[i - 1]) and not np.isnan(P[i]):
                    T = P[i]
                else:
                    u = max(T - 25, 0); T += -(1 - np.exp(-i / tau)) * c6 * (A[i] / 6000) ** n * u * (u / 475) ** q / 60
            M[i] = T
        return M

    def err(p, keys):
        c6, n, tau = p
        if not (0 < c6 < 1 and 0 <= n < 5 and 1 <= tau <= 180):
            return 1e3
        e = []
        for k in keys:
            P, A = R[k]; M = sim(c6, n, tau, P, A); m = ~np.isnan(P); e += list(np.abs(M[m] - P[m]))
        return float(np.mean(e))
    keys = [k for k in R if not k.startswith("2026-03-30")]
    opt = lambda ks, x0: minimize(lambda x: err(x, ks), x0, method="Nelder-Mead", options=dict(maxiter=2000, xatol=1e-4, fatol=1e-3))
    f = opt(keys, (0.06, 1.6, 5))
    loo = [err(opt([j for j in keys if j != k], f.x).x, [k]) for k in keys]
    c6, n, tau = f.x
    return {"HSC_C6": c6, "HSC_N": n, "HSC_TAU": tau}, \
           {"runs": keys, "mean_miss_C": round(float(f.fun), 1), "leave_one_out_miss_C": round(float(np.mean(loo)), 1)}


PARTS = {"heat": fit_heat, "eaph": fit_eaph, "targets": fit_targets, "tin": fit_tin, "rec": fit_rec, "hsc": fit_hsc}


def app_values():
    """Numbers as typed in app.js today (`NAME=value`)."""
    txt = APP.read_text(encoding="utf-8")
    return {m.group(1): float(m.group(2)) for m in re.finditer(r"\b([A-Z][A-Z0-9_]+)=(-?\d+(?:\.\d+)?)(?![\d.])", txt)}


def save(new):
    """Merge {part: (values, check)} into twin_fits.json, write twin_fits.csv (fitted vs app.js), return that table."""
    OUT.mkdir(exist_ok=True)
    path = OUT / "twin_fits.json"
    res = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for p, (vals, check) in new.items():
        res[p] = {"values": {k: round(float(v), 4) for k, v in vals.items()}, "check": check}
    res["_note"] = "Fitted from 03_data_analysis data by scripts/twin_fits.py; app.js values typed by hand. 8 replay stretches held out."
    path.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    app = app_values()
    T = pd.DataFrame([dict(part=p, name=k, fitted=v, app_js=app.get(k)) for p, r in res.items() if p in PARTS for k, v in r["values"].items()])
    T["diff_pct"] = ((T.fitted - T.app_js) / T.app_js.abs() * 100).round(1)
    T.to_csv(OUT / "twin_fits.csv", index=False)
    return T


def main(parts):
    sys.stdout.reconfigure(encoding="utf-8")
    F = frame()
    new = {}
    for p in parts:
        print(f"fitting {p} ...", flush=True)
        new[p] = PARTS[p](F)
    print(save(new).to_string(index=False))
    for p in parts:
        print(p, new[p][1])


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if a in PARTS] or list(PARTS))
