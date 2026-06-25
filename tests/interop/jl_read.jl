# Cross-language Zarr interop (Julia reader).
#
# Reads the plain-codec and HTJ2K stores written by py_write.py and asserts they
# decode to identical Julia arrays. Equality with the plain codec proves the
# HTJ2K codec preserves data across the language boundary (independent of
# Zarr.jl's dimension-order convention). Exits non-zero on mismatch so CI fails.

using Zarr, ZarrCompressorJPH

outdir = ARGS[1]
zp = zopen("$outdir/py_plain.zarr", "r"; zarr_format = 3)[:, :]
zh = zopen("$outdir/py_htj2k.zarr", "r"; zarr_format = 3)[:, :]

if size(zp) != size(zh) || zp != zh
    println(stderr, "INTEROP FAILURE: htj2k != plain (sizes $(size(zp)) vs $(size(zh)))")
    exit(1)
end
println("interop OK: julia read python-written htj2k == plain, size $(size(zh))")
