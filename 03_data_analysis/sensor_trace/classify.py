"""Verdict per Excel tag: traceability + usefulness.  Reads out/trace_metrics.csv."""
import os, re
import pandas as pd, numpy as np

HERE = os.path.dirname(__file__)
T = pd.read_csv(os.path.join(HERE, "out", "trace_metrics.csv"))

AREA = {"1": "Gas & air supply", "2": "Air pre-heating", "3": "Reformer / gas prep.",
        "4": "Stack", "5": "Off-gas & after-burner", "6": "Anode recycle",
        "7": "Exhaust & heat recovery", "8": "Safety monitors"}

def nums(tag):
    return [n for n in re.sub(r"^[A-Z]+\s*", "", tag).split(",") if n]

# sensors the stage rules / trip checks already read (03_data_analysis/*.py)
USED_IN_CODE = {"TIRZ 8,1,10", "TIRZ 8,1,3", "PIR 2,02", "PIRZ 8,1,2", "TIRZ 8,1,1", "TIRC 2,06",
                "FIRC 1,1,1", "FIRC 1,1,2", "FIRC 1,2", "FIRC 1,3", "FIRC 1,4", "FIRC 1,5",
                "TIR 7,04", "TIR 7,05", "TIR 6,01", "TIR 2,05", "TIRC 5,17", "TIRC 5,09", "TIRC 3,15",
                "TIRC 3,07", "EIRC 2,01", "TIRZ 8,2,1", "TIRZ 8,2,2", "TIRZ 8,2,3", "TIRZ 8,2,4",
                "TIRZ 8,2,5", "TIRZ 8,1,9", "TIR 1,1,1", "TIR 1,2,1", "TIR 1,3", "TIR 1,4,1",
                "PIR 1,5", "PIR 1,3,2", "PIR 1,1,1"}
# control + safety twins on the same spot (keep the first as the main signal)
TWINS = {"TIRZ 8,2,5": "TIRC 5,17", "TIRZ 8,2,1": "TIRC 3,1,1", "TIRZ 8,2,2": "TIRC 5,3,1",
         "TIRZ 8,2,3": "TIRC 5,3,2", "TIRZ 8,1,1": "TIRC 2,06", "TIR 7,05": "TIRZ 8,1,10",
         "TIRZ 8,2,4": "TIRC 6,1,1"}
# parallel line 1 / line 2 sensors (two module branches) - pairs move together
LINE_PAIRS = {"TIR 2,1,2": "TIR 2,1,1", "TIR 7,3,2": "TIR 7,3,1", "TIR 7,2,2": "TIR 7,2,1",
              "TIR 7,1,2": "TIR 7,1,1", "TIR 5,6,2": "TIR 5,6,1", "TIR 5,4,2": "TIR 5,4,1",
              "PIR 5,3,2": "PIR 5,3,1", "PIR 5,4,2": "PIR 5,4,1", "TIRC 5,5,2": "TIRC 5,5,1",
              "TIRC 3,19,2": "TIRC 3,19,1", "PIR 5,1,2": "PIR 5,1,1", "TIRC 5,1,2": "TIRC 5,1,1",
              "PIR 5,2,2": "PIR 5,2,1", "TIRC 5,2,2": "TIRC 5,2,1", "TIR 1,4,2": "TIR 1,2,2",
              "PIR 1,1,3": "PIR 1,1,1"}
