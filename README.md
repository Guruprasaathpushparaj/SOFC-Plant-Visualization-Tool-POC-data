# SOFC plant POC — START HERE

This folder holds a proof-of-concept study of a **60 kW solid oxide fuel cell (SOFC) plant**.
We used **39 days of plant logger data** (2025-10-30 → 2026-03-30) to:

1. split the plant's operation into **stages** (heat-up, hot standby, part load, shutdown, …),
2. understand what every **sensor** does in each stage,
3. generate **synthetic (fake but realistic) plant data**, and
4. build a small **2D digital twin** you can open in a browser.

---

## Where to start (pick your goal)

| I want to… | Open this |
|---|---|
| **Understand the results without code** | [06_deliverables/](06_deliverables/): plain-language PDF reports, numbered in reading order. Start with `01_plant_and_sensors/sofc-plant-explained.pdf`, then `02_operating_stages/plant-stages-explained.pdf` |
| **See the plant come alive** | [05_twin_2d/](05_twin_2d/): double-click `app.bat` (see [How to start the apps](#how-to-start-the-apps)) |
| **Learn how the plant is meant to work** | [01_docs/](01_docs/): plant drawings, the stage definitions (`operational-modes.md`) and the sensor/safety map (`component_sensor_map_en.md`) |
| **Re-run or check the analysis** | [03_data_analysis/](03_data_analysis/): Jupyter notebooks + the Python scripts behind them (see its README) |
| **Make synthetic data** | [04_synthetic_data/](04_synthetic_data/) (see its README): stitched real episodes, or months of twin data at a chosen availability (`dataset_app.bat`) |
| **Play back a data file in the twin** | [05_twin_2d/](05_twin_2d/): top bar **Source → Data file…**, open a generated `.csv.gz`, a Save data file or a logger day file |

---

## Folder map

```
01_POC/
├── README.md               ← you are here
├── 01_docs/                plant reference: drawings, sensor lists, stage definitions (input material)
├── 02_data/                the raw and processed plant data (28 GB, read-only input)
├── 03_data_analysis/       notebooks + scripts that turn raw data into stages and findings
│   ├── *.ipynb             one notebook per question (see 03_data_analysis/README.md for the order)
│   ├── scripts/            shared Python code the notebooks import
│   └── <name>/             results (CSV, PNG, parquet) of the notebook/script with the same name
├── 04_synthetic_data/      builds the episode library and makes new fake plant days
├── 05_twin_2d/             2D digital twin (local web page)
├── 06_deliverables/        finished reports (PDF / Excel), grouped by topic 01…07
└── graphify-out/           auto-generated code map (graph.html); safe to ignore
```

The numbers follow the work: reference → data → analysis → synthetic data → twin → reports.

> **Do not rename** `01_docs` … `05_twin_2d`: the scripts find each other by these exact folder names.

---

## How the pieces connect

```
02_data/raw  (logger .txt, 1 per day)
     │  03_data_analysis/scripts/downsample.py
     ▼
02_data/parquet (1 s)  →  02_data/downsampled (10 s)
     │  03_data_analysis/scripts/operating_states.py   (stage rules from 01_docs/operational-modes.md)
     ▼
operating stages per minute
     │  03_data_analysis/scripts/plant_stages.py        (the 8 decided plant stages)
     ▼
03_data_analysis/plant_stages/plant_stages_1min.parquet
     ├──► analysis notebooks (start-up, shutdown, slopes, heaters, availability …) ─► 06_deliverables/
     ├──► 04_synthetic_data/  (episode library → random stage pattern → synthetic day)
     └──► 05_twin_2d/tools/prep.py, bends.py  (sensor fits for the digital twin)
                │
                ▼
          05_twin_2d/app.js (the twin)
                │  04_synthetic_data/twin_dataset.js   (runs the twin headless: any days, availability, stage counts)
                ▼
          04_synthetic_data/twin_<days>d_<avail>pct_<P>pl_<C>cs/sofc_twin_dataset.csv.gz
                │  twin Source → Data file…
                ▼
          played back in 05_twin_2d
```

## The 8 plant stages (the key idea in this project)

| Stage | What the plant is doing |
|---|---|
| Heat-up air | start-up, only hot air is blown through the stack |
| Heat-up N₂+H₂ | start-up, protective forming gas on (stack above ~210 °C) |
| Hot standby | stack hot and ready, no power drawn |
| Fuel switch | natural gas on, no current yet |
| Part load | the plant is making power (full rated power was never reached) |
| Air-flow cooling | shutting down, air still blowing to cool the stack |
| Shutdown | everything off except the controls |
| Trip / emergency purge | safety stop: only air, N₂, H₂ and controls on |

Defined in `03_data_analysis/scripts/plant_stages.py`, explained in `06_deliverables/02_operating_stages/plant-stages-explained.pdf`.

## Setup

Python 3.13, then once from this folder:

```
python -m pip install -r requirements.txt
```

The 2D twin needs no Python, only Edge or Chrome. The twin dataset maker (`04_synthetic_data/twin_dataset.js`) also needs
[Node.js](https://nodejs.org) on the PATH; its app needs streamlit (in `requirements.txt`).

## How to start the apps

**2D digital twin** (`05_twin_2d/`). Pick one:

| Way | What to do |
|---|---|
| App window (easiest) | Double-click `05_twin_2d/app.bat`. It opens in its own Edge or Chrome window, no server needed |
| Desktop icon | Double-click `05_twin_2d/install_shortcut.bat` once. A "SOFC Plant Twin" icon appears on the desktop |
| Browser | Double-click `05_twin_2d/start.bat` (needs Python). It serves the page at http://localhost:8765 and opens it. Close the black window to stop it |
| Plain file | Double-click `05_twin_2d/index.html` |

The twin opens in Shutdown. Press **Start plant** to run a cold start. To watch a data file instead of the simulation, pick
**Source → Data file…** in the top bar (play speed up to 1 day per second, slider to jump); **Source → Twin** goes back.

**Twin dataset app** (`04_synthetic_data/dataset_app.bat`): double-click it. It opens in its own Edge or Chrome window. Pick
days and availability, press **Make dataset**, then download the result. Close the minimized "SOFC dataset app" window to stop it.
Command line instead: `node 04_synthetic_data/twin_dataset.js --days 181 --availability 95` (all options in `04_synthetic_data/README.md`).

**Synthetic-data pattern app** (`04_synthetic_data/pattern_app.py`):

```
cd 04_synthetic_data
streamlit run pattern_app.py
```

It opens at http://localhost:8501. Press Ctrl+C in the terminal to stop it.

**Notebooks**:

```
cd 03_data_analysis
jupyter lab
```

Run the notebooks from inside `03_data_analysis/` because they import from `scripts/`.

**Tests**: `python -m pytest 03_data_analysis/tests`
