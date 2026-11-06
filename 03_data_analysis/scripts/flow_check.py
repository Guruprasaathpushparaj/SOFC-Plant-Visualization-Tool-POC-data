"""Check, for every day, that the flow within each stage matches operational-modes.md §2–§4.

Every day is segmented with operating_states.segment(); the days are stitched
into one timeline so a stage that crosses midnight is judged as one episode.
Each episode is then checked against the documented flow and values:

    §2    stage transitions          (e.g. Shut-down -> Start-up -> Hot standby -> load)
    §3.1  Start-up flow              heat-up ~50 °C/h -> ~510 °C hold (< 6 h) -> 8–27 °C/h -> Hot standby;
                                     a no-load re-heat / cool-back of a hot stack is Thermal adjustment
                                     (Hot standby = constant T)
    §3.2  Hot standby -> load        ramp-up 0.3–0.9 A/min per string, limit 1 A/min
    §3.3  Shut-down flow             600→300 °C at -45…-75 °C/h, 300→100 °C at -27…-57 °C/h,
                                     natural cooling -1…-2 °C/h, then plant off at ambient until a new Start-up
    §4.3  Hot standby levels         ~510 °C (low-temperature hold, ≥ 6 h) or 575–610 °C

Documented ranges were read off this data, so a value is OK when it falls inside
the range widened by TOL on each side; [Rule] limits (120 °C/h, 1 A/min, 720 °C)
are checked without tolerance (status LIMIT). Segmentation rules set by the
user (6 h hold, Shut-down ends within 30 K of ambient) are checked without tolerance too
(status RULE): a RULE flag means the stage labels disagree with §1. Usage:

    python 03_data_analysis/scripts/flow_check.py            # all days
    python 03_data_analysis/scripts/flow_check.py 20260319   # one or more days

Writes to 03_data_analysis/flow_check/:
    episodes.csv      one row per stage episode, with its operation sequence
    checks.csv        one row per check (episode, check, value, expected, status)
    per_day.csv       one row per day: number of OK / DEVIATION / RULE / LIMIT checks
"""
import contextlib
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import industrial_stages as ins  # noqa: E402
import operating_states as ops  # noqa: E402

OUT = ops.ROOT / "03_data_analysis" / "flow_check"
TOL = 0.2                 # widen documented (observed) ranges by 20 % of their width each side
GAP_SPLIT = pd.Timedelta(hours=ins.EPISODE_GAP_H)  # one shared plant-episode gap (6 h)
LIMIT_HEAT = 120.0        # °C/h heat-up limit [Rule, Elcogen]
LIMIT_DIDT = 1.0          # A/min per string load ramp limit [Rule, Elcogen]
LIMIT_T = 720.0           # °C maximum stack temperature [Rule, IKTS]

# §2 transition diagram plus the §1 rules (Shut-down may end in a new Start-up;
# Hot standby is practically skipped at stop, §3.3). Start-up only follows a
# Shut-down (or Idle) and Part load only follows Hot standby; a re-heat or
# cool-back of a hot stack is the Thermal adjustment stage (2026-10-14, later).
ALLOWED = {
    ("Idle", "Start-up"), ("Idle", "Shut-down"),
    ("Start-up", "Hot standby"),
    ("Hot standby", "Part load"), ("Hot standby", "Rated power"),
    ("Part load", "Rated power"), ("Rated power", "Part load"),
    ("Part load", "Hot standby"), ("Rated power", "Hot standby"),
    ("Part load", "Shut-down"), ("Rated power", "Shut-down"),
    ("Hot standby", "Shut-down"),
    ("Shut-down", "Start-up"),
    ("Hot standby", ops.ADJUST), (ops.ADJUST, "Hot standby"),
    ("Part load", ops.ADJUST), ("Rated power", ops.ADJUST), (ops.ADJUST, "Shut-down"),
}


def transition_ok(prv, e):
    return (prv["stage"], e["stage"]) in ALLOWED


