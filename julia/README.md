# julia

Julia bindings for OpenJPH HTJ2K encode/decode, built on top of `libopenjph_c.so`
from the `native/` package.

Two packages live here:

- **`OpenJPH.jl`** — low-level Julia wrapper around the C ABI; exposes `openjph_encode`
  and `openjph_decode` for all supported integer types (UInt8, Int8, UInt16, Int16,
  UInt32, Int32).
- **`ZarrCompressorJPH.jl`** — Zarr v3 array-to-bytes codec (`HTJ2KCodec`) built on
  top of `OpenJPH.jl`.

## Installation

```julia
# From the Julia REPL
using Pkg
Pkg.add(url="https://github.com/LimenResearch/openjph-bindings", subdir="julia/OpenJPH.jl")
Pkg.add(url="https://github.com/LimenResearch/openjph-bindings", subdir="julia/ZarrCompressorJPH.jl")
```

`Pkg.build("OpenJPH")` runs automatically and resolves `libopenjph_c.so` via the
priority system described in the top-level README (prebuilt download → local source →
downloaded source).

## Basic usage

```julia
using OpenJPH

data = rand(UInt16, 64, 128)
encoded = openjph_encode(data)
decoded = openjph_decode(encoded)
@assert decoded == data
```

## Development

```bash
# Build from the local native/ directory (fastest for monorepo work)
NATIVE_PATH=$(pwd)/../native julia --project=OpenJPH.jl -e 'import Pkg; Pkg.build("OpenJPH")'

julia --project=OpenJPH.jl           -e 'import Pkg; Pkg.test("OpenJPH")'
julia --project=ZarrCompressorJPH.jl -e 'import Pkg; Pkg.test("ZarrCompressorJPH")'
```
