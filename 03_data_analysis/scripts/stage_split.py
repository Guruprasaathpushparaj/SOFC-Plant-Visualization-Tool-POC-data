"""Split the 1 s raw data into one file per stage episode (Shut-down: per sub-stage).

02_data/parquet/<day>.parquet (1 Hz, all logger columns, values as delivered)
  + stage labels per minute (04_synthetic_data/library/traces_1min.parquet,
    built by build_library.py from operating_states.py)
  -> 02_data/by_stage/<n>_<stage>/<episode_id>.parquet
  -> 02_data/by_stage/7_Shut-down/1_Cooling/<episode_id>_cooling.parquet
  -> 02_data/by_stage/7_Shut-down/2_At_ambient/<episode_id>_at_ambient.parquet
  -> 02_data/by_stage/index.csv          (one row per file)
  -> 02_data/by_stage/summary.csv        (hours and rows per stage / sub-stage)

Shut-down has two sub-stages (operating_states.sub_stage): Cooling (load to zero,
forced or natural cooling, stack still warm) and At ambient (plant off, within
DT_AMBIENT of ambient). A Shut-down episode that holds both is cut at the change, so
each file holds one sub-stage only.

Every 1 s row takes the stage, sub_stage, operation and episode_id of its minute.
Rows whose minute has no stage (logger gaps, 'No data') are left out and counted.
An episode that crosses midnight is written into one file. Every logger column of
any day is kept (the union, 836 columns; a column is blank on days it was not
logged) and stored as float64 (columns that are blank on some days are text in the
day files), so every episode file has the same schema. Rows are kept exactly as logged: some
days (2026-03-01/02/03, 03-13, ...) log the same second twice with different values;
index.csv counts those in dup_timestamps.

    python stage_split.py            # build everything (overwrites by_stage/)
    python stage_split.py --summary  # print the summary of an existing build
"""
import shutil
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from operating_states import SD_AMBIENT, SD_COOLING, STAGES

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "02_data" / "parquet"
LABELS = ROOT / "04_synthetic_data" / "library" / "traces_1min.parquet"
EPISODES = ROOT / "04_synthetic_data" / "library" / "episodes.csv"
OUT = ROOT / "02_data" / "by_stage"
TIME = "Date Time"
LABEL_COLS = ["stage", "sub_stage", "operation", "phase", "episode_id", "file_id"]
# Shut-down sub-stage -> (folder, file suffix)
SUB_DIRS = {SD_COOLING: ("1_Cooling", "cooling"), SD_AMBIENT: ("2_At_ambient", "at_ambient")}


def stage_dir(stage, sub_stage=""):
    d = OUT / f"{STAGES.index(stage) + 1}_{stage.replace(' ', '_')}"
    return d / SUB_DIRS[sub_stage][0] if sub_stage in SUB_DIRS else d


def file_id(episode_id, sub_stage):
    return f"{episode_id}_{SUB_DIRS[sub_stage][1]}" if sub_stage in SUB_DIRS else episode_id


def file_path(stage, sub_stage, fid):
    return stage_dir(stage, sub_stage) / f"{fid}.parquet"


def load_labels():
    lab = pd.read_parquet(LABELS, columns=LABEL_COLS[:-1])
    lab = lab[lab["episode_id"].notna() & (lab["episode_id"] != "")]
    lab = lab.fillna("").astype(str)
    lab["file_id"] = [file_id(e, ss) for e, ss in zip(lab["episode_id"], lab["sub_stage"])]
    return lab


def pieces(lab, ep):
    """One row per output file: start/end from the labelled minutes, rest from the episode table."""
    g = lab.reset_index(names="minute").groupby("file_id", sort=False)
    pc = g.agg(episode_id=("episode_id", "first"), stage=("stage", "first"), sub_stage=("sub_stage", "first"),
               start=("minute", "min"), end=("minute", "max"), minutes=("minute", "size"),
               operations=("operation", lambda x: " > ".join(x[x != x.shift()])),
               phases=("phase", lambda x: " > ".join(v for v in dict.fromkeys(x) if v)))
    pc["end"] += pd.Timedelta("1min")
    # hours with a stage label; logger gaps inside the piece are left out (as in episodes.csv)
    pc["duration_h"] = (pc.pop("minutes") / 60).round(2)
    pc["gap_min"] = ((pc["end"] - pc["start"]).dt.total_seconds() / 60 - 60 * pc["duration_h"]).round().astype(int)
    return pc.join(ep[["run", "complete", "ends_in_trip", "use_for_training", "fold"]], on="episode_id")


