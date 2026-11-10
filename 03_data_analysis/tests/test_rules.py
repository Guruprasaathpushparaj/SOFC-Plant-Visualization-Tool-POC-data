"""Small fake examples with known answers for the rules behind the report numbers.

Run:  python -m pytest 03_data_analysis/tests      (from 01_POC/)
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "scripts")
)  # scripts import each other by name
import availability as av  # noqa: E402
import industrial_stages as ins  # noqa: E402
import plant_stages as ps  # noqa: E402

T0 = pd.Timestamp("2026-03-01 00:00")


def minutes(n):
    return pd.date_range(T0, periods=n, freq="1min")


# ---- 1. availability numbers ---------------------------------------------------
def toy_trip_day():
    """65 min: 10 Part load, 5 purge, 40 Air-flow cooling, 10 Hot standby; one trip at \
minute 10."""
    stages = [ps.PL] * 10 + [ps.PURGE] * 5 + [ps.AFC] * 40 + [ps.HS] * 10
    d = pd.DataFrame({"plant_stage": stages}, index=minutes(65))
    d["bucket"] = d["plant_stage"].map(av.BUCKET)
    trips = pd.DataFrame({"trip": [1], "start": [T0 + pd.Timedelta(minutes=10)]})
    return d, av.trip_recovery(d, trips)


def test_every_plant_stage_has_a_bucket():
    assert set(ps.STAGES + ["No data"]) <= set(av.BUCKET)


@pytest.mark.parametrize(
    "rule, forced_min", [("strict", 45), ("lenient", av.LENIENT_FORCED_MIN)]
)
def test_forced_minutes_after_a_trip(rule, forced_min):
    d, rec = toy_trip_day()
    assert len(rec) == 1 and rec.cooled_down[0]  # 40 min of air cooling > 30
    assert rec.ready_again[0] == T0 + pd.Timedelta(
        minutes=55
    )  # first Hot standby minute
    n = av.numbers(d, rec, pd.Series(True, index=d.index).values, rule, "toy")
    assert n["forced_h"] * 60 == pytest.approx(forced_min)
    assert n["power_h"] * 60 == pytest.approx(10)
    assert n["FOR_pct"] == pytest.approx(100 * forced_min / (forced_min + 10))
    assert n["MTTR_h"] * 60 == pytest.approx(
        forced_min
    )  # MTTR uses the same forced length


def test_trip_without_recovery_is_skipped():
    d, _ = toy_trip_day()
    d = d.iloc[:55]  # data ends before Hot standby
    trips = pd.DataFrame({"trip": [1], "start": [T0 + pd.Timedelta(minutes=10)]})
    assert av.trip_recovery(d, trips).empty


# ---- 2. plant stage order ------------------------------------------------------
def test_gas_in_shutdown_is_cooling_and_gas_in_hot_standby_is_fuel_switch():
    s = pd.DataFrame(
        {
            "stage": ["Shut-down", "Hot standby"],
            "phase": ["Natural gas", "Natural gas"],
            "F_air": [ps.AIR_COOL + 100, ps.AIR_COOL + 100],
            "I_string_A": [0.0, 0.0],
        },
        index=minutes(2),
    )
    assert list(ps.base_stage(s)) == [ps.AFC, ps.FS]


# ---- 3. trip windows -----------------------------------------------------------
def cuts_at(*mins):
    return pd.DataFrame(
        {
            "time": [T0 + pd.Timedelta(minutes=m, seconds=20) for m in mins],
            "kind": ["EMERGENCY PURGE"] * len(mins),
        }
    )


def test_cuts_within_30_min_chain_into_one_trip():
    w = ins.trip_windows(cuts_at(0, 25, 50))
    assert len(w) == 1 and w["n cuts"][0] == 3
    assert w.start[0] == T0 + pd.Timedelta(
        minutes=1
    )  # the minute holding the cut keeps its stage
    assert w.end[0] == T0 + pd.Timedelta(minutes=51 + ins.TRIP_HOLD_MIN)  # = 66 min


def test_cuts_more_than_30_min_apart_are_two_trips():
    assert len(ins.trip_windows(cuts_at(0, 31))) == 2