KEY = {"TIRC 2,06": "EAPH heater control temperature (start-up ramp)",
       "EIRC 2,01": "EAPH heater power - shows when the plant is heating",
       "TIR 2,05": "Air entering the EAPH heater", "TIR 2,03": "APH outlet - air pre-heat",
       "FIRC 1,1,1": "Cathode air flow 1 - plant on/off and cooling rate",
       "FIRC 1,1,2": "Cathode air flow 2", "FIRC 1,3": "Nitrogen - forming-gas / purge phase",
       "FIRC 1,5": "Hydrogen - forming-gas phase", "FIRC 1,4": "Natural gas - fuel phase",
       "FIRC 1,2": "POx air - only with natural gas",
       "TIRZ 8,1,10": "Exhaust trip sensor (8 of 10 part-load runs tripped on it)",
       "TIRZ 8,1,3": "Stack safety temperature", "PIRZ 8,1,2": "Safety pressure monitor",
       "TIRC 5,17": "After-burner housing heater (ERH) temperature",
       "TIRC 3,1,1": "EAGH heater temperature", "TIRC 5,3,1": "EAOH1 heater temperature",
       "TIRC 5,3,2": "EAOH2 heater temperature", "TIRC 6,1,1": "EAOH3 heater temperature",
       "TIRC 3,07": "Reformer catalyst inlet", "TIRC 3,15": "Reformer catalyst outlet",
       "TIRC 5,09": "After-burner (TOX) representative temperature",
       "TIRC 5,1,1": "Stack cathode outlet 1", "TIRC 5,2,1": "Stack anode outlet 1",
       "PIR 2,02": "Cathode inlet pressure (used in stage rules)"}

