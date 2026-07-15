#!/usr/bin/env bash
# The C, Python, and Julia layers each have their own independent release
# lineage and version (see docs/RELEASING.md) — this no longer asserts they
# all agree on one number. What it does check:
#   1. C's own version (native/src/openjph_c.cpp) tracks the OpenJPH version
#      it actually vendors (native/CMakeLists.txt's FetchContent GIT_TAG),
#      plus a trailing wrapper-revision digit.
#   2. Python's C-release pin (python/pyproject.toml [tool.pyopenjph]) and the
#      Julia Artifacts.toml are deliberately NOT checked here: both point at
#      published, immutable C-v* releases and are exercised at build/release
#      time, so there is no always-live invariant left to drift.
#   3. OpenJPH.jl and ZarrCompressorJPH.jl version independently (each has its own
#      tag, e.g. OpenJPH.jl-vX.Y.Z) and are deliberately not checked against each
#      other here — ZarrCompressorJPH.jl declares which OpenJPH versions it
#      supports via its own [compat] bound, not by matching version numbers.
# Run locally or in CI; exits non-zero on any mismatch.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
get() { grep -oP "$2" "$root/$1" | head -1; }

c_ver=$(get native/src/openjph_c.cpp                   '^static const char version\[\] = "\K[^"]+')
vendored_ojph_ver=$(get native/CMakeLists.txt          'GIT_TAG\s+\K[0-9.]+')
ojph_jl_ver=$(get julia/OpenJPH.jl/Project.toml        '^version = "\K[^"]+')
zarr_jl_ver=$(get julia/ZarrCompressorJPH.jl/Project.toml '^version = "\K[^"]+')

# c_ver carries a trailing wrapper-revision digit beyond the vendored
# OpenJPH version, e.g. "0.29.0.0" for vendored "0.29.0".
c_ver_ojph_part="${c_ver%.*}"

printf 'C wrapper version:       %s (vendors OpenJPH %s)\n' "$c_ver" "$vendored_ojph_ver"
printf 'OpenJPH.jl version:      %s\n' "$ojph_jl_ver"
printf 'ZarrCompressorJPH.jl:    %s\n' "$zarr_jl_ver"

fail=0
[ "$c_ver_ojph_part" = "$vendored_ojph_ver" ] || {
  echo "MISMATCH: native/src/openjph_c.cpp's version ($c_ver) doesn't track the vendored OpenJPH version ($vendored_ojph_ver)"
  fail=1
}

if [ "$fail" = 0 ]; then echo "all versions consistent"; else exit 1; fi
