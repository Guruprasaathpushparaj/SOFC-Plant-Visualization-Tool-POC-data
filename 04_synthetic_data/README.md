# 04_synthetic_data

Makes new, realistic plant days by stitching together real stage episodes.

| Step | File | What it does |
|---|---|---|
| 1 | `build_library.py` | Builds `library/` from the real data: every stage episode, minute traces, stage-to-stage transitions |
| 2 | `pattern_generator.py` | Random stage order for a chosen total time (only allowed stage changes) → `datasets/seed_<seed>/pattern_<seed>.csv` (plan only) |
| 2b | `pattern_app.py` | Same, with a point-and-click screen: `cd "04_synthetic_data" && streamlit run pattern_app.py` |
| 3 | `pattern_filler.py` | Fills each block of a pattern with real sensor data → `synthetic_<seed>.parquet` + `.png`; the folder is renamed by availability and stage counts, e.g. `datasets/200h_af32pct_…_seed7/` (see `datasets/README.md`) |
| 4 | `to_twin.py` | Parquet → `synthetic_<seed>.csv.gz` in the same folder (heater power W→kW, −1 → blank). Play it in the 2D twin: Source → Data file (101 of 111 twin sensors filled by name) |

Stages: planning (library, generator, app) uses the old 7 operating stages on purpose. The synthetic parquet also has a `plant_stage` column with the decided 8 plant stages, copied from the real minute behind each row (`03_data_analysis/plant_stages/plant_stages_1min.parquet`). So Fuel switch, Air-flow cooling and Shutdown come out as parts of old-stage blocks; you cannot order them as blocks.

## Twin dataset app (2026-11-06)

**Open:** double-click `dataset_app.bat`. It starts a small local server (`dataset_app/server.js`, no window, this PC only, port 8517)
and opens the app (`dataset_app/index.html`) in its own Edge / Chrome window. The server stops by itself about 40 s after the
last app window closes. Pick start date, days, availability, part loads, cold shutdowns (hot standbys follow), press Make dataset:
progress bar, then availability, counts, stage strip + stack temperature, time per stage, stage changes and downloads.
Saved datasets (with `preview.json`) are listed and can be reopened.

**Needs:** Node.js on the PATH, Edge or Chrome, `curl.exe` (built into Windows 10/11), and the sibling folder `05_twin_2d`
(`app.js`, `data/sensors.js`, `data/bends.js`). No Python, no packages. Internet only for the Geist font and the icons
(without it the app falls back to system fonts and shows no icons).

**Command line (same generator):**
`node twin_dataset.js --days 181 --availability 95 --part-loads 5 --cold-shutdowns 1 [--hot-standbys 7] [--rated-powers 0] [--rated-hours 4] [--start 2027-01-01] [--out folder] [--check]`
→ `datasets/twin_<days>d_<availability>pct_<P>pl_<C>cs/` (`sofc_twin_dataset.csv.gz`: one row per minute, the twin's "Save data" columns + `timestamp`;
`events.csv`; `summary.json`; `preview.json` for the app). About 40 s per 6 months.

**v2.6 (2026-11-09):** the data has the twin v3.5 efficiency columns (`eta_module_pct`, `eta_string1..5_pct`; gross DC,
gas split 1/5 per string). `summary.json` adds `eta_part_load_pct` / `eta_rated_pct` (median module efficiency) and `sensors`
(column count); the app shows them as an Efficiency tile. Datasets made before v2.6 have no efficiency columns.

**Story:** runs the 2D twin (`05_twin_2d/app.js`, unchanged, headless) and presses its buttons. Start up from 25 °C at minute 0 →
hot standby → part loads and cold shutdowns (Shut down, cool to < 40 °C, air off, stay, Start plant), each between hot standbys →
final Shut down, plant off to the end. Twin rules (fuel switch only from hot standby, part load always back to hot standby) give
hot standbys = part loads + cold shutdowns + 1. No trips. Availability = part load + hot standby + fuel switch over the period
(as `03_data_analysis/scripts/availability.py`) and is exact: the last hot standby ends on the target minute. Part load and hot
standby share the available time 4 : 1 (fixed ±20 % cycle); the extra not available time is split over the cold shutdown stays and
the final plant off time. Minimum not available time ≈ 735 (start up) + 2,070 (final cooling) + 2,805 per cold shutdown minutes;
the generator stops with a message when the target cannot be met. It checks every count, the exact availability, first stage
heat up air and last stage shutdown.

`library/traces_1min.parquet` is also read by several notebooks in `03_data_analysis/`.
Explained in `06_deliverables/05_synthetic_data/`.
