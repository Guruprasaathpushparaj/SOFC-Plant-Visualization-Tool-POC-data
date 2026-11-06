---
title: Instrument Map by Component — Temperature · Pressure · Flow · Power (based on ICA List)
created: 2026-10-05
language: en (Korean original: component_sensor_map.md)
sources:
  - 20241113_ICA_List_PoC_Prototype.xlsm (sheet Tabelle1, 429 rows)
  - 20251003_PoC_PFD_P&ID_Rev.1.9.vsdx (page 2 'P&ID' — instrument positions and flow order)
  - 02_data/downsampled (10 s, 39 days · 836 columns — column availability and units checked)
  - Knowledge map edges/edges.yaml (flow_to · heats)
  - 20260327 Safety Functions + Test Instructions.xlsx (S-PLC 0xB9E8 — trip values)
status: Draft 3 — 9 user corrections + 3 P&ID confirmations applied (2026-10-05)
---

# Instrument Map by Component (Temperature · Pressure · Flow · Power)

## 0. How to read this document

- **Tags and descriptions are copied from the ICA List as-is.** Values in brackets are the ICA measuring ranges.
- **Upstream / Downstream** = instruments on the pipe directly before / after the component in flow direction.
  - Where the ICA description says 'Inlet · Outlet · to · After', that wording was followed.
  - Where the description gives no location (e.g. 'Air Stream'), the position was taken from the indicator bubble on P&ID Rev1.9 and the pipe flow order → marked **[P&ID]**.
  - Where both are weak, the entry is marked **[assumed]**.
- **Power** = heater current (IIR), power control output (EIRC), rated consumption (ICA column 'Power VAC'), and voltage / current / power columns found in the data.
- **Data column names:** for most tags the dots are replaced by underscores (TIR3.18 → `TIR_3_18`). Flow controllers use `ct_FIRC_xx_PV_ProcessValue` (FIRC1.1.1 → `ct_FIRC_111_PV_ProcessValue`). Exceptions are given in the tables.
- ICA column 'Sensor & Actor': **S** = measured value, **A** = control output (set value).

---

## 1. Instruments per component + upstream / downstream

### 1.1 FPM — Cathode air (system 1.1)

Flow [P&ID]: air supply → F1.1 → PR1.1.1 / PR1.1.2 → V1.1.2 / V1.1.3 → **PIR** → MV → **FIRC·MFC** → both streams merge → **TIR1.1.1 · PIR1.1.2** → TWV-CA

| Component | Position | Temperature | Pressure | Flow | Power |
|---|---|---|---|---|---|
| **MFC-Air-1** (Stream 1) | Upstream | — | PIR1.1.1 Air Stream (0–10 bar) [P&ID] | — | — |
| | Component | — | — | **FIRC1.1.1** actual · set value (0–6000 ln/min) | — |
| | Downstream | TIR1.1.1 Air Stream (−200–1300 °C) [P&ID] | PIR1.1.2 Air Stream (0–0.4 bar) [P&ID] | — | — |
| **MFC-Air-2** (Stream 2) | Upstream | — | PIR1.1.3 Air Stream (0–10 bar) [P&ID] | — | — |
| | Component | — | — | **FIRC1.1.2** actual · set value (0–6000 ln/min) | — |
| | Downstream | TIR1.1.1 (shared, after the two streams merge) [P&ID] | PIR1.1.2 (shared) [P&ID] | — | — |
| **TWV-CA** (3-way valve) | Upstream | TIR1.1.1 | PIR1.1.2 | — | — |
| | Component | — | — | **FIRC1.1.3** 3 Way Valve actual · set value (0–63 m³/h) ¹ | — |
| | Downstream → EAPH direct | (TIR2.05 · PIR2.01 = EAPH inlet, §1.4) | — | — | — |
| | Downstream → APH | TIR2.04 [P&ID confirmed: TWV → APH inlet pipe] · TIR2.1.1 APH1 Inlet Air · TIR2.1.2 APH2 Inlet Air | — | — | — |

