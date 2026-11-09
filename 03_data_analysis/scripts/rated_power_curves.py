"""Curve fits for every sensor that changes during part load: can a curve or a time lag beat the straight line?

Follows rated_power_extrapolation.py (same part-load minutes, same glitch drop). Model families, all least squares:
    line            y = a + b·P
    quadratic       y = a + b·P + c·P²
    lag τ           y = a + b·L                 L = power through a first-order lag (time constant τ min), 0 at run start
    power + lag τ   y = a + b·P + c·L           fast part + slow part
    start + lag τ   y = y0 + b·P + c·L          y0 = the sensor's reading at the run's first minute (hot standby level)
τ is picked from TAUS. Each sensor keeps the model with the lowest leave-one-run-out MAE (fit on 9 runs, predict the
whole 10th; honest), so a curve only wins when it also predicts a run it never saw. R² and MAE are also given on the
fitted minutes. At 60 kW the lag models are read at steady state (L = P = 60); "start + lag" uses the median run start.
apply_best() puts these values into use_<p>kW of sensor_extrapolation.csv (user, 2026-11-06), using the best curve
whose 60 kW value is plausible: within one seen part-load range below the lowest / above the highest reading (a straight
line through the part-load data lands about 0.8 range past it). Otherwise the next best, and the line as last resort.
Without this, 320-min lags fitted on <= 44-min runs read e.g. 2496 °C stack TCs and -2985 ohm insulation at 60 kW.

shortcut: runs last 8–44 min, so lags of hours are poorly pinned and a quadratic or lag gain read at 60 kW can land far
outside the part-load range; the heat balance stays the better method for stack temperatures.

Usage:  python 03_data_analysis/scripts/rated_power_curves.py
Writes: 03_data_analysis/rated_power/curve_fits.csv, curve_fit_plots.pdf
"""
import numpy as np
import pandas as pd

import rated_power_extrapolation as rp

TAUS = [5, 10, 20, 40, 80, 160, 320]


def lag(P, run, tau):
    """First-order lag of P per run, starting from 0 (each run starts in hot standby, no current)."""
    a, out, l, prev = 1 - np.exp(-1 / tau), np.empty(len(P)), 0.0, None
    for k, (p, r) in enumerate(zip(P, run)):
        if r != prev:
            l, prev = 0.0, r
        l += a * (p - l)
        out[k] = l
    return out


def models(P, L):
    """name -> (X builder taking (P, lagged dict, y0), uses_start). Built once per call so taus stay explicit."""
    m = {"line": (lambda p, l, y0: np.c_[np.ones_like(p), p], False),
         "quadratic": (lambda p, l, y0: np.c_[np.ones_like(p), p, p * p], False)}
    for t in TAUS:
        m[f"lag {t} min"] = (lambda p, l, y0, t=t: np.c_[np.ones_like(p), l[t]], False)
        m[f"power + lag {t} min"] = (lambda p, l, y0, t=t: np.c_[np.ones_like(p), p, l[t]], False)
        m[f"start + lag {t} min"] = (lambda p, l, y0, t=t: np.c_[p, l[t]], True)
    return m


def _fit(X, y):
    return np.linalg.lstsq(X, y, rcond=None)[0]


def fit_sensor(y, P, L, run, M):
    """All models for one sensor (rows already glitch-free). Returns {name: dict(coef, pred, r2, mae, loro_mae)}."""
    y0 = pd.Series(y).groupby(run).transform("first").values          # reading at each run's first kept minute
    out = {}
    for name, (build, start) in M.items():
        X = build(P, L, y0)
        t = y - y0 if start else y
        if len(y) < X.shape[1] + 10:
            continue
        c = _fit(X, t)
        pred = X @ c + (y0 if start else 0)
        err = []
        for k in np.unique(run):
            tr, te = run != k, run == k
            if tr.sum() < X.shape[1] + 10:
                continue
            err.append(np.abs(X[te] @ _fit(X[tr], t[tr]) + (y0[te] if start else 0) - y[te]))
        ss = np.sum((y - y.mean()) ** 2)
        out[name] = {"coef": c, "pred": pred, "r2": 1 - np.sum((y - pred) ** 2) / ss if ss > 0 else np.nan,
                     "mae": np.abs(y - pred).mean(), "loro_mae": np.concatenate(err).mean() if err else np.nan,
                     "start": start, "y0_med": float(np.median(pd.Series(y0).groupby(run).first()))}
    return out


