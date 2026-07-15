# Hatchling build hook: download the prebuilt libopenjph_c from a published
# C-v* GitHub release and package it into the wheel (the wgpu-py model — no
# compilation, ever). The release is pinned in _backend.py; PYOPENJPH_NATIVE_RELEASE overrides it, and
# PYOPENJPH_BUILD_PLATFORM selects a non-host target for cross-platform
# builds (see tools/build_wheels.py).

from __future__ import annotations

import hashlib
import os
import platform
import sys
import tarfile
import urllib.request
from pathlib import Path

try:
    from hatchling.builders.hooks.plugin.interface import BuildHookInterface
except ImportError:  # standalone use via tools/download_native.py
    BuildHookInterface = object

REPO_URL = "https://github.com/Clepio-Biotech/openjph-bindings"

# Release-asset stem (native.yml's matrix.name) -> wheel platform tag.
# linux libs are built in manylinux_2_28 containers; macos with
# MACOSX_DEPLOYMENT_TARGET=10.15 (arm64 macs start at 11.0).
PLATFORMS = {
    "linux-x86_64": "manylinux_2_28_x86_64",
    "linux-aarch64": "manylinux_2_28_aarch64",
    "macos-x86_64": "macosx_10_15_x86_64",
    "macos-aarch64": "macosx_11_0_arm64",
    "windows-x86_64": "win_amd64",
    "windows-aarch64": "win_arm64",
}

_LIB_SUFFIXES = {".so", ".dylib", ".dll"}

# sha256 of each openjph_c-<plat>.tar.gz release asset, keyed by release tag
# (release assets are mutable on GitHub, so the tag alone is not enough).
# Releases not listed here (dev overrides) are downloaded without verification.
CHECKSUMS = {
    "C-v0.29.0.1": {
        "linux-x86_64": "6bccf8688925a4f4751de6255e164f6234b579759fc88fd7dd524ae0f2c1fe4d",
        "linux-aarch64": "d858aadc5c05b508c83b7c1bd247dea54814c9bbdb2d4352b0c4547242f36715",
        "macos-x86_64": "10917d7ce2077136b83ec462088b35cbd6cb2dc759c99716eb94ca325405411d",
        "macos-aarch64": "15939cb213773deeaf5b4383434b4ac241ebfd3bc36f0fd3c35ee84e4b4755e4",
        "windows-x86_64": "423f50769a4c3c128cbb1a3ff1929509ce52d9bf9f8fed2297737c2701f8f487",
        "windows-aarch64": "823d9e9383ee44e195771582549998e86df1fef0317c54061ce2f164c552432e",
    },
}


def host_platform() -> str:
    os_name = {"linux": "linux", "darwin": "macos", "win32": "windows"}[sys.platform]
    arch = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }[platform.machine().lower()]
    return f"{os_name}-{arch}"


def pinned_release(project_root: Path) -> str:
    with open(
        project_root / "src" / "openjph" / "_backend.py", "rt", encoding="utf-8"
    ) as f:
        for line in f.readlines():
            if line.startswith("NATIVE_VERSION ="):
                break
        else:
            line = ""
            RuntimeError("Could not detect NATIVE_VERSION")
        native_version = line.partition("=")[2].strip().strip("\"'")
        return "C-v" + native_version


def download_native_lib(release: str, plat: str, dest: Path) -> Path:
    require_checksum = bool(os.environ.get("PYOPENJPH_REQUIRE_CHECKSUM"))
    url = f"{REPO_URL}/releases/download/{release}/openjph_c-{plat}.tar.gz"
    dest.mkdir(parents=True, exist_ok=True)
    archive = dest / "openjph_c.tar.gz"
    print(f"downloading {url}")
    urllib.request.urlretrieve(url, archive)
    expected = CHECKSUMS.get(release, {}).get(plat)
    if expected is not None:
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != expected:
            raise RuntimeError(
                f"sha256 mismatch for {url}: expected {expected}, got {digest}"
            )
    elif require_checksum:
        raise RuntimeError(
            f"sha256 check for {url} is required but checksum is not listed."
        )
    else:
        print(f"warning: no pinned sha256 for {release} {plat}, skipping verification")
    with tarfile.open(archive) as tar:
        tar.extractall(dest, filter="data")
    archive.unlink()
    libs = [p for p in dest.iterdir() if p.suffix in _LIB_SUFFIXES]
    if len(libs) != 1:
        raise RuntimeError(
            f"expected exactly one shared library from {url}, found {libs}"
        )
    return libs[0]


def to_h_file(p: str) -> str:
    path = Path(p)
    fname = path.name
    fname = fname.rpartition(".")[0] + ".h"
    if fname.startswith("lib"):
        fname = fname[3:]
    return str(path.parent / fname)


class NativeLibBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        root = Path(self.root)
        plat = os.environ.get("PYOPENJPH_BUILD_PLATFORM") or host_platform()
        release = os.environ.get("PYOPENJPH_NATIVE_RELEASE") or pinned_release(root)

        lib = download_native_lib(release, plat, root / "build" / release / plat)

        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{PLATFORMS[plat]}"
        build_data["force_include"][str(lib)] = f"openjph/{lib.name}"
        build_data["force_include"][to_h_file(str(lib))] = to_h_file(
            f"openjph/{lib.name}"
        )
