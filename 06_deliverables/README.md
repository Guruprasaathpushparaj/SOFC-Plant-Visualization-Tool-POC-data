# deliverables: finished reports

Plain-language reports (PDF) and result tables (Excel), written for readers without a coding background.
**New reader? Start with `poc-story-explained.pdf`** (this folder): the whole POC in one report: dataset, stage separation, why 8 stages, each stage in detail, findings, the twin app.
Then read the folders in number order. Inside each folder, the **bold** file is the best place to start.

| Folder | Topic | Start with |
|---|---|---|
| `01_plant_and_sensors/` | What the plant is, which sensors exist, which are logged, data gaps | **sofc-plant-explained.pdf** |
| `02_operating_stages/` | How the operation is cut into stages, from the first try to the 8 decided plant stages | **plant-stages-explained.pdf** (final result); **stage-atlas-explained.pdf** = one chapter per stage + what changes at every stage move; the others show how we got there |
| `03_sensors_and_devices_per_stage/` | What each sensor, heater and device does in each stage | **sensors-by-stage-explained.pdf** |
| `04_plant_behaviour_and_performance/` | Heating/cooling speeds, trips, stack voltage, availability, efficiency, rated-power estimate | **stack-slopes-explained.pdf** |
| `05_synthetic_data/` | How synthetic plant data is made and how ready it is | **synthetic-data-step1-explained.pdf** |
| `06_digital_twin/` | The 2D twin: plan, physics, checks against the real plant | **digital-twin-plan-explained.pdf** |
| `07_project_tools_and_code_health/` | Code quality check and tooling notes | **codebase-health-explained.pdf** |

Excel files: `01_plant_and_sensors/sensor-list-traced-and-rated.xlsx` (every listed sensor, traced and rated),
`04_plant_behaviour_and_performance/all-curve-slopes.xlsx` (slope of every changing curve per stage).
