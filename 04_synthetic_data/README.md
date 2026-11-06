# 04_synthetic_data

Makes new, realistic plant days by stitching together real stage episodes.

| Step | File | What it does |
|---|---|---|
| 1 | `build_library.py` | Builds `library/` from the real data: every stage episode, minute traces, stage-to-stage transitions |
| 2 | `pattern_generator.py` | Random stage order for a chosen total time (only allowed stage changes) → `patterns/pattern_<seed>.csv` |
| 2b | `pattern_app.py` | Same, with a point-and-click screen: `cd "04_synthetic_data" && streamlit run pattern_app.py` |
| 3 | `pattern_filler.py` | Fills each block of a pattern with real sensor data → `patterns/synthetic_<seed>.parquet` + `.png` |

Stages: planning (library, generator, app) uses the old 7 operating stages on purpose. The synthetic parquet also has a `plant_stage` column with the decided 8 plant stages, copied from the real minute behind each row (`03_data_analysis/plant_stages/plant_stages_1min.parquet`). So Fuel switch, Air-flow cooling and Shutdown come out as parts of old-stage blocks; you cannot order them as blocks.

`library/traces_1min.parquet` is also read by several notebooks in `03_data_analysis/`.
Explained in `06_deliverables/05_synthetic_data/`.