¹ In the ICA, FIRC1.1.3's 'Actual value' row is listed as A/SetVal and the 'Set point' row as S/ActVal — the two are swapped.

### 1.2 FPM — POx air (1.2) · N₂ (1.3) · H₂ (1.5)

| Component | Position | Temperature | Pressure | Flow |
|---|---|---|---|---|
| **MFC-POxAir** | Upstream | — | PIR1.2.1 Air Stream (0–10 bar) [P&ID] | — |
| | Component | — | — | **FIRC1.2** POx-Air (0–700 ln/min) |
| | Downstream | TIR1.2.1 POx-Air (FPM) · TIR1.2.2 POx-Air (FPM to PGM) | PIR1.2.2 POx-Air (0–0.4 bar) | — |
| | → Reformer inlet | TIR3.04 POx Air PGM Inlet · TIR3.05 Reformer Inlet POx Air | — | — |
| **MFC-N2** | Upstream | — | PIR1.3.1 Nitrogen Supply (0–10 bar) | — |
| | Component | — | — | **FIRC1.3** Nitrogen (0–1300 ln/min) |
| | Downstream | TIR1.3 Purge Gas | PIR1.3.2 Purge Gas (0–10 bar) | — |
| **MFC-H2** | Upstream | — | PIR1.5 Hydrogen Supply (0–10 bar) | — |
| | Component | — | — | **FIRC1.5** Hydrogen (0–70 ln/min) |
| | Downstream | — (none in ICA) | — | — |

### 1.3 FPM — Natural gas (1.4)

Flow [P&ID]: NG supply → desulfurization cartridges → particle filter → Haug compressor → buffer → storage tank 15 bar → PR1.4 (15→13 bar) → **PIR1.4.1** → MV1.4.3 → **FIRC1.4·MFC-Fuel** → **TIR1.4.1 · PIR1.4.2 · TIR1.4.2** → PGM inlet **TIR3.01**

| Component | Position | Temperature | Pressure | Flow | Power · status |
|---|---|---|---|---|---|
| **Haug-Compressor** (booster) | Upstream | — | (PIRZ8.1.2 — ICA says 'Fuel Supply', the safety document says 'Control Container' pressure. Assignment not confirmed, see §4 ⁹) | — | — |
| | Component | — | — | — | EIC1.4 · EIC1.4.1~1.4.4: alarm · ready · start/stop · drain valve (digital signals, no data) |
| | Downstream | — | PIR1.4.1 Fuel Pressure Booster (0–16 bar) [P&ID: directly after PR1.4] | — | — |
| **MFC-Fuel** | Upstream | — | PIR1.4.1 (0–16 bar) | — | — |
| | Component | — | — | **FIRC1.4** Fuel (0–200 ln/min) | — |
| | Downstream | TIR1.4.1 Fuel (FPM) · TIR1.4.2 Fuel (FPM to PGM) ² | PIR1.4.2 Fuel FPM (0–10 bar) | — | — |
| | → PGM inlet | TIR3.01 Fuel PGM Inlet | — | — | — |
| Desulfurization cartridges · filters | — | No temperature or pressure instruments in the ICA (the P&ID only carries the note 'Desulf Δp = max. 150 mbar') | | | |

² On the P&ID, TIR1.4.1 · TIR1.4.2 are number-only bubbles downstream of the MFC (x 14.18 · 14.76). This differs from the knowledge-map anchors (upstream L-NG-1.4.1 · 1.4.2) — pending knowledge-map update.

### 1.4 PGM — Air preheating (APH-1 · APH-2 · EAPH)