out = []
for _, r in T.iterrows():
    tag, n = r.tag_n, nums(r.tag_n)
    fam = r.tag_n.split()[0]
    area = AREA.get(n[0], "-") if n else "-"
    if fam in ("EIR", "EIRC") and n and n[0] == "4": area = "Stack electrical"
    if fam == "EIRC" and n and n[0] in ("2", "3", "5"): area = "Heater power"
    trace, verdict, why = "Yes", "Useful", ""

    # ---- traceability ----
    if r.how == "none":
        trace = "No"
    elif r.how == "renamed":
        trace = "Yes (other name)"
    elif r.how == "map doc":
        trace = "Yes (other name)"
    elif r.how == "assumed":
        trace = "Yes (assumed match)"
    partial = {"FIRC 1,1,3": "real values only from 2026-03-17 (tag renamed in PLC)",
               "PIR 7,1,2": "reads -1 (not connected) until 2026-02-17"}
    if tag in partial or (fam == "EIRC" and n[0] == "4" and n[2] in ("3", "7", "8")):
        trace = "Partly"

    # ---- usefulness ----
    if trace == "No":
        verdict, why = "Not traceable", ("tag name is blank" if not n else "no column with this tag in any of the 836 logged columns")
    elif r.duplicate_of == r.duplicate_of:            # not NaN
        verdict, why = "Duplicate row", f"same tag already listed as row {int(r.duplicate_of)}"
    elif tag == "TIR 4,6,19":
        verdict, why = "Not usable", "stuck at 1300 °C on all 39 days - broken thermocouple"
    elif tag == "TIR 4,6,25":
        verdict, why = "Not usable", "reads 2-66 °C while the other stack sensors read 500-650 °C - not in the stack (wrong spot or loose)"
    elif fam == "EIR" and int(n[2]) not in (12, 15, 18):
        verdict, why = "Not usable", "package voltage: real readings (≈5 V) only on 13-15 Nov 2025, ≈0 V since 16 Nov 2025 - channel lost or unscaled"
    elif tag == "QIR 1,4":
        verdict, why = "Not usable", "gas-quality value ≈0 nearly all the time; 4 short spikes only"
    elif fam == "EIRC" and n[0] == "4" and n[2] == "5":
        verdict, why = "Low value", "slew-rate setting: stays at one value - a setting, not a measurement"
    elif fam == "EIRC" and n[0] == "4" and n[2] == "6":
        verdict, why = "Low value", "operating-mode setting (0 or 3); same information as load on/off"
    elif fam == "EIRC" and n[0] == "4" and n[2] in ("3", "7", "8"):
        verdict, why = "Limited", "only logged from 2026-03-17; device status column has shifted/garbage values on 2026-03-20"
    elif tag == "FIRC 1,1,3":
        verdict, why = "Limited", partial[tag] + "; shows hot-standby vs. cold clearly when present"
    elif tag == "PIR 7,1,2":
        verdict, why = "Limited", partial[tag]
    elif tag in TWINS:
        verdict, why = "Back-up twin", f"safety/control twin of {TWINS[tag]} - same spot, moves 1:1 (r ≥ 0.96); keep for trip checks, drop from models"
    elif tag in LINE_PAIRS:
        verdict, why = "Back-up twin", f"line-2 partner of {LINE_PAIRS[tag]} - moves 1:1 (r ≥ 0.98); keep only to compare the two lines"
    elif fam == "TIR" and n[:2] == ["4", "6"]:
        verdict, why = "Key (as a group)", "stack temperature grid: one sensor alone repeats the others (r = 1.00), but together they give the stack mean, hottest spot and spread"
    elif tag in KEY:
        verdict, why = "Key", KEY[tag]
    elif fam == "EIR":                                  # stack voltages .12 .15 .18
        verdict, why = "Key", f"stack {[12,15,18].index(int(n[2]))+1} voltage of string {n[1]} (≈110 V hot, 0 V cold)"
    elif fam == "EIRC" and n[0] == "4":
        k = n[2]
        verdict, why = {"1": ("Key", "string load voltage (only non-zero while drawing current)"),
                        "2": ("Key", "string current - the only measure of electrical load"),
                        "4": ("Useful", "current set-point given to the load"),
                        "9": ("Key", "lowest voltage seen by the load - the limit that capped part load")}[k]
    elif fam == "EIRC" and n[0] in ("3", "5"):
        verdict, why = "Useful", "heater current (logged as IIR) - shows when the heater is on"
    elif tag in ("PIR 1,1,1", "PIR 1,2,1", "PIR 1,3,1", "PIR 1,5", "PIR 1,4,1"):
        verdict, why = "Low value", "supply line pressure: almost constant (4-6 bar); only useful to spot a supply fault"
    elif tag in ("TIR 1,1,1", "TIR 1,2,1", "TIR 1,3", "TIR 1,4,1", "TIR 1,2,2", "TIR 2,04", "TIR 2,1,1", "TIR 4,1", "TIR 3,04", "TIR 3,05", "TIR 3,01", "TIR 3,02"):
        verdict, why = "Low value", "near room temperature most of the time; little change between stages" + \
            (" (part of the ambient proxy in the stage rules)" if tag in ("TIR 1,1,1", "TIR 1,2,1", "TIR 1,3", "TIR 1,4,1") else "")
    else:
        verdict, why = "Useful", "working, follows the plant through the stages"

    if r.how == "assumed" and verdict not in ("Not usable",):
        why += " | match to data column is assumed"
    out.append(dict(sno=r.sno, tag=r.tag.strip(), area=area, data_column=r.column if r.column == r.column else "",
                    traceable=trace, verdict=verdict, reason=why, used_in_stage_rules=tag in USED_IN_CODE,
                    coverage_pct=round(100 * r.coverage, 1) if r.coverage == r.coverage else None,
                    days_moving=r.days_alive, stage_explains_pct=round(100 * r.eta2_stage) if r.eta2_stage == r.eta2_stage else None,
                    most_similar=r.most_like if isinstance(r.most_like, str) else "", similarity_r=round(r.max_r, 3) if r.max_r == r.max_r else None,
                    p01=r.p01, p99=r.p99,
                    median_shutdown=r["med_Shut-down"], median_startup=r["med_Start-up"],
                    median_hot_standby=r["med_Hot standby"], median_part_load=r["med_Part load"]))
F = pd.DataFrame(out)
F.to_csv(os.path.join(HERE, "out", "verdict.csv"), index=False)
print(F.traceable.value_counts(), "\n", F.verdict.value_counts())
print(pd.crosstab(F.area, F.verdict))
