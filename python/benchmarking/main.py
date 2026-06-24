"""Benchmark percentile clipping before lossy OpenJPH compression.

For each sampled 128x128 crop x percentile condition x qstep: optionally
clip+rescale, OpenJPH lossy round-trip, restore to the original intensity
domain, then record compression ratio, NRMSE, PSNR, ROI intensity error and
saturation. Originals and reconstructions are saved as TIFFs; metrics go to
results.csv. See README.md for the full CLI.
"""

from __future__ import annotations

import argparse
import csv
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import partial
from pathlib import Path

import numpy as np
import tifffile

import openjph

import metrics
from sampler import Crop, Sampler

# Lossy compression needs irreversible=True + a qstep; the rest are the
# binding's defaults for single-component planar 2D data.
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
    "source_file",
    "z_index",
    "y",
    "x",
    "crop_type",
    "percentile",
    "qstep",
    "compression_ratio",
    "nrmse",
    "psnr",
    "roi_intensity_error",
    "saturation_fraction",
    "original_bytes",
    "encoded_bytes",
    "status",
    "error",
]


@dataclass
class PercentileCondition:
    """A named clipping condition parsed from the CLI."""

    name: str
    low: float | None
    high: float | None

    @classmethod
    def parse(cls, token: str) -> "PercentileCondition":
        if token.lower() == "none":
            return cls(name="none", low=None, high=None)
        try:
            low_s, high_s = token.split(",")
            return cls(name=token, low=float(low_s), high=float(high_s))
        except ValueError as exc:  # noqa: TRY003
            raise argparse.ArgumentTypeError(
                f"Invalid percentile condition {token!r}; "
                "expected 'none' or 'low,high' (e.g. 0.1,99.9)"
            ) from exc


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
        help="Channel name and folder, e.g. DAPI=/data/DAPI. Repeatable.",
    )
    p.add_argument(
        "--percentiles",
        nargs="+",
        default=["none"],
        help="Clipping conditions: 'none' or 'low,high' (e.g. 0.1,99.9).",
    )
    p.add_argument(
        "--qsteps",
        nargs="+",
        type=float,
        default=[0.001],
        help="OpenJPH irreversible quantisation steps.",
    )
    p.add_argument("--outdir", default="bench_out", help="Output directory.")
    p.add_argument("--crop-size", type=int, default=128)
    p.add_argument("--slices-per-channel", type=int, default=8)
    p.add_argument(
        "--crops-per-slice",
        type=int,
        default=1,
        help="Crops per slice (first targets bright signal; clipped to slice capacity).",
    )
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--num-workers",
        type=int,
        default=1,
        help="Parallel worker processes (one crop per task).",
    )
    return p


def compress_roundtrip(arr: np.ndarray, qstep: float) -> tuple[np.ndarray, int]:
    """Lossy OpenJPH encode/decode. Returns (reconstruction, encoded_bytes)."""
    encoded = openjph.encode(arr, qstep=qstep, **ENCODE_KWARGS)
    decoded = openjph.decode(encoded, shape=arr.shape, dtype="uint16")
    return decoded, len(encoded)


def run_condition(
    crop: Crop,
    cond: PercentileCondition,
    qstep: float,
    bounds: tuple[float | None, float | None],
    mask: np.ndarray,
    recon_dir: Path,
) -> dict:
    """Run one (crop, percentile, qstep) condition and return a CSV row."""
    original = crop.array
    row = _base_row(crop, cond, qstep)

    clip = metrics.apply_clip(original, *bounds)
    recon_rescaled, encoded_bytes = compress_roundtrip(clip.rescaled, qstep)
    reconstruction = metrics.restore_from_clip(recon_rescaled, clip.lo, clip.hi)

    original_bytes = original.nbytes
    row.update(
        {
            "status": "ok",
            "original_bytes": original_bytes,
            "encoded_bytes": encoded_bytes,
            "compression_ratio": original_bytes / encoded_bytes
            if encoded_bytes
            else float("nan"),
            "nrmse": metrics.nrmse(original, reconstruction),
            "psnr": metrics.psnr(original, reconstruction),
            "roi_intensity_error": metrics.roi_intensity_error(
                original, reconstruction, mask
            ),
            "saturation_fraction": clip.saturation_fraction,
        }
    )

    fname = f"{crop.stem}__{_safe(cond.name)}__q{qstep}.tif"
    tifffile.imwrite(recon_dir / fname, reconstruction)
    return row


