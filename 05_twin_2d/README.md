# SOFC Plant Twin (2D, local)

**Version 2.0 (2026-11-06, internal build v36)** – DC/DC per string, load bank totals (Σ P, Σ I, V) and load bank power trend. Release tag `v2.0`.

A small local website: redrawn plant schematic, knobs and playbooks, a fitted stack heat model with recuperator and air heater,
and clickable parts that show their sensor readings.

## Open it

- **As an app (2026-11-05):** double-click `app.bat` – opens the twin in its own Edge (or Chrome) window, no browser bar,
  no server. Run `install_shortcut.bat` once for a "SOFC Plant Twin" desktop icon (delete the icon to undo).
- **Installed app:** run `start.bat`, then in Edge/Chrome click the install icon in the address bar (or menu → Apps →
  Install this site as an app). It gets a Start-menu entry and keeps working offline after the first open, also when
  `start.bat` is not running (`sw.js` caches the files; it fetches fresh copies whenever the server is on).
- Or double-click `index.html` (works offline; fonts fall back to system fonts without internet).

**If it does not open on another PC** (`05_twin_2d` is self-contained, so copy just that folder if you like):
- Unzip first. Running `app.bat` from inside a .zip only unpacks the .bat, so the rest of the app is missing.
- Windows cannot start any `.bat` from a folder whose path contains `&` (e.g. `R&D`). Rename the folder or
  double-click `index.html`. Since 2026-11-06, `#` and `%` in the path work.
- `start.bat` needs Python on the PATH. `app.bat` needs Edge or Chrome in the default install folder.
- A desktop icon made by `install_shortcut.bat` still points to the old folder after a move. Run it again.

## Save a dataset

**Save data** (top bar, 2026-11-05) downloads the recorded minutes (up to the last 48 simulated hours) as CSV:
`minute, plant_stage`, then one column per sensor (114: 111 plant columns + 3 twin-calculated load-bank totals `P_total_kW`, `I_total_A`, `V_total_V`; empty = no reading). `histCsv()` in app.js.

## Files

| File | What it is |
|---|---|
| `index.html` | Page layout |
| `app.bat`, `install_shortcut.bat` | App window launcher, desktop icon |
| `manifest.webmanifest`, `sw.js`, `icons/` | Installable-app setup and offline cache |
| `style.css` | Colours (light and dark), layout |
| `app.js` | Heat model, stage rules, playbooks, schematic, sensor panel, trend |
| `data/sensors.js` | Sensor fits per plant stage, stage-change easing per slow sensor, median flows per stage (generated) |
| `tools/prep.py` | Rebuilds `data/sensors.js` from `02_data/downsampled` and `03_data_analysis/plant_stages/plant_stages_1min.parquet` |
| `data/bends.js` | Plant warming speed per stage × 100 °C band × air level, and the stage-border bend/jerk per border type (generated) |
| `tools/bends.py` | Rebuilds `data/bends.js` from the same two sources |

## Rebuild the data

```
python 05_twin_2d/tools/prep.py
python 05_twin_2d/tools/bends.py
```

Run it after new day files are added or the plant stages are relabelled (`03_data_analysis/scripts/plant_stages.py`).

## How the readings work

- Sensor panel (2026-11-04): click a part, a line (it highlights and shows the sensors of the part it belongs to) or a
  zone background (FPM supply, PGM process module, electrical loads) to list its sensors; chips above the list pick a
  zone or "All sensors" (114). Electrical (2026-11-06): DC/DC converters = per-string current, voltage, stack voltage (plant tags, also listed under the stack); load bank = the 3 calculated totals Σ P, Σ I, V = Σ P ÷ Σ I. In a group the list is split part by part. Every shown reading is recorded once per
  simulated minute (`recordAll()` → `S.hist[i].v`); a reading that changed in the last 24 h gets a small time plot
  (stage colour strip, same 24 h axis as the stack trend), tap to enlarge with axes and the trip line. Steady readings
  get no plot. Plots redraw at most 4×/s and only when on screen.