| Component | Position | Temperature | Pressure | Power |
|---|---|---|---|---|
| **APH-1** air side | Upstream | TIR2.1.1 APH1 Inlet Air | — | — |
| | Upstream (shared) | TIR2.04 [P&ID confirmed: TWV → APH inlet pipe] ³ | — | — |
| | Downstream | TIR2.02 APH1 and 2 Outlet Air (shared) · TIR2.03 [P&ID confirmed: APH outlet riser → EAPH] ³ | — | — |
| **APH-2** air side | Upstream | TIR2.1.2 APH2 Inlet Air | — | — |
| | Downstream | TIR2.02 (shared) · TIR2.03 ³ | — | — |
| **EAPH** (electric air pre-heater) | Upstream | TIR2.05 EAPH Inlet · TIR2.03 (air coming from the APH) ³ | PIR2.01 EAPH Inlet (0–0.4 bar) | — |
| | Component | TIRZ8.1.1 EAPH monitoring (safety) | — | **Rated 40 kW** (ICA VAC, 3 phases × 13.64 kW; description 'ca. 50 kW') · **EIRC2.01** power controller (Jumo) ⁴ |
| | Downstream | **TIRC2.06 EAPH Outlet** (EAPH control reference) | PIR2.02 Stack Module Inlet (0–0.4 bar) | — |

³ The TIR2.03 · TIR2.04 positions were confirmed on the P&ID (user, 2026-10-05): TIR2.03 = APH outlet riser (APH → EAPH), TIR2.04 = TWV → APH inlet pipe. The ICA descriptions ('2.03 FPM to EAPH' · '2.04 APH to EAPH') appear to be swapped relative to these positions → the tables follow the P&ID.
⁴ EIRC2.01 itself has no data column. The controller data is in the `pi_EIRC_2_01_ActV_*` columns (master + slave 1·2): voltage `…_Voltage_[V]` · `…_MainsVoltage_[V]`, current `…_Current_[A]`, power `…_Power_[W]` · `ActV_In_ThreePhasePower_[W]` (3-phase total, max 31 kW on 2026-03-24).

### 1.5 PGM — Fuel · reforming (Ejector · Reformer · ERH · EAGH)

| Component | Position | Temperature | Pressure | Power |
|---|---|---|---|---|
| **Ejector** | Upstream (NG motive flow) | TIR3.01 Fuel PGM Inlet · TIR3.02 Ejector Main Stream | PIR3.01 Ejector Main Stream (0–10 bar) | — |
| | Upstream (suction = AOG recycle) | TIR6.01 Recycling Gas Inlet · TIRC6.1.1 (EAOH3) | PIR6.01 Recycling Gas Inlet (0–0.4 bar) | — |
| | Downstream | TIRC3.03 Ejector Outlet | PIR3.02 Ejector Outlet (0–0.4 bar) | — |
| **Reformer** | Upstream | TIR3.06 Reformer Inlet Mixed (fuel + recycle) · TIR3.05 Reformer Inlet POx Air · TIR3.04 POx Air PGM Inlet | (PIR3.02) | — |
| | Catalyst inlet | **TIRC3.07** Reformer Cat Mix (representative catalyst inlet) | — | — |
| | Catalyst outlet | **TIRC3.15** After Reformer Cat (representative catalyst outlet) | — | — |
| | Downstream | TIRC3.17 Reformer Outlet | — | — |
| **ERH** (reformer/burner housing heater) | Component | **TIRC5.17** ERH temperature (control) | — | **Output EIRC5.1.3** (power control) · **Rated 3.3 kW** (3 × 1100 W, L3) |
| **EAGH** (reformate line heater) | Upstream | TIRC3.17 Reformer Outlet | — | — |
| | Component | **TIRC3.1.1** EAGH (control) · TIRZ8.2.1 EAGH monitoring | — | Rated 1.3 kW (L1) · **IIR3.1.1** current (0–16 A) ⁵ · EIRC3.1.1 |
| | Downstream = stack anode inlet | TIR3.18 Stack Module Inlet · TIR3.19.1 / 3.19.2 (§2) | PIR3.03 Stack Module Inlet (0–0.4 bar) | — |

