#!/usr/bin/env bash
# Cross-language Zarr interop check: a Zarr array written by the Python codec must
# read back identically through the Julia codec (compared against a plain-codec
# store to factor out Zarr.jl's axis-order convention).
#
# Requires: pyopenjph installed (`pip install python/[zarr]` — the build downloads
# its pinned C release binary), and the Julia OpenJPH/ZarrCompressorJPH packages built.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

echo "[interop] Python writes -> Julia reads"
python "$here/py_write.py" "$work"
julia --project="$root/julia/ZarrCompressorJPH.jl" "$here/jl_read.jl" "$work"
echo "[interop] OK"
