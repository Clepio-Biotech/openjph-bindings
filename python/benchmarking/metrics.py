"""Preprocessing and metrics for the OpenJPH clipping benchmark.

Pipeline per condition: original -> apply_clip (clip to global [lo,hi], rescale
to full uint16) -> OpenJPH lossy round-trip -> restore_from_clip (back to
original intensities) -> metrics. All metrics compare in the original intensity
domain so clipping conditions are comparable. Clip bounds come from
percentile_thresholds over the pooled channel sample (global, not per-crop).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

UINT16_MAX = 65535


@dataclass
class ClipResult:
    """Output of :func:`apply_clip`."""

    rescaled: np.ndarray  # uint16, clipped+stretched, ready to compress
    lo: float
    hi: float
    saturation_fraction: float


def percentile_thresholds(
    pixels: np.ndarray, low_pct: float, high_pct: float
) -> tuple[float, float]:
    """Clip bounds (lo, hi) at the given percentiles of ``pixels``.

    ``pixels`` is the pooled sample (e.g. all crops of a channel) so the bounds
    are global rather than per-crop.
    """
    return float(np.percentile(pixels, low_pct)), float(np.percentile(pixels, high_pct))


def apply_clip(arr: np.ndarray, lo: float | None, hi: float | None) -> ClipResult:
    """Clip ``arr`` to [lo, hi] and stretch to the full uint16 range.

    ``lo``/``hi`` of ``None`` is the identity ("no clipping") condition: the raw
    array is returned and the restore step is a no-op (bounds 0..UINT16_MAX).
    """
    arr = np.asarray(arr)
    if lo is None or hi is None:
        return ClipResult(arr.astype(np.uint16, copy=True), 0.0, float(UINT16_MAX), 0.0)

    if hi <= lo:  # degenerate (flat) bounds: avoid divide-by-zero
        hi = lo + 1.0
    clipped = np.clip(arr.astype(np.float64), lo, hi)
    rescaled = np.round((clipped - lo) / (hi - lo) * UINT16_MAX).astype(np.uint16)
    saturation = float(np.mean((arr < lo) | (arr > hi)))
    return ClipResult(rescaled, float(lo), float(hi), saturation)


def restore_from_clip(rescaled: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Inverse of the rescale step: map [0, 65535] back to [lo, hi]."""
    restored = rescaled.astype(np.float64) / UINT16_MAX * (hi - lo) + lo
    return np.round(restored).clip(0, UINT16_MAX).astype(np.uint16)


def nrmse(original: np.ndarray, reconstruction: np.ndarray) -> float:
    """Normalised RMSE, normalised by the original's intensity range."""
    a = original.astype(np.float64)
    b = reconstruction.astype(np.float64)
    rmse = np.sqrt(np.mean((a - b) ** 2))
    rng = a.max() - a.min()
    if rng == 0:
        return 0.0
    return float(rmse / rng)


def psnr(
    original: np.ndarray, reconstruction: np.ndarray, data_range: float | None = None
) -> float:
    """Peak signal-to-noise ratio in dB, normalised to the original's range."""
    a = original.astype(np.float64)
    b = reconstruction.astype(np.float64)
    mse = np.mean((a - b) ** 2)
    if mse == 0:
        return float("inf")
    if data_range is None:
        data_range = a.max() - a.min()
    if data_range == 0:
        return float("inf")
    return float(20 * np.log10(data_range) - 10 * np.log10(mse))


def bright_mask(arr: np.ndarray, percentile: float = 99.0) -> np.ndarray:
    """Boolean mask selecting the bright-signal pixels of a crop."""
    threshold = np.percentile(arr, percentile)
    mask = arr >= threshold
    if not mask.any():
        mask = arr >= arr.max()
    return mask


def roi_intensity_error(
    original: np.ndarray, reconstruction: np.ndarray, mask: np.ndarray | None = None
) -> float:
    """Mean relative intensity error within the bright-signal ROI.

    Defined as ``mean(|recon - orig|) / mean(orig)`` over the masked pixels.
    """
    if mask is None:
        mask = bright_mask(original)
    a = original.astype(np.float64)[mask]
    b = reconstruction.astype(np.float64)[mask]
    if a.size == 0:
        return 0.0
    denom = a.mean()
    if denom == 0:
        return 0.0
    return float(np.mean(np.abs(a - b)) / denom)