- The reformer catalyst temperature is represented by one inlet (TIRC3.07) and one outlet (TIRC3.15) sensor (user decision 2026-10-05). TIRC3.08 ~ 3.14 · 3.16 are auxiliary points in the same catalyst bed.
- ERH lists its temperature (TIRC5.17), output (EIRC5.1.3) and rating (user decision). The monitoring sensor TIRZ8.2.5 and current IIR5.1.3 exist in the ICA; the safety trip is in §4.

⁵ IIR data columns follow the pattern `pi_IIR_3_1_1_ActVal` (IIR6.1.1 → `pi_IIR_6_1_1_ActVal`). They are not linked in the knowledge map. Columns with the same meaning, `PLC_pv_rCurrEAGH · rCurrERH · rCurrEAOH_1~3`, also exist but are 0 on all 39 days.

### 1.6 PGM — Downstream of the stack (AOG heaters · afterburner · exhaust)

Flow:
- **Anode off-gas (AOG):** stack anode outlet (TIRC5.2.1 · 5.2.2 = Anode Outlet, confirmed by user) → upstream of EAOH3 → TWV-AOG split
  - Recycle: EAOH3 → Ejector
  - TOX branches: EAOH1 · EAOH2 → TOX
- **Cathode off-gas:** the pipes carrying TIRC5.1.1 · 5.1.2 = **cathode outlet lines** (confirmed by user) → TWV1/2_COG → TOX · APH bypass

| Component | Position | Temperature | Pressure | Power |
|---|---|---|---|---|
| **EAOH3** (recycle) | Upstream = stack anode outlet | **TIRC5.2.1 · TIRC5.2.2** Stack Module Outlet Anode1/2 (confirmed by user) | PIR5.2.1 · PIR5.2.2 Stack Outlet Anode1/2 (same location) · PIR6.01 Recycling Gas Inlet [P&ID: riser before EAOH3] | — |
| | Component | **TIRC6.1.1** EAOH 3 (control) · TIRZ8.2.4 monitoring | — | Rated 1.3 kW (L2) · **IIR6.1.1** (0–16 A) · EIRC6.1.1 |
| | Downstream | TIR6.01 Recycling Gas Inlet [P&ID: after EAOH3] → ejector suction | — | — |
| **EAOH1** (TOX branch 1) | Upstream | — (no instrument between TWV-AOG and EAOH1) | — | — |
| | Component | **TIRC5.3.1** EAOH 1 (control) · TIRZ8.2.2 monitoring | — | Rated 1.3 kW (L1) · **IIR5.1.1** (0–16 A) · EIRC5.1.1 |
| | Downstream | TIRC5.5.1 TOX Inlet Anode1 | PIR5.4.1 TOX Inlet Anode1 | — |
| **EAOH2** (TOX branch 2) | Upstream | — (no instrument) | — | — |
| | Component | **TIRC5.3.2** EAOH 2 (control) · TIRZ8.2.3 monitoring | — | Rated 1.3 kW (L2) · **IIR5.1.2** (0–16 A) · EIRC5.1.2 |
| | Downstream | TIRC5.5.2 TOX Inlet Anode2 | PIR5.4.2 TOX Inlet Anode2 | — |
| **TWV1_COG / TWV2_COG** (cathode off-gas split) | Upstream = cathode outlet line | **TIRC5.1.1 / TIRC5.1.2** Stack Outlet Cathode1/2 (confirmed by user) | PIR5.1.1 / PIR5.1.2 Stack Outlet Cathode1/2 | — |
| | Downstream → TOX | TIR5.4.1 / TIR5.4.2 TOX Inlet Cathode1/2 | PIR5.3.1 / PIR5.3.2 TOX Inlet Cathode1/2 [P&ID confirmed] ⁶ | — |
| | Downstream → APH bypass | TIR5.6.1 / TIR5.6.2 TOX Bypass1/2 [P&ID: cathode bypass pipe] ⁶ | — | — |
| **Afterburner (TOX)** | Upstream | The 8 'TOX Inlet' instruments above (T · P of Anode 1·2 and Cathode 1·2) | | — |
| | Component | **TIRC5.09** TOX — representative TOX temperature ⁷ | — | — |
| | Downstream | TIR7.1.1 / TIR7.1.2 TOX Outlet1/2 | — | — |
| **APH-1 / APH-2** flue-gas side | Upstream | TIR7.1.1 / 7.1.2 → (bypass joins) → TIR7.2.1 / 7.2.2 TOX Outlet Mixed1/2 [P&ID order] | PIR7.1.1 / PIR7.1.2 APH Inlet Exhaust1/2 | — |
| | Downstream | TIR7.3.1 / TIR7.3.2 APH Outlet Exhaust1/2 → shared TIR7.04 APH Exhaust Outlet | PIR7.02 APH Exhaust Outlet | — |
| **Exhaust** | Downstream (roof exhaust) | TIR7.05 Exhaust | PIR7.03 Exhaust | — |

