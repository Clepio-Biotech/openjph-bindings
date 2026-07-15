# Build all six platform wheels on one machine, the wgpu-py way: nothing is
# compiled — python/hatch_build.py downloads each platform's prebuilt
# libopenjph_c from the pinned C-v* release and tags the wheel accordingly.
#
#   python tools/build_wheels.py --outdir dist
#   PYOPENJPH_NATIVE_RELEASE=C-v0.29.0.2 python tools/build_wheels.py --outdir dist
#
# Requires the `build` package (python -m pip install build).

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "python"))

from hatch_build import PLATFORMS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=ROOT_DIR / "dist")
    args = parser.parse_args()

    for plat in PLATFORMS:
        print(f"--- building wheel for {plat} ---")
        env = os.environ | {
            "PYOPENJPH_BUILD_PLATFORM": plat,
            "PYOPENJPH_REQUIRE_CHECKSUM": "true",
        }
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                str(ROOT_DIR / "python"),
                "--outdir",
                str(args.outdir),
            ],
            check=True,
            env=env,
        )

    print("\nbuilt wheels:")
    for wheel in sorted(args.outdir.glob("*.whl")):
        print(f"  {wheel.name}")


if __name__ == "__main__":
    main()