def pick(f, order):
    """Lowest held-out MAE; models within 1e-9 of it count as a tie and the simpler one (earlier in order) wins."""
    names = [n for n in order if n in f and np.isfinite(f[n]["loro_mae"])]
    lo = min(f[n]["loro_mae"] for n in names)
    return next(n for n in names if f[n]["loro_mae"] <= lo * (1 + 1e-9) + 1e-12), names


def at_power(name, r, p):
    """Model value at steady power p (L = P = p)."""
    c = r["coef"]
    if name == "line":
        return c[0] + c[1] * p
    if name == "quadratic":
        return c[0] + c[1] * p + c[2] * p * p
    if name.startswith("start"):
        return r["y0_med"] + (c[0] + c[1]) * p
    if name.startswith("power"):
        return c[0] + (c[1] + c[2]) * p
    return c[0] + c[1] * p


def fit_all(d, t):
    """Best model per sensor in t (the extrapolate() table). Returns (results table, per-sensor fits for plotting)."""
    P_all, run_all = d["P_dc_kW"].values, d["run"].values
    L_all = {tau: lag(P_all, run_all, tau) for tau in TAUS}
    rows, keep = [], {}
    for s, grp in zip(t.sensor, t.group):
        y = d[s].values
        ok = ~np.isnan(y)
        k = np.zeros(len(y), bool)
        k[ok] = rp.robust_keep(P_all[ok], y[ok])                      # same glitch drop as the straight-line table
        P, run, yy = P_all[k], run_all[k], y[k]
        L = {tau: v[k] for tau, v in L_all.items()}
        M = models(P, L)
        f = fit_sensor(yy, P, L, run, M)
        best, names = pick(f, list(M))
        lo, hi = np.nanmin(yy), np.nanmax(yy)
        ok60 = lambda n: lo - (hi - lo) <= at_power(n, f[n], rp.STEPS[-1]) <= hi + (hi - lo)
        ext = next((n for n in sorted(names, key=lambda n: (f[n]["loro_mae"], list(M).index(n))) if ok60(n)), "line")
        lin, b = f["line"], f[best]
        rows.append({"sensor": s, "group": grp, "best_model": best, "n_min": int(k.sum()),
                     "r2_line": lin["r2"], "r2_best": b["r2"], "mae_line": lin["mae"], "mae_best": b["mae"],
                     "loro_mae_line": lin["loro_mae"], "loro_mae_best": b["loro_mae"],
                     "loro_mae_cut_pct": 100 * (1 - b["loro_mae"] / lin["loro_mae"]) if lin["loro_mae"] > 0 else 0.0,
                     "at_60kW_line": at_power("line", lin, rp.STEPS[-1]), "at_60kW_best": at_power(best, b, rp.STEPS[-1]),
                     "best_r2_any": max(f[n]["r2"] for n in names),
                     "extrap_model": ext, "r2_extrap": f[ext]["r2"], "mae_extrap": f[ext]["mae"],
                     "loro_mae_extrap": f[ext]["loro_mae"], "at_60kW_extrap": at_power(ext, f[ext], rp.STEPS[-1])})
        keep[s] = {"mask": k, "line": lin, "best": (best, b), "extrap": (ext, f[ext])}
    return pd.DataFrame(rows), keep


def apply_best(t, fits):
    """Write each sensor's best plausible curve (fit_all "extrap") into t's use_<p>kW columns (steady state at p kW)
    and its name into t.model."""
    for s, f in fits.items():
        name, b = f["extrap"]
        m = t.sensor == s
        t.loc[m, "model"] = name
        for p in rp.STEPS:
            t.loc[m, f"use_{p}kW"] = at_power(name, b, p)


GRAY, BLUE, ORANGE = "#9aa4b3", "#2f5f9e", "#d9822b"