⁶ PIR5.3.x is indeed TOX Inlet Cathode (P&ID confirmed by user, 2026-10-05); 'Anode Off-Gas' in the ICA medium column is a typo. TIR5.6.x is also listed with medium Anode Off-Gas, but on the P&ID it sits on the cathode bypass pipe.
⁷ TOX is represented by **TIRC5.09** alone, out of TIRC5.07 ~ 5.15 (9 sensors).
- Basis: Safety Functions (0xB9E8) continuously checks the plausibility of the burner trip sensor TIRZ8.1.9 against TIRC5.09.
- Data, 2026-03-24: mean 570 °C (TIRZ8.1.9: 567 °C), correlation 0.986. Not on the faulty-sensor list.
- The other 8 are auxiliary points in the same TOX (means spread from 476 to 565 °C).

---

## 2. Stack module — manifold inlets/outlets and module total current · voltage · power

### 2.1 Manifold inlet / outlet temperature and pressure

| Location | Temperature | Pressure | Notes |
|---|---|---|---|
| **Anode inlet** (reformate) | **TIR3.18** Stack Module Inlet · **TIR3.19.1** Stack Manifold 1 Inlet · **TIR3.19.2** Stack Manifold 2 Inlet | **PIR3.03** Stack Module Inlet (0–0.4 bar) | The P&ID labels these 'TIRC 3.19.1 / 3.19.2' (ICA: TIR). TIR3.18 · 3.19.x data = 5-min averages |
| **Cathode inlet** (air) | **TIRC2.06** EAPH Outlet (= just before the stack cathode inlet; on the P&ID directly upstream of the stack) | **PIR2.02** Stack Module Inlet (0–0.4 bar) | The ICA has no temperature instrument named 'Stack Cathode Inlet' |
| **Anode outlet** | **TIRC5.2.1** Outlet Anode1 · **TIRC5.2.2** Outlet Anode2 | **PIR5.2.1** · **PIR5.2.2** (0–0.4 bar) | TIRC data = 5-min averages |
| **Cathode outlet** | **TIRC5.1.1** Outlet Cathode1 · **TIRC5.1.2** Outlet Cathode2 | **PIR5.1.1** · **PIR5.1.2** (0–0.4 bar) | |
| Stack interior | **TIR4.6.1 ~ 4.6.36** Stack Module (36 sensors) · **TIRZ8.1.3** Stack Module monitoring (safety, trip 720 °C) | — | Mapping of TCs to individual stacks is unknown (36 TCs → no mapping to the 20 stacks) |

### 2.2 Stack module total current · voltage · power — no system output measurement

**Conclusion: the current data contains no system (module) total output. Only per-string current, voltage and power are available.**

- Each of the 5 strings is connected to its own programmable load (El.Load4.1~4.5, 14 kW · 600 V · 42 A each). The ICA has no instrument that measures the whole module at once.
- Columns and instruments that look like a system output cannot be used either (checked over 39 days).

