"""Build the 1 s and 10 s parquet files for days missing from the original set.

02_data/raw/<day>.txt -> 02_data/parquet/<day>.parquet -> 02_data/downsampled/<day>_10s.parquet

Reproduces the original files (checked against all existing days):
* 1 s: tab-separated, decimal comma, lines without a tab skipped, header read as UTF-8
  with replacement (so 'Gerät' -> 'Ger�t'), all-blank columns as string, the rest float64.
* 10 s: mean over clock-aligned 10 s windows (labelled by window start), windows without
  any sample dropped, text columns take the first value. Column order and dtypes follow 1 s.

A 1 s file is (re)built from raw only when it is missing or empty; single-header raw files only.

    python downsample.py            # build every day that has no 10 s file yet
    python downsample.py 20260322   # (re)build the 10 s file of the given days
    python downsample.py --check    # rebuild all 10 s files in memory and compare with disk
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pv

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "02_data" / "raw"
SRC = ROOT / "02_data" / "parquet"
DST = ROOT / "02_data" / "downsampled"


def raw_to_parquet(day):
    with open(RAW / f"{day}.txt", "rb") as fh:
        header = fh.readline().decode("utf-8", errors="replace").rstrip("\r\n").split("\t")
        lines = [line for line in fh if b"\t" in line]
    if {line.count(b"\t") for line in lines} != {len(header) - 1}:
        raise ValueError(f"{day}: header changes inside the file, not handled here")
    d = pv.read_csv(
        pa.py_buffer(b"".join(lines)),
        read_options=pv.ReadOptions(column_names=header),
        parse_options=pv.ParseOptions(delimiter="\t"),
        convert_options=pv.ConvertOptions(decimal_point=",", column_types={"Date Time": "string"}),
    ).to_pandas()
    d["Date Time"] = pd.to_datetime(d["Date Time"], format="%d.%m.%Y %H:%M:%S").astype("datetime64[us]")
    for c in d.columns[1:]:
        d[c] = d[c].astype("str") if d[c].isna().all() else d[c].astype("float64")
    d.to_parquet(SRC / f"{day}.parquet", index=False)
    print(f"{day}: {len(d)} rows x {d.shape[1]} cols -> {SRC / f'{day}.parquet'}")


def downsample(day):
    src = SRC / f"{day}.parquet"
    if not src.exists() or src.stat().st_size == 0:
        raw_to_parquet(day)
    d = pd.read_parquet(src).set_index("Date Time")
    num = d.columns[d.dtypes == "float64"]
    g = d.groupby(d.index.floor("10s"))
    out = pd.concat([g[num].mean(), g[d.columns.difference(num)].first()], axis=1)[d.columns]
    out = out.astype(d.dtypes.to_dict()).copy()
    out.index.name = "Date Time"
    return out.reset_index()


def check(day):
    new, old = downsample(day), pd.read_parquet(DST / f"{day}_10s.parquet")
    if list(new.columns) != list(old.columns) or len(new) != len(old):
        return f"shape {new.shape} vs {old.shape}"
    if not new["Date Time"].equals(old["Date Time"]):
        return "timestamps differ"
    num = new.columns[new.dtypes == "float64"]
    a, b = new[num].to_numpy(), old[num].to_numpy()
    ok = np.isclose(a, b, equal_nan=True, rtol=1e-9, atol=1e-15)     # atol: summation-order noise around 0
    return "ok" if ok.all() else f"{(~ok).sum()} values differ"


if __name__ == "__main__":
    args = sys.argv[1:]
    days = sorted(p.stem for p in RAW.glob("*.txt"))
    if args == ["--check"]:
        for day in days:
            if (DST / f"{day}_10s.parquet").exists():
                print(day, check(day))
        sys.exit()
    for day in args or [d for d in days if not (DST / f"{d}_10s.parquet").exists()]:
        out = downsample(day)
        out.to_parquet(DST / f"{day}_10s.parquet", index=False)
        print(f"{day}: {len(out)} rows x {out.shape[1]} cols -> {DST / f'{day}_10s.parquet'}")
