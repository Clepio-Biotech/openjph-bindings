# Releasing & binary distribution

The C wrapper, the Python package, and the Julia packages each have their own version and their
own release tag (see discussion #14) — a change to one no longer forces a release of the others.

- **C** (`native/`) — tag `C-vX.Y.Z.W`, where `X.Y.Z` is the vendored OpenJPH version
  (`native/CMakeLists.txt`'s `FetchContent_Declare` `GIT_TAG`) and `W` is a wrapper-revision digit
  we bump on wrapper-only changes. This is the only lineage with an automated release pipeline
  today.
- **Python** (`python/`) — its own version in `pyproject.toml`. PyPI publishing is currently
  disabled everywhere (`wheels.yml`'s triggers are commented out; `ci.yml`'s `publish-pypi` job is
  gated `&& false`) — standing up Python's own tag/publish pipeline is separate, future work.
- **Julia** (`julia/OpenJPH.jl`, `julia/ZarrCompressorJPH.jl`) — tag `Julia-vX.Y.Z`. This is a
  plain git tag with no CI action of its own: Julia isn't distributed through a binary pipeline the
  way C is, so tagging just marks the commit where the `Project.toml`s were bumped.

`tests/check_versions.sh` enforces the parts of this that can drift silently: C's own version
tracks the OpenJPH version it wraps, Julia's two packages agree with each other, and Python's
`_BINDINGS_TAG` (below) points at the current C tag.

## Cutting a C release

1. Bump `native/src/openjph_c.cpp`'s `version` string if needed (vendored-OpenJPH-version +
   wrapper-revision digit) and confirm `bash tests/check_versions.sh` passes.
2. Tag the commit `C-vX.Y.Z.W` and push it. `.github/workflows/ci.yml`'s tag trigger is scoped to
   `C-v*` specifically, so this is the only tag shape that kicks off the native build/publish
   pipeline (a `Julia-v*`/future `Python-v*` tag push does nothing here).
3. `native-linux-build`/`native-windows-build`/`native-macos-build` build `libopenjph_c` for all 6
   platforms (`linux-{x86_64,aarch64}`, `macos-{x86_64,aarch64}`, `windows-{x86_64,aarch64}`) and
   package **both** a `.zip` and a `.tar.gz` per platform — Julia's Pkg.Artifacts machinery only
   unpacks tarballs, not zips, so the `.tar.gz` is what Julia actually consumes.
4. `publish-github` attaches all of it (zips, tarballs, a `commit-sha` file) to a GitHub Release
   named after the tag.
5. Verify before moving on: `gh release view C-vX.Y.Z.W --json assets` should show 12 files (2
   archive formats × 6 platforms) plus `commit-sha`.

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

## Julia: installing from a branch instead of a tag

`[sources]` is only honoured for the **top-level** project, not for a dependency, so a downstream
package must declare both modules:

```toml
[sources]
OpenJPH           = {url = "https://github.com/Clepio-Biotech/openjph-bindings", subdir = "julia/OpenJPH.jl",          rev = "main"}
ZarrCompressorJPH = {url = "https://github.com/Clepio-Biotech/openjph-bindings", subdir = "julia/ZarrCompressorJPH.jl", rev = "main"}
```

`OpenJPH` still resolves its binary from whatever `Artifacts.toml` says at that `rev` — same
mechanism regardless of whether `rev` is a branch, commit, or `Julia-v*` tag.

## Notes / pitfalls

- `.github/workflows/wheels.yml`'s `publish-native` job is **dead code today**: its `pull_request`/
  `push` triggers were commented out when `ci.yml` took over native builds, leaving only
  `workflow_dispatch`. It also uses different asset naming (a `lib` prefix) and only covers 5
  platforms (no `windows-aarch64`). Don't treat it as a live part of the pipeline.
- Because OpenJPH is statically embedded in `libopenjph_c` (`WHOLE_ARCHIVE`), the built library has
  no external dependencies to worry about across platforms.
