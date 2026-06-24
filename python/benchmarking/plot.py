"""Plot benchmark results produced by ``main.py``.

Reads ``results.csv`` and writes, per channel:

* ``ratio_vs_roi_error_<channel>.png`` - compression ratio vs ROI intensity error
* ``ratio_vs_nrmse_<channel>.png``     - compression ratio vs NRMSE

plus ``summary.csv`` - median metrics grouped by channel + percentile + qstep.

Usage::

    python plot.py --results bench_out/results.csv --outdir bench_out
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    return [r for r in rows if r.get("status") == "ok"]


def _f(row: dict, key: str) -> float | None:
    value = row.get(key, "")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float:
    values = sorted(values)
    n = len(values)
    if n == 0:
        return float("nan")
    mid = n // 2
    if n % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def scatter_by_percentile(
    rows: list[dict], xkey: str, xlabel: str, title: str, out: Path
) -> None:
    # Compression ratio spans orders of magnitude (log y). The metric does too
    # but can be exactly 0 (e.g. min-max), so use symlog x to keep those points.
    # The raw cloud is faint; a black-edged median marker per condition shows the trend.
    by_cond: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        x = _f(r, xkey)
        y = _f(r, "compression_ratio")
        if x is None or y is None or x < 0 or y <= 0:
            continue
        by_cond[r["percentile"]].append((x, y))

    fig, ax = plt.subplots(figsize=(7, 5))
    cmap = plt.get_cmap("tab10")
    for i, cond in enumerate(sorted(by_cond)):
        xs = [p[0] for p in by_cond[cond]]
        ys = [p[1] for p in by_cond[cond]]
        color = cmap(i % 10)
        ax.scatter(xs, ys, s=6, alpha=0.2, color=color, linewidths=0)
        ax.scatter(
            [_median(xs)],
            [_median(ys)],
            s=160,
            color=color,
            marker="o",
            edgecolor="black",
            linewidth=1.3,
            zorder=5,
            label=f"{cond} (median)",
        )
    # linthresh = smallest positive metric value, so the linear band near 0 is tight.
    positives = [x for pts in by_cond.values() for x, _ in pts if x > 0]
    ax.set_xscale("symlog", linthresh=min(positives) if positives else 1e-6)
    ax.set_yscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Compression ratio")
    ax.set_title(title)
    ax.legend(title="percentile", fontsize=8)
    ax.grid(True, which="both", alpha=0.3)
    ax.tick_params(axis="x", labelrotation=30)  # avoid 0 and 1e-6 overlapping
    fig.tight_layout()
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"Wrote {out}")


def summary_table(rows: list[dict], out: Path) -> None:
    metric_keys = [
        "compression_ratio",
        "nrmse",
        "psnr",
        "roi_intensity_error",
        "saturation_fraction",
    ]
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["channel"], r["percentile"], r["qstep"])].append(r)

    header = ["channel", "percentile", "qstep", "n"] + [
        f"median_{k}" for k in metric_keys
    ]
    table: list[list] = []
    for (channel, pct, qstep), grp in sorted(groups.items()):
        line = [channel, pct, qstep, len(grp)]
        for k in metric_keys:
            vals = [v for v in (_f(r, k) for r in grp) if v is not None]
            line.append(round(_median(vals), 6))
        table.append(line)

    with out.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(table)
    print(f"Wrote {out}")

    # Echo a readable version to stdout.
    widths = [
        max(len(str(row[i])) for row in [header, *table]) for i in range(len(header))
    ]
    for row in [header, *table]:
        print("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--results", default="bench_out/results.csv")
    p.add_argument("--outdir", default="bench_out")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rows = load_rows(Path(args.results))
    if not rows:
        print("No successful rows in results.csv; nothing to plot.")
        return 1

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # One pair of plots per channel, since different signals may behave differently.
    for channel in sorted({r["channel"] for r in rows}):
        crows = [r for r in rows if r["channel"] == channel]
        scatter_by_percentile(
            crows,
            "roi_intensity_error",
            "ROI intensity error",
            f"{channel}: compression ratio vs ROI intensity error",
            outdir / f"ratio_vs_roi_error_{channel}.png",
        )
        scatter_by_percentile(
            crows,
            "nrmse",
            "NRMSE",
            f"{channel}: compression ratio vs NRMSE",
            outdir / f"ratio_vs_nrmse_{channel}.png",
        )
    summary_table(rows, outdir / "summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
