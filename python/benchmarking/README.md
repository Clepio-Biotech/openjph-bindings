# OpenJPH normalization benchmark

Evaluates which normalization strategy (percentile clip + rescale) gives the
best fidelity at a given compression ratio under lossy OpenJPH (HTJ2K), and
how that depends on what kind of signal a region carries.

## Data

Data is one folder per channel; each TIFF is a 2D image
(`/data/561/*.tif`, `/data/638/*.tif`).

## Pipeline and modules

1. `census.py` — cuts every z-slice into `--tile-size` tiles and records four
  features per tile (`median`, `p99`, `fg_frac`, `dynamic_range`). Assigns, per
  channel, a structural group (background / sparse-signal / dense-signal, via
  Otsu cuts): how much of the tile carries signal.
2. `calibrate.py` — a fixed qstep gives different file sizes under different
  clipping, so each configuration needs its own qsteps to compare at matched
  ratio. Sweeps qstep on a few tiles and inverts the qstep→ratio curve to hit
  target ratios spanning `--ratio-min`..`--ratio-max`.
3. `benchmark.py` — samples tiles from the census **stratified by group**, runs
  every `condition × qstep`, OpenJPH round-trips each, and records compression
  ratio, NRMSE, PSNR, ROI intensity error, saturation, and **read/encode/write
  timings**.
4. `metrics.py` — clip/rescale and the distortion metrics.
5. `plots.py` — three figure sets per channel (see below).

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