def build():
    lab = load_labels()
    ep = pd.read_csv(EPISODES, parse_dates=["start", "end"]).set_index("episode_id")
    if OUT.exists():
        shutil.rmtree(OUT)
    pc = pieces(lab, ep)
    for st, ss in pc[["stage", "sub_stage"]].drop_duplicates().itertuples(index=False):
        stage_dir(st, ss).mkdir(parents=True, exist_ok=True)

    # every column logged on any day, in order of first appearance: tags added or
    # renamed later (e.g. FIRC 1,1,3 is ct_FIRC_113_PV_ProcessValue from 2026-03-17)
    # are blank on the days before, not dropped
    columns = list(dict.fromkeys(c for f in sorted(SRC.glob("*.parquet"))
                                 for c in pq.read_schema(f).names if c != TIME))
    schema = None
    writers, rows, dups, first, last = {}, {}, {}, {}, {}
    dropped = 0
    for f in sorted(SRC.glob("*.parquet")):
        d = pd.read_parquet(f)
        d = d.reindex(columns=[TIME] + columns)
        d[columns] = d[columns].apply(pd.to_numeric, errors="coerce").astype("float64")
        m = d[TIME].dt.floor("min")
        d = pd.concat([d, lab.reindex(m.values).set_axis(d.index)], axis=1)
        keep = d["file_id"].notna()
        dropped += int((~keep).sum())
        d = d[keep]
        for eid, part in d.groupby("file_id", sort=False):
            t = pa.Table.from_pandas(part, preserve_index=False)
            if schema is None:
                schema = t.schema
            if eid not in writers:
                writers[eid] = pq.ParquetWriter(file_path(part["stage"].iat[0], part["sub_stage"].iat[0], eid),
                                                schema, compression="zstd")
                rows[eid], dups[eid], first[eid] = 0, 0, part[TIME].iat[0]
            writers[eid].write_table(t.cast(schema))
            rows[eid] += len(part)
            dups[eid] += int(part[TIME].duplicated().sum())
            last[eid] = part[TIME].iat[-1]
        # close files whose piece ends on or before this day's last minute
        day_end = d[TIME].max() if len(d) else None
        for eid in [e for e in writers if day_end is not None and pc.loc[e, "end"] <= day_end]:
            writers.pop(eid).close()
        print(f"{f.stem}: {keep.sum():>6} rows labelled, {(~keep).sum():>5} without stage", flush=True)
    for w in writers.values():
        w.close()

    idx = pc.loc[list(rows)].copy()
    idx.insert(0, "file", [file_path(st, ss, f).relative_to(OUT).as_posix()
                           for f, st, ss in zip(idx.index, idx["stage"], idx["sub_stage"])])
    idx["first_row"] = pd.Series(first)
    idx["last_row"] = pd.Series(last)
    idx["rows_1s"] = pd.Series(rows)
    idx["dup_timestamps"] = pd.Series(dups)
    idx["coverage_pct"] = (100 * (idx["rows_1s"] - idx["dup_timestamps"])
                           / (idx["duration_h"] * 3600)).round(1)
    idx = idx.sort_values("start")
    idx.to_csv(OUT / "index.csv", index_label="file_id")

    summ = summary(idx)
    summ.to_csv(OUT / "summary.csv")
    print(f"\n{len(idx)} files from {idx['episode_id'].nunique()} episodes, "
          f"{dropped} rows without a stage left out\n")
    print(summ.to_string())
    return idx, summ


def summary(idx=None):
    idx = pd.read_csv(OUT / "index.csv", keep_default_na=False) if idx is None else idx
    s = idx.groupby(["stage", "sub_stage"]).agg(files=("file", "size"), hours=("duration_h", "sum"),
                                                rows_1s=("rows_1s", "sum"))
    s["size_MB"] = [sum(p.stat().st_size for p in stage_dir(st, ss).glob("*.parquet")) / 1e6
                    for st, ss in s.index]
    order = [(st, ss) for st in STAGES for ss in ["", *SUB_DIRS] if (st, ss) in s.index]
    s = s.reindex(order)
    s.loc[("Total", ""), :] = s.sum()
    return s.round(1)


def load_stage(stage, sub_stage=None, columns=None, training_only=False):
    """All 1 s rows of one stage (every file, in time order) as one DataFrame.
    sub_stage: for Shut-down, operating_states.SD_COOLING or SD_AMBIENT; None = both."""
    idx = pd.read_csv(OUT / "index.csv", keep_default_na=False)
    idx = idx[idx["stage"] == stage]
    if sub_stage is not None:
        idx = idx[idx["sub_stage"] == sub_stage]
    if training_only:
        idx = idx[idx["use_for_training"]]
    cols = None if columns is None else [TIME, *columns, *LABEL_COLS]
    return pd.concat([pd.read_parquet(OUT / f, columns=cols) for f in idx["file"]], ignore_index=True)


def load_episode(episode_id, columns=None):
    """One episode (a Shut-down episode with both sub-stages comes back as one table)."""
    idx = pd.read_csv(OUT / "index.csv", keep_default_na=False)
    files = idx.loc[idx["episode_id"] == episode_id].sort_values("start")["file"]
    cols = None if columns is None else [TIME, *columns, *LABEL_COLS]
    return pd.concat([pd.read_parquet(OUT / f, columns=cols) for f in files], ignore_index=True)


if __name__ == "__main__":
    if "--summary" in sys.argv:
        print(summary().to_string())
    else:
        build()
