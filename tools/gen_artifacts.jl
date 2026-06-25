# Generate julia/OpenJPH.jl/Artifacts.toml from a published GitHub release.
#
# Run this AFTER `release.yml` has published the per-platform tarballs for a tag,
# to bind libopenjph_c to those tarballs (lazy, platform-dispatched). Requires
# ArtifactUtils in the active environment:
#
#   julia -e 'import Pkg; Pkg.activate(temp=true); Pkg.add("ArtifactUtils")' \
#         tools/gen_artifacts.jl v0.1.0
#
# This is part of the D6 consumer switch and is NOT wired up until a release with
# the native binaries exists.

using ArtifactUtils
using Base.BinaryPlatforms

const REPO = "https://github.com/Clepio-Biotech/openjph-bindings"
const ARTIFACTS_TOML = normpath(joinpath(@__DIR__, "..", "julia", "OpenJPH.jl", "Artifacts.toml"))

# (release-asset stem, Julia platform) for each tarball release.yml publishes.
const TARGETS = [
    ("linux-x86_64",   Platform("x86_64",  "linux")),
    ("linux-aarch64",  Platform("aarch64", "linux")),
    ("macos-x86_64",   Platform("x86_64",  "macos")),
    ("macos-arm64",    Platform("aarch64", "macos")),
    ("windows-x86_64", Platform("x86_64",  "windows")),
]

function main(tag::AbstractString)
    isfile(ARTIFACTS_TOML) && rm(ARTIFACTS_TOML)
    for (stem, platform) in TARGETS
        url = "$(REPO)/releases/download/$(tag)/libopenjph_c-$(stem).tar.gz"
        @info "Binding libopenjph_c" platform url
        # Downloads the tarball, computes its tree hash + sha256, and records a
        # lazy, platform-constrained binding in Artifacts.toml.
        add_artifact!(ARTIFACTS_TOML, "libopenjph_c", url;
                      platform = platform, lazy = true, force = true)
    end
    @info "Wrote $(ARTIFACTS_TOML)"
end

main(isempty(ARGS) ? error("usage: gen_artifacts.jl <release-tag>  e.g. v0.1.0") : ARGS[1])