def _base_row(crop: Crop, cond: PercentileCondition, qstep: float) -> dict:
    return {
        "channel": crop.channel,
        "source_file": crop.source_file,
        "z_index": crop.z_index,
        "y": crop.y,
        "x": crop.x,
        "crop_type": crop.crop_type,
        "percentile": cond.name,
        "qstep": qstep,
    }


def process_crop(
    crop: Crop,
    conditions: list[PercentileCondition],
    qsteps: list[float],
    thresholds: dict[tuple[str, str], tuple[float, float]],
    recon_dir: Path,
) -> list[dict]:
    """Run every (percentile, qstep) condition for one crop. Runs in a worker."""
    mask = metrics.bright_mask(crop.array)
    rows: list[dict] = []
    for cond in conditions:
        # Global per-channel bounds; absent (e.g. "none") means identity.
        bounds = thresholds.get((crop.channel, cond.name), (None, None))
        for qstep in qsteps:
            try:
                rows.append(run_condition(crop, cond, qstep, bounds, mask, recon_dir))
            except Exception as exc:  # noqa: BLE001 - record and continue
                row = _base_row(crop, cond, qstep)
                row.update(
                    {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                )
                rows.append(row)
    return rows


def _safe(name: str) -> str:
    return name.replace(",", "-").replace("/", "-")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    channels = parse_channels(args.channel)
    conditions = [PercentileCondition.parse(t) for t in args.percentiles]
    qsteps = list(args.qsteps)

    outdir = Path(args.outdir)
    orig_dir = outdir / "chunks" / "original"
    recon_dir = outdir / "chunks" / "reconstructed"
    orig_dir.mkdir(parents=True, exist_ok=True)
    recon_dir.mkdir(parents=True, exist_ok=True)

    sampler = Sampler(
        channels=channels,
        crop_size=args.crop_size,
        slices_per_channel=args.slices_per_channel,
        crops_per_slice=args.crops_per_slice,
        seed=args.seed,
    )
    crops = sampler.sample()
    print(f"Sampled {len(crops)} crops across {len(channels)} channels.")

    # Save originals once in the main process (small arrays, shared across conditions).
    for crop in crops:
        tifffile.imwrite(orig_dir / f"{crop.stem}.tif", crop.array)

    # Global clip bounds per (channel, condition): pool every crop of a channel
    # and take the percentiles once, so clipping uses sample-wide statistics.
    thresholds: dict[tuple[str, str], tuple[float, float]] = {}
    for channel in channels:
        pixels = np.concatenate(
            [c.array.ravel() for c in crops if c.channel == channel]
        )
        for cond in conditions:
            if cond.low is not None:
                thresholds[(channel, cond.name)] = metrics.percentile_thresholds(
                    pixels, cond.low, cond.high
                )

    # Each crop is one task: workers only receive 128x128 arrays, so RAM per worker is tiny.
    work = partial(
        process_crop,
        conditions=conditions,
        qsteps=qsteps,
        thresholds=thresholds,
        recon_dir=recon_dir,
    )
    if args.num_workers == 1:
        results = [work(crop) for crop in crops]
    else:
        with ProcessPoolExecutor(max_workers=args.num_workers) as pool:
            results = list(pool.map(work, crops))
    rows = [row for crop_rows in results for row in crop_rows]
    n_fail = sum(1 for r in rows if r["status"] == "failed")

    results_path = outdir / "results.csv"
    with results_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    ok = len(rows) - n_fail
    print(f"Wrote {results_path} ({ok} ok, {n_fail} failed).")
    print(f"Original crops:      {orig_dir}")
    print(f"Reconstructed crops: {recon_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