| Name | Status |
|---|---|
| `PLC_pv_rSystemOutPower` | Column exists but is 0 on all 39 days |
| EIR10.1 ~ 10.3 (L1~L3 voltage 0–230 V) | ICA only · no data column · not on the P&ID |
| PAGS (grid simulator power analyzer, RS485) | ICA only · no data column |
| DC-DC · transformer · grid output (design 60 kW DC → 50 kW AC) | No instrument or data column |

If a module total is needed, compute it from the string values **[calculated, not measured]**:

| Quantity | Calculation | Notes |
|---|---|---|
| Total current | Σ `EIRC_4s_CurrentMon` (s = 1~5) | Each string has its own load, so this means 'total load current' |
| Total voltage | Not defined | Meaningful per string only (§3) |
| Total power | Σ string power = Σ `EIRC_4s_VoltageMon` × `EIRC_4s_CurrentMon` / 1000 [kW] | The sum of `EIRC_4s_Actual_Power` is equivalent but has many gaps and invalid values (§3) |

---

## 3. Per-string current · voltage · power (s = 1~5) — the electrical output values that actually exist

### 3.1 Total voltage and current sensors per string

The total voltage of each string is read by **EIRC4.s.1** and the total current by **EIRC4.s.2**. Both are monitors on the programmable load connected to the string (El.Load4.s).

| String | Total voltage sensor | Voltage data column | Total current sensor | Current data column | Load rating |
|---|---|---|---|---|---|
| String 1 | **EIRC4.1.1** | `EIRC_41_VoltageMon` | **EIRC4.1.2** | `EIRC_41_CurrentMon` | El.Load4.1 — 14 kW · 600 V · 42 A |
| String 2 | **EIRC4.2.1** | `EIRC_42_VoltageMon` | **EIRC4.2.2** | `EIRC_42_CurrentMon` | El.Load4.2 — 14 kW · 600 V · 42 A |
| String 3 | **EIRC4.3.1** | `EIRC_43_VoltageMon` | **EIRC4.3.2** | `EIRC_43_CurrentMon` | El.Load4.3 — 14 kW · 600 V · 42 A |
| String 4 | **EIRC4.4.1** | `EIRC_44_VoltageMon` | **EIRC4.4.2** | `EIRC_44_CurrentMon` | El.Load4.4 — 14 kW · 600 V · 42 A |
| String 5 | **EIRC4.5.1** | `EIRC_45_VoltageMon` | **EIRC4.5.2** | `EIRC_45_CurrentMon` | El.Load4.5 — 14 kW · 600 V · 42 A |

- Ranges (ICA): voltage 0–800 V (description 0–600 V) · current 0–75 A (description 0–42 A).
- The same values also exist as PLC columns: `PLC_hostSetp_ctrl_ctEIRC4s_rVoltMonitor` · `…_rCurrMonitor`.
- **EIRC4.s.1 (load voltage) has values only while the load is on.** For the string voltage while the load is off (including open-circuit voltage), use `TotalVoltage_Ms`.
  - `TotalVoltage_Ms` is not a sensor but the sum of the 4 stack voltages (EIR4.s.12 + .15 + .18 + .21). It has no ICA row.
- String power = EIRC4.s.1 × EIRC4.s.2 / 1000 [kW] ('Power' row in §3.2).

### 3.2 Full list for each string

