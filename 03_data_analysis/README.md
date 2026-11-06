# 03_data_analysis: notebooks and scripts

Each notebook answers one question. Its results go into the sub-folder with the same name
(e.g. `startup_analysis.ipynb` → `startup/`). Shared code lives in `scripts/`.

**Run notebooks with `03_data_analysis/` as the working folder**: they do `sys.path.insert(0, "scripts")`
and read data from `../02_data/`.

## Notebooks in reading order

| # | Notebook | Question it answers | Results in |
|---|---|---|---|
| 1 | `preprocessing.ipynb` | Clean the logger data, keep the sensors the stage rules need | `preprocessing/`, `../02_data/preprocessed_stage/` |
| 2 | `operating_states.ipynb` | Label every minute with a stage (§12 = the **8 decided plant stages**) | `operating_states/`, `plant_stages/` |
| 3 | `stage_sensor_runs.ipynb` | Stage sensors drawn over each run of consecutive days | — |
| 4 | `industrial_stages.ipynb` | Same stages mapped to industry codes S0–S8 | `industrial_stages/` |
| 5 | `startup_analysis.ipynb` | Start-up: heat-up recipe, rates, gases, timing | `startup/` |
| 6 | `thermal_adjustment_analysis.ipynb` | Re-heats and cool-backs of a hot stack | `thermal_adjustment/` |
| 7 | `part_load_analysis.ipynb` | Part load: current ramps, cell voltage, exhaust trips | `part_load/` |
| 8 | `shutdown_analysis.ipynb` | Shutdown: cool-down rates, forced cooling | `shutdown/` |
| 9 | `cold_idle_analysis.ipynb` | Plant-off hours | `cold_idle/` |
| 10 | `excel_sensor_analysis.ipynb` | Is every sensor in the Excel list logged and useful? | `excel_sensors/` |
| 11 | `sensors_by_stage.ipynb` | How each of 156 sensors behaves per stage | `sensors_by_stage/` |
| 12 | `stage_vs_other_correlation.ipynb` | Do the non-stage sensors follow the stage sensors? | `stage_corr/` |
| 13 | `heater_temperatures.ipynb` | Stack temperature vs the gas-line heaters | `heater_temperatures/` |
| 14 | `slopes_jerk.ipynb` | Heating/cooling slopes and bends at stage borders | `slopes_jerk/` |

## scripts/: the shared code

| Script | What it does |
|---|---|
| `downsample.py` | raw `.txt` → 1 s parquet → 10 s parquet (`02_data/`) |
| `operating_states.py` | Stage rules for one day (based on `../01_docs/operational-modes.md`) |
| `plant_stages.py` | **The 8 decided plant stages** for all days → `plant_stages/plant_stages_1min.parquet` |
| `industrial_stages.py`, `ladder_stages.py`, `stage_crosswalk.py` | Other ways of naming / detecting the same stages |
| `stage_split.py` | Cut the 1 s data into one file per stage episode → `02_data/by_stage/` |
| `stage_signals.py` | Loader shared by the per-stage notebooks |
| `flow_check.py` | Check that stages follow each other in an allowed order |
| `trip_check.py` | Find safety trips and check trip limits |
| `heater_temps.py`, `slopes_jerk.py` | Code behind notebooks 13 and 14 |
| `availability.py` | Plant availability (run: `python scripts/availability.py`) → `availability/` |
| `efficiency_check.py` | Calculated efficiency / fuel use |
| `correlation_common.py` | Correlation across all columns → `correlation/` |

`sensor_trace/`: traces every tag of the Excel sensor list to a logged column (`analyse.py`, then `classify.py`).

`blocks.csv`: loose table (2026-11-03), one row per plant-stage block with start/end stack temperature and
heating rate. Nothing in the project reads it; the maintained version is `plant_stages/plant_stage_blocks.csv`.
