"""SOFC plant availability from the decided plant stages (plant_stages.py output).

Every logged minute is put in one of four buckets:
  power   - Part load (plant delivers current)
  ready   - Hot standby, Fuel switch (hot, can take load within minutes)
  planned - Heat-up air, Heat-up N2+H2, Air-flow cooling, Shutdown (not able to \
deliver, by choice)
  forced  - Trip: purge, plus the time after a trip until the plant is ready again
'No data' minutes are left out of the period.

Two rules for the time after a trip (decision still open):
  strict  - everything from the trip cut until the next Hot standby / Part load minute \
is forced
  lenient - if the plant was cooled down after the trip, only the first 15 minutes are \
forced
            (the cool-down is treated as a planned stop)

Numbers (IEEE Std 762 style):
  AF   availability factor     = (power + ready) / period
  SF   service factor          = power / period
  FOR  forced outage rate      = forced / (forced + power)
  Ai   inherent availability   = MTBF / (MTBF + MTTR)
       MTBF = hot hours (power + ready) / trips, MTTR = mean hours from trip to ready
  EAF  equivalent availability = AF x (best reachable power / rated power)

Run:  python scripts/availability.py      (from 03_data_analysis/)
Writes availability/availability_summary.csv, availability/trip_recovery.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
OUT = BASE / "availability"

BUCKET = {
    "Part load": "power",
    "Hot standby": "ready",
    "Fuel switch": "ready",
    "Heat-up air": "planned",
    "Heat-up N₂+H₂": "planned",
    "Air-flow cooling": "planned",
    "Shutdown": "planned",
    "Trip: purge": "forced",
    "No data": "nodata",
}
RATED_KW = 60.0
BEST_KW = 51.0  # part-load extrapolation (46-56 kW), see sofc synthetic data notes
LENIENT_FORCED_MIN = 15


def load():
    d = pd.read_parquet(BASE / "plant_stages" / "plant_stages_1min.parquet")
    trips = pd.read_csv(
        BASE / "industrial_stages" / "trip_windows.csv",
        parse_dates=["start", "end", "first cut"],
    )
    d["bucket"] = d["plant_stage"].map(BUCKET)
    return d, trips


def trip_recovery(d, trips):
    """Per trip: when it happened, when the plant was ready again, and whether it was \
cooled down."""
    rows = []
    for _, t in trips.iterrows():
        t0 = t["start"]  # trip window start from industrial_stages.trip_windows
        after = d.loc[t0 + pd.Timedelta(minutes=1) :]
        hits = after.index[after["plant_stage"].isin(["Hot standby", "Part load"])]
        if (
            hits.empty
        ):  # data ends before the plant recovered: no recovery time to count yet
            continue
        t1 = hits[0]
        seg = d.loc[t0 : t1 - pd.Timedelta(minutes=1)]
        cooled = (seg["plant_stage"] == "Air-flow cooling").sum() > 30
        rows.append(
            dict(
                trip=int(t["trip"]),
                cut=t0,
                ready_again=t1,
                clock_h=(t1 - t0).total_seconds() / 3600,
                logged_h=(seg["bucket"] != "nodata").sum() / 60,
                cooled_down=cooled,
            )
        )
    return pd.DataFrame(rows)


def forced_mask(d, rec, rule):
    m = pd.Series(False, index=d.index)
    for _, r in rec.iterrows():
        end = r.ready_again - pd.Timedelta(minutes=1)
        if rule == "lenient" and r.cooled_down:
            end = r.cut + pd.Timedelta(
                minutes=LENIENT_FORCED_MIN - 1
            )  # .loc is inclusive
        m.loc[r.cut : end] = True
    return m


def numbers(d, rec, sel, rule, label, period_h=None):
    x = d.loc[sel, "bucket"].copy()
    f = forced_mask(d, rec, rule)[sel]
    x[f & (x != "nodata")] = "forced"
    h = x[x != "nodata"].value_counts() / 60
    P, R, F = h.get("power", 0.0), h.get("ready", 0.0), h.get("forced", 0.0)
    T = period_h if period_h else h.sum()
    lo, hi = d.index[sel][0], d.index[sel][-1]
    r = rec[(rec.cut >= lo) & (rec.cut <= hi)]
    n = len(r)
    mtbf = (P + R) / n if n else np.nan
    mttr = (
        (
            r.logged_h
            if rule == "strict"
            else np.where(r.cooled_down, LENIENT_FORCED_MIN / 60, r.logged_h)
        ).mean()
        if n
        else np.nan
    )
    af = (P + R) / T
    return dict(
        label=label,
        rule=rule,
        period_h=T,
        power_h=P,
        ready_h=R,
        planned_h=h.get("planned", 0.0) + (T - h.sum()),
        forced_h=F,
        AF_pct=100 * af,
        SF_pct=100 * P / T,
        FOR_pct=100 * F / (F + P) if F + P else np.nan,
        trips=n,
        MTBF_h=mtbf,
        MTTR_h=mttr,
        Ai_pct=100 * mtbf / (mtbf + mttr) if n else np.nan,
        EAF_pct=100 * af * BEST_KW / RATED_KW,
    )


def main():
    d, trips = load()
    rec = trip_recovery(d, trips)
    allp = pd.Series(True, index=d.index).values
    mar = (d.index >= "2026-03-12") & (d.index < "2026-03-31")
    cal_mar_h = (
        pd.Timestamp("2026-03-31") - pd.Timestamp("2026-03-12")
    ).total_seconds() / 3600
    res = []
    for rule in ("strict", "lenient"):
        res.append(numbers(d, rec, allp, rule, "All 39 logged days"))
        res.append(numbers(d, rec, mar, rule, "12-30 Mar, logged hours"))
        res.append(
            numbers(
                d, rec, mar, rule, "12-30 Mar, clock hours (unlogged = off)", cal_mar_h
            )
        )
    res = pd.DataFrame(res)
    OUT.mkdir(exist_ok=True)
    res.round(2).to_csv(OUT / "availability_summary.csv", index=False)
    rec = rec.round({"clock_h": 2, "logged_h": 2})
    rec.to_csv(OUT / "trip_recovery.csv", index=False)
    pd.set_option("display.width", 220)
    print(rec.to_string(index=False))
    print(res.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
