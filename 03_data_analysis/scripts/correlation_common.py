"""Pearson and Spearman correlation across all columns of the common dataset.

Reads one ../02_data/common/<day>.txt (tab-separated, decimal comma, 1 Hz)
(or --all for every day), resamples to RESAMPLE means, drops
constant / mostly-empty columns, then writes into 03_data_analysis/correlation/:

  pearson.csv, spearman.csv           full matrices
  correlation.xlsx                    both matrices + top pairs + dropped columns
  top_pairs.csv                       all column pairs ranked by |r|
  heatmap_pearson.png / _spearman.png clustered heatmaps (same column order)

Usage:  python correlation_common.py [--file 20251030.txt | --all] [--resample 10s]
                                      [--min-coverage 0.5]
"""

import argparse
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow.csv as pv
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.spatial.distance import squareform

BASE = Path(__file__).resolve().parents[1]
SRC = BASE.parent / "02_data" / "common"
OUT = BASE / "correlation"


def load_day(args):
    path, resample = args
    t0 = time.time()
    table = pv.read_csv(
        path,
        parse_options=pv.ParseOptions(delimiter="\t"),
        convert_options=pv.ConvertOptions(
            decimal_point=",", column_types={"Date Time": "string"}
        ),
    )
    df = table.to_pandas()
    df.index = pd.to_datetime(df.pop("Date Time"), format="%d.%m.%Y %H:%M:%S")
    df = df.apply(pd.to_numeric, errors="coerce").astype("float64")
    df = df.resample(resample).mean()
    print(
        f"  {path.name}: {len(table):,} rows -> {len(df):,} ({time.time() - t0:.1f}s)",
        flush=True,
    )
    return df


def top_pairs(pear, spear):
    iu = np.triu_indices(len(pear), k=1)
    cols = pear.columns
    pairs = pd.DataFrame(
        {
            "col_a": cols[iu[0]],
            "col_b": cols[iu[1]],
            "pearson": pear.values[iu],
            "spearman": spear.values[iu],
        }
    )
    pairs["spearman_minus_pearson"] = pairs["spearman"] - pairs["pearson"]
    pairs["max_abs"] = pairs[["pearson", "spearman"]].abs().max(axis=1)
    return pairs.sort_values("max_abs", ascending=False).reset_index(drop=True)


def cluster_order(corr):
    dist = 1 - corr.abs().fillna(0).values
    np.fill_diagonal(dist, 0)
    dist = (dist + dist.T) / 2
    return leaves_list(linkage(squareform(dist, checks=False), method="average"))


def heatmap(corr, order, title, path):
    c = corr.iloc[order, order]
    n = len(c)
    size = max(12, n * 0.09)
    fig, ax = plt.subplots(figsize=(size, size))
    im = ax.imshow(c.values, cmap="RdBu_r", vmin=-1, vmax=1, interpolation="nearest")
    fs = max(2, min(8, 900 / n))
    ax.set_xticks(range(n), c.columns, rotation=90, fontsize=fs)
    ax.set_yticks(range(n), c.index, fontsize=fs)
    ax.set_title(title, fontsize=14)
    fig.colorbar(im, ax=ax, fraction=0.02, pad=0.01)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default="20251030.txt", help="single day file in common/")
    ap.add_argument("--all", action="store_true", help="use every file in common/")
    ap.add_argument("--resample", default="10s")
    ap.add_argument(
        "--min-coverage",
        type=float,
        default=0.5,
        help="drop columns with less than this fraction of non-null values",
    )
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    files = sorted(SRC.glob("*.txt")) if a.all else [SRC / a.file]
    print(f"Loading {len(files)} files, resample={a.resample}")
    with ProcessPoolExecutor(min(a.workers, len(files))) as ex:
        days = list(ex.map(load_day, [(f, a.resample) for f in files]))
    df = pd.concat(days).sort_index()
    df = df[~df.index.duplicated()].dropna(how="all")
    print(f"Combined: {df.shape[0]:,} rows x {df.shape[1]} cols")

    coverage = df.notna().mean()
    std = df.std()
    dropped = pd.DataFrame({"coverage": coverage, "std": std})
    dropped["reason"] = np.where(
        coverage < a.min_coverage, "low coverage", np.where(~(std > 0), "constant", "")
    )
    dropped = dropped[dropped["reason"] != ""]
    df = df.drop(columns=dropped.index)
    print(
        f"Dropped {len(dropped)} columns (constant / low coverage); "
        f"{df.shape[1]} remain"
    )

    df64 = df
    t0 = time.time()
    pear = df64.corr(method="pearson", min_periods=100)
    spear = df64.rank().corr(
        method="pearson", min_periods=100
    )  # Spearman = Pearson on ranks
    print(f"Correlations computed ({time.time() - t0:.1f}s)")

    # near-constant columns (float noise only) pass the std check but give all-NaN rows
    empty = pear.columns[(pear.notna().sum() <= 1) | (spear.notna().sum() <= 1)]
    if len(empty):
        pear = pear.drop(index=empty, columns=empty)
        spear = spear.drop(index=empty, columns=empty)
        extra = pd.DataFrame(
            {
                "coverage": coverage[empty],
                "std": std[empty],
                "reason": "no valid correlation",
            }
        )
        dropped = pd.concat([dropped, extra])
        print(
            f"Dropped {len(empty)} more columns with no valid correlation; "
            f"{len(pear)} remain"
        )

    pear.to_csv(OUT / "pearson.csv", float_format="%.4f")
    spear.to_csv(OUT / "spearman.csv", float_format="%.4f")
    pairs = top_pairs(pear, spear)
    pairs.to_csv(OUT / "top_pairs.csv", index=False, float_format="%.4f")

    with pd.ExcelWriter(OUT / "correlation.xlsx") as xw:
        pairs.head(1000).to_excel(xw, sheet_name="top_pairs", index=False)
        pear.round(4).to_excel(xw, sheet_name="pearson")
        spear.round(4).to_excel(xw, sheet_name="spearman")
        dropped.to_excel(xw, sheet_name="dropped_columns")

    order = cluster_order(spear)
    heatmap(
        pear,
        order,
        f"Pearson correlation ({a.resample} means, {len(df):,} rows)",
        OUT / "heatmap_pearson.png",
    )
    heatmap(
        spear,
        order,
        f"Spearman correlation ({a.resample} means, {len(df):,} rows)",
        OUT / "heatmap_spearman.png",
    )

    print(f"\nOutputs written to {OUT}")
    print("\nTop 15 pairs by |r|:")
    print(pairs.head(15).to_string(index=False, float_format="%.3f"))
    big_gap = pairs.reindex(
        pairs["spearman_minus_pearson"].abs().sort_values(ascending=False).index
    ).head(10)
    print("\nLargest Spearman vs Pearson gaps (non-linear / outlier-driven):")
    print(big_gap.to_string(index=False, float_format="%.3f"))


if __name__ == "__main__":
    main()