def plot_rows(d, res, fits, sensors, axs):
    """One row per sensor on axs (n x 2): left = reading vs power, right = reading over the part-load minutes."""
    R = res.set_index("sensor")
    P_all, minute = d["P_dc_kW"].values, np.arange(len(d))
    bounds = np.flatnonzero(np.diff(d["run"].values)) + 0.5
    pg = np.linspace(0, P_all.max(), 50)
    for (a, c), s in zip(axs, sensors):
        r, f = R.loc[s], fits[s]
        m, y = f["mask"], d[s].values
        name, b = f["best"]
        a.scatter(P_all[m], y[m], s=4, color=GRAY)
        a.plot(pg, f["line"]["coef"][0] + f["line"]["coef"][1] * pg, color=BLUE, lw=1.2, label="line")
        if name == "quadratic":
            a.plot(pg, [at_power(name, b, p) for p in pg], color=ORANGE, lw=1.2, label=name)
        elif name != "line":
            a.scatter(P_all[m], b["pred"], s=4, color=ORANGE, label=name)
        a.set_xlabel("DC power, kW", fontsize=7); a.tick_params(labelsize=6)
        a.legend(fontsize=6, loc="best")
        c.plot(minute[m], y[m], ".", ms=2.5, color=GRAY, label="plant")
        c.plot(minute[m], f["line"]["pred"], color=BLUE, lw=0.9, label=f"line R² {r.r2_line:.2f}, MAE {r.mae_line:.3g}")
        if name != "line":
            c.plot(minute[m], b["pred"], color=ORANGE, lw=0.9, label=f"{name} R² {r.r2_best:.2f}, MAE {r.mae_best:.3g}")
        for x in bounds:
            c.axvline(x, color=GRAY, lw=0.4, ls=":")
        c.set_xlabel("part-load minute (dotted = next run)", fontsize=7); c.tick_params(labelsize=6)
        c.legend(fontsize=6, loc="best")
        a.set_title(f"{s}  ·  {r.group}", fontsize=8, loc="left")
        c.set_title(f"best: {name} · held-out MAE {r.loro_mae_line:.3g} → {r.loro_mae_best:.3g} ({r.loro_mae_cut_pct:.0f} % less)",
                    fontsize=8, loc="left")
    for a, c in axs[len(sensors):]:
        a.axis("off"); c.axis("off")


def plot_all(d, res, fits, path, per_page=6):
    """Every sensor in res, per_page rows per A4 page, by group then best R²."""
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    order = res.sort_values(["group", "r2_best"], ascending=[True, False]).sensor.tolist()
    with PdfPages(path) as pdf:
        for i in range(0, len(order), per_page):
            fig, axs = plt.subplots(per_page, 2, figsize=(11.7, 16.5), gridspec_kw={"width_ratios": [1, 1.6]})
            plot_rows(d, res, fits, order[i:i + per_page], axs)
            fig.tight_layout()
            pdf.savefig(fig); plt.close(fig)


def self_check():
    run = np.repeat([1, 2, 3, 4], 40)
    P = np.tile(np.r_[np.linspace(3, 30, 20), np.full(20, 30.0)], 4) * np.repeat([1, 0.8, 0.6, 0.9], 40)
    L = {t: lag(P, run, t) for t in TAUS}
    assert L[5][0] == P[0] * (1 - np.exp(-1 / 5)) and L[5][40] < P[40]            # lag restarts from 0 each run
    y = 100 + 4 * L[20]                                                           # a pure 20-min lag response
    M = models(P, L)
    f = fit_sensor(y, P, L, run, M)
    best = pick(f, list(M))[0]
    assert best == "lag 20 min" and f[best]["r2"] > 0.999 and f["line"]["r2"] < f[best]["r2"], best
    assert abs(at_power(best, f[best], 60) - 340) < 1e-6


if __name__ == "__main__":
    self_check()
    d = rp.pl_minutes()
    t = rp.extrapolate(d)
    res, fits = fit_all(d, t)
    res.to_csv(rp.OUT / "curve_fits.csv", index=False)
    plot_all(d, res, fits, rp.OUT / "curve_fit_plots.pdf")
    print(res.groupby("group")[["r2_line", "r2_best", "loro_mae_cut_pct"]].median().round(3))
