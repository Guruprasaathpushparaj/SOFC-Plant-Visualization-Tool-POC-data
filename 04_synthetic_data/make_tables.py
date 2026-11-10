"""Relational CSV tables of a twin dataset run: one fact table (readings) + lookup \
tables joined by keys.

    python 04_synthetic_data/make_tables.py [datasets/twin_181d_85pct_4pl_1cs_4rp4h]  \
-> 04_synthetic_data/<run>/tables/

Keys: stage_id (stages), component_id (components), sensor_id (sensors = readings \
column names), episode_id (episodes).
Sources: <run>/sofc_twin_dataset.csv.gz + events.csv, 05_twin_2d/data/sensors.js \
(prep.py fits), 05_twin_2d/app.js PARTS,
03_data_analysis/scripts/plant_stages.py, \
03_data_analysis/plant_stages/plant_stage_transitions.csv (real plant counts).
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RUN = (
    ROOT
    / "04_synthetic_data"
    / (sys.argv[1] if len(sys.argv) > 1 else "datasets/twin_181d_85pct_4pl_1cs_4rp4h")
)
OUT = RUN / "tables"
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT / "03_data_analysis" / "scripts"))
import plant_stages as ps  # noqa: E402

# 1. stages ----------------------------------------------------------------------------
DESC = dict(
    re.findall(r"^    (\S.*?)\s{2,}(.+)$", ps.__doc__, re.M)
)  # the 8 lines of the plant_stages docstring
TWIN = {
    "Heat-up air": "Heat up",
    "Heat-up N₂+H₂": "Heat up",
    "Hot standby": "Heat up",
    "Fuel switch": "Hot standby",
    "Air-flow cooling": "Air flow cooling",
    "Trip: purge": "Trip / Emergency purge",
}
stages = pd.DataFrame(
    {
        "stage_id": range(1, len(ps.STAGES) + 1),
        "stage": ps.STAGES,
        "twin_label": [TWIN.get(s, s) for s in ps.STAGES],
        "description": [DESC.get(s.split()[0], DESC.get(s, "")) for s in ps.STAGES],
        "colour": [ps.COLORS[s] for s in ps.STAGES],
    }
)
stages.loc[stages.stage == "Shutdown", "description"] = " ".join(
    line.strip()
    for line in ps.__doc__[
        ps.__doc__.index("everything off") : ps.__doc__.index("Trip: purge")
    ].splitlines()
).strip()
SID = dict(zip(stages.stage, stages.stage_id))

# 2. components (twin app PARTS) -------------------------------------------------------
app = (ROOT / "05_twin_2d" / "app.js").read_text(encoding="utf-8")
# whitespace-tolerant: app.js is prettier-formatted
parts = re.findall(
    r'^\s*(\w+):\s*\{\s*title:\s*"([^"]+)",\s*desc:\s*"([^"]+)"',
    app[re.search(r"const PARTS\s*=", app).start() :],
    re.M,
)
heaters = set(
    re.search(r"const HEATERS\s*=\s*new Set\(\[(.*?)\]\)", app, re.S)
    .group(1)
    .replace('"', "")
    .replace(" ", "")
    .split(",")
)
components = pd.DataFrame(parts, columns=["component_id", "title", "description"])
components["is_heater"] = components.component_id.isin(heaters)

# 3. sensors + per-stage fits (sensors.js) ---------------------------------------------
js = (ROOT / "05_twin_2d" / "data" / "sensors.js").read_text(encoding="utf-8")
data = json.loads(js[js.index("{") : js.rindex("}") + 1])
# the 3 load-bank totals are twin-calculated sensors added by app.js, not by prep.py
tot = re.findall(
    r'\{\s*tag:\s*"([^"]+)",\s*col:\s*"(\w+)",\s*desc:\s*"([^"]+)",'
    r'\s*unit:\s*"(\w+)",\s*fits:\s*\{\}\s*,?\s*\}',
    app,
)
data["components"]["load"] += [
    {"tag": t, "col": c, "desc": d, "unit": u, "fits": {}} for t, c, d, u in tot
]
srows, frows = [], []
for comp, items in data["components"].items():
    for r in items:
        srows.append(
            {
                "sensor_id": r["col"],
                "tag": r["tag"],
                "description": r["desc"],
                "unit": r["unit"],
                "component_id": comp,
                "rated_value": r.get("rated", {}).get("v"),
                "rated_model": r.get("rated", {}).get("model"),
            }
        )
        for stg, f in r["fits"].items():
            frows.append(
                {
                    "sensor_id": r["col"],
                    "stage_id": SID[stg],
                    "intercept": f[0],
                    "slope_per_degC": f[1],
                    "p02": f[2],
                    "p10": f[3],
                    "p50": f[4],
                    "p90": f[5],
                    "p98": f[6],
                    "n_minutes": f[7],
                }
            )
sensors, fits = (
    pd.DataFrame(srows),
    pd.DataFrame(frows).sort_values(["sensor_id", "stage_id"], kind="stable"),
)

# 4. stage supply flows (plant medians per stage, from sensors.js flows) ---------------
FLOW = {
    "air": "cathode_air_ln_min",
    "12": "pox_air_ln_min",
    "13": "n2_ln_min",
    "14": "natural_gas_ln_min",
    "15": "h2_ln_min",
    "I": "string_current_A",
}
flows = pd.DataFrame(
    [
        {"stage_id": SID[s], **{FLOW[k]: v for k, v in d.items()}}
        for s, d in data["flows"].items()
    ]
).sort_values("stage_id")

# 5. stage transitions counted in the real plant data ----------------------------------
tr = pd.read_csv(
    ROOT / "03_data_analysis" / "plant_stages" / "plant_stage_transitions.csv",
    index_col=0,
)
transitions = tr.stack().rename("count").reset_index()
transitions.columns = ["from_stage", "to_stage", "count"]
transitions = transitions[transitions["count"] > 0]
transitions.insert(0, "to_stage_id", transitions.pop("to_stage").map(SID))
transitions.insert(0, "from_stage_id", transitions.pop("from_stage").map(SID))

# 6. episodes + readings (the dataset itself) ------------------------------------------
raw = pd.read_csv(next(RUN.glob("*.csv.gz")))
ev = pd.read_csv(RUN / "events.csv")
ev["end_minute"] = ev.minute.shift(-1, fill_value=len(raw)) - 1
episodes = pd.DataFrame(
    {
        "episode_id": range(1, len(ev) + 1),
        "stage_id": ev.stage.map(SID),
        "start_minute": ev.minute,
        "end_minute": ev.end_minute,
        "start_time": raw.timestamp.iloc[ev.minute].values,
        "end_time": raw.timestamp.iloc[ev.end_minute].values,
        "duration_min": ev.end_minute - ev.minute + 1,
        "stack_C_start": ev.stack_C,
        "stack_C_end": raw.T_stack_C.iloc[ev.end_minute].round(1).values,
    }
)
readings = raw.rename(columns={"plant_stage": "stage_id"})
readings["stage_id"] = readings.stage_id.map(SID)
readings["episode_id"] = episodes.episode_id.repeat(episodes.duration_min).values
readings = readings[
    ["minute", "timestamp", "episode_id", "stage_id"]
    + [c for c in raw.columns if c in set(sensors.sensor_id)]
]

# self-check: every key in the fact tables resolves, every sensor column is described
assert set(raw.columns) - {"timestamp", "minute", "plant_stage"} <= set(
    sensors.sensor_id
), "undescribed sensor column"
assert (
    readings.stage_id.notna().all()
    and readings.episode_id.notna().all()
    and len(readings) == len(raw)
)
assert (readings.groupby("episode_id").stage_id.nunique() == 1).all()
assert (
    fits.stage_id.notna().all()
    and transitions.from_stage_id.notna().all()
    and transitions.to_stage_id.notna().all()
)
assert set(sensors.component_id) <= set(components.component_id)

for name, df in [
    ("stages", stages),
    ("components", components),
    ("sensors", sensors),
    ("sensor_stage_fits", fits),
    ("stage_flows", flows),
    ("stage_transitions", transitions),
    ("episodes", episodes),
]:
    df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")
readings.to_csv(OUT / "readings.csv.gz", index=False, compression="gzip")
print(
    {
        n: len(pd.read_csv(OUT / f"{n}.csv"))
        for n in [
            "stages",
            "components",
            "sensors",
            "sensor_stage_fits",
            "stage_flows",
            "stage_transitions",
            "episodes",
        ]
    },
    "readings",
    readings.shape,
)
