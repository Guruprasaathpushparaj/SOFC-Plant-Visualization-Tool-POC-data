# Graph Report - 01_POC  (2026-11-05)

## Corpus Check
- 43 files · ~144,337 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 185 file(s) not represented in the graph (top: .csv 148, .parquet 18, .ipynb 15)

## Summary
- 780 nodes · 1574 edges · 38 communities (33 shown, 5 thin omitted)
- Extraction: 95% EXTRACTED · 5% INFERRED · 0% AMBIGUOUS · INFERRED: 72 edges (avg confidence: 0.8)
- Token cost: 362,792 input · 0 output

## Community Hubs (Navigation)
- 2D twin and P&ID page
- Twin app engine (app.js)
- Operating-state rules
- Plant stages and trips
- Plant layout drawing
- Stage signals and Q&A notebooks
- Stage splitter and trip check
- Raw data loading and prep
- Synthetic day filler
- 106-sensor heatmap
- Pattern generator CLI
- Ladder logic and crosswalk
- Flow check per stage
- Episode library builder
- Operating modes (doc)
- Episode library class
- Stack heaters and trips
- Heater temperatures
- Slopes and jerk tables
- Docs index and safety refs
- Mode flow diagram (Korean)
- Availability
- Library bounds and flows
- Air path and exhaust trips
- Gas phase and standby literature
- Stage literature and patents
- Heat-up and cooling runs
- Curve slopes and lags
- Pattern Streamlit app
- Gas supply plan rules
- Safety limits and transitions
- Stage-border bends
- String power and voltages
- Real supply profiles
- Hot-standby exits
- Random stage order
- Stage block CSVs

