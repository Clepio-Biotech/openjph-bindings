# OpenJPH clipping benchmark

Evaluates whether percentile/quantile **clipping + rescaling** before lossy
OpenJPH (HTJ2K) compression improves fidelity of the bright signal in large
uint16 microscopy data.

## Layout

Data is one folder per channel; each TIFF is a single 2D z-slice:

```
/data/DAPI/*.tif
/data/CD31/*.tif
```

Slices are huge and numerous, so the benchmark works on representative
**128×128 crops** (a bright-region crop plus random crops, from a spread of
z-slices).

## Modules

- `sampler.py` — picks representative 128×128 crops + their metadata.
- `metrics.py` — percentile clip/rescale, NRMSE, PSNR, ROI intensity error
  (bright-signal mask), saturation fraction.
- `main.py` — computes global clip bounds per (channel, condition) from the
  pooled crops, then runs every *percentile × qstep* condition, OpenJPH lossy
  round-trips each crop, saves originals/reconstructions as TIFFs and writes
  `results.csv`.
- `plot.py` — reads `results.csv`, plots compression ratio vs ROI error and vs
  NRMSE (one pair per channel), and writes a per-channel median summary table.

## Setup

Dependencies live in the `benchmarking` group of `python/pyproject.toml`
(`matplotlib`, `tifffile`) and are pinned in `uv.lock`:

```bash
cd python
uv sync --group benchmarking
```

## Run

```bash
cd python/benchmarking
../.venv/bin/python main.py \
  --channel DAPI=/data/DAPI \
  --channel CD31=/data/CD31 \
  --percentiles none 0.001,99.999 0.01,99.99 0.1,99.9 1,99 \
  --qsteps 0.0005 0.001 0.003 \
  --slices-per-channel 50 --crops-per-slice 10 \
  --num-workers 96 \
  --outdir bench_out

../.venv/bin/python plot.py --results bench_out/results.csv --outdir bench_out
```

`--crops-per-slice` defaults to 1 (the bright crop); extra crops are distinct
random tiles, clipped to how many 128×128 tiles the slice holds.
`--num-workers` parallelises across crops (one crop per task, so per-worker RAM
stays small); it defaults to 1 (serial).

Outputs:

```
bench_out/results.csv
bench_out/summary.csv
bench_out/ratio_vs_roi_error_<channel>.png
bench_out/ratio_vs_nrmse_<channel>.png
bench_out/chunks/original/*.tif
bench_out/chunks/reconstructed/*.tif
```

## Notes

- Lossy compression uses `openjph.encode(..., irreversible=True, qstep=q)`;
  smaller `qstep` ⇒ higher fidelity / larger files.
- PSNR is normalised to each crop's intensity range (not a fixed uint16 peak),
  so it is meaningful for low-valued data.
- A clipping condition is `low,high` percentiles or `none` (identity). Bounds
  are global per channel (percentiles over all that channel's crops), so the
  same `[lo, hi]` is applied to every crop. `0,100` is global min-max (no
  saturation). Clipped data is stretched to full uint16 before compression and
  mapped back before metrics, so all conditions compare in the original domain.
- Per-crop / per-condition failures are recorded in `results.csv`
  (`status=failed`) and do not stop the run.
