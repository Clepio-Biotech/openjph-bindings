# Download a prebuilt libopenjph_c from a C-v* GitHub release (the tarballs
# ci.yml's publish-github job attaches, one per platform) — e.g. to test a new
# C release before bumping the pin, by pointing PYOPENJPH_LIB_PATH at the
# downloaded library. The Python analog of tools/gen_artifacts.jl.
#
#   python tools/download_native.py                        # host platform, pinned release
#   python tools/download_native.py --release C-v0.29.0.2  # a specific release
#   python tools/download_native.py --platform all         # all six platforms
#   python tools/download_native.py --print-checksums      # emit a CHECKSUMS entry
#   python tools/download_native.py --update-checksums     # write it into
#                                                          # python/hatch_build.py
#
# The download/pin logic lives in python/hatch_build.py (the wheel build hook)
# so source installs work from an sdist; this is just its CLI.

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "python"))

from hatch_build import (
    REPO_URL,
    PLATFORMS,
    download_native_lib,
    host_platform,
    pinned_release,
)


def checksums_entry(release: str) -> str:
    lines = [f'    "{release}": {{']
    for plat in PLATFORMS:
        url = f"{REPO_URL}/releases/download/{release}/openjph_c-{plat}.tar.gz"
        with urllib.request.urlopen(url) as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        lines.append(f'        "{plat}": "{digest}",')
    lines.append("    },")
    return "\n".join(lines) + "\n"


def update_checksums(release: str) -> None:
    path = ROOT_DIR / "python" / "hatch_build.py"
    src = path.read_text(encoding="utf-8")
    # Drop any existing entry for this release, then insert the fresh one at
    # the top of the CHECKSUMS dict.
    src = re.sub(rf'    "{re.escape(release)}": \{{.*?\}},\n', "", src, flags=re.DOTALL)
    src, n = re.subn("CHECKSUMS = {\n", "CHECKSUMS = {\n" + checksums_entry(release), src)
    if n != 1:
        raise RuntimeError(f"could not find CHECKSUMS dict in {path}")
    path.write_text(src, encoding="utf-8")
    print(f"updated {path} for {release}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=None, help="C-v* release tag (default: the pin)")
    parser.add_argument("--platform", default=None, choices=[*PLATFORMS, "all"])
    parser.add_argument("--dest", type=Path, default=ROOT_DIR / "native-download")
    parser.add_argument(
        "--print-checksums", action="store_true",
        help="download all six assets and print a CHECKSUMS entry for python/hatch_build.py",
    )
    parser.add_argument(
        "--update-checksums", action="store_true",
        help="like --print-checksums, but write the entry into python/hatch_build.py",
    )
    args = parser.parse_args()

    release = args.release or pinned_release(ROOT_DIR / "python")
    if args.update_checksums:
        update_checksums(release)
        return
    if args.print_checksums:
        print(checksums_entry(release), end="")
        return
    platforms = list(PLATFORMS) if args.platform == "all" else [args.platform or host_platform()]
    for plat in platforms:
        print(download_native_lib(release, plat, args.dest / release / plat))


if __name__ == "__main__":
    main()
