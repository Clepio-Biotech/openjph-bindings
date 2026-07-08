#!/usr/bin/env bash
# Assert the version strings across the monorepo agree. The package versions
# (pyproject + both Project.toml) carry a bare version; the download-tag fields
# (build.jl BINDINGS_VERSION, python CMake _BINDINGS_TAG) carry a leading 'v'.
# Run locally or in CI; exits non-zero on any mismatch.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
get() { grep -oP "$2" "$root/$1" | head -1; }

ref_ver=$(get native/src/openjph_c.cpp                 '^static const char version\[\] = "\K[^"]+')
py_ver=$(get python/pyproject.toml                     '^version = "\K[^"]+')
ojph_ver=$(get julia/OpenJPH.jl/Project.toml           '^version = "\K[^"]+')
zarr_ver=$(get julia/ZarrCompressorJPH.jl/Project.toml '^version = "\K[^"]+')
bind_tag=$(get julia/OpenJPH.jl/deps/build.jl          'BINDINGS_VERSION\s*=\s*"\K[^"]+')
cmake_tag=$(get python/CMakeLists.txt                  '_BINDINGS_TAG "\K[^"]+')
# Note: python/CMakeLists.txt will be removed soon

printf 'openjph_c.cpp (ref):  %s\n' "$ref_ver"
printf 'pyproject:            %s\n' "$py_ver"
printf 'OpenJPH.jl:           %s\n' "$ojph_ver"
printf 'ZarrCompressorJPH:    %s\n' "$zarr_ver"
printf 'build.jl tag:         %s\n' "$bind_tag"
printf 'python CMake tag:     %s\n' "$cmake_tag"

fail=0
[ "$ref_ver" = "$py_ver"  ] || { echo "MISMATCH: pyproject.toml";      fail=1; }
[ "$ref_ver" = "$ojph_ver"  ] || { echo "MISMATCH: OpenJPH.jl";        fail=1; }
[ "$ref_ver" = "$zarr_ver"  ] || { echo "MISMATCH: ZarrCompressorJPH"; fail=1; }
[ "v$ref_ver" = "$bind_tag"  ] || { echo "MISMATCH: build.jl tag";     fail=1; }
[ "v$ref_ver" = "$cmake_tag" ] || { echo "MISMATCH: python CMake tag"; fail=1; }

if [ "$fail" = 0 ]; then echo "all versions consistent"; else exit 1; fi