## God Nodes (most connected - your core abstractions)
1. `SOFC Plant Twin (2D, local)` - 27 edges
2. `segment()` - 16 edges
3. `run_all()` - 16 edges
4. `index.html (twin page layout)` - 16 edges
5. `fill()` - 15 edges
6. `generate()` - 15 edges
7. `One notebook per question, results in same-name folder` - 15 edges
8. `106 Other Sensors: How to Make Them in Each Stage (heatmap)` - 15 edges
9. `The 8 plant stages` - 14 edges
10. `render()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `System layout with sensors.png` --references--> `PCM (power conditioning module)`  [EXTRACTED]
  05_twin_2d/README.md → 01_docs/System layout with sensors.png
- `Linked stages chain (v26)` --semantically_similar_to--> `Allowed stage changes rule`  [INFERRED] [semantically similar]
  05_twin_2d/README.md → 04_synthetic_data/README.md
- `System layout with sensors.png` --references--> `FPM (fuel processing module, gas supply area)`  [EXTRACTED]
  05_twin_2d/README.md → 01_docs/System layout with sensors.png
- `System layout with sensors.png` --references--> `Fraunhofer IKTS`  [EXTRACTED]
  05_twin_2d/README.md → 01_docs/System layout with sensors.png
- `System layout with sensors.png` --references--> `KSOE Phase II project`  [EXTRACTED]
  05_twin_2d/README.md → 01_docs/System layout with sensors.png

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **SOFC operating stage cycle (Start-up -> Hot standby -> Part load -> Shut-down)** — 01_docs_operational_modes_start_up, 01_docs_operational_modes_hot_standby, 01_docs_operational_modes_thermal_adjustment, 01_docs_operational_modes_part_load, 01_docs_operational_modes_shut_down, 01_docs_operational_modes_idle [EXTRACTED 1.00]
- **Fuel path NG -> ejector -> reformer -> EAGH -> stack anode** — 01_docs_component_sensor_map_en_firc_1_4, 01_docs_component_sensor_map_en_ejector, 01_docs_component_sensor_map_en_reformer, 01_docs_component_sensor_map_en_eagh, 01_docs_component_sensor_map_en_stack_module, 01_docs_component_sensor_map_en_eaoh3 [EXTRACTED 1.00]
- **Temperature trips feeding SPLC_EMERGENCYPURGE** — 01_docs_component_sensor_map_en_tirz_8_1_1_trip, 01_docs_component_sensor_map_en_tirz_8_1_3_trip, 01_docs_component_sensor_map_en_tirz_8_1_9_trip, 01_docs_component_sensor_map_en_tirz_8_1_10_trip, 01_docs_component_sensor_map_en_heater_trips_950, 01_docs_component_sensor_map_en_splc_emergencypurge [EXTRACTED 1.00]
- **Raw logger to plant-stage labelling pipeline** — 03_data_analysis_scripts_downsample, 02_data_parquet, 03_data_analysis_scripts_operating_states, 03_data_analysis_scripts_plant_stages, 03_data_analysis_plant_stages_plant_stages_1min [EXTRACTED 1.00]
- **Synthetic plant day generation pipeline** — 04_synthetic_data_build_library, 04_synthetic_data_library_traces_1min, 04_synthetic_data_pattern_generator, 04_synthetic_data_pattern_filler, 04_synthetic_data_patterns [EXTRACTED 1.00]
- **Twin generated data build and load** — 05_twin_2d_tools_prep, 05_twin_2d_tools_bends, 05_twin_2d_data_sensors, 05_twin_2d_data_bends, 05_twin_2d_app, 05_twin_2d_index [EXTRACTED 1.00]
- **Per-stage derivability of the 106 sensors from the 50** — 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_106_other_sensors, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_fifty_core_sensors, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_stage_idle, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_stage_start_up, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_stage_hot_standby, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_stage_thermal_adjustment, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_stage_part_load, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_stage_shutdown_cooling, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_stage_shutdown_ambient [EXTRACTED 1.00]
- **Six cell categories of the derivability heatmap** — 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_cat_follows, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_cat_partly_follows, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_cat_own_behaviour, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_cat_flat, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_cat_too_few_examples, 01_docs_106_other_sensor_data__in_relation_with_the_50_sensors_and_stages_cat_no_data [EXTRACTED 1.00]
- **Start-up sequence Cold → 510 °C → hold → Hot standby** — 01_docs_flow_diagram_cold, 01_docs_flow_diagram_heatup_stage1, 01_docs_flow_diagram_intermediate_hold, 01_docs_flow_diagram_hot_standby [EXTRACTED 1.00]
- **Load cycle Hot standby ↔ Part load ↔ Rated power** — 01_docs_flow_diagram_hot_standby, 01_docs_flow_diagram_load_ramp_up, 01_docs_flow_diagram_part_load, 01_docs_flow_diagram_rated_power, 01_docs_flow_diagram_load_ramp_down [EXTRACTED 1.00]
- **Shut-down sequence ramp-down → Hot standby → 300 °C → Cold** — 01_docs_flow_diagram_load_ramp_down, 01_docs_flow_diagram_cooldown, 01_docs_flow_diagram_near_300c, 01_docs_flow_diagram_cold [EXTRACTED 1.00]
- **Cathode air path: supply line -> TWV -> EAPH -> SOFC stack** — 01_docs_system_layout_with_sensors_cathode_air_line, 01_docs_system_layout_with_sensors_twv, 01_docs_system_layout_with_sensors_eaph, 01_docs_system_layout_with_sensors_sofc_stack [EXTRACTED 1.00]
- **Fuel/anode path: NG line -> Desulf -> compressor -> ejector -> reformer -> EAGH -> stack** — 01_docs_system_layout_with_sensors_fuel_ng_line, 01_docs_system_layout_with_sensors_desulf, 01_docs_system_layout_with_sensors_compressor_storage_unit, 01_docs_system_layout_with_sensors_ejector, 01_docs_system_layout_with_sensors_reformer, 01_docs_system_layout_with_sensors_eagh, 01_docs_system_layout_with_sensors_sofc_stack [INFERRED 0.75]
- **Flue gas path: burner -> APH1 + APH2 in parallel -> exhaust (TIRZ 8.1.10)** — 01_docs_system_layout_with_sensors_burner, 01_docs_system_layout_with_sensors_aph1, 01_docs_system_layout_with_sensors_aph2, 01_docs_system_layout_with_sensors_tirz_8_1_10 [EXTRACTED 1.00]

## Communities (38 total, 5 thin omitted)

### Community 0 - "2D twin and P&ID page"
Cohesion: 0.05
Nodes (41): component_sensor_map_en.md (sensor/safety map), operational-modes.md (stage definitions), System layout with sensors.png, Fraunhofer IKTS, KSOE Phase II project, PGM (power generation module, hot box), shutdown_analysis.ipynb, Allowed stage changes rule (+33 more)

### Community 1 - "Twin app engine (app.js)"
Cohesion: 0.10
Nodes (50): applyRules(), blendRestart(), buildReadings(), checkTrip(), drawBend(), drawPlots(), drawTrend(), eased() (+42 more)

### Community 2 - "Operating-state rules"
Cohesion: 0.07
Nodes (24): apply_context(), blocks(), classify_row(), count_episodes(), fuel_rules(), gas_phase(), last_stage(), load_signals() (+16 more)

### Community 3 - "Plant stages and trips"
Cohesion: 0.06
Nodes (21): industrial_stages.ipynb (S0-S8), operating_states.ipynb (sec 12 = 8 plant stages), plant_stages_1min.parquet, add_codes(), blocks(), code_of(), episodes(), plot_band() (+13 more)

### Community 4 - "Plant layout drawing"
Cohesion: 0.06
Nodes (39): APH1 air pre-heater 1 (flue gas heat exchanger), APH2 air pre-heater 2 (flue gas heat exchanger), Burner / after-burner (H2+CO+O2 -> CO2+H2O), Cathode Air supply line (V1.1.1, MV1.1.1, F1.1, PR1.1.1/PR1.1.2, MV1.1.2/MV1.1.3), Haug compressor-storage unit (3-stage compressor, 15 bar storage tank, RVL), Condensate drain (LIR 7.01, V7.01), Safety PLC, Control Unit, UPS and BoP components, Desulfurisation (Desulf, dp max 150 mbar) (+31 more)

### Community 5 - "Stage signals and Q&A notebooks"
Cohesion: 0.06
Nodes (23): cold_idle_analysis.ipynb, excel_sensor_analysis.ipynb, part_load_analysis.ipynb, preprocessing.ipynb, Excel sensor list tag tracing, band_rates(), _columns(), episodes() (+15 more)

### Community 6 - "Stage splitter and trip check"
Cohesion: 0.10
Nodes (20): 02_data/by_stage episode files, build(), file_id(), file_path(), load_episode(), load_labels(), load_stage(), pieces() (+12 more)

### Community 7 - "Raw data loading and prep"
Cohesion: 0.09
Nodes (13): 02_data/parquet (1 s) and downsampled (10 s), cluster_order(), heatmap(), load_day(), main(), top_pairs(), check(), downsample() (+5 more)

### Community 8 - "Synthetic day filler"
Cohesion: 0.13
Nodes (16): air_cost(), ambient_start_T(), best(), blend(), chain(), fill(), hold(), mix_cost() (+8 more)

### Community 9 - "106-sensor heatmap"
Cohesion: 0.10
Nodes (29): 106 Other Sensors, Category: Flat, Category: Follows the 50, Category: No data, Category: Own behaviour, Category: Partly follows, Category: Too few examples, The 50 Core Sensors (+21 more)

### Community 10 - "Pattern generator CLI"
Cohesion: 0.13
Nodes (15): main(), canon(), durations(), generate(), labels(), main(), order_closest(), parse_pairs() (+7 more)

### Community 11 - "Ladder logic and crosswalk"
Cohesion: 0.12
Nodes (10): Other ways of naming/detecting the same stages, contacts(), output_filter(), run(), scan(), tof(), ton(), run() (+2 more)

### Community 12 - "Flow check per stage"
Cohesion: 0.17
Nodes (14): band_rate(), check_adjust(), check_idle(), check_load(), check_shutdown(), check_standby(), check_startup(), episodes() (+6 more)

### Community 13 - "Episode library builder"
Cohesion: 0.17
Nodes (11): stitch(), episodes(), flag_faults(), folds(), label_all(), load_sensors(), main(), quiet() (+3 more)

### Community 14 - "Operating modes (doc)"
Cohesion: 0.18
Nodes (19): TIR4.6.1-4.6.36 stack module thermocouples, Ambient proxy (median of TIR_1_1_1, TIR_1_2_1, TIR_1_3, TIR_1_4_1), Cool-down rate -45 to -75 C/h March (limit 120 C/h), Elcogen E3000 stacks (manual), Heat-up interrupted (plant off) 2026-03-17/18, Heat-up rate ~50-56 C/h (limit 120 C/h), Hot standby, Idle (plant off, stack warm) (+11 more)

### Community 15 - "Episode library class"
Cohesion: 0.11
Nodes (5): real_library(), Library, phase_mix(), raw_extra(), real_minutes()

### Community 16 - "Stack heaters and trips"
Cohesion: 0.18
Nodes (18): Anode off-gas path (TIRC5.2.x anode outlet), Cathode off-gas path (TIRC5.1.x, TWV1/2_COG), EAGH reformate line heater (TIRC3.1.1), EAOH1 TOX branch heater (TIRC5.3.1), EAOH2 TOX branch heater (TIRC5.3.2), EAOH3 recycle heater (TIRC6.1.1), Ejector (AOG recycle), ERH reformer/burner housing heater (TIRC5.17, EIRC5.1.3, 3.3 kW) (+10 more)

### Community 17 - "Heater temperatures"
Cohesion: 0.14
Nodes (8): heater_temperatures.ipynb, heater_panels(), heater_states(), load_heaters(), plot_stretch(), stage_table(), stretches(), legend_handles()

### Community 18 - "Slopes and jerk tables"
Cohesion: 0.19
Nodes (8): all_column_slopes(), band(), centred_rate(), column_area(), column_kind(), sensor_descriptions(), slope_group(), stack_rate_table()

### Community 19 - "Docs index and safety refs"
Cohesion: 0.13
Nodes (13): ICA List PoC Prototype (20241113_ICA_List_PoC_Prototype.xlsm), Instrument Map by Component (ICA List), PoC PFD/P&ID Rev 1.9, Safety Functions + Test Instructions (S-PLC 0xB9E8), SPLC_EMERGENCYSTOP safety state, Unprotected anode cooling hypothesis, docs folder README, 03_data_analysis/excel_sensor_analysis.ipynb (+5 more)

### Community 20 - "Mode flow diagram (Korean)"
Cohesion: 0.24
Nodes (15): Flow Diagram (SOFC mode transitions, Korean notes), Cold mode (ambient ~20 °C), Cool-down (Shut-down stage 2), Heat-up stage 1 (to ~510 °C at ~50 °C/h), Hot standby (power 0, stable temp, 575-600 °C), Intermediate hold (~510 °C, hours to ~2 days), Load ramp-down (Shut-down stage 1, -1 to -3 A/min/str; stop 8 A/10 s), Load ramp-up (0.3-0.9 A/min/str, ~2 kW/min) (+7 more)

### Community 21 - "Availability"
Cohesion: 0.22
Nodes (8): forced_mask(), load(), main(), numbers(), trip_recovery(), plant_days(), blocks(), stage_map()

### Community 22 - "Library bounds and flows"
Cohesion: 0.15
Nodes (8): flow_levels(), library(), flow_levels(), flow_medians(), library_bounds(), library_counts(), sub_pieces(), with_air()

### Community 23 - "Air path and exhaust trips"
Cohesion: 0.18
Nodes (13): APH-1 / APH-2 air preheaters, EAPH electric air pre-heater (40 kW), EIRC2.01 EAPH power controller (pi_EIRC_2_01_ActV_*), Exhaust (TIR7.05, PIR7.03), FIRC1.1.1 MFC-Air-1 flow, FIRC1.1.2 MFC-Air-2 flow, FIRC1.1.3 3-way valve TWV-CA, FPM cathode air system 1.1 (+5 more)

### Community 24 - "Gas phase and standby literature"
Cohesion: 0.18
Nodes (13): FIRC1.3 nitrogen MFC, FIRC1.5 hydrogen MFC, Heater on without air (false start), gas_phase column (Natural gas, Forming gas, N2 purge, Air only, Plant off), Hot standby low-temperature hold (~510 C, >=6 h), Pre-load (ready for load), Cold standby (200 C hold), Hanasaki et al. 2014 JES, SOFC durability against standby and shutdown (+5 more)

### Community 25 - "Stage literature and patents"
Cohesion: 0.18
Nodes (13): arXiv 1806.04506 power surges in fuel-cell data centers, Bloom patent US7846599B2 (start up / shutdown), Bloom load-following SOFC whitepaper (2024), Generating / normal operating mode, IEC 62282 fuel cell standards (not verified), JQME 2020 multi-stack SOFC reliability, LG patent US10622649, Load-following operation (+5 more)

### Community 26 - "Heat-up and cooling runs"
Cohesion: 0.17
Nodes (8): cooling_runs(), _cut_at_gap(), _days(), heatup_runs(), load_all_columns(), load_frame(), run_all(), summarise_blocks()

### Community 27 - "Curve slopes and lags"
Cohesion: 0.18
Nodes (6): block_ids(), line_slope(), onset_lags(), other_curve_slopes(), stack_block_slopes(), stage_runs()

### Community 29 - "Gas supply plan rules"
Cohesion: 0.20
Nodes (6): fix_gas(), gas_faults(), _merge(), plan_phases(), scale_runs(), _take()

### Community 30 - "Safety limits and transitions"
Cohesion: 0.20
Nodes (10): PIRZ8.1.2 pressure monitoring (assignment unconfirmed), SPLC_EMERGENCYPURGE safety state, TIRC5.09 representative TOX temperature, TIRZ8.1.3 stack trip > 720 C, TIRZ8.1.9 afterburner trip > 930 C, IKTS Commissioning Overview, Operating window (inlet 580 C, max 720 C), Stage transition map (ALLOWED / DESIGN) (+2 more)

### Community 31 - "Stage-border bends"
Cohesion: 0.24
Nodes (6): bend_time(), border_shape(), border_table(), border_type_curves(), _grid(), _smooth()

### Community 32 - "String power and voltages"
Cohesion: 0.29
Nodes (7): EIRC4.s.2 load current monitor (EIRC_4s_CurrentMon), EIRC4.s.1 load voltage monitor (EIRC_4s_VoltageMon), Knowledge map edges/edges.yaml, Minimum cell voltage EIRC_4s_ActV_Min_CellVoltage, El.Load4.1-4.5 programmable loads (14 kW each), String power = EIRC4.s.1 x EIRC4.s.2 / 1000, TotalVoltage_Ms (sum of 4 stack voltages)

### Community 33 - "Real supply profiles"
Cohesion: 0.29
Nodes (4): plot(), phase_profiles(), runs_of(), step_name()

## Ambiguous Edges - Review These
- `Haug compressor (NG booster)` → `PIRZ8.1.2 pressure monitoring (assignment unconfirmed)`  [AMBIGUOUS]
  01_docs/component_sensor_map_en.md · relation: conceptually_related_to
- `SPLC_EMERGENCYPURGE safety state` → `8 A / 10 s step drop at load stop`  [AMBIGUOUS]
  01_docs/operational-modes.md · relation: conceptually_related_to
- `Hot standby (power 0, stable temp, 575-600 °C)` → `Part load (0 < P < rated, measured 9-34 kW)`  [AMBIGUOUS]
  01_docs/Flow_diagram.png · relation: conceptually_related_to
- `FIRC 1.1.1 / 1.1.2 / 1.1.3 cathode air flow controllers` → `TIR 2.05 temperature before EAPH`  [AMBIGUOUS]
  01_docs/System layout with sensors.png · relation: conceptually_related_to

## Knowledge Gaps
- **66 isolated node(s):** `Flow_diagram.png (process flow diagram)`, `System layout with sensors.png`, `106 other sensors vs 50 stage sensors chart`, `03_data_analysis/excel_sensor_analysis.ipynb`, `ICA List PoC Prototype (20241113_ICA_List_PoC_Prototype.xlsm)` (+61 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 251 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `SOFC Plant Twin (2D, local)` connect `2D twin and P&ID page` to `Twin app engine (app.js)`, `Plant stages and trips`, `Raw data loading and prep`?**
  _High betweenness centrality (0.243) - this node is a cross-community bridge._
- **What connects `Flow_diagram.png (process flow diagram)`, `System layout with sensors.png`, `106 other sensors vs 50 stage sensors chart` to the rest of the system?**
  _66 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `2D twin and P&ID page` be split into smaller, more focused modules?**
  _Cohesion score 0.05310734463276836 - nodes in this community are weakly interconnected._
- **Why does `System layout with sensors.png` connect `2D twin and P&ID page` to `Plant layout drawing`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Should `Twin app engine (app.js)` be split into smaller, more focused modules?**
  _Cohesion score 0.09993011879804332 - nodes in this community are weakly interconnected._

### Low-confidence Hints
_AMBIGUOUS edges — the extractor was unsure. Verify before acting on these._

- **What is the exact relationship between `Haug compressor (NG booster)` and `PIRZ8.1.2 pressure monitoring (assignment unconfirmed)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `SPLC_EMERGENCYPURGE safety state` and `8 A / 10 s step drop at load stop`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._