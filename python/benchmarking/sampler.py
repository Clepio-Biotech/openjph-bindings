"""Sample representative 128x128 2D crops from a multi-channel TIFF dataset.

One folder per channel, one 2D z-slice per TIFF. Slices are huge and numerous,
so we read only a subset of slices per channel and take a few small crops each.
"""

from __future__ import annotations

import random

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tifffile

TIFF_SUFFIXES = (".tif", ".tiff", ".TIF", ".TIFF")


@dataclass
class Crop:
    """A single sampled crop plus the metadata describing where it came from."""

    channel: str
    source_file: str
    z_index: int
    y: int
    x: int
    height: int
    width: int
    crop_type: str
    array: np.ndarray

    @property
    def stem(self) -> str:
        """A filesystem-friendly identifier, handy for output filenames."""
        return f"{self.channel}_z{self.z_index:04d}_y{self.y:05d}_x{self.x:05d}_{self.crop_type}"


def list_tiffs(folder: str | Path) -> list[Path]:
    """Return a sorted list of TIFF files in ``folder``."""
    folder = Path(folder)
    files = [p for p in folder.iterdir() if p.suffix in TIFF_SUFFIXES]
    return sorted(files)


def _read_slice(path: Path) -> np.ndarray:
    """Read a single 2D z-slice as a 2D array."""
    arr = tifffile.imread(path)
    arr = np.asarray(arr)
    if arr.ndim != 2:
        # Squeeze singleton dimensions (e.g. a (1, H, W) page) if possible.
        arr = np.squeeze(arr)
    if arr.ndim != 2:
        raise ValueError(f"{path} is not a 2D image (shape={arr.shape})")
    return arr


def _bright_top_left(slice_arr: np.ndarray, crop_size: int) -> tuple[int, int]:
    """Top-left corner of the crop whose centre is the brightest pixel."""
    h, w = slice_arr.shape
    yc, xc = np.unravel_index(int(np.argmax(slice_arr)), slice_arr.shape)
    y = int(np.clip(yc - crop_size // 2, 0, h - crop_size))
    x = int(np.clip(xc - crop_size // 2, 0, w - crop_size))
    return y, x


class Sampler:
    """Sample representative crops from one or more channel folders."""

    def __init__(
        self,
        channels: dict[str, str | Path],
        crop_size: int = 128,
        slices_per_channel: int = 8,
        crops_per_slice: int = 1,
        seed: int = 0,
    ) -> None:
        self.channels = {name: Path(path) for name, path in channels.items()}
        self.crop_size = crop_size
        self.slices_per_channel = slices_per_channel
        self.crops_per_slice = crops_per_slice
        self.rng = random.Random(seed)

    def _select_slice_files(self, files: list[Path]) -> list[Path]:
        """Pick a spread of z-slices across the available files."""
        if len(files) <= self.slices_per_channel:
            return files
        # Evenly spaced indices give a deterministic, representative spread.
        idx = np.linspace(0, len(files) - 1, self.slices_per_channel)
        return [files[int(round(i))] for i in idx]

    def _crops_from_slice(
        self, channel: str, path: Path, z_index: int, slice_arr: np.ndarray
    ) -> list[Crop]:
        h, w = slice_arr.shape
        cs = self.crop_size
        if h < cs or w < cs:
            raise ValueError(f"{path} ({h}x{w}) is smaller than crop size {cs}x{cs}")

        # First crop targets the bright signal; the rest are distinct random
        # grid cells. Clip to how many non-overlapping crops the slice holds.
        max_crops = (h // cs) * (w // cs)
        n = max(1, min(self.crops_per_slice, max_crops))

        corners: list[tuple[int, int, str]] = [
            (*_bright_top_left(slice_arr, cs), "bright")
        ]
        cells = self.rng.sample(range(max_crops), max_crops)  # shuffled cell ids
        cols = w // cs
        for cell in cells:
            if len(corners) >= n:
                break
            y, x = (cell // cols) * cs, (cell % cols) * cs
            corners.append((y, x, "random"))

        crops: list[Crop] = []
        for y, x, crop_type in corners:
            sub = np.ascontiguousarray(slice_arr[y : y + cs, x : x + cs])
            crops.append(
                Crop(
                    channel=channel,
                    source_file=str(path),
                    z_index=z_index,
                    y=y,
                    x=x,
                    height=cs,
                    width=cs,
                    crop_type=crop_type,
                    array=sub,
                )
            )
        return crops

    def sample(self) -> list[Crop]:
        """Return all sampled crops across every channel."""
        crops: list[Crop] = []
        for channel, folder in self.channels.items():
            files = list_tiffs(folder)
            if not files:
                raise ValueError(
                    f"No TIFF files found in {folder} for channel {channel}"
                )
            selected = self._select_slice_files(files)
            for path in selected:
                z_index = files.index(path)
                slice_arr = _read_slice(path)
                crops.extend(self._crops_from_slice(channel, path, z_index, slice_arr))
        return crops