def stitch(days):
    frames = []
    for d in days:
        print(f"segmenting {d} ...", flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            s, _ = ops.segment(d)
        s["day"] = pd.Timestamp(d).date()
        frames.append(s)
    return pd.concat(frames).sort_index()


def episodes(s):
    """Contiguous runs of one stage; 'No data' is skipped, gaps ≥ GAP_SPLIT split."""
    v = s[s["stage"] != "No data"]
    gap = v.index.to_series().diff() > GAP_SPLIT
    ep = ins.runs(v["stage"])
    out = []
    for k, g in v.groupby(ep):
        seq = g["operation"][g["operation"] != g["operation"].shift()].tolist()
        out.append(dict(ep=int(k), stage=g["stage"].iat[0], start=g.index[0],
                        end=g.index[-1] + pd.Timedelta("1min"),
                        days=sorted(set(g["day"])), gap_before=bool(gap.loc[g.index[0]]),
                        ops=" -> ".join(seq), rows=g,
                        sub_stages=" -> ".join(x for x in g["sub_stage"][g["sub_stage"] != g["sub_stage"].shift()] if x),
                        phases=" -> ".join(x for x in g["phase"][g["phase"] != g["phase"].shift()] if x),
                        # re-heat / cool-back of a hot stack, from its operations
                        hot_start=g["operation"].isin(ops.REHEAT_OPS).any(),
                        hot_end=g["operation"].isin(ops.COOL_BACK_OPS).any()))
    for i, e in enumerate(out):
        e["prev_ep"] = out[i - 1] if i > 0 and not e["gap_before"] else None
        e["prev"] = out[i - 1]["stage"] if i > 0 and not e["gap_before"] else None
        e["next"] = out[i + 1]["stage"] if i + 1 < len(out) and not out[i + 1]["gap_before"] else None
    return out


def judge(value, lo, hi, limit=False):
    if value is None or pd.isna(value):
        return "n/a"
    if limit:
        return "OK" if lo <= value <= hi else ("RULE" if limit == "rule" else "LIMIT")
    w = (hi - lo) * TOL
    return "OK" if lo - w <= value <= hi + w else "DEVIATION"


def band_rate(T, top, bottom):
    """Cool-down rate between the last downward crossings of top and bottom (§4.1).

    If the stack never reached top in the episode, the band starts at its
    highest temperature; if it never fell to bottom, it ends at its lowest.
    """
    T = T.dropna()
    top, bottom = min(top, T.max()), max(bottom, T.min())
    if top - bottom < 50:
        return None
    t0 = T.index[T >= top - 1][-1]
    after = T[t0:]
    t1 = after.index[after <= bottom + 1][0]
    h = (t1 - t0).total_seconds() / 3600
    return round((T[t1] - T[t0]) / h, 2) if h > 0 else None


def med(x):
    x = x.dropna()
    return round(float(x.median()), 2) if len(x) else None


def share(g, phases):
    """% of the episode's logged minutes in the given gas/air phases."""
    ph = g["phase"][g["phase"] != ""]
    return round(100 * ph.isin(phases).mean(), 1) if len(ph) else None


def forming_switch_T(g, on):
    """Stack °C where forming gas comes on (on=True) or goes off for good (False)."""
    f = (g["phase"] == ops.PH_FORMING).to_numpy()
    if not f.any() or (on and f[0]) or (not on and f[-1]):
        return None
    if on and np.flatnonzero(f)[0] < ops.GAS_GAP_MIN:  # a short gap at the block start is not a switch-on
        return None
    i = np.flatnonzero(f)[0] if on else np.flatnonzero(f)[-1] + 1
    return round(float(g["T_stack_C"].iloc[i]), 1) if pd.notna(g["T_stack_C"].iloc[i]) else None


def check_startup(e, g):
    r = []
    # §5.2: heat-up starts in air; forming gas (N2 + H2) protects the anode from ~200 °C
    r.append(("§5.2 forming gas on at stack °C", forming_switch_T(g, True), 150, 300, False))
    T, dT = g["T_stack_C"], g["dTdt_C_per_h"]
    r.append(("§4.2 heat-up rate, max °C/h (median TC)", round(dT.max(), 1), -1e9, LIMIT_HEAT, True))
    # regular 1-min clock: 'No data' rows and missing days are dropped from g, so shift(30) must be 30 min, not 30 rows
    tmax = g["T_stack_max_C"].asfreq("1min")
    r.append(("§4.2 heat-up rate, max °C/h (hottest TC)",
              round((tmax.shift(-30) - tmax.shift(30)).max(), 1), -1e9, LIMIT_HEAT, True))
    if e["prev"] == "Shut-down" and T.dropna().iat[0] < ops.T_AMB_DEFAULT + ops.DT_AMBIENT:
        r.append(("§3.1 start temperature (from ambient)", round(T.dropna().iat[0], 1), 10, 40, False))
    step1 = (T > 100) & (T < 500) & (dT > ops.DTDT_HEAT)
    r.append(("§3.1 heat-up step 1 rate, median °C/h", med(dT[step1]), 34, 56, False))
    hold = g["operation"] == "Intermediate hold (~510 °C)"
    if hold.any():
        r.append(("§3.1 intermediate hold level °C", med(T[hold]), 490, 530, False))
        r.append(("§3.1 intermediate hold < 6 h, hours", round(hold.sum() / 60, 1), 0, 6, "rule"))
    step2 = (T > 520) & (T < 570) & (dT > 0)
    if step2.any():
        r.append(("§3.1 step 2 rate 520→570 °C, median °C/h", med(dT[step2]), 8, 27, False))
    nxt = e["next"] if e["next"] is not None else "open (data ends/gap)"
    r.append(("§3.1 Start-up ends in Hot standby", nxt, "-" if e["next"] is None else "Hot standby", None, None))
    return r


def check_standby(e, g):
    r = []
    T, dT = g["T_stack_C"], g["dTdt_C_per_h"]
    low = g["operation"] == ops.LOW_HOLD
    if low.any():
        r.append(("§4.3 low-temperature hold level °C", med(T[low]), 480, 540, False))
        r.append(("§4.3 low-temperature hold ≥ 6 h, hours", round(low.sum() / 60, 1), 6, 1e9, "rule"))
    hold = g["operation"] == "Temperature hold"
    if hold.any():
        r.append(("§4.3 hot standby level °C", med(T[hold]), 575, 610, False))
    r.append(("§5.2 Hot standby under forming gas or natural gas, % of minutes",
              share(g, [ops.PH_FORMING, ops.PH_NG]), 95, 100, "rule"))
    # §1: Hot standby is a constant temperature (20-min slope, as used for the
    # labels; the 10 edge minutes are left out, their window sees the next ramp)
    r.append(("§1 hot standby constant, |dT/dt| p95 °C/h",
              med(g["dTdt_20min_C_per_h"].iloc[10:-10].abs().quantile([.95])), 0, ops.DTDT_STABLE, False))
    return r


def check_load(e, g):
    r = []
    dI = g["dIdt_A_per_min"].where(g["dIdt_A_per_min"].abs() > ops.DIDT_RAMP)
    up, dn = dI[dI > 0], dI[dI < 0]
    if len(up):
        r.append(("§3.2 ramp-up p95 A/min/string", round(up.quantile(.95), 2), 0.3, 0.9, False))
        r.append(("§4.4 ramp-up max ≤ 1 A/min/string", round(up.max(), 2), 0, LIMIT_DIDT, True))
    if len(dn):
        r.append(("§3.3 ramp-down p5 A/min/string", round(dn.quantile(.05), 2), -3, -1, False))
    r.append(("§3.2 current max A/string (rated 30 A)", round(g["I_string_A"].max(), 1), 0, 30, True))
    r.append(("§5.2 load on natural gas, % of minutes", share(g, [ops.PH_NG]), 100, 100, "rule"))
    return r


def check_shutdown(e, g):
    r = []
    T, dT = g["T_stack_C"], g["dTdt_C_per_h"]
    air = g["P_air_in"] > ops.AIR_ON
    # forced-cooling blocks only: the Shut-down now runs on through the air-off
    # tail, where air switching on just before the next heat-up is not cooling
    forced = T[air & (g["operation"] == "Cool-down (air flow on)")]
    if len(forced) > 30:
        r.append(("§3.3 forced cooling 600→300 °C, band rate °C/h", band_rate(forced, 600, 300), -75, -45, False))
        r.append(("§3.3 forced cooling 300→100 °C, band rate °C/h", band_rate(forced, 300, 100), -57, -27, False))
    # §5.2 normal shut-down: forming gas protects the anode, switched off once cool
    r.append(("§5.2 forming gas off at stack °C", forming_switch_T(g, False), 150, 320, False))
    amb_end = g["T_amb_C"] + ops.DT_AMBIENT
    nat = ~air & (g["P_EAPH_kW"] * 1000 < ops.EAPH_ON_W) & (T > amb_end) & (dT < 0)
    if nat.sum() > 60:
        r.append(("§3.3 natural cooling, median °C/h", med(dT[nat]), -2, -1, False))
    t_end = round(T.dropna().iat[-1], 1)
    if e["next"] is None:
        r.append(("§1 Shut-down ends at ambient + 30 K or at a new Start-up", f"open at {t_end} °C (data ends/gap)", "-", None, None))
    elif e["next"] == "Start-up":
        r.append(("§1 Shut-down ends at ambient + 30 K or at a new Start-up", "Start-up", "Start-up", None, None))
    else:
        r.append(("§1 Shut-down ends at ambient + 30 K, end °C", t_end, -50, round(amb_end.dropna().iat[-1], 1), "rule"))
    return r


def check_adjust(e, g):
    # Thermal adjustment: a hot stack (no load) re-heating or cooling back (§1)
    r = []
    T, dT = g["T_stack_C"], g["dTdt_C_per_h"]
    r.append(("§4.2 re-heat rate, max °C/h (median TC)", round(dT.max(), 1), -1e9, LIMIT_HEAT, True))
    r.append(("§4.5 cool-back rate, min °C/h (median TC)", round(dT.min(), 1), -LIMIT_HEAT, 1e9, True))
    # §3.1/§4.2: the 8–27 °C/h step is the climb from the ~510 °C hold to 575 °C
    reheat = (g["operation"] == "Re-heat to operating temperature") & T.between(520, 570) & (dT > 0)
    if reheat.sum() > 30:
        r.append(("§3.1 re-heat 520→570 °C after low hold, median °C/h", med(dT[reheat]), 8, 27, False))
    r.append(("§1 stack stays hot (≥ 450 °C), min °C", round(T.min(), 1), ops.T_HOT, 1e9, "rule"))
    r.append(("§5.2 hot stack under forming gas or natural gas, % of minutes",
              share(g, [ops.PH_FORMING, ops.PH_NG]), 95, 100, "rule"))
    return r


def check_idle(e, g):
    # Idle is a warm, plant-off stack with no Shut-down before it (§1)
    val = "Shut-down before" if e["prev"] == "Shut-down" else "no Shut-down before"
    return [("§1 Idle never follows a Shut-down", val, "no Shut-down before", None, None),
            ("§1 Idle: plant off (no air, no gas), % of minutes", share(g, [ops.PH_OFF]), 95, 100, "rule")]


CHECKS = {"Start-up": check_startup, "Hot standby": check_standby, "Part load": check_load,
          "Rated power": check_load, "Shut-down": check_shutdown, "Idle": check_idle,
          ops.ADJUST: check_adjust}


def run(days):
    s = stitch(days)
    eps = episodes(s)
    rows = []
    for e in eps:
        g = e["rows"]
        base = dict(ep=e["ep"], stage=e["stage"], start=e["start"], end=e["end"],
                    days=",".join(str(d) for d in e["days"]))
        if e["prev"] is not None:
            ok = transition_ok(e["prev_ep"], e)
            rows.append({**base, "check": "§2 transition", "value": f"{e['prev']} -> {e['stage']}",
                         "expected": "in §2 diagram", "status": "OK" if ok else "DEVIATION"})
        rows.append({**base, "check": "§4 max stack temperature °C (hottest TC)",
                     "value": round(g["T_stack_max_C"].max(), 1), "expected": f"≤ {LIMIT_T}",
                     "status": judge(g["T_stack_max_C"].max(), -50, LIMIT_T, True)})
        for name, val, lo, hi, limit in CHECKS[e["stage"]](e, g):
            if limit is None:  # categorical check
                st = "OPEN" if lo == "-" else ("OK" if val == lo else "DEVIATION")
                exp = lo
            else:
                st = judge(val, lo, hi, limit)
                exp = f"≥ {lo}" if hi >= 1e8 else f"≤ {hi}" if lo <= -1e8 else f"{lo} … {hi}"
            rows.append({**base, "check": name, "value": val, "expected": exp, "status": st})
    checks = pd.DataFrame(rows)
    ep_tab = pd.DataFrame([{k: v for k, v in e.items() if k not in ("rows", "prev_ep")} for e in eps])
    ep_tab["duration_h"] = ((ep_tab.end - ep_tab.start).dt.total_seconds() / 3600).round(1)
    ep_tab["days"] = ep_tab["days"].map(lambda d: ",".join(map(str, d)))

    # A multi-day episode's checks are counted on every day it covers.
    ex = checks.assign(day=checks["days"].str.split(",")).explode("day")
    per_day = ex.pivot_table(index="day", columns="status", values="check", aggfunc="count", fill_value=0)
    for c in ("OK", "DEVIATION", "RULE", "LIMIT", "OPEN", "n/a"):
        if c not in per_day:
            per_day[c] = 0
    per_day["verdict"] = np.select([per_day["LIMIT"] > 0, per_day["RULE"] > 0, per_day["DEVIATION"] > 0],
                                   ["LIMIT BREACH", "LABEL vs RULE", "DEVIATES"], "MATCHES")
    flagged = ex[ex.status.isin(["DEVIATION", "LIMIT", "RULE"])].groupby("day")["check"].agg(
        lambda x: "; ".join(sorted(set(x))))
    per_day["flagged_checks"] = flagged.reindex(per_day.index).fillna("")
    stages = s[s.stage != "No data"].groupby("day")["stage"].agg(
        lambda x: " -> ".join(x[x != x.shift()]))
    stages.index = stages.index.astype(str)
    per_day.insert(0, "stage_flow", stages.reindex(per_day.index))
    return ep_tab, checks, per_day[["stage_flow", "OK", "DEVIATION", "RULE", "LIMIT", "OPEN", "verdict", "flagged_checks"]]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    days = sys.argv[1:] or sorted(p.name[:8] for p in ops.SRC.glob("*_10s.parquet"))
    ep_tab, checks, per_day = run(days)
    OUT.mkdir(parents=True, exist_ok=True)
    ep_tab.to_csv(OUT / "episodes.csv", index=False)
    checks.to_csv(OUT / "checks.csv", index=False)
    per_day.to_csv(OUT / "per_day.csv")
    pd.set_option("display.width", 250, "display.max_colwidth", 120, "display.max_rows", 500)
    print(per_day[["OK", "DEVIATION", "RULE", "LIMIT", "OPEN", "verdict", "flagged_checks"]].to_string())
    bad = checks[checks.status.isin(["DEVIATION", "RULE", "LIMIT"])]
    print(f"\n{len(bad)} flagged checks of {len(checks)}:")
    print(bad[["days", "stage", "check", "value", "expected", "status"]].to_string(index=False))
