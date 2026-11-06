"""Stage crosswalk: one sensor signature per minute, any plant's stage names on top.

Plants name their stages differently (our S0–S8, the LG patent family
US10797329, Hanasaki 2014, Bloom US7846599B2), and the same name can mean
different things: LG "Hot standby" is 800–1000 °C with no fuel, Hanasaki "Hot
standby" is 600 °C still making a little power. Sorting sensor readings by name
therefore breaks as soon as a second plant's data arrives.

This module sorts by what the sensors show instead. Every minute gets a
plant-neutral signature of five facts:

    thermal   Cold / Warm / Hot          stack temperature vs the plant's own limits
    trend     Rising / Held / Falling    20-min dT/dt vs ±DTDT_HELD (±DTDT_HELD_WARM below t_hot)
    supply    Off / Air / Protective / Fuel   gas phase (forming gas and N2 = Protective)
    load      No load / Load / Rated     string current
    trip      True / False               protective trip window
    been_hot  True / False               stack held hot or loaded since it was last cold;
                                         the one fact that needs memory (a hot rise is a
                                         heat-up if False, a set-point change if True)

Each vocabulary is a table of rows in VOCAB (first matching row wins, "*" =
any). Adding a plant = adding rows, not code. Every row carries a match grade:
exact (the source's definition fits the signature), partial (closest name, a
definition detail differs) or none (the source has no name for it).

Usage:
    python 03_data_analysis/scripts/stage_crosswalk.py
Reads 03_data_analysis/industrial_stages/industrial_states_1min.parquet,
writes to 03_data_analysis/stage_crosswalk/.
"""
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[1]
SRC = HERE / "industrial_stages" / "industrial_states_1min.parquet"
OUT = HERE / "stage_crosswalk"

# ---- signature limits (per plant: pass another dict for another plant) ----
OURS = {"t_cold": 46.0,     # °C: ambient (16 °C median) + 30 K, = operating_states DT_AMBIENT
        "t_hot": 450.0,     # °C: = operating_states T_HOT
        "i_load": 1.0,      # A per string
        "i_rated": 28.5}    # A per string
DTDT_HELD = 5.0             # °C/h: = operating_states DTDT_STABLE
DTDT_HELD_WARM = 1.0        # °C/h: natural cooling below t_hot is only 1–4 °C/h, not a hold

SUPPLY = {"Plant off": "Off", "Air only": "Air", "Forming gas (N2 + H2)": "Protective",
          "N2 purge": "Protective", "Natural gas": "Fuel", "": ""}

# ---- vocabularies ----------------------------------------------------------
# (vocab, label, thermal, trend, supply, load, trip, been_hot, match)
_ = "*"
VOCAB = [
    # LG Electronics US10797329, "transitioning a fuel cell system between modes"
    ("LG", "Trip (not named in LG)",              _, _, _, _, True, _, "none"),
    ("LG", "Normal operating mode",               _, _, _, "Load", False, _, "exact"),
    ("LG", "Normal operating mode",               _, _, _, "Rated", False, _, "exact"),
    ("LG", "Power-ready hot standby",             "Hot", _, "Fuel", "No load", False, _, "exact"),
    ("LG", "Hot standby mode",                    "Hot", "Held", _, "No load", False, _, "exact"),
    ("LG", "Hot standby mode (set-point change)", "Hot", _, _, "No load", False, True, "partial"),
    ("LG", "Shut-down mode",                      "Cold", _, "Off", "No load", False, _, "exact"),
    ("LG", "Shut-down mode",                      "Cold", _, "Air", "No load", False, _, "exact"),
    ("LG", "Heat-up transition (not named)",      _, "Rising", _, "No load", False, _, "none"),
    ("LG", "Cool-down transition (not named)",    _, _, _, "No load", False, _, "none"),
    # Hanasaki et al., J. Electrochem. Soc. 2014 (standby and shutdown protocols)
    ("Hanasaki", "Shutdown (emergency)",          _, _, _, _, True, _, "exact"),
    ("Hanasaki", "Operation",                     _, _, _, "Load", False, _, "exact"),
    ("Hanasaki", "Operation",                     _, _, _, "Rated", False, _, "exact"),
    ("Hanasaki", "Hot standby (but no power made)", "Hot", "Held", _, "No load", False, _, "partial"),
    ("Hanasaki", "Cold standby (but not a set hold)", "Warm", "Held", _, "No load", False, _, "partial"),
    ("Hanasaki", "Heat-up (not named)",           _, "Rising", _, "No load", False, _, "none"),
    ("Hanasaki", "Cool-down (not named)",         _, "Falling", _, "No load", False, _, "none"),
    ("Hanasaki", "Plant off (not named)",         _, _, _, _, False, _, "none"),
    # Bloom Energy US7846599B2 (start up / steady state / shut down only)
    ("Bloom", "Shut down operating mode",         _, _, _, _, True, _, "partial"),
    ("Bloom", "Steady state operating mode",      _, _, _, "Load", False, _, "exact"),
    ("Bloom", "Steady state operating mode",      _, _, _, "Rated", False, _, "exact"),
    ("Bloom", "Steady state operating mode",      "Hot", "Held", _, "No load", False, _, "exact"),
    ("Bloom", "Steady state operating mode",      "Hot", _, _, "No load", False, True, "partial"),
    ("Bloom", "Start up operating mode",          _, "Rising", _, "No load", False, _, "exact"),
    ("Bloom", "Shut down operating mode",         _, "Falling", _, "No load", False, _, "exact"),
    ("Bloom", "Shut down operating mode",         "Warm", "Held", _, "No load", False, True, "partial"),
    ("Bloom", "Plant off (not named)",            _, _, _, _, False, _, "none"),
]
VOCAB = pd.DataFrame(VOCAB, columns=["vocab", "label", "thermal", "trend", "supply", "load", "trip", "been_hot", "match"])
FACTS = ["thermal", "trend", "supply", "load", "trip", "been_hot"]


