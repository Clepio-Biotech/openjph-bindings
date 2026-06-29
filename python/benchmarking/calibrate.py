"""Pick a per-condition qstep grid so achieved compression ratios are comparable.

A fixed qstep yields different file sizes under different clipping (coarser
clipping compresses more), so to compare normalization strategies at matched
compression ratio each condition needs its own qsteps. This samples a few tiles,
sweeps a wide log-spaced qstep range per condition, measures the median achieved
ratio at each qstep, then inverts that curve to choose the qsteps hitting target
ratios spanning ``--ratio-min``..``--ratio-max``. Output is ``qsteps.csv``
(columns: condition, qstep), consumed by benchmark.py.

Usage::

    python calibrate.py --channel 561=/data/561 --channel 638=/data/638 \\
        --census census.csv --percentiles none 0,100 0.1,99.9 1,99 \\
        --out qsteps.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

import openjph

import metrics
from benchmark import ENCODE_KWARGS, Condition, Tile, sample_tiles
from census import list_tiffs, parse_channels, read_tile_region


def ratio_at(arr: np.ndarray, bounds, qstep: float) -> float:
    clip = metrics.apply_clip(arr, *(bounds or (None, None)))
    encoded = openjph.encode(clip.rescaled, qstep=qstep, **ENCODE_KWARGS)
    return arr.nbytes / len(encoded) if encoded else float("nan")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--channel", action="append", required=True, metavar="NAME=PATH")
    p.add_argument("--census", default="bench_out/census.csv")
    p.add_argument("--percentiles", nargs="+", default=["none"])
    p.add_argument(
        "--tiles",
        type=int,
        default=40,
        help="Tiles to calibrate on (sampled across all groups).",
    )
    p.add_argument("--tile-size", type=int, default=128)
    p.add_argument("--ratio-min", type=float, default=10.0)
    p.add_argument("--ratio-max", type=float, default=100.0)
    p.add_argument(
        "--num-qsteps",
        type=int,
        default=12,
        help="qsteps per condition (target ratios are log-spaced).",
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="bench_out/qsteps.csv")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    channels = parse_channels(args.channel)
    conditions = [Condition.parse(t) for t in args.percentiles]

    # A handful of tiles spread across groups.
    per_group = max(1, args.tiles // 3)
    picked = sample_tiles(Path(args.census), per_group, args.seed)
    files = {c: list_tiffs(p) for c, p in channels.items()}
    tiles = []
    for r in picked:
        path = str(files[r["channel"]][int(r["z"])])
        arr = read_tile_region(path, int(r["tile_y"]), int(r["tile_x"]), args.tile_size)
        tiles.append(
            Tile(
                r["channel"],
                int(r["z"]),
                int(r["tile_y"]),
                int(r["tile_x"]),
                r["group"],
                path,
                array=arr,
            )
        )
    print(f"Calibrating on {len(tiles)} tiles.")

    # Per-channel clip bounds, matching benchmark.py (pooled tile pixels).
    bounds_by_channel = {}
    for channel in channels:
        pixels = np.concatenate(
            [t.array.ravel() for t in tiles if t.channel == channel]
        )
        bounds_by_channel[channel] = {
            c.name: (
                metrics.percentile_thresholds(pixels, c.low, c.high)
                if c.low is not None
                else None
            )
            for c in conditions
        }

    # Wide log-spaced probe grid; map each qstep to the median ratio it achieves.
    probe = np.logspace(-4, -1.0, 24)
    targets = np.logspace(
        np.log10(args.ratio_min), np.log10(args.ratio_max), args.num_qsteps
    )

    rows_out = []
    for cond in conditions:
        med_ratio = np.array(
            [
                float(
                    np.median(
                        [
                            ratio_at(
                                t.array, bounds_by_channel[t.channel][cond.name], q
                            )
                            for t in tiles
                        ]
                    )
                )
                for q in probe
            ]
        )
        # ratio increases with qstep; invert by interpolating qstep over log-ratio.
        order = np.argsort(med_ratio)
        lr, lq = np.log10(med_ratio[order]), np.log10(probe[order])
        qsteps = np.power(10.0, np.interp(np.log10(targets), lr, lq))
        for q in sorted(set(np.round(qsteps, 6))):
            rows_out.append((cond.name, q))
        print(
            f"[{cond.name}] ratio {med_ratio.min():.1f}..{med_ratio.max():.1f} "
            f"-> {len(set(np.round(qsteps, 6)))} qsteps"
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["condition", "qstep"])
        writer.writerows(rows_out)
    print(f"Wrote {out} ({len(rows_out)} rows).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
