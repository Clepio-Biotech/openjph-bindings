#!/usr/bin/env bash
# The C, Python, and Julia layers each have their own independent release
# lineage and version (see docs/RELEASING.md) — this no longer asserts they
# all agree on one number. What it does check:
#   1. C's own version (native/src/openjph_c.cpp) tracks the OpenJPH version
#      it actually vendors (native/CMakeLists.txt's FetchContent GIT_TAG),
#      plus a trailing wrapper-revision digit.
#   2. Julia's two packages (OpenJPH.jl, ZarrCompressorJPH.jl) agree with
#      each other — still one Julia lineage, two packages.
#   3. Python's _BINDINGS_TAG (the git tag its FetchContent source-fallback
#      pulls from this repo, python/CMakeLists.txt) points at the current C
#      release tag, not Python's own version.
# Run locally or in CI; exits non-zero on any mismatch.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
get() { grep -oP "$2" "$root/$1" | head -1; }

c_ver=$(get native/src/openjph_c.cpp                   '^static const char version\[\] = "\K[^"]+')
vendored_ojph_ver=$(get native/CMakeLists.txt          'GIT_TAG\s+\K[0-9.]+')
ojph_jl_ver=$(get julia/OpenJPH.jl/Project.toml        '^version = "\K[^"]+')
zarr_jl_ver=$(get julia/ZarrCompressorJPH.jl/Project.toml '^version = "\K[^"]+')
py_bindings_tag=$(get python/CMakeLists.txt            '_BINDINGS_TAG "\K[^"]+')

# c_ver carries a trailing wrapper-revision digit beyond the vendored
# OpenJPH version, e.g. "0.29.0.0" for vendored "0.29.0".
c_ver_ojph_part="${c_ver%.*}"
c_tag="C-v${c_ver}"

printf 'C wrapper version:       %s (vendors OpenJPH %s)\n' "$c_ver" "$vendored_ojph_ver"
printf 'OpenJPH.jl version:      %s\n' "$ojph_jl_ver"
printf 'ZarrCompressorJPH.jl:    %s\n' "$zarr_jl_ver"
printf 'python _BINDINGS_TAG:    %s\n' "$py_bindings_tag"

fail=0
[ "$c_ver_ojph_part" = "$vendored_ojph_ver" ] || {
  echo "MISMATCH: native/src/openjph_c.cpp's version ($c_ver) doesn't track the vendored OpenJPH version ($vendored_ojph_ver)"
  fail=1
}
[ "$ojph_jl_ver" = "$zarr_jl_ver" ] || {
  echo "MISMATCH: OpenJPH.jl ($ojph_jl_ver) vs ZarrCompressorJPH.jl ($zarr_jl_ver)"
  fail=1
}
[ "$py_bindings_tag" = "$c_tag" ] || {
  echo "MISMATCH: python/CMakeLists.txt's _BINDINGS_TAG ($py_bindings_tag) should equal the current C tag ($c_tag)"
  fail=1
}

if [ "$fail" = 0 ]; then echo "all versions consistent"; else exit 1; fi
