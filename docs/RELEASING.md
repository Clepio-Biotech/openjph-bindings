# Releasing & binary distribution

This repo ships its native library (`libopenjph_c`) to two ecosystems:

- **Python** → PyPI wheels (built by `wheels.yml`, published on `v*` tags). Each wheel bundles the
  native lib; users get it via `pip install pyopenjph`. Nothing for Python goes to GitHub Releases.
- **Julia** → per-platform binaries published as GitHub **Release tarballs** (built by
  `release.yml`), bound by `julia/OpenJPH.jl/Artifacts.toml` and dispatched by Pkg.

## Current state (pre-first-release)

Until a multi-platform release exists, the Julia side resolves the native lib **locally**:

- Monorepo development: `OpenJPH.jl/deps/build.jl` auto-detects the sibling `native/` and builds it
  (no `NATIVE_PATH`, no network). `ZarrCompressorJPH` finds `OpenJPH` via `[sources] {path = ...}`.
- This works today and is what CI exercises.

The producer CI (`release.yml`) is written but **has not been run end-to-end**, and the consumer
switch below is **not yet applied**.

## Activating Artifacts-based distribution (the D6 consumer switch)

Do this once `release.yml` has published the per-platform tarballs for a real tag:

1. **Cut a tag** `vX.Y.Z` and push it. `release.yml` builds `libopenjph_c-<platform>.tar.gz` for
   `linux-{x86_64,aarch64}`, `macos-{x86_64,arm64}`, `windows-x86_64` and attaches them to the
   release. (`wheels.yml` separately publishes the PyPI wheels.)
2. **Generate `Artifacts.toml`:**
   ```bash
   julia -e 'import Pkg; Pkg.activate(temp=true); Pkg.add("ArtifactUtils")' \
         tools/gen_artifacts.jl vX.Y.Z
   ```
   This writes `julia/OpenJPH.jl/Artifacts.toml` with a lazy, platform-dispatched binding for each
   tarball (url + sha256 + tree-hash). Commit it.
3. **Switch `OpenJPH.jl` to load from the artifact** instead of the build product:
   ```julia
   using Pkg.Artifacts
   const libopenjph_c = joinpath(artifact"libopenjph_c", "libopenjph_c." * _dlext)
   ```
   and reduce `deps/build.jl` to the `NATIVE_PATH` dev override only (Pkg now supplies the binary
   per platform; no download/regex logic).
4. **Switch `ZarrCompressorJPH`'s `[sources]`** from the path form to the URL form so a standalone
   `Pkg.add(url=..., subdir="julia/ZarrCompressorJPH.jl")` resolves:
   ```toml
   [sources]
   OpenJPH = {url = "https://github.com/Clepio-Biotech/openjph-bindings", subdir = "julia/OpenJPH.jl", rev = "vX.Y.Z"}
   ```
5. **Keep versions in sync** — bump `pyproject.toml`, both `Project.toml`, and the download-tag
   constants together; `tests/check_versions.sh` (run in CI) enforces this.

## Notes / pitfalls baked into `release.yml`

- **Linux** binaries build inside `manylinux_2_28` (glibc 2.28 floor) so they load on older distros,
  matching the wheels. `linux-aarch64` builds under QEMU.
- **macOS** dylibs get `install_name_tool -id @rpath/libopenjph_c.dylib` so an absolute-path
  `dlopen` works wherever Pkg unpacks the artifact.
- **Windows** ships only the runtime `openjph_c.dll` (no import lib needed for `ccall`).
- OpenJPH is statically embedded (`WHOLE_ARCHIVE`), so the binaries have no external OpenJPH dep.
