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

## How `libopenjph_c` reaches each language

The native library is **distributed as a prebuilt binary** to both ecosystems; building from
source is only needed when developing the C layer itself.

| | Julia | Python |
|---|---|---|
| **Prebuilt (default)** | Pkg downloads the right per-platform binary via `OpenJPH.jl/Artifacts.toml` from a `C-v*` GitHub Release — no C++ toolchain needed | every install (wheel or source) contains the binary from the `C-v*` release pinned in `python/pyproject.toml` — `hatch_build.py` downloads it at build time; nothing is ever compiled |
| **Local build (override)** | build `native/` yourself with `tools/build_native_local.jl`, then point at it with a `~/.julia/artifacts/Overrides.toml` entry — the package itself has no build step or local-detection logic | set the `PYOPENJPH_LIB_PATH` environment variable to a custom `libopenjph_c` at **runtime** — no reinstall needed (the wgpu-py `WGPU_LIB_PATH` pattern) |

So a normal install needs no compiler on either side, and both ecosystems resolve the native
library the same way: from a published, immutable `C-v*` release. Developers testing an
in-progress native change build `native/` themselves and override at load time —
`Overrides.toml` for Julia (see `docs/RELEASING.md`), `PYOPENJPH_LIB_PATH` for Python. To try a
*different published* C release against Python, download it with
`python tools/download_native.py --release C-vX.Y.Z.W` and point `PYOPENJPH_LIB_PATH` at the
printed library.

---

## Developer setup

### Prerequisites

- cmake ≥ 3.24 and a C++17 compiler (only for local/source builds)
- Julia ≥ 1.11 (for `[sources]` and Pkg Artifacts)
- Python ≥ 3.12

### Julia

```bash
# Resolves libopenjph_c from the published Pkg Artifact — no local build needed.
julia --project=julia/OpenJPH.jl -e 'import Pkg; Pkg.instantiate()'

# Run tests (Pkg.test with no argument tests the active project's package)
julia --project=julia/OpenJPH.jl           -e 'import Pkg; Pkg.test()'
julia --project=julia/ZarrCompressorJPH.jl -e 'import Pkg; Pkg.test()'
```

To test against an in-progress native change instead, see `docs/RELEASING.md`
(`tools/build_native_local.jl` + `Overrides.toml`).

### Python

```bash
# Downloads the pinned C-v* release binary at build time — no compiler needed.
pip install "python/[test,zarr]"

# Run tests
cd python && pytest tests/

# Test against a locally built native/ instead (no reinstall):
PYOPENJPH_LIB_PATH=/path/to/build/libopenjph_c.so pytest tests/
```

### native (standalone)

`native/` can be built and tested independently of both language wrappers:

```bash
cmake -B build native/ -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
# Produces: build/libopenjph_c.so
```