| Quantity | ICA tag | Data column | Range · notes |
|---|---|---|---|
| **Current** | **EIRC4.s.2** Load: Current Monitor | `EIRC_4s_CurrentMon` (= `PLC_hostSetp_ctrl_ctEIRC4s_rCurrMonitor`) | 0–75 A (ICA description 0–42 A) |
| **Voltage — load side** | **EIRC4.s.1** Load: Voltage Monitor | `EIRC_4s_VoltageMon` (= `…_rVoltMonitor`) | 0–800 V. Has values only while the load is on |
| **Voltage — stack sum** | (no ICA row · calculated value) | `TotalVoltage_Ms` | = EIR4.s.12 + .15 + .18 + .21 (difference 0.02 V, verified) ⁸ |
| **Power** | (no ICA row) | `EIRC_4s_Actual_Power` [kW] | = VoltageMon × CurrentMon / 1000 (verified). Rated 14 kW per string. **Present on only 12 of 39 days and contains invalid values of 3.0 × 10³⁷** → compute V × I where possible |
| Stack voltage | **EIR4.s.12 · .15 · .18 · .21** Stack 1~4 total voltage | `pi_EIR_4_s_12` … | 0–160 V |
| Package voltage | **EIR4.s.10 · .11 / .13 · .14 / .16 · .17 / .19 · .20** Stack 1~4 Package 1 · 2 | `pi_EIR_4_s_10` … | 0–15 V |
| Minimum cell voltage | (no ICA row) | `EIRC_4s_ActV_Min_CellVoltage` · set value `EIRC_4s_Setp_Min_CellVoltage` | V per cell (control lower limit 0.75 V/cell) |
| Minimum stack voltage | (no ICA row) | `String_s_ActMinVoltage` · stack number `String_s_ModulWithMinVoltage` | = minimum of the 4 stack voltages (verified) |
| Load settings | EIRC4.s.4 Set Input setting (0–800 V) · EIRC4.s.5 · .6 Basic Mode · EIRC4.s.7 ON/OFF · EIRC4.s.8 Device Status | `EIRC_4s_SP_Analog` · `…_SP_SlewRateAbs` · `…_OpMode` · `…_OUT_Enable` etc. | Control outputs · status (A/S) |
| Insulation resistance | EIR4.s.22 Insulation measurement | `pi_EIR_4_s_22` | Unresolved Ω vs kΩ unit conflict (CONFLICT-RISO-01) → do not use. Safety trip is BE s.1 (§4) |

⁸ The knowledge map links `TotalVoltage_Ms` to EIRC4.s.1 (Load Voltage Monitor). The data shows that `TotalVoltage_Ms` is the sum of the 4 stack voltages, while the load-side voltage monitor is `EIRC_4s_VoltageMon`. Candidate for correcting the link.

---

## 4. Safety trips by component (Safety Functions, S-PLC 0xB9E8, 2026-03-27)

Source: `20260327 Safety Functions + Test Instructions.xlsx` (sheets Security Features · State Definitions). Every trip condition acts when it **persists for more than 50 ms**.

### 4.1 Process equipment → SPLC_EMERGENCYPURGE

| Component | Trip sensor | Trip condition | Plausibility reference (as stated in the document) |
|---|---|---|---|
| EAPH | TIRZ8.1.1 | > **1050 °C** | None ('validation during IBN') |
| Stack module | TIRZ8.1.3 | > **720 °C** | TIR4.6.23 |
| Afterburner (TOX) | TIRZ8.1.9 | > **930 °C** | TIRC5.09 |
| Exhaust outlet | TIRZ8.1.10 | > **300 °C** (100 → 200 °C on 2026-01-28, → 300 °C on 2026-03-27) | 'TIRC7.03' (tag not in the ICA — to be confirmed) |
| EAGH | TIRZ8.2.1 | > **950 °C** | TIRC3.1.1 |
| EAOH1 | TIRZ8.2.2 | > **950 °C** | TIRC5.3.1 |
| EAOH2 | TIRZ8.2.3 | > **950 °C** | TIRC5.3.2 |
| EAOH3 | TIRZ8.2.4 | > **950 °C** | TIRC6.1.1 |
| ERH (reformer auxiliary heater) | TIRZ8.2.5 | > **860 °C** | TIRC5.17 |
| Stack insulation (strings 1~5) | BE1.1 · BE2.1 · BE3.1 · BE4.1 · BE5.1 | < **2 kΩ** | — |
| Pressure monitoring | PIRZ8.1.2 | < **750 mbar a** | — ⁹ |
| Exhaust fans (control / PGM container) | FZ8.0.14 / FZ8.0.15 | Loss of exhaust air flow | — |

