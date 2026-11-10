# Synthetic plant datasets

Each folder is **one made-up plant run**. There are two kinds:

| Kind | Folders | Length | Made from | Made by |
|---|---|---|---|---|
| **Stitched runs** | `200h_…_seed<seed>` (4) | 200 hours | Real plant minutes, copied stage by stage | `pattern_generator.py` → `pattern_filler.py` → `to_twin.py` |
| **Twin runs** | `twin_…` (2) | 181 days | The 2D twin, run without its window | Dataset app (`../dataset_app.bat`) or `../twin_dataset.js` |

---

# Stitched runs (200 h)

Each runs 200 hours (1 Jan 00:00 → 9 Jan 08:00 2026) and is stitched together from real stage episodes of the
plant. The folder name says how much of the time the plant was available and how many times it went through each stage.

## Reading a folder name

`200h_af32pct_4hua_4hun_5hs_3fs_3pl_7afc_7sd_seed7`

| Part | Means |
|---|---|
| `200h` | length of the run |
| `af32pct` | **availability 32 %**: share of time in Part load, Hot standby or Fuel switch (same rule as `03_data_analysis/scripts/availability.py`) |
| `4hua` | 4 × Heat-up with air |
| `4hun` | 4 × Heat-up with N₂ + H₂ |
| `5hs` | 5 × Hot standby |
| `3fs` | 3 × Fuel switch |
| `3pl` | 3 × Part load |
| `7afc` | 7 × Air-flow cooling |
| `7sd` | 7 × Shutdown |
| `1trip` | 1 × Trip / emergency purge (left out when there is none) |
| `seed7` | the random number that made it; same seed → same plan |

Counts are stage episodes in the `plant_stage` column (the 8 decided plant stages). Each folder comes from a plan
with 3 start-ups, 5 hot standbys, 3 part loads, 2 thermal adjustments and 4 shut-downs. The real episodes copied in
split these into more plant-stage episodes, so the counts differ from folder to folder.

## The four runs

| Folder | Availability | Part load episodes | Trips |
|---|---|---|---|
| `200h_af25pct_3hua_3hun_6hs_3fs_3pl_5afc_5sd_1trip_seed42` | 25 % | 3 | 1 |
| `200h_af32pct_4hua_3hun_6hs_4fs_3pl_6afc_6sd_seed419230` | 32 % | 3 | 0 |
| `200h_af32pct_4hua_4hun_5hs_3fs_3pl_7afc_7sd_seed7` | 32 % | 3 | 0 |
| `200h_af55pct_2hua_3hun_5hs_3fs_3pl_3afc_3sd_1trip_seed184571` | 55 % | 3 | 1 |

## Files in each folder (in the order they are made)

| File | What it is | Open with |
|---|---|---|
| `pattern_<seed>.csv` | **The plan.** One row per stage block: stage, start, end, hours | Excel |
| `pattern_<seed>_phases.csv` | The plan's gas / air supply steps inside each block, with flows (ln/min) | Excel |
| `pattern_<seed>.png` | Picture of the plan (stage timeline) | Image viewer |
| `synthetic_<seed>.parquet` | **The dataset.** One row per minute (12,000), all sensors, copied from real plant minutes | Python / pandas |
| `synthetic_<seed>_blocks.csv` | Which real episode filled each plan block, and how well it fits | Excel |
| `synthetic_<seed>.png` | Picture of the main sensors over the 200 h | Image viewer |
| `synthetic_<seed>.csv.gz` | **Twin-ready copy** of the dataset (heater power in kW). Open in the 2D twin: Source → Data file… | 2D twin |

## How the folders are made

```
pattern_generator.py / pattern_app.py  →  seed_<seed>/pattern_<seed>.csv       (plan only: named by seed)
pattern_filler.py / app "Save"         →  folder renamed to 200h_af…_seed<seed>/ + synthetic_<seed>.parquet
to_twin.py                             →  synthetic_<seed>.csv.gz in the same folder
```

A folder still called `seed_<seed>` is a plan that has not been filled yet.

---

# Twin runs (181 days)

Each runs 181 days (1 Jan 00:00 → 1 Jul 00:00 2027), one row per minute (260,640 rows). The twin presses its own
buttons in a fixed story: it **starts up from 25 °C at minute 0**, cycles hot standby ↔ part load (some part loads go up
to rated power and back), has a cold shutdown in the middle, and **ends in shutdown**. Availability is exact to the
minute. The data is smooth (no sensor noise) and is twin physics, not plant data.

## Reading a folder name

`twin_181d_85pct_4pl_1cs_4rp4h`

| Part | Means |
|---|---|
| `181d` | length of the run in days |
| `85pct` | **availability 85 %**: share of time in Part load, Rated power or Fuel switch (hot standby with gas on) |
| `4pl` | 4 × Part load |
| `1cs` | 1 × Cold shutdown (plant cools and stays off, then starts up again) |
| `4rp4h` | 4 × Rated power, 4 hours each (left out when there is none) |

## The two runs

They are the same run except for how long each rated-power spell lasts.

| Folder | Availability | Part loads | Rated power | Hot standbys | Cold shutdowns | Highest stack T at rated power |
|---|---|---|---|---|---|---|
| `twin_181d_85pct_4pl_1cs_4rp4h` | 85 % | 4 | 4 × 4 h (960 min) | 6 | 1 | 968 °C |
| `twin_181d_85pct_4pl_1cs_4rp50h` | 85 % | 4 | 4 × 50 h (12,000 min) | 6 | 1 | 984 °C |

Stage order (both): start up → HS → PL → RP → HS → PL → RP → HS → cold shutdown → HS → PL → RP → HS → PL → RP → HS →
shutdown. Efficiency: about 18 % in part load, 48 % at rated power. The twin never trips or cools the stack by
temperature, so stack temperatures at rated power go far above the plant's 720 °C trip limit.

## Files in each folder

| File | What it is | Open with |
|---|---|---|
| `sofc_twin_dataset.csv.gz` | **The dataset.** One row per minute: `timestamp`, `minute`, `plant_stage` + 120 sensor and calculated columns (same columns as the twin's "Save data") | Python / pandas, or the 2D twin: Source → Data file… |
| `events.csv` | One row per stage change: minute, time, stage, stack temperature | Excel |
| `summary.json` | Counts, minutes per stage, availability, efficiency, highest stack temperature | Text editor |
| `preview.json` | Hourly summary the dataset app uses to draw its charts | (dataset app) |

New runs from the dataset app are saved here and listed under "Saved datasets". See `../README.md` for all options.
