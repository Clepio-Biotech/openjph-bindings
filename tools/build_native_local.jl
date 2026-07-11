# Build libopenjph_c from a local native/ source tree, for testing an
# in-progress native change against Julia before cutting a new C release.
#
# This is a plain manual script — it is NOT wired into any Pkg build hook.
# After running it, register the printed OUTPUT DIRECTORY (not the .so file
# itself) in ~/.julia/artifacts/Overrides.toml, keyed by OpenJPH's package
# UUID and the "libopenjph_c" artifact name (see docs/RELEASING.md), so
# `using OpenJPH` resolves to it instead of the published artifact.
#
#   julia tools/build_native_local.jl ../native ./local-build
#
# usage: build_native_local.jl <native-src-dir> <output-dir>

const _dlext = Sys.iswindows() ? "dll" : Sys.isapple() ? "dylib" : "so"

function build_cmake_native(native_src_dir, out_dir)
    cmake = Sys.which("cmake")
    if cmake === nothing
        error(
            "cmake is required to build libopenjph_c from source.\n" *
            "Install with:  sudo apt install cmake g++")
    end

    mkpath(out_dir)
    build_dir = joinpath(out_dir, "native_cmake_build")
    mkpath(build_dir)

    @info "Configuring native library..." src=native_src_dir build=build_dir
    run(`$cmake $native_src_dir -B $build_dir -DCMAKE_BUILD_TYPE=Release`)

    ncpu = Sys.CPU_THREADS
    @info "Compiling libopenjph_c ($ncpu threads)..."
    run(`$cmake --build $build_dir -j$ncpu`)

    built = joinpath(build_dir, "libopenjph_c.$(_dlext)")
    isfile(built) || error(
        "cmake build finished but expected library not found at $built")

    lib_out = joinpath(out_dir, "libopenjph_c.$(_dlext)")
    cp(built, lib_out; force=true)
    @info "Build complete." lib=lib_out
    lib_out
end

length(ARGS) == 2 || error(
    "usage: build_native_local.jl <native-src-dir> <output-dir>")
lib_path = build_cmake_native(ARGS[1], ARGS[2])
out_dir = abspath(ARGS[2])
println()
println("Built: $lib_path")
println()
println("IMPORTANT: point Overrides.toml at the DIRECTORY, not the .so file.")
println("OpenJPH.jl resolves the library as joinpath(artifact\"libopenjph_c\", \"libopenjph_c.$(_dlext)\")")
println("— overriding to a directory preserves that; overriding straight to the")
println(".so file makes the joinpath append the filename a second time and fail.")
println()
println("Register it locally with an entry like this in")
println("~/.julia/artifacts/Overrides.toml:")
println()
println("[8c589a84-a498-4fe3-acea-e589744a4834] # OpenJPH.jl's package UUID")
println("libopenjph_c = \"$out_dir\"")
