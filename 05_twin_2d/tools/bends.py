"""Stage-border bends for the 2D twin: how the slope changes when the plant moves from one stage to the next.
The bend and jerk method is imported from 03_data_analysis/scripts/slopes_jerk.py (one copy only), so the twin's
bend panel shows the same numbers as the analysis: per border type (clean borders) slope before/after, bend time,
median curve -45..+60 min (border_type_curves) and median peak acceleration / jerk within ±15 min (border_table).
Signals: stack T and heaters (mean of EAGH, EAOH1, EAOH2).
Writes 05_twin_2d/data/bends.js (loaded by index.html).
Run from anywhere: python 05_twin_2d/tools/bends.py"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "03_data_analysis" / "scripts"))
import slopes_jerk as sj  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "bends.js"
SIG = {"stack": ("T_stack_C", "Stack T"), "heaters": ("T_heaters_C", "Heaters T")}  # bends.js key: (frame column, border_table name)

d = sj.load_frame()
curves, cj = sj.border_type_curves(d, signals=[c for c, _ in SIG.values()])
bt = sj.border_table(d)
peaks = bt[bt.clean].groupby(["frm", "to", "signal"])[["accel_max", "jerk_max"]].median()
tm = np.array(cj["minutes"])

out = []
for (a, b), g in curves.groupby(["frm", "to"]):
    e = {"from": a, "to": b, "n": int(g.borders.max()), "sig": {}}
    for k, (c, name) in SIG.items():
        r = g[g.signal == c]
        if r.empty:
            continue
        r = r.iloc[0]
        pk = peaks.loc[(a, b, name)] if (a, b, name) in peaks.index else None
        e["sig"][k] = {"n": int(r.borders), "pre": round(float(r.before), 1), "post": round(float(r.after), 1),
                       "bend": None if np.isnan(r.bend_t90_min) else [int(r.bend_t10_min), int(r.bend_t90_min)],
                       "acc": None if pk is None else round(float(pk.accel_max), 2),
                       "jerk": None if pk is None else round(float(pk.jerk_max), 2),
                       "curve": [None if z is None else round(z, 1) for z in cj["curves"][f"{a} > {b}"][c]]}
    out.append(e)
out.sort(key=lambda e: -e["n"])

# Plant warming speed for the twin's warming stages: median stack slope (9-min smoothed, °C/h)
# per stage x 100 °C band x air level (strong = air > 7000 ln/min); cells with >= 30 min only.
WARM = ["Heat-up air", "Heat-up N₂+H₂", "Fuel switch", "Part load"]
x = d.reindex(pd.date_range(d.index[0], d.index[-1], freq="1min"))
# min_periods=3 (as slopes_jerk._smooth): windows shrink at day/log edges instead of blanking the first/last ~9 min
x["slope"] = x.T_stack_C.rolling(9, center=True, min_periods=3).mean().diff().rolling(9, center=True, min_periods=3).mean() * 60
x["band"] = (x.T_stack_C // 100 * 100).clip(0, 600)
x["strong"] = x.F_air > 7000
tab = (x[x.plant_stage.isin(WARM)].dropna(subset=["slope", "band"])
       .groupby(["plant_stage", "strong", "band"]).slope.agg(["median", "size"]).reset_index())
tab = tab[tab["size"] >= 30]
warm = [{"stage": r.plant_stage, "strong": bool(r.strong), "band": int(r.band), "slope": round(float(r["median"]), 1), "min": int(r["size"])}
        for _, r in tab.iterrows()]

OUT.write_text("window.SOFC_BENDS=" + json.dumps({"tm": [int(tm[0]), int(tm[-1])], "borders": out, "warm": warm}, ensure_ascii=False) + ";\n",
               encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")
print(f"{sum(e['n'] for e in out)} clean borders, {len(out)} border types -> {OUT}")
for e in out:
    s = e["sig"].get("stack", {})
    h = e["sig"].get("heaters", {})
    print(f"{e['from']:>17} -> {e['to']:<17} n={e['n']:>2}  stack {s.get('pre', 0):+6.1f} -> {s.get('post', 0):+6.1f} bend {s.get('bend')} "
          f"jerk {s.get('jerk')}  | heaters {h.get('pre', 0):+6.1f} -> {h.get('post', 0):+6.1f} bend {h.get('bend')} jerk {h.get('jerk')}")
print("warming speed table (°C/h):")
for w in warm:
    print(f"  {w['stage']:<15} {'strong' if w['strong'] else 'normal'} {w['band']:>3}–{w['band'] + 99} °C  {w['slope']:+6.1f}  ({w['min']} min)")