**What SPLC_EMERGENCYPURGE does** (State Definitions):

- **Opened (purge):**
  - Air MV1.1.2 · MV1.1.3 (purge flow 3000 Nl/min each)
  - N₂ MV1.3.2 (1200 Nl/min)
  - H₂ MV1.5.3 (60 Nl/min)
  - NG vents MV1.4.4 · MV1.4.5
- **Closed:** POx air MV1.2 · NG MV1.4.3
- **Interrupted / stopped:**
  - Heater and stack contactors (QA1 · QA2 · stack QA1.1 ~ QA5.1)
  - PCM
  - Compressor stopped

### 4.2 Container and personnel safety → SPLC_EMERGENCYSTOP

| Target | Trip sensor | Trip condition |
|---|---|---|
| Control container O₂ | QZB1 | < **17 %** |
| Control container H₂ | QZB2 · QZB3 | > **40 % LEL** |
| PGM container CO | QZB4 | > **60 ppm** |
| PGM container H₂ | QZB5 | > **40 % LEL** |
| Smoke detection (control · operator area · PGM) | QZA1 · QZA2 · QZA3 | Smoke detected |
| Emergency stop buttons | SF1 (PGM) · SF3.1 ~ SF3.3 (control) | Pressed |

**SPLC_EMERGENCYSTOP:**
- All supply valves (MV1.1.2 · 1.1.3 · 1.2 · 1.3.2 · 1.4.3 · 1.4.5 · 1.5.3) close. Only the NG vent MV1.4.4 opens.
- Contactors, PCM and compressor are switched off.
- **The N₂ · H₂ purge is blocked as well.** This is the basis for the unprotected-anode-cooling hypothesis (top-priority unverified hypothesis in CLAUDE.md).

⁹ The two documents describe PIRZ8.1.2 differently.
- ICA: 'Pressure monitoring Fuel Supply' · natural gas · 0–0.4 bar
- Safety Functions: 'Pressure Monitoring (Control Container)' · < 750 mbar **a**
- Its assignment to a component (§1.3, upstream of Haug) is not confirmed.

---

## 5. Open points and caveats

1. **No system output measurement** — §2.2. Module / system output can only be obtained as the sum of the string values.
2. **`EIRC_4s_Actual_Power`** has gaps and invalid values — §3.
3. **`PLC_pv_rCurr*`** is 0 on all 39 days. Use `pi_IIR_*_ActVal` for heater currents.
4. **Electrical data columns not linked in the knowledge map:**
   - 5 IIR columns
   - String power · minimum cell / stack voltage
   - EAPH controller V/I/P

   Candidates for the knowledge-map update.
5. **Heater instruments whose knowledge-map anchors disagree with the ICA descriptions (the viewer follows the descriptions):**
   - TIRC5.3.1 · 5.3.2 (description EAOH1/2, anchor EAPH)
   - TIRC5.17 (description ERH, anchor EAOH2)
   - EIRC5.1.3 ↔ EIRC6.1.1 (swapped)
6. **Locations still to be confirmed:**
   - PIRZ8.1.2 (⁹)
   - Exhaust trip reference sensor 'TIRC7.03'
7. **Applied from user confirmation on 2026-10-05:**
   - Reformer catalyst = TIRC3.07 (inlet) · TIRC3.15 (outlet)
   - ERH = temperature TIRC5.17 · output EIRC5.1.3 · rating
   - TIR2.03 = APH outlet riser · TIR2.04 = TWV → APH inlet pipe (P&ID confirmed; swapped relative to the ICA descriptions)
   - PIR5.3.x = TOX Inlet Cathode (P&ID confirmed)
   - TIRC5.1.x = cathode outlet line
   - TIRC5.2.x = anode outlet · upstream of EAOH3
   - TOX representative = TIRC5.09
   - Condensate trap row removed
