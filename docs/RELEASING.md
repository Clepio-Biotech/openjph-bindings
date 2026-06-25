# Releasing & binary distribution

This repo ships its native library (`libopenjph_c`) to two ecosystems:

- **Python** → PyPI wheels (built by `wheels.yml`, published on `v*` tags). Each wheel bundles the
  native lib; users get it via `pip install pyopenjph`. Nothing for Python goes to GitHub Releases.
- **Julia** → per-platform binaries published as GitHub **Release tarballs** by the
  `publish-native` job in `wheels.yml`, bound by `julia/OpenJPH.jl/Artifacts.toml` and dispatched by
  Pkg. These are **recycled from the wheels** (`tools/extract_native_from_wheels.sh` pulls the lib
  cibuildwheel already built), not a separate build — valid because OpenJPH is statically embedded.

## Current state (pre-first-release)

Until a multi-platform release exists, the Julia side resolves the native lib **locally**:

- Monorepo development: `OpenJPH.jl/deps/build.jl` auto-detects the sibling `native/` and builds it
  (no `NATIVE_PATH`, no network). `ZarrCompressorJPH` finds `OpenJPH` via `[sources] {path = ...}`.
- This works today and is what CI exercises.

The producer CI (the `publish-native` job in `wheels.yml`) and the consumer switch below are
**not yet applied** end-to-end — they activate once a real multi-platform release exists.

## Activating Artifacts-based distribution (the D6 consumer switch)

Do this once `release.yml` has published the per-platform tarballs for a real tag:

1. **Cut a tag** `vX.Y.Z` and push it. `wheels.yml` builds the wheels, publishes them to PyPI, and
   its `publish-native` job extracts the bundled native lib from each wheel and attaches
   `libopenjph_c-<platform>.tar.gz` for `linux-{x86_64,aarch64}`, `macos-{x86_64,arm64}`,
   `windows-x86_64` to the GitHub release.
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

## Notes / pitfalls

- The native libs are **recycled from the wheels**, so cibuildwheel's platform handling carries
  over for free: Linux libs are manylinux (glibc floor matches the wheels), `aarch64` via QEMU,
  macOS from the x86_64/arm64 runners, Windows as the runtime DLL.
- Because OpenJPH is statically embedded (`WHOLE_ARCHIVE`), the in-wheel lib has **no external
  deps**, so `auditwheel`/`delocate` do not vendor or rename it — extracting it for Julia is safe.
- The extractor (`tools/extract_native_from_wheels.sh`) renames the Windows lib (`openjph_c.dll`) to
  the canonical `libopenjph_c.dll` inside the tarball; Linux/macOS already ship
  `libopenjph_c.{so,dylib}`. It skips musllinux wheels and de-dups across cp312/cp313.
