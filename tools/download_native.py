# Download a prebuilt libopenjph_c from a C-v* GitHub release (the tarballs
# ci.yml's publish-github job attaches, one per platform) — e.g. to test a new
# C release before bumping the pin, by pointing PYOPENJPH_LIB_PATH at the
# downloaded library. The Python analog of tools/gen_artifacts.jl.
#
#   python tools/download_native.py                        # host platform, pinned release
#   python tools/download_native.py --release C-v0.29.0.2  # a specific release
#   python tools/download_native.py --platform all         # all six platforms
#
# The download/pin logic lives in python/hatch_build.py (the wheel build hook)
# so source installs work from an sdist; this is just its CLI.

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "python"))

from hatch_build import PLATFORMS, download_native_lib, host_platform, pinned_release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=None, help="C-v* release tag (default: the pin)")
    parser.add_argument("--platform", default=None, choices=[*PLATFORMS, "all"])
    parser.add_argument("--dest", type=Path, default=ROOT_DIR / "native-download")
    args = parser.parse_args()

    release = args.release or pinned_release(ROOT_DIR / "python")
    platforms = list(PLATFORMS) if args.platform == "all" else [args.platform or host_platform()]
    for plat in platforms:
        print(download_native_lib(release, plat, args.dest / release / plat))


if __name__ == "__main__":
    main()
