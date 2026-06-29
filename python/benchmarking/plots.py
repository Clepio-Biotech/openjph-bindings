"""Figures for the OpenJPH normalization benchmark.

Three independent figure sets, per channel:

1. characterization (from census.csv) - how signal is distributed in the volume:
   group counts, fg_frac vs dynamic_range density, p99 histogram, and the group
   mix along z.
2. performance (from results.csv) - distortion vs compression ratio, one series
   per normalization condition, overall and faceted by content group. Also writes
   best_condition_by_ratio.csv: the condition with the lowest distortion at each
   target ratio, per group.
3. throughput (from results.csv) - read+encode+write throughput, overall and by
   group.

Usage::

    python plots.py --census census.csv --results results.csv --outdir bench_out
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

GROUPS = ["background", "sparse-signal", "dense-signal"]
METRICS = [("nrmse", "NRMSE"), ("roi_intensity_error", "ROI intensity error")]
# Shared y-limits per metric so every panel is on the same scale. Chosen to
# contain the tile-spread bands (p25-p75) across all panels with headroom.
YLIM = {"nrmse": 0.10, "roi_intensity_error": 0.20}


def load_csv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def col(rows: list[dict], key: str) -> np.ndarray:
    out = np.array([_f(r.get(key)) for r in rows], dtype=np.float64)
    return out


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


# --- 1. characterization -------------------------------------------------------


def characterize(census: list[dict], channel: str, outdir: Path) -> None:
    rows = [r for r in census if r["channel"] == channel]
    dyn = col(rows, "dynamic_range")
    fg = col(rows, "fg_frac")
    p99 = col(rows, "p99")
    z = col(rows, "z")
    groups = np.array([r["group"] for r in rows])

    fig, axes = plt.subplots(2, 2, figsize=(13, 10))

    counts = [int((groups == g).sum()) for g in GROUPS]
    axes[0, 0].bar(GROUPS, counts, color="tab:blue")
    axes[0, 0].set_title("tile counts by group")
    axes[0, 0].set_ylabel("tiles")
    axes[0, 0].tick_params(axis="x", labelrotation=15)

    h = axes[0, 1].hist2d(
        np.log1p(dyn), fg, bins=80, cmap="viridis", norm=matplotlib.colors.LogNorm()
    )
    fig.colorbar(h[3], ax=axes[0, 1], label="tiles")
    axes[0, 1].set_title("coverage vs dynamic range")
    axes[0, 1].set_xlabel("log1p(dynamic_range)")
    axes[0, 1].set_ylabel("fg_frac")

    pos = p99[p99 > 0]
    axes[1, 0].hist(
        pos, bins=np.logspace(0, np.log10(pos.max() + 1), 60), color="tab:green"
    )
    axes[1, 0].set_xscale("log")
    axes[1, 0].set_yscale("log")
    axes[1, 0].set_title("tile p99 intensity")
    axes[1, 0].set_xlabel("p99")
    axes[1, 0].set_ylabel("tiles")

    # Group mix along z: fraction of each group per slice.
    zs = np.unique(z)
    frac = {g: [] for g in GROUPS}
    for zi in zs:
        m = z == zi
        n = max(int(m.sum()), 1)
        for g in GROUPS:
            frac[g].append(float(((groups == g) & m).sum()) / n)
    bottom = np.zeros(len(zs))
    for g in GROUPS:
        axes[1, 1].bar(zs, frac[g], bottom=bottom, width=1.0, label=g)
        bottom += np.array(frac[g])
    axes[1, 1].set_title("group fraction along z")
    axes[1, 1].set_xlabel("z")
    axes[1, 1].set_ylabel("fraction")
    axes[1, 1].legend(fontsize=8)

    fig.suptitle(f"{channel}: sample characterization")
    fig.tight_layout()
    out = outdir / f"characterize_{channel}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"Wrote {out}")


# --- 2. performance (rate-distortion) -----------------------------------------


def _quantile_curves(ratio: np.ndarray, dist: np.ndarray, ratio_grid: np.ndarray):
    """Per ratio bin: (median, p25, p75) of distortion across tiles.

    Each tile is one deterministic round-trip, so the spread within a bin is
    tile-to-tile heterogeneity, not run noise; p25-p75 summarizes that band.
    """
    edges = np.concatenate(([0], np.sqrt(ratio_grid[:-1] * ratio_grid[1:]), [np.inf]))
    med = np.full(len(ratio_grid), np.nan)
    lo = np.full(len(ratio_grid), np.nan)
    hi = np.full(len(ratio_grid), np.nan)
    for i in range(len(ratio_grid)):
        sel = (ratio >= edges[i]) & (ratio < edges[i + 1])
        if sel.any():
            med[i], lo[i], hi[i] = np.percentile(dist[sel], [50, 25, 75])
    return med, lo, hi


def rd_panel(
    ax, rows: list[dict], metric: str, conds: list[str], ratio_grid: np.ndarray, cmap
) -> dict[str, np.ndarray]:
    """Median rate-distortion curve + p25-p75 tile-spread band per condition."""
    curves: dict[str, np.ndarray] = {}
    for i, cond in enumerate(conds):
        crows = [r for r in rows if r["percentile"] == cond]
        ratio = col(crows, "compression_ratio")
        dist = col(crows, metric)
        ok = np.isfinite(ratio) & np.isfinite(dist) & (ratio > 0)
        if ok.sum() < 5:
            continue
        med, lo, hi = _quantile_curves(ratio[ok], dist[ok], ratio_grid)
        color = cmap(i % 10)
        ax.fill_between(ratio_grid, lo, hi, color=color, alpha=0.18, linewidth=0)
        ax.plot(ratio_grid, med, "-o", color=color, ms=4, label=cond)
        curves[cond] = med
    ax.set_xscale("log")
    ax.set_xlabel("compression ratio")
    ax.grid(True, which="both", alpha=0.3)
    return curves


def performance(results: list[dict], channel: str, outdir: Path) -> None:
    rows = [r for r in results if r["channel"] == channel and r["status"] == "ok"]
    if not rows:
        return
    conds = sorted({r["percentile"] for r in rows})
    cmap = plt.get_cmap("tab10")
    ratio = col(rows, "compression_ratio")
    ratio = ratio[np.isfinite(ratio) & (ratio > 0)]
    ratio_grid = np.logspace(np.log10(max(ratio.min(), 1)), np.log10(ratio.max()), 10)

    sub = "median + p25-p75 across tiles"
    for metric, label in METRICS:
        # Overall pooled curve, on its own — note it mixes tile types at each
        # ratio (different conditions reach a ratio with different mixes), so it
        # is descriptive only; rank strategies on the by-group panels.
        fig, ax = plt.subplots(figsize=(7, 5))
        rd_panel(ax, rows, metric, conds, ratio_grid, cmap)
        ax.set_ylim(0, YLIM[metric])
        ax.set_ylabel(label)
        ax.legend(fontsize=8, title="condition")
        ax.set_title(f"{channel}: overall {label} (pooled; mixes tile types)\n{sub}")
        fig.tight_layout()
        _save(fig, outdir / f"performance_overall_{metric}_{channel}.png")

        # By structural group: the trustworthy comparison (tile type held fixed).
        _facet(
            rows,
            "group",
            GROUPS,
            metric,
            label,
            conds,
            ratio_grid,
            cmap,
            channel,
            "by content group",
            outdir,
            f"performance_by_group_{metric}_{channel}.png",
            best_writer=lambda g, curves: _write_best(
                curves, conds, ratio_grid, channel, g, metric, outdir
            ),
        )


def _facet(
    rows,
    key,
    values,
    metric,
    label,
    conds,
    ratio_grid,
    cmap,
    channel,
    what,
    outdir,
    fname,
    best_writer=None,
) -> None:
    """One row of rate-distortion panels, one per value of ``key``."""
    fig, axes = plt.subplots(
        1, len(values), figsize=(6 * len(values), 5), squeeze=False, sharey=True
    )
    for ax, v in zip(axes[0], values):
        curves = rd_panel(
            ax, [r for r in rows if r[key] == v], metric, conds, ratio_grid, cmap
        )
        ax.set_title(v)
        ax.set_ylim(0, YLIM[metric])
        if best_writer is not None:
            best_writer(v, curves)
    axes[0][0].set_ylabel(label)
    axes[0][-1].legend(fontsize=8, title="condition")
    fig.suptitle(
        f"{channel}: compression ratio vs {label}, {what} "
        f"(median + p25-p75 across tiles)"
    )
    fig.tight_layout()
    _save(fig, outdir / fname)


def _save(fig, out: Path) -> None:
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"Wrote {out}")


def _write_best(curves, conds, ratio_grid, channel, group, metric, outdir) -> None:
    """Append the best (lowest-distortion) condition per ratio to a CSV."""
    out = outdir / "best_condition_by_ratio.csv"
    new = not out.exists()
    with out.open("a", newline="") as fh:
        writer = csv.writer(fh)
        if new:
            writer.writerow(
                ["channel", "group", "metric", "ratio", "best_condition", "best_value"]
            )
        for i, ratio in enumerate(ratio_grid):
            vals = {
                c: curves[c][i]
                for c in conds
                if c in curves and np.isfinite(curves[c][i])
            }
            if not vals:
                continue
            best = min(vals, key=vals.get)
            writer.writerow(
                [
                    channel,
                    group,
                    metric,
                    round(float(ratio), 2),
                    best,
                    round(float(vals[best]), 6),
                ]
            )


# --- 3. throughput ------------------------------------------------------------


def throughput(results: list[dict], channel: str, outdir: Path) -> None:
    rows = [r for r in results if r["channel"] == channel and r["status"] == "ok"]
    groups = np.array([r["group"] for r in rows])
    # Compress + serialize only (encode + write); read time is excluded.
    seconds = col(rows, "encode_seconds") + col(rows, "write_seconds")
    mp = col(rows, "original_bytes") / 2e6  # uint16: 2 bytes/pixel
    tp = mp / seconds
    ok = np.isfinite(tp) & (tp > 0)
    if not ok.any():
        return
    factor = 2.0  # input bytes per pixel (uint16); MB/s = factor x MP/s

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # (a) encode+write throughput distribution.
    axes[0].hist(tp[ok], bins=60, color="tab:purple")
    med = np.median(tp[ok])
    axes[0].axvline(
        med,
        color="black",
        ls="--",
        label=f"median {med:.0f} MP/s ({med * factor:.0f} MB/s)",
    )
    axes[0].set_title("encode+write throughput (all chunks)")
    axes[0].set_xlabel("MP/s")
    axes[0].set_ylabel("chunks")
    axes[0].legend(fontsize=8)
    axes[0].secondary_xaxis(
        "top", functions=(lambda x: x * factor, lambda x: x / factor)
    ).set_xlabel("MB/s input")

    # (b) encode+write throughput by content group.
    data = [tp[ok & (groups == g)] for g in GROUPS]
    data = [d if d.size else np.array([np.nan]) for d in data]
    axes[1].boxplot(data, tick_labels=GROUPS, showfliers=False)
    axes[1].set_title("encode+write throughput by group")
    axes[1].set_ylabel("MP/s")
    axes[1].tick_params(axis="x", labelrotation=15)
    axes[1].secondary_yaxis(
        "right", functions=(lambda y: y * factor, lambda y: y / factor)
    ).set_ylabel("MB/s (input)")

    # (c) where the time goes: median encode/write per tile, by group.
    parts = ["encode_seconds", "write_seconds"]
    cols = {p: col(rows, p) for p in parts}
    bottom = np.zeros(len(GROUPS))
    for p, c in zip(parts, ["tab:orange", "tab:green"]):
        med_ms = [
            1e3 * np.nanmedian(cols[p][groups == g]) if (groups == g).any() else 0.0
            for g in GROUPS
        ]
        axes[2].bar(GROUPS, med_ms, bottom=bottom, color=c, label=p.split("_")[0])
        bottom += np.array(med_ms)
    axes[2].set_title("median time per tile (encode + write)")
    axes[2].set_ylabel("ms")
    axes[2].tick_params(axis="x", labelrotation=15)
    axes[2].legend(fontsize=8)

    fig.suptitle(
        f"{channel}: compression throughput "
        f"(single tile, single worker; encode + write to disk)"
    )
    fig.tight_layout()
    out = outdir / f"throughput_{channel}.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"Wrote {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--census", default="bench_out/census.csv")
    p.add_argument("--results", default="bench_out/results.csv")
    p.add_argument("--outdir", default="bench_out")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    best = outdir / "best_condition_by_ratio.csv"
    if best.exists():
        best.unlink()  # rewritten fresh by performance()

    census = load_csv(Path(args.census))
    results = load_csv(Path(args.results))
    channels = sorted({r["channel"] for r in census})
    for channel in channels:
        characterize(census, channel, outdir)
        performance(results, channel, outdir)
        throughput(results, channel, outdir)
    if best.exists():
        print(f"Wrote {best}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
