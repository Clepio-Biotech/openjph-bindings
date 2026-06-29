"""Census of every tile in the volume, to characterize how signal is distributed.

Scans each z-slice of each channel in parallel, cuts it into ``--tile-size``
tiles, and records a few cheap features per tile. From those it assigns, per
channel, a structural ``group`` (background / sparse-signal / dense-signal):
how much of the tile carries signal (coverage), data-driven via Otsu cuts —
background = low dynamic range; among signal tiles, dense = high foreground
coverage, sparse = low. Output is ``census.csv``, one row per tile, keyed by
``(channel, z, tile_y, tile_x)`` so benchmark/plots can join.

Usage::

    python census.py --channel 561=/data/561 --channel 638=/data/638 \\
        --tile-size 128 --num-workers 90 --out census.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import tifffile

TIFF_SUFFIXES = (".tif", ".tiff", ".TIF", ".TIFF")

CENSUS_FIELDS = [
    "channel",
    "z",
    "tile_y",
    "tile_x",
    "median",
    "p99",
    "fg_frac",
    "dynamic_range",
    "group",
]


def list_tiffs(folder: str | Path) -> list[Path]:
    """Sorted TIFF files in ``folder`` (one 2D z-slice each)."""
    folder = Path(folder)
    return sorted(p for p in folder.iterdir() if p.suffix in TIFF_SUFFIXES)


def read_slice(path: str | Path) -> np.ndarray:
    """Read a TIFF as a 2D array, squeezing singleton dimensions."""
    arr = np.squeeze(np.asarray(tifffile.imread(path)))
    if arr.ndim != 2:
        raise ValueError(f"{path} is not 2D (shape={arr.shape})")
    return arr


def read_tile_region(path: str | Path, y: int, x: int, ts: int) -> np.ndarray:
    """Read just one ts x ts tile from a slice, touching only its rows on disk.

    Uses a memmap so the read cost reflects the tile, not the whole slice; falls
    back to a full read for compressed/non-mappable TIFFs.
    """
    try:
        mm = tifffile.memmap(path)
        tile = np.ascontiguousarray(np.squeeze(mm)[y : y + ts, x : x + ts])
        del mm
        return tile
    except (ValueError, MemoryError, NotImplementedError):
        return np.ascontiguousarray(read_slice(path)[y : y + ts, x : x + ts])


def slice_features(arr: np.ndarray, ts: int) -> dict[str, np.ndarray]:
    """Vectorized per-tile features for one slice, cut into ``ts`` x ``ts`` tiles.

    Returns arrays (one element per tile) for tile_y, tile_x and the four
    features. Tiles are flattened to (n_tiles, ts*ts) so every feature is a
    single C-level reduction over all tiles at once.
    """
    h, w = arr.shape
    ny, nx = h // ts, w // ts
    arr = arr[: ny * ts, : nx * ts]
    tiles = (
        arr.reshape(ny, ts, nx, ts)
        .transpose(0, 2, 1, 3)
        .reshape(ny * nx, ts * ts)
        .astype(np.float32)
    )
    med = np.median(tiles, axis=1)
    p1, p99, p999 = np.percentile(tiles, [1.0, 99.0, 99.9], axis=1)
    mad = np.median(np.abs(tiles - med[:, None]), axis=1)
    # Foreground = above the tile's own noise floor (median + 5 robust sigma).
    fg_frac = np.mean(tiles > (med + 5.0 * 1.4826 * mad)[:, None], axis=1)
    cell = np.arange(ny * nx)
    return {
        "tile_y": (cell // nx) * ts,
        "tile_x": (cell % nx) * ts,
        "median": med,
        "p99": p99,
        "fg_frac": fg_frac,
        "dynamic_range": p999 - p1,
    }


def _scan_one(task: tuple[str, str, int, int]) -> dict:
    """Worker: feature-scan one slice. ``task`` is (channel, path, z, tile_size)."""
    channel, path, z, ts = task
    feats = slice_features(read_slice(path), ts)
    feats["channel"] = channel
    feats["z"] = z
    return feats


def otsu_threshold(values: np.ndarray, bins: int = 256) -> float:
    """Otsu's threshold: the value maximizing between-class variance. Used to
    find a natural cut in a bimodal feature distribution."""
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0 or finite.min() == finite.max():
        return float(finite.max()) if finite.size else 0.0
    hist, edges = np.histogram(finite, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2.0
    w = hist.astype(np.float64)
    w0 = np.cumsum(w)
    w1 = w.sum() - w0
    sum_total = np.cumsum(w * centers)
    grand = sum_total[-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        mu0 = sum_total / w0
        mu1 = (grand - sum_total) / w1
        between = w0 * w1 * (mu0 - mu1) ** 2
    between[~np.isfinite(between)] = -np.inf
    return float(centers[int(np.argmax(between))])


def assign_groups(dyn: np.ndarray, fg: np.ndarray) -> np.ndarray:
    """Per-channel structural ``group`` array for one channel's tiles.

    Background vs signal by Otsu on log1p(dynamic_range); among signal, dense vs
    sparse by Otsu on foreground coverage.
    """
    is_signal = np.log1p(dyn) > otsu_threshold(np.log1p(dyn))
    cov_cut = otsu_threshold(fg[is_signal]) if is_signal.any() else np.inf
    return np.where(
        ~is_signal,
        "background",
        np.where(fg > cov_cut, "dense-signal", "sparse-signal"),
    )


def parse_channels(values: list[str]) -> dict[str, str]:
    channels: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise argparse.ArgumentTypeError(
                f"--channel must be NAME=PATH, got {value!r}"
            )
        name, path = value.split("=", 1)
        channels[name] = path
    return channels


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--channel",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="Channel name and folder, e.g. 561=/data/561. Repeatable.",
    )
    p.add_argument("--tile-size", type=int, default=128)
    p.add_argument(
        "--z-stride",
        type=int,
        default=1,
        help="Scan every Nth slice (1 = whole sample).",
    )
    p.add_argument("--num-workers", type=int, default=1)
    p.add_argument("--out", default="bench_out/census.csv")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    channels = parse_channels(args.channel)

    tasks: list[tuple[str, str, int, int]] = []
    for channel, folder in channels.items():
        files = list_tiffs(folder)
        if not files:
            raise SystemExit(f"No TIFF files in {folder} for channel {channel}")
        for z, path in enumerate(files):
            if z % args.z_stride == 0:
                tasks.append((channel, str(path), z, args.tile_size))
    print(f"Scanning {len(tasks)} slices across {len(channels)} channels...")

    if args.num_workers == 1:
        scanned = [_scan_one(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=args.num_workers) as pool:
            scanned = list(pool.map(_scan_one, tasks))

    # Pool per channel so the group cuts use that channel's whole population.
    by_channel: dict[str, list[dict]] = {c: [] for c in channels}
    for s in scanned:
        by_channel[s["channel"]].append(s)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CENSUS_FIELDS)
        for channel, slices in by_channel.items():
            if not slices:
                continue
            cat = {
                k: np.concatenate([s[k] for s in slices])
                for k in (
                    "tile_y",
                    "tile_x",
                    "median",
                    "p99",
                    "fg_frac",
                    "dynamic_range",
                )
            }
            z = np.concatenate([np.full(len(s["tile_y"]), s["z"]) for s in slices])
            group = assign_groups(cat["dynamic_range"], cat["fg_frac"])
            for i in range(z.size):
                writer.writerow(
                    [
                        channel,
                        int(z[i]),
                        int(cat["tile_y"][i]),
                        int(cat["tile_x"][i]),
                        round(float(cat["median"][i]), 3),
                        round(float(cat["p99"][i]), 3),
                        round(float(cat["fg_frac"][i]), 5),
                        round(float(cat["dynamic_range"][i]), 3),
                        group[i],
                    ]
                )
            counts = {g: int((group == g).sum()) for g in np.unique(group)}
            print(f"[{channel}] {z.size} tiles -> {counts}")
            n += z.size

    print(f"Wrote {out} ({n} tiles).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
