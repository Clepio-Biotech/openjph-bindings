"""Benchmark normalization strategies before lossy OpenJPH compression.

Samples tiles from ``census.csv`` (stratified by content group so rare signal
tiles are well represented), then for each tile runs every
``condition x qstep``: optionally percentile-clip+rescale, OpenJPH lossy
round-trip, restore to the original intensity domain, and record compression
ratio, distortion metrics, and timings. Per-condition qstep grids come from
``qsteps.csv`` (see calibrate.py) so achieved compression ratios span a
comparable range across conditions. Metrics go to ``results.csv``.

Timings, per row: ``read_seconds`` (read the tile from disk once, shared across
that tile's rows), ``encode_seconds`` (the OpenJPH encode call), and
``write_seconds`` (serialize the .jph to disk). ``end_to_end_seconds`` sums them
(read + compress + write). These are single-tile, single-worker costs; aggregate
parallel throughput is total work over wall-clock, not the per-row figures.

Usage::

    python benchmark.py --channel 561=/data/561 --channel 638=/data/638 \\
        --census census.csv --qsteps qsteps.csv \\
        --percentiles none 0,100 0.1,99.9 1,99 \\
        --samples-per-group 200 --num-workers 90 --outdir bench_out
"""

from __future__ import annotations

import argparse
import csv
import os
import random
import shutil
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import tifffile

import openjph

import metrics
from census import list_tiffs, parse_channels, read_tile_region

ENCODE_KWARGS = dict(
    irreversible=True,
    num_decompositions=5,
    block_size=(64, 64),
    progression_order="CPRL",
    color_transform=False,
    planar=True,
)

CSV_FIELDS = [
    "channel",
    "z",
    "tile_y",
    "tile_x",
    "group",
    "percentile",
    "qstep",
    "compression_ratio",
    "nrmse",
    "psnr",
    "roi_intensity_error",
    "saturation_fraction",
    "original_bytes",
    "encoded_bytes",
    "read_seconds",
    "encode_seconds",
    "write_seconds",
    "end_to_end_seconds",
    "throughput_mpps",
    "throughput_e2e_mpps",
    "status",
    "error",
]


@dataclass
class Condition:
    """A named clipping condition: 'none' (identity) or 'low,high' percentiles."""

    name: str
    low: float | None
    high: float | None

    @classmethod
    def parse(cls, token: str) -> "Condition":
        if token.lower() == "none":
            return cls("none", None, None)
        try:
            low_s, high_s = token.split(",")
            return cls(token, float(low_s), float(high_s))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Invalid condition {token!r}; expected 'none' or 'low,high'."
            ) from exc


@dataclass
class Tile:
    """A sampled tile: census labels, source path, and (once read) its array."""

    channel: str
    z: int
    tile_y: int
    tile_x: int
    group: str
    path: str
    array: np.ndarray | None = None
    read_seconds: float = 0.0


def sample_tiles(census: Path, per_group: int, seed: int) -> list[dict]:
    """Pick ``per_group`` tiles from each (channel, group), seeded random by row."""
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with census.open(newline="") as fh:
        for r in csv.DictReader(fh):
            buckets[(r["channel"], r["group"])].append(r)
    rng = random.Random(seed)
    picked: list[dict] = []
    for (channel, group), rows in sorted(buckets.items()):
        picked += rng.sample(rows, min(per_group, len(rows)))
    return picked


def load_grid(path: Path, conditions: list[Condition]) -> dict[str, list[float]]:
    """Read qsteps.csv (columns: condition, qstep) into condition -> [qsteps]."""
    grid: dict[str, list[float]] = defaultdict(list)
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            grid[r["condition"]].append(float(r["qstep"]))
    missing = [c.name for c in conditions if c.name not in grid]
    if missing:
        raise SystemExit(f"qsteps.csv has no rows for conditions: {missing}")
    return {k: sorted(set(v)) for k, v in grid.items()}


def read_tile(tile: Tile, tile_size: int) -> Tile:
    """Worker: read one tile from disk, timing the read (shared across methods)."""
    t0 = time.perf_counter()
    tile.array = read_tile_region(tile.path, tile.tile_y, tile.tile_x, tile_size)
    tile.read_seconds = time.perf_counter() - t0
    return tile


def _base_row(tile: Tile, cond: Condition, qstep: float) -> dict:
    return {
        "channel": tile.channel,
        "z": tile.z,
        "tile_y": tile.tile_y,
        "tile_x": tile.tile_x,
        "group": tile.group,
        "percentile": cond.name,
        "qstep": qstep,
    }