def signature(d, lim=OURS):
    """Plant-neutral facts of each minute (columns T_stack_C, dTdt_20min_C_per_h, I_string_A, phase, trip)."""
    t, r, i = d["T_stack_C"], d["dTdt_20min_C_per_h"].fillna(0.0), d["I_string_A"].fillna(0.0)
    hot, cold = t >= lim["t_hot"], t <= lim["t_cold"]
    band = np.where(hot, DTDT_HELD, DTDT_HELD_WARM)
    trend = np.select([r >= band, r <= -band], ["Rising", "Falling"], "Held")
    load = np.select([i >= lim["i_rated"], i >= lim["i_load"]], ["Rated", "Load"], "No load")
    # been hot: held hot or loaded at some minute since the last cold minute (gaps carry over)
    proof = (hot & (trend == "Held")) | (load != "No load")
    been_hot = proof.groupby(cold.cumsum()).cummax() & ~cold
    return pd.DataFrame({
        "thermal": np.select([cold, hot], ["Cold", "Hot"], "Warm"),
        "trend": trend,
        "supply": d["phase"].map(SUPPLY).fillna(""),
        "load": load,
        "trip": d["trip"].astype(bool),
        "been_hot": been_hot,
    }, index=d.index).where(t.notna())


def translate(sig, vocab):
    """Label and match grade of each minute in one vocabulary (first matching row wins)."""
    label = pd.Series(pd.NA, index=sig.index, dtype=object)
    match = label.copy()
    for _, row in VOCAB[VOCAB["vocab"] == vocab].iterrows():
        hit = label.isna() & sig["thermal"].notna()
        for f in FACTS:
            if row[f] != "*":
                hit &= sig[f] == row[f]
        label[hit], match[hit] = row["label"], row["match"]
    return label.fillna("No data"), match.fillna("no data")


def run():
    OUT.mkdir(exist_ok=True)
    d = pd.read_parquet(SRC)
    sig = signature(d)
    out = pd.concat([d[["ind_stage"]], sig], axis=1)
    for v in VOCAB["vocab"].unique():
        out[v], out[f"{v}_match"] = translate(sig, v)
    out.to_parquet(OUT / "crosswalk_1min.parquet")
    VOCAB.to_csv(OUT / "vocabularies.csv", index=False)

    for v in VOCAB["vocab"].unique():
        (pd.crosstab(out["ind_stage"], out[v]) / 60).round(1).to_csv(OUT / f"ours_vs_{v}_hours.csv")
    grade = pd.concat({v: out.groupby("ind_stage")[f"{v}_match"].value_counts(normalize=True).unstack(fill_value=0)
                       for v in VOCAB["vocab"].unique()}, axis=1)
    (grade * 100).round(0).to_csv(OUT / "match_grade_pct.csv")
    sigs = (out.groupby(FACTS + ["ind_stage"], dropna=True).size() / 60).round(1).rename("hours")
    sigs.reset_index().sort_values("hours", ascending=False).to_csv(OUT / "signatures.csv", index=False)
    return out


if __name__ == "__main__":
    out = run()
    pd.set_option("display.width", 250)
    for v in VOCAB["vocab"].unique():
        print(f"\n== ours vs {v} (hours)")
        print((pd.crosstab(out["ind_stage"], out[v]) / 60).round(1).to_string())
    print("\n== match grade, % of each stage's minutes")
    print(pd.read_csv(OUT / "match_grade_pct.csv", header=[0, 1], index_col=0).to_string())
