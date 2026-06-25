# openjph-bindings

Language bindings for [OpenJPH](https://github.com/aous72/OpenJPH) — a high-performance HTJ2K (High Throughput JPEG 2000) codec.

## Repository layout

```
openjph-bindings/
├── native/     # C ABI shared library (libopenjph_c.so) — the single source of truth
├── python/     # pyopenjph — Python bindings and optional Zarr v3 codec
└── julia/      # OpenJPH.jl and ZarrCompressorJPH.jl — Julia bindings and Zarr codec
```

The design principle is that `native/` is the only place where C++ touches OpenJPH. Both language wrappers depend on it and have no independent C++ build paths.

---

## How `libopenjph_c.so` reaches each language

There are three ways to obtain the shared library, in order of preference:

- **P0 — prebuilt binary**: use a compiled `.so` directly, no C++ toolchain needed.
- **P1 — build from local source**: point to a `native/` directory already on disk; cmake compiles the `.so`.
- **P2 — build from downloaded source**: fetch the `native/` source from GitHub automatically, then cmake compiles the `.so` (same as P1, but the download happens first).

The two languages expose these paths differently because their packaging ecosystems work differently:

| | Julia | Python |
|---|---|---|
| **P0** | `build.jl` downloads `libopenjph_c.so` from a GitHub Release | `pip install pyopenjph` downloads a wheel that already contains `libopenjph_c.so` — cmake never runs |
| **P1** | `build.jl` runs cmake on the directory pointed to by `NATIVE_PATH` | scikit-build-core runs cmake on `python/CMakeLists.txt`, which reads `NATIVE_PATH` and calls `add_subdirectory` |
| **P2** | `build.jl` downloads the `openjph-bindings` source tarball, extracts `native/`, then runs cmake | `python/CMakeLists.txt` uses CMake FetchContent to clone the `openjph-bindings` repo and build `native/` |

Julia has no wheel concept, so `build.jl` always runs at install time and must handle P0 explicitly. Python's wheel IS the prebuilt artifact — cmake only runs when building wheels (on CI) or when a user installs from source without a matching wheel for their platform.

### Setting `NATIVE_PATH`

P1 is triggered by setting `NATIVE_PATH` to the path of a local `native/` directory. This can be done via:

- A shell environment variable: `NATIVE_PATH=/path/to/native`
- A `.env` file in the package root (`julia/OpenJPH.jl/.env` or `python/.env`):
  ```
  NATIVE_PATH=/path/to/openjph-bindings/native
  ```

Inside this monorepo `NATIVE_PATH` is **optional**: the Julia `build.jl` and the Python
`CMakeLists.txt` both auto-detect the sibling `native/` directory, so a fresh monorepo build works
with no environment variable. Set `NATIVE_PATH` only to point at a `native/` directory elsewhere.

---

## Developer setup

### Prerequisites

- cmake ≥ 3.24 and a C++17 compiler (for P1/P2 builds)
- Julia ≥ 1.9
- Python ≥ 3.12

### Julia

```bash
# Build from the sibling native/ (auto-detected in the monorepo — no NATIVE_PATH needed)
julia --project=julia/OpenJPH.jl -e 'import Pkg; Pkg.build("OpenJPH")'

# Run tests (Pkg.test with no argument tests the active project's package)
julia --project=julia/OpenJPH.jl           -e 'import Pkg; Pkg.test()'
julia --project=julia/ZarrCompressorJPH.jl -e 'import Pkg; Pkg.test()'
```

### Python

```bash
# P1: build from local native/ (fastest for monorepo development)
NATIVE_PATH=$(pwd)/native pip install -e "python/[test,zarr]"

# Run tests
cd python && pytest tests/
```

### native (standalone)

`native/` can be built and tested independently of both language wrappers:

```bash
cmake -B build native/ -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
# Produces: build/libopenjph_c.so
```
