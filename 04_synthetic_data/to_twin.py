"""Turn pattern-filler datasets (datasets/<day>/synthetic_*.parquet) into files the 2D twin can play.

    python "04_synthetic_data/to_twin.py"                       # every datasets/*/synthetic_*.parquet
    python "04_synthetic_data/to_twin.py" "04_synthetic_data/datasets/200h_af32pct_4hua_4hun_5hs_3fs_3pl_7afc_7sd_seed7/synthetic_7.parquet"

Writes synthetic_<name>.csv.gz next to each parquet. Open it in the twin with
Source -> Data file. The twin matches columns by sensor name (101 of its 111 sensors are in the
datasets; the 5 heater currents and 5 TotalVoltage_M* stay blank) and takes the stage from plant_stage.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def to_twin(src: Path) -> Path:
    d = pd.read_parquet(src).replace(-1, np.nan)   # -1 = logger fill value (twin tools/prep.py clean())
    assert d["EIRC_2_01_ActV_In_ThreePhasePower"].max() > 1000, f"{src.name}: heater power not in W, already converted?"
    d["EIRC_2_01_ActV_In_ThreePhasePower"] /= 1000  # W -> kW, as tools/prep.py
    d["plant_stage"] = d["plant_stage"].replace("No data", "")  # blank -> the twin's own stage rules
    out = src.with_suffix(".csv.gz")
    d.to_csv(out, date_format="%Y-%m-%d %H:%M", index_label="Date Time")
    return out


if __name__ == "__main__":
    files = [Path(a) for a in sys.argv[1:]] or sorted((HERE / "datasets").glob("*/synthetic_*.parquet"))
    for f in files:
        print(to_twin(f))