def run_tile(
    tile: Tile,
    conditions: list[Condition],
    grid: dict[str, list[float]],
    bounds_by_channel: dict[str, dict[str, tuple[float, float] | None]],
    scratch_dir: str,
) -> list[dict]:
    """Worker: every (condition, qstep) for one tile, timing encode + write.

    The .jph is written to a per-worker scratch file (overwritten each row) so
    write_seconds reflects real serialization to disk without piling up files.
    """
    original = tile.array
    bounds = bounds_by_channel[tile.channel]
    mask = metrics.bright_mask(original)
    mp = original.size / 1e6
    scratch = os.path.join(scratch_dir, f"{os.getpid()}.jph")
    rows: list[dict] = []
    for cond in conditions:
        clip = metrics.apply_clip(original, *(bounds[cond.name] or (None, None)))
        for qstep in grid[cond.name]:
            row = _base_row(tile, cond, qstep)
            try:
                t0 = time.perf_counter()
                encoded = openjph.encode(clip.rescaled, qstep=qstep, **ENCODE_KWARGS)
                t_enc = time.perf_counter() - t0
                t0 = time.perf_counter()
                with open(scratch, "wb") as fh:
                    fh.write(encoded)
                    fh.flush()
                t_wr = time.perf_counter() - t0
                # Decode is for the fidelity metrics, not part of the write path.
                recon_rescaled = openjph.decode(
                    encoded, shape=original.shape, dtype="uint16"
                )
                recon = metrics.restore_from_clip(recon_rescaled, clip.lo, clip.hi)
                e2e = tile.read_seconds + t_enc + t_wr
                row.update(
                    {
                        "status": "ok",
                        "original_bytes": original.nbytes,
                        "encoded_bytes": len(encoded),
                        "compression_ratio": original.nbytes / len(encoded)
                        if encoded
                        else float("nan"),
                        "nrmse": metrics.nrmse(original, recon),
                        "psnr": metrics.psnr(original, recon),
                        "roi_intensity_error": metrics.roi_intensity_error(
                            original, recon, mask
                        ),
                        "saturation_fraction": clip.saturation_fraction,
                        "read_seconds": tile.read_seconds,
                        "encode_seconds": t_enc,
                        "write_seconds": t_wr,
                        "end_to_end_seconds": e2e,
                        "throughput_mpps": mp / t_enc if t_enc else float("nan"),
                        "throughput_e2e_mpps": mp / e2e if e2e else float("nan"),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - record and continue
                row.update(
                    {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                )
            rows.append(row)
    return rows


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--channel",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Channel name and folder. Repeatable.",
    )
    p.add_argument("--census", default="bench_out/census.csv")
    p.add_argument("--qsteps", default="bench_out/qsteps.csv")
    p.add_argument(
        "--percentiles",
        nargs="+",
        default=["none"],
        help="Conditions: 'none' or 'low,high' (e.g. 0.1,99.9).",
    )
    p.add_argument("--samples-per-group", type=int, default=200)
    p.add_argument("--tile-size", type=int, default=128)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--num-workers", type=int, default=1)
    p.add_argument(
        "--save-tiles",
        action="store_true",
        help="Also write original TIFFs (off by default).",
    )
    p.add_argument("--outdir", default="bench_out")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    channels = parse_channels(args.channel)
    conditions = [Condition.parse(t) for t in args.percentiles]
    grid = load_grid(Path(args.qsteps), conditions)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    picked = sample_tiles(Path(args.census), args.samples_per_group, args.seed)
    files = {c: list_tiffs(p) for c, p in channels.items()}
    tiles = [
        Tile(
            r["channel"],
            int(r["z"]),
            int(r["tile_y"]),
            int(r["tile_x"]),
            r["group"],
            str(files[r["channel"]][int(r["z"])]),
        )
        for r in picked
    ]
    print(f"Sampled {len(tiles)} tiles from {args.census}.")

    # Read every tile once (timed); the array is reused for all its conditions.
    reader = partial(read_tile, tile_size=args.tile_size)
    if args.num_workers == 1:
        tiles = [reader(t) for t in tiles]
    else:
        with ProcessPoolExecutor(max_workers=args.num_workers) as pool:
            tiles = list(pool.map(reader, tiles))
    print(f"Read {len(tiles)} tile arrays.")

    # Global per-channel clip bounds: percentiles over that channel's pooled tile
    # pixels, so every tile of a channel sees the same [lo, hi] (sample-wide).
    bounds_by_channel: dict[str, dict[str, tuple[float, float] | None]] = {}
    for channel in channels:
        pixels = np.concatenate(
            [t.array.ravel() for t in tiles if t.channel == channel]
        )
        bounds_by_channel[channel] = {
            cond.name: (
                metrics.percentile_thresholds(pixels, cond.low, cond.high)
                if cond.low is not None
                else None
            )
            for cond in conditions
        }

    if args.save_tiles:
        orig_dir = outdir / "chunks" / "original"
        orig_dir.mkdir(parents=True, exist_ok=True)
        for t in tiles:
            stem = f"{t.channel}_z{t.z:04d}_y{t.tile_y:05d}_x{t.tile_x:05d}"
            tifffile.imwrite(orig_dir / f"{stem}.tif", t.array)

    scratch_dir = outdir / ".write_scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    work = partial(
        run_tile,
        conditions=conditions,
        grid=grid,
        bounds_by_channel=bounds_by_channel,
        scratch_dir=str(scratch_dir),
    )
    if args.num_workers == 1:
        results = [work(t) for t in tiles]
    else:
        with ProcessPoolExecutor(max_workers=args.num_workers) as pool:
            results = list(pool.map(work, tiles))
    shutil.rmtree(scratch_dir, ignore_errors=True)
    rows = [row for tile_rows in results for row in tile_rows]
    n_fail = sum(r["status"] == "failed" for r in rows)

    results_path = outdir / "results.csv"
    with results_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {results_path} ({len(rows) - n_fail} ok, {n_fail} failed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
