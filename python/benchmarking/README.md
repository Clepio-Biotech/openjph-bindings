# OpenJPH normalization benchmark

Evaluates which normalization strategy (percentile clip + rescale) gives the
best fidelity at a given compression ratio under lossy OpenJPH (HTJ2K), and
how that depends on what kind of signal a region carries.

## Data

Data is one folder per channel; each TIFF is a 2D image
(e.g., `/data/561/*.tif`, `/data/638/*.tif`).

## Pipeline and modules

1. `census.py` — cuts every z-slice into `--tile-size` tiles and records four
  features per tile (`median`, `p99`, `fg_frac`, `dynamic_range`). Assigns, per
  channel, a structural group (background / sparse-signal / dense-signal, via
  Otsu cuts): how much of the tile carries signal.
2. `calibrate.py` — a fixed qstep gives different file sizes under different
  clipping, so each configuration needs its own qsteps to compare at matched
  ratio. Sweeps qstep on a few tiles and inverts the qstep→ratio curve to hit
  target ratios spanning `--ratio-min`..`--ratio-max`.
3. `benchmark.py` — samples tiles from the census stratified by group, runs
  every `condition × qstep`, OpenJPH round-trips each, and records compression
  ratio, NRMSE, PSNR, ROI intensity error, saturation, and read/encode/write
  timings.
4. `metrics.py` — clip/rescale and the distortion metrics.
5. `plots.py` — three figure sets per channel (see below).

## Signal classification

Every tile is labelled `background`, `sparse-signal`, or `dense-signal` from two
cheap features, with all cuts found per channel over that channel's whole tile
population (`census.py`):

- Foreground fraction `fg_frac` — the share of a tile's pixels above a
  global per-channel signal floor: `median + 5 · 1.4826 · MAD`, estimated
  once per channel over a pooled sample of pixels, where `MAD` is the median absolute deviation
  (`1.4826 · MAD` is the robust std-equivalent for Gaussian noise). The floor is
  the channel's background level, so `fg_frac` measures absolute brightness
  coverage: a tile uniformly full of signal scores high (dense), a few bright
  spots in darkness score low (sparse).
- Dynamic range `dynamic_range = p99.9 − p1` of the tile's intensities.

The two splits are both data-driven, via [Otsu's
method](https://en.wikipedia.org/wiki/Otsu%27s_method) — the threshold that
maximizes between-class variance of a (here, bimodal) distribution:

1. background vs signal: a tile is signal if
   `log1p(dynamic_range) > Otsu(log1p(dynamic_range))` over all tiles in the
   channel; otherwise it is *background* (flat, no structure). `log1p` keeps the
   long intensity tail from dominating the threshold.
2. dense vs sparse (signal tiles only): dense if
   `fg_frac > Otsu(fg_frac)` over the signal tiles; otherwise *sparse*.

## Metrics

Let `a` be the original tile and `b` its reconstruction, both restored to the
original intensity domain (uint16). The bright-signal ROI is the pixel set
`M = { a ≥ P99(a) }` (top 1% by intensity).

| Metric | Definition |
| --- | --- |
| Compression ratio | `original_bytes / encoded_bytes` |
| NRMSE | `sqrt(mean((a − b)²)) / (max(a) − min(a))` |
| PSNR (dB) | `20·log10(max(a) − min(a)) − 10·log10(mean((a − b)²))` |
| ROI intensity error | `mean(|a − b|) / mean(a)` over pixels in `M` |
| Saturation fraction | share of pixels clipped outside `[lo, hi]` by the normalization |

NRMSE is a whole-tile fidelity measure normalized to the tile's intensity range
(so it is comparable across tiles and channels); ROI intensity error reports the
relative error where it matters most for microscopy — the bright structures.

## Setup

```bash
cd python
uv sync --group benchmarking
```

## Run

```bash
cd python/benchmarking
DATA=/data; OUT=bench_out

python census.py \
  --channel 561=$DATA/561 --channel 638=$DATA/638 \
  --tile-size 128 --num-workers 90 --out $OUT/census.csv

python calibrate.py \
  --channel 561=$DATA/561 --channel 638=$DATA/638 \
  --census $OUT/census.csv \
  --percentiles none 0,100 0.1,99.9 1,99 \
  --out $OUT/qsteps.csv

python benchmark.py \
  --channel 561=$DATA/561 --channel 638=$DATA/638 \
  --census $OUT/census.csv --qsteps $OUT/qsteps.csv \
  --percentiles none 0,100 0.1,99.9 1,99 \
  --samples-per-group 200 --num-workers 90 --outdir $OUT

python plots.py \
  --census $OUT/census.csv --results $OUT/results.csv --outdir $OUT
```

## Outputs

A normalizatin configuration is defined by `low,high` percentiles or `none`.

Bounds are global per channel (percentiles over the sampled tiles' pooled
pixels), so the same `[lo, hi]` is applied to every tile. Clipped data is
stretched to full uint16 before compression and mapped back before metrics,
so all conditions compare in the original intensity domain.

```
bench_out/census.csv                       one row per tile (whole volume)
bench_out/qsteps.csv                       per-configuration qstep grid
bench_out/results.csv                      one row per tile x config x qstep
bench_out/best_condition_by_ratio.csv      best config per ratio, per data group
bench_out/characterize_<channel>.png       sample characterization
bench_out/performance_by_group_<metric>_<ch>.png   ratio vs distortion, by data group
bench_out/throughput_<channel>.png         read/encode/write throughput, by data group
```