- Flows set by a knob (air, POx air, N₂, H₂, NG, current) read the knob.
- Stack temperature is the model value: one heat balance in every stage, fitted on the 39 days with the
  8 replay stretches held out:
  `dT/dt = k·(air/6000)^1.5·(Tin − T) + heaters + fuel + current − loss`
  - air exchange k = 0.561/h when the air warms the stack, 0.316/h when it cools it (the hot box gives heat back);
  - air-in Tin = recuperator `25 + e·(T − 25)`, e = 0.88 at 6000 → 0.83 at 8000+ ln/min; with heaters on the
    air heater ramps its outlet towards the target at the plant's 60 °C/h (max 40 kW); else a 10-min lag;
  - fuel heat 0.370 °C/h per ln/min natural gas, current 6.61 °C/h per A per string, hot-box heaters 7.62 °C/h,
    loss 0.0121/h × (T − 25).
  - All fitted numbers are re-made by `03_data_analysis/scripts/twin_fits.py` (results + app.js comparison in
    `03_data_analysis/twin_fits/`). 2026-11-05: fuel / current heat and EAPH efficiency refitted on the rebuilt stage
    file (were 0.386 / 6.34 / 0.89); 10 part-load runs: stack miss 11.82 → 12.06 °C, EAPH power 6.45 → 6.46 kW.
  Replay of 8 plant stretches: mean error 56 → 17.5 °C; every stage within ±20 °C on average except air-flow
  cooling at 9000 ln/min (recuperator weaker on that stretch than on the other days). Start plant button (cold start) uses the
  plant's settings (air heater 300 °C, 500 °C from 210 °C): 490 °C after 11.4 h (plant 11.6–12.0 h).
  `data/bends.js` "warm" (plant speed per stage) is no longer used by the model; the borders feed the bend panel.
- Fuel switch and part load (2026-11-04): the plant keeps the air heater on and holds the air-in at its target
  (580 °C fuel switch, 600 °C part load), also when the recuperator alone would be hotter (TWV-CA mixes in bypass air):
  with heaters on the twin's air-in now follows the target only, not `max(recuperator, target)`. Replay of the 10 plant
  part-load runs (8–44 min, plant knobs in): mean stack miss 4.2 °C (unchanged; the 8 other stretches unchanged too).
  The plant never ran part load longer than 44 min (stack up to 677 °C), so where it would settle is not in the data;
  at plant settings the twin keeps warming (settles ~759 °C).
- Stack safety: TIRZ 8.1.3 is no longer capped at the plant's p98, so the rule-check lamp follows the twin stack, and at
  720 °C the twin trips like the plant (16-min purge, PURGE_MIN). Part load: trip at a stack of ~696 °C.
- Stage rules (2026-11-04, user): trip purge only from hot standby or part load; after the purge the twin goes back to
  hot standby (air 6000, heaters on, air heater 500 °C, N₂ + H₂ on, gas/current off). Part load is always followed by
  hot standby: leaving part load any other way (Shut down, gas off, current 0) unloads to those settings
  (`followPartLoad` / `toStandby` in app.js). The only exception is a trip purge. Stage bar too: from part load a click on
  any stage other than hot standby unloads to hot standby instead of jumping (`jump()`); the bar shows "↩ Hot standby"
  after Part load.
- Names (2026-11-04, user): the "Shutdown" stage and "Shut down" button keep their plain names; the trip stage
  "Trip: purge" is shown as "Trip / Emergency purge" (stage bar, legend, pill, Trip button; display name only,
  `NAME`/`nm()` in app.js; data key stays "Trip: purge").
- Stack keeper (switch, default on, twin only): above 660 °C stack it raises the cathode air (+200 ln/min per min) to
  10000, then lowers the air-heater target (−5 °C per min, min 500 °C); below 655 °C it hands both back. At plant
  part-load settings: peak 675 °C, then 654–661 °C, safety TC ≤ 697 °C. Keeper off: trip after ~1.3 h.
- Air heater EAPH readings from the model (2026-11-04; `CALC`, `followRec`, `eaphIn`, `eaphPower` in app.js):
  outlet TIRC 2.06 = air-in Tin; inlet TIR 2.05 = recuperator air `Rb + Rg`, where Rb follows `25 + e·(T − 25)`
  (e 0.85 at 6000 → 0.87 at 9000 ln/min) with a 32-min lag and Rg = 0.85 °C per ln/min NG with a 32-min lag;
  with heaters on the inlet is capped at the outlet. Power = air·cp·(outlet − inlet) ÷ 0.909, 0–40 kW, 0 with heaters off.
  Fitted on the 39 days with the 8 replay stretches held out: inlet miss 23.5 → 12.6 °C (held out).
  Replay of the 8 stretches: power miss 1.42 → 0.66 kW, inside-stage match r 0.08 → 0.95; outlet 21.9 → 18.5 °C
  (heat-up/standby ≤ 2 °C); part load power still low (plant draws 15–23 kW late in part load without matching air warming).
  The stack heat balance keeps its old recuperator formula (`REC_PHYS=false`): the lagged one made the 9000-air
  cooling replay worse (74 → 156 °C). Stack results unchanged.
- The "Last stage change" panel compares the twin's slope before/after, bend time, peak acceleration and jerk with the
  plant median for the same border type (30-min fits each side, 10→90 % bend time, ±15 min peaks).
- Every other sensor: per plant stage, a straight-line fit against stack temperature (used where R² ≥ 0.25,
  else the stage median), kept inside the stage's p2–p98. This is what the plant typically showed, not a
  physics prediction per part.
