# Generate julia/OpenJPH.jl/Artifacts.toml from a published GitHub release of the
# C lineage (tags/C-v*, see .github/workflows/ci.yml and docs/RELEASING.md).
#
# Run this AFTER a C-v* tag has been pushed and ci.yml's publish-github job has
# finished, to bind libopenjph_c to that release's tarballs (lazy,
# platform-dispatched). Requires ArtifactUtils in the active environment:
#
#   julia -e 'import Pkg; Pkg.activate(temp=true); Pkg.add("ArtifactUtils")' \
#         tools/gen_artifacts.jl C-v0.29.0.0

using ArtifactUtils
using Base.BinaryPlatforms

const REPO = "https://github.com/Clepio-Biotech/openjph-bindings"
const ARTIFACTS_TOML = normpath(joinpath(@__DIR__, "..", "julia", "OpenJPH.jl", "Artifacts.toml"))

# (release-asset stem, Julia platform) for each tarball ci.yml's native-*-build
# jobs publish — stems must match those jobs' matrix.name exactly.
const TARGETS = [
    ("linux-x86_64",    Platform("x86_64",  "linux")),
    ("linux-aarch64",   Platform("aarch64", "linux")),
    ("macos-aarch64",   Platform("aarch64", "macos")),
    ("macos-x86_64",    Platform("x86_64",  "macos")),
    ("windows-x86_64",  Platform("x86_64",  "windows")),
    ("windows-aarch64", Platform("aarch64", "windows")),
]

function main(tag::AbstractString)
    isfile(ARTIFACTS_TOML) && rm(ARTIFACTS_TOML)
    for (stem, platform) in TARGETS
        url = "$(REPO)/releases/download/$(tag)/openjph_c-$(stem).tar.gz"
        @info "Binding libopenjph_c" platform url
        # Downloads the tarball, computes its tree hash + sha256, and records a
        # lazy, platform-constrained binding in Artifacts.toml.
        add_artifact!(ARTIFACTS_TOML, "libopenjph_c", url;
                      platform = platform, lazy = true, force = true)
    end
    @info "Wrote $(ARTIFACTS_TOML)"
end

isempty(ARGS) && error("usage: gen_artifacts.jl <C lineage release tag>  e.g. C-v0.29.0.0")
main(ARGS[1])
