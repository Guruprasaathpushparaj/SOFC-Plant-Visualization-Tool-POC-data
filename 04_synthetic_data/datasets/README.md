# Synthetic plant datasets

Each folder is **one made-up plant run** from the 2D twin, run without its window (`../twin_dataset.js`, or the
dataset app `../dataset_app.bat`). One row per minute. The data is smooth (no sensor noise) and is twin physics, not
plant data.

## The three runs

| Folder | Length | What happens | Rows |
|---|---|---|---|
| `twin_181d_85pct_4pl_1cs_4rp4h` | 181 days | 4 part loads, each going up to rated power for 4 h; 1 cold shutdown; availability 85 % | 260,640 |
| `twin_181d_85pct_4pl_1cs_4rp50h` | 181 days | the same, with 50 h of rated power each time | 260,640 |
| `twin_steady_41162h` | 1,717 days (4.7 years) | heat up → 1 h hot standby → **41,162 h of part load** → 1 h hot standby → air flow cooling → shutdown | 2,472,786 |

## Stage names

The twin app shows seven stages. The data files (`plant_stage` column, `events.csv`, `summary.json`) keep the twin's
storage names for them:

| Stage in the twin app | Name in the files | What happens |
|---|---|---|
| Heat up | `Heat-up air`, then `Heat-up N₂+H₂` | the stack is heated in air (25 → 211 °C), then under forming gas (→ 495 °C) |
| Hot standby | `Fuel switch` | natural gas on, no current |
| Part load | `Part load` | power at low current (about 6 A per string, 14.6 kW) |
| Rated power | `Rated power` | 30 A per string, 52 kW; reached only from part load |
| Air flow cooling | `Air-flow cooling` | air cools the stack down to 40 °C |
| Shutdown | `Shutdown` | plant off |
| Trip / Emergency purge | `Trip: purge` | emergency stop (in none of the runs here) |

The storage names stay on purpose: the twin reads them back when it replays a file (Source → Data file…), and its own
"Save data" writes them the same way. A file that said `Hot standby` would replay as Heat up.

Short names in folder names and in `summary.json` → `order`: SU = heat up (start up), HS = hot standby, PL = part load,
RP = rated power, CS = cold shutdown, SD = shutdown.

---

# 181-day runs

Each runs 181 days (1 Jan 00:00 → 1 Jul 00:00 2027). The twin presses its own buttons in a fixed story: it **heats up
from 25 °C at minute 0**, cycles hot standby ↔ part load (some part loads go up to rated power and back), has a cold
shutdown in the middle, and **ends in shutdown**. Availability is exact to the minute.

## Reading a folder name

`twin_181d_85pct_4pl_1cs_4rp4h`

| Part | Means |
|---|---|
| `181d` | length of the run in days |
| `85pct` | **availability 85 %**: share of time in hot standby, part load or rated power |
| `4pl` | 4 × part load |
| `1cs` | 1 × cold shutdown (plant cools and stays off, then heats up again) |
| `4rp4h` | 4 × rated power, 4 hours each (left out when there is none) |

## The two runs

They are the same run except for how long each rated-power spell lasts.

| Folder | Availability | Part loads | Rated power | Hot standbys | Cold shutdowns | Highest stack T at rated power |
|---|---|---|---|---|---|---|
| `twin_181d_85pct_4pl_1cs_4rp4h` | 85 % | 4 | 4 × 4 h (960 min) | 6 | 1 | 968 °C |
| `twin_181d_85pct_4pl_1cs_4rp50h` | 85 % | 4 | 4 × 50 h (12,000 min) | 6 | 1 | 984 °C |

Stage order (both): SU HS PL RP HS PL RP HS CS HS PL RP HS PL RP HS SD. Efficiency: about 18 % in part load, 48 % at
rated power. The twin never trips or cools the stack by temperature, so stack temperatures at rated power go far above
the plant's 720 °C trip limit.

---

# Steady run (41,162 h)

Made with `node 04_synthetic_data/twin_dataset.js --steady-hours 41162` (folder name `twin_steady_<hours>h`).

41,162 h is the longest cell life in the NEST stack data for the Elcogen stacks (condition S0054, 30 A held; cell 16).
Only this timing is taken from the NEST data: current, voltage and fuel are the twin's own.

| Stage | Minutes |
|---|---|
| Heat up | 734 (273 in air, 461 under forming gas) |
| Hot standby | 121 (1 h before and 1 h after part load) |
| Part load | 2,469,720 (exactly 41,162 h) |
| Air flow cooling | 2,210 |
| Shutdown | 1 (the file ends at plant off) |

Period 1 Jan 2027 00:00 → 14 Sep 2031 05:06.

- Part load settles after about 10 h: stack 758.2 °C, 14.6 kW. From then on the rows are the same apart from the time.
- The stack safety thermocouple `TIRZ_8_1_3` reads 789 °C all through part load, above the plant's 720 °C limit
  (the twin never trips on temperature).
- 23 MB compressed, about 2.4 GB once loaded in pandas: read it in parts if memory is short.

---

## Files in each folder

| File | What it is | Open with |
|---|---|---|
| `sofc_twin_dataset.csv.gz` | **The dataset.** One row per minute: `timestamp`, `minute`, `plant_stage` + 120 sensor and calculated columns (same columns as the twin's "Save data") | Python / pandas, or the 2D twin: Source → Data file… |
| `events.csv` | One row per stage change: minute, time, stage, stack temperature | Excel |
| `summary.json` | Counts, minutes per stage, availability, efficiency, highest stack temperature | Text editor |
| `preview.json` | Hourly summary the dataset app uses to draw its charts | (dataset app) |

New runs from the dataset app are saved here and listed under "Saved datasets". See `../README.md` for all options.

Stitched 200-hour runs (`200h_…_seed<seed>/`, made from real plant minutes by `../pattern_filler.py`) also land in
this folder. None are here at the moment; they use the plant data's own eight stage names (see `../README.md`).