- Stage-change jerk: for slow sensors (°C, heater A, kW, 3-way valve m³/h) and the 4 border types where ≥ 3 sensors
  moved clearly on the plant (heat-up air → N₂+H₂, shutdown → air-flow cooling, hot standby → fuel switch,
  fuel switch → part load), the reading blends from the old-stage line to the new-stage line on a minimum-jerk
  S-curve with the plant's delay and duration for that sensor (`ease` in `data/sensors.js`, from `tools/prep.py`:
  old line −30…−1 min, new line +30…+60 min, 10 → 90 % crossing). Flows, pressures and other borders step.
  Leave-one-border-out test: median error 19.9 → 13.3 % of the move, better in 65 % of cases.
  The "Sensor jerk" switch (Plant pace / One step) compares the two.

The schematic is a simplified redraw; the original `01_docs/System layout with sensors.png` is not used.

- Start plant button (2026-11-04): the twin now opens in shutdown (25 °C, air off) and waits. "Start plant" (replaces the
  "Cold start" playbook button, same settings) is allowed only from shutdown or air-flow cooling; locked in every other stage.
- Start from ambient (2026-11-04, v22): Start plant only from shutdown (air-flow cooling re-heat removed); a still-warm
  stack in shutdown is first set to ambient 25 °C (stack, air-in, recuperator, flows off), then the cold start runs.
- Trip and shut-down rules v24 (2026-11-04, user): (1) trip purge 16 min (`PURGE_MIN`, plant purges 15–17 min).
  (2) Shut down cools at 9000 ln/min and turns the air off below 40 °C (`SD_AIR`, `AIR_OFF_T`; plant full cool-down
  after trip #8: air 9000, 664 → 41 °C in 18 h; twin from hot standby 34 h, so the twin still cools too slowly at 9000).
  (3) A purge is also allowed in fuel switch straight after part load: taking the current to 0 in part load with the gas
  on now keeps the gas on 10 min at 0 A (`UNLOAD_MIN`, plant 19 + 30 Mar: 9–10 min) before hot standby; the Trip
  buttons are open in that window (`unloading()` in `canPurge`). Fuel switch on the way up to load stays locked.
  (4) Red "Emergency stop" button (`eStop()`), any stage, also during a purge: air, N₂, H₂, gas, POx, current and
  heaters all off at once; N₂ + H₂ rule set to manual; stage reads Shutdown (pill "· emergency stop"); Trip locked;
  any knob, playbook, stage-bar click or Start plant resets it.
- Plant cooling slope after hot standby, v25 (2026-11-04, user: "calculate the slope from hot standby to cooling from the
  POC data and use it in the twin"): `hsCoolRate()` in app.js. Leaving hot standby into air-flow cooling (heaters off,
  air on, no gas: Shut down from hot standby, heaters off, or the stage-bar Air-flow cooling click while in hot standby,
  which now starts a real cool-down from the current stack temperature instead of jumping to 242 °C) the stack moves at
  −f·C6·(air/6000)^N·u·(u/475)^Q °C/h, u = stack − 25 °C, f = 1 − e^(−t/TAU), t = min since hot standby ended;
  C6 0.0605/h, N 1.65, Q 0.5, TAU 4.2 min. Below 300 °C it blends into the heat balance (heat balance only below 250).
  Fitted on the 5 free plant cool-downs straight out of hot standby (02-04, 02-16, 02-18 at 6000; 03-04 8000; 03-20
  10000; cut where the air heater came back on): stack miss 12.2 → 5.1 °C (twin replay), each run left out 10.8 °C.
  2026-03-30 (14 min hot standby right after part load) still cools faster than both (53 °C off). Switch "Cooling after
  hot standby" (Plant slope / Heat balance) compares. Scripts: session scratchpad fabd3352…/scratchpad/hsc
  (extract.py, addtin.py, fit5.py, replay.js, free.js).
- Linked stages, v26 (2026-11-04, user: "do not allow the plant to directly go to heat-up N₂+H₂, hot standby, fuel switch,
  part load; it should be a link"): no stage-bar jump into these four (`LINK_HINT`, `LINK_FROM`, `linkStep()` in app.js).
  Chain Start plant → heat-up air → heat-up N₂+H₂ → hot standby → fuel switch → part load (→ hot standby). Heat-up N₂+H₂
  (210 °C) and hot standby (heat-up stops warming) come by themselves; Fuel switch button works only from hot standby
  (starts the load playbook), Part load only from fuel switch (current on now), Hot standby from fuel switch / part load
  unloads. Buttons not reachable from the current stage are greyed (aria-disabled, reason in the tooltip, message on click).
  "Go to part load" works only from hot standby. Heat-up air, air-flow cooling and shutdown still jump. Manual knobs
  (e.g. natural gas) are not locked. Headless test: all refusals from shutdown, then 14 h cold start → HS → FS → PL → HS.
