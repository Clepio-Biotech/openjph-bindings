# Releasing & binary distribution

The C wrapper, the Python package, and the Julia packages each have their own version and their
own release tag (see discussion #14) — a change to one no longer forces a release of the others.

- **C** (`native/`) — tag `C-vX.Y.Z.W`, where `X.Y.Z` is the vendored OpenJPH version
  (`native/CMakeLists.txt`'s `FetchContent_Declare` `GIT_TAG`) and `W` is a wrapper-revision digit
  we bump on wrapper-only changes. This is the only lineage with an automated release pipeline
  today.
- **Python** (`python/`) — its own version in `pyproject.toml`, tag `Python-vX.Y.Z`, released
  through `.github/workflows/python.yml` (see "Cutting a Python release" below). The wheels ship
  the prebuilt `libopenjph_c` — nothing is compiled at wheel-build or install time.
- **Julia** — `OpenJPH.jl` and `ZarrCompressorJPH.jl` each version and tag independently
  (`OpenJPH.jl-vX.Y.Z`, `ZarrCompressorJPH.jl-vX.Y.Z`), not a shared "Julia" tag: they're two
  packages with independent `[compat]`-declared compatibility, not one lineage. Both are plain git
  tags with no CI action of their own — Julia isn't distributed through a binary pipeline the way C
  is, so tagging just marks the commit where a `Project.toml` was bumped.

`tests/check_versions.sh` enforces the one invariant that can drift silently: C's own version
tracks the OpenJPH version it wraps. Python's C-release pin and Julia's `Artifacts.toml` point at
published, immutable `C-v*` releases and are exercised at build/release time, so they're not
checked continuously. `OpenJPH.jl` and `ZarrCompressorJPH.jl` are deliberately not checked against
each other — `ZarrCompressorJPH.jl` declares which `OpenJPH` versions it supports via its own
`[compat]` bound.

## Cutting a C release

1. Bump `native/src/openjph_c.cpp`'s `version` string if needed (vendored-OpenJPH-version +
   wrapper-revision digit) and confirm `bash tests/check_versions.sh` passes.
2. Tag the commit `C-vX.Y.Z.W` and push it. `.github/workflows/ci.yml`'s tag trigger is scoped to
   `C-v*` specifically, so this is the only tag shape that kicks off the native build/publish
   pipeline (a Julia or future Python package tag push does nothing here).
3. `native-linux-build`/`native-windows-build`/`native-macos-build` build `libopenjph_c` for all 6
   platforms (`linux-{x86_64,aarch64}`, `macos-{x86_64,aarch64}`, `windows-{x86_64,aarch64}`) and
   package a `.tar.gz` per platform — Julia's Pkg.Artifacts machinery only unpacks tarballs, not
   zips, so that's the only archive format shipped.
4. `publish-github` attaches all of it (tarballs, a `commit-sha` file) to a GitHub Release named
   after the tag.
5. Verify before moving on: `gh release view C-vX.Y.Z.W --json assets` should show 6 files (one
   `.tar.gz` per platform) plus `commit-sha`.

## Pointing Julia at a C release

`julia/OpenJPH.jl/Artifacts.toml` is generated, not hand-written. After a `C-v*` release is
published and verified:

```bash
julia -e 'import Pkg; Pkg.activate(temp=true); Pkg.add("ArtifactUtils")' \
      tools/gen_artifacts.jl C-vX.Y.Z.W
```

This rewrites `Artifacts.toml` with a lazy, platform-dispatched binding (URL + sha256 + tree-hash)
for each of the 6 platforms' tarballs. Commit it. `OpenJPH.jl`'s `src/OpenJPH.jl` always resolves
`libopenjph_c` from this artifact — there is no local-build override or in-monorepo `native/`
detection in the package itself (that machinery, and the top-level-`const` bug it caused, was
removed; see git history if you need the details).

## Cutting a Python release

Python follows the wgpu-py model: the package never compiles C — every build (wheel or source
install) downloads the prebuilt `libopenjph_c` from the `C-v*` release pinned in
`python/pyproject.toml` `[tool.pyopenjph] native-release` (the download lives in
`python/hatch_build.py`, a hatchling build hook). Cutting a `Python-v*` release is therefore the
one deliberate moment Python switches C binary:

1. If the release should ship a newer C release, bump the `NATIVE_VERSION` in `_backend.py`
   (a normal, reviewed commit — CI's `python-tests` immediately runs against the new binary).
2. Bump `[project] version` in `python/pyproject.toml`.
3. Tag the commit `Python-vX.Y.Z` and push it. `python.yml` then:
   - builds all 6 platform wheels on one Linux runner (`tools/build_wheels.py` — each wheel is
     `py3-none-<platform>`, containing that platform's binary from the pinned release),
   - installs and tests the matching wheel on all 6 platforms' real runners,
   - verifies the tag matches the version and publishes wheels + sdist to PyPI.

`python.yml` can also be run manually (`workflow_dispatch`), optionally overriding which `C-v*`
release to package — useful for a dry run before committing a pin bump.

## Testing a local native change against Python

The package has no build-from-source path; use the runtime override (the wgpu-py `WGPU_LIB_PATH`
pattern) — no reinstall needed:

```bash
cmake -B build native/ -DCMAKE_BUILD_TYPE=Release && cmake --build build -j
PYOPENJPH_LIB_PATH=$PWD/build/libopenjph_c.so pytest python/tests
```

To try a *different published* C release instead, download it first:

```bash
python tools/download_native.py --release C-vX.Y.Z.W
```

and point `PYOPENJPH_LIB_PATH` at the printed library. As with Julia below, this manual step is
how an in-progress native change is verified against Python before cutting the next `C-v*` tag —
CI always tests the wrapper against its pinned, published release.

## Testing a local native change against Julia

Since the package has no build-override logic, use Julia's own artifact-override mechanism instead
of anything project-specific:

```bash
julia tools/build_native_local.jl native ./local-build
```

This cmake-builds `native/` and prints the resulting library **directory**. Register that
directory (not the `.so` file itself — see below) in `~/.julia/artifacts/Overrides.toml`, keyed by
`OpenJPH.jl`'s package UUID (`8c589a84-a498-4fe3-acea-e589744a4834`) and the `libopenjph_c`
artifact name:

```toml
[8c589a84-a498-4fe3-acea-e589744a4834]
libopenjph_c = "/absolute/path/to/local-build"
```

Two things about `Overrides.toml` that are easy to get wrong (found by testing this end to end,
not from the docs):

- **It must point at a directory, not the library file.** `OpenJPH.jl` resolves the library as
  `joinpath(artifact"libopenjph_c", "libopenjph_c.<ext>")` — normally `artifact"..."` returns the
  artifact's install *directory*, and that `joinpath` reaches the file inside it. An override
  replaces whatever `artifact"..."` returns, so pointing it at the `.so` file directly makes that
  `joinpath` append the filename a second time and fail to load. `tools/build_native_local.jl`'s
  output directory already has the right shape (it contains `libopenjph_c.<ext>` directly), so
  just point at that directory as printed.
- **Editing `Overrides.toml` does not retroactively affect an already-precompiled package.** Julia
  only re-resolves `artifact"libopenjph_c"` the next time `OpenJPH.jl` actually gets precompiled;
  changing the override file alone doesn't invalidate an existing `.ji` cache, since
  `Overrides.toml` is depot-wide runtime configuration, not a tracked compile dependency of the
  package. If `using OpenJPH` still resolves the old path after editing the override, force a
  fresh precompile, e.g.:
  ```bash
  rm -rf ~/.julia/compiled/v*/OpenJPH
  julia --project=julia/OpenJPH.jl -e 'import Pkg; Pkg.precompile()'
  ```

Remove the entry (or set it to `""`) and force a precompile the same way to go back to the
published artifact. This needs no change to `OpenJPH.jl` or `Artifacts.toml`, and it's why CI
doesn't try to test native+Julia changes together in one pipeline — the wrapper is always tested
against its pinned, published release; verifying an in-progress native change against Julia is
this manual step, done before cutting the next `C-v*` tag.

## Julia: pinning to a branch, commit, or tag

`julia/ZarrCompressorJPH.jl/Project.toml` itself declares `OpenJPH` this way (currently pinned to
`rev = "main"`):

```toml
[sources]
OpenJPH = {url = "https://github.com/Clepio-Biotech/openjph-bindings", subdir = "julia/OpenJPH.jl", rev = "main"}
```

Bumping `rev` (e.g. to a specific `OpenJPH.jl-vX.Y.Z` tag once one exists) is a deliberate, manual
edit — it does not track local changes to `../OpenJPH.jl`, on purpose (see the versioning section
above). To co-develop both packages in one branch instead, use `Pkg.develop(path="../OpenJPH.jl")`
in your own local session rather than changing this file.

`[sources]` is only honoured for the **top-level** project, not for a dependency, so a downstream
package consuming both must declare both modules itself the same way:

```toml
[sources]
OpenJPH           = {url = "https://github.com/Clepio-Biotech/openjph-bindings", subdir = "julia/OpenJPH.jl",          rev = "main"}
ZarrCompressorJPH = {url = "https://github.com/Clepio-Biotech/openjph-bindings", subdir = "julia/ZarrCompressorJPH.jl", rev = "main"}
```

`OpenJPH` still resolves its binary from whatever `Artifacts.toml` says at that `rev` — same
mechanism regardless of whether `rev` is a branch, commit, or tag.

## Notes / pitfalls

- Because OpenJPH is statically embedded in `libopenjph_c` (`WHOLE_ARCHIVE`), the built library has
  no external dependencies to worry about across platforms.
