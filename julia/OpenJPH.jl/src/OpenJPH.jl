module OpenJPH

using Libdl
using Artifacts, LazyArtifacts

const _dlext     = Sys.iswindows() ? "dll" : Sys.isapple() ? "dylib" : "so"
const _deps_file = joinpath(@__DIR__, "..", "deps", "deps.jl")

# Resolve the native library. A local build (produced by deps/build.jl from
# NATIVE_PATH or the in-monorepo native/ source) takes precedence so the C layer
# can be developed in place; otherwise Pkg supplies the right per-platform binary
# from Artifacts.toml. deps.jl records only the basename, resolved relative to
# deps/ at load time so a local override stays relocatable.
const libopenjph_c = if isfile(_deps_file)
    include(_deps_file)   # defines const libopenjph_c_name
    joinpath(@__DIR__, "..", "deps", libopenjph_c_name)
else
    joinpath(artifact"libopenjph_c", "libopenjph_c.$(_dlext)")
end

# OpenJPH is statically embedded in libopenjph_c — no separate library to load.
Libdl.dlopen(libopenjph_c, Libdl.RTLD_GLOBAL | Libdl.RTLD_LAZY)

# ---- C struct mirrors ----

struct OJPHArray
    data      :: Ptr{Cvoid}
    ndim      :: Csize_t
    dim0      :: Csize_t
    dim1      :: Csize_t
    dim2      :: Csize_t
    bit_depth :: Cuint
    is_signed :: Cint
end

struct OJPHEncodeParams
    irreversible       :: Cint
    qstep              :: Cfloat
    use_qstep          :: Cint
    num_decompositions :: Cint
    block_width        :: Cint
    block_height       :: Cint
    progression_order  :: NTuple{8, Cchar}
    color_transform    :: Cint
    planar             :: Cint
end

# ---- C return codes (openjph_c.h) ----

const _OPENJPH_OK = Cint(0)
const _OPENJPH_ERR_BUFFER_TOO_SMALL = Cint(-2)

# ---- type <-> (bit_depth, is_signed) mapping ----

function _bit_depth_signed(::Type{T}) where T
    T == UInt8  && return (Cuint(8),  Cint(0))
    T == Int8   && return (Cuint(8),  Cint(1))
    T == UInt16 && return (Cuint(16), Cint(0))
    T == Int16  && return (Cuint(16), Cint(1))
    T == UInt32 && return (Cuint(32), Cint(0))
    T == Int32  && return (Cuint(32), Cint(1))
    throw(ArgumentError("Unsupported element type: $T"))
end

function _type_from_bd_signed(bd::Cuint, sgn::Cint)
    bd == 8  && sgn == 0 && return UInt8
    bd == 8  && sgn == 1 && return Int8
    bd == 16 && sgn == 0 && return UInt16
    bd == 16 && sgn == 1 && return Int16
    bd == 32 && sgn == 0 && return UInt32
    bd == 32 && sgn == 1 && return Int32
    error("Unsupported: $(bd)-bit $(sgn == 1 ? "signed" : "unsigned")")
end

_str_to_po(s::String) = ntuple(i -> i <= ncodeunits(s) ? Cchar(codeunit(s, i)) : Cchar(0), 8)

# True iff `a` is stored contiguously in column-major order, so that pointer(a)
# followed by a linear read of length(a) elements is valid. This is stricter and
# less wasteful than `a isa DenseArray`: it also accepts contiguous views (which
# are not <: DenseArray) without copying, while rejecting strided views,
# transpose, and adjoint (whose pointer/size disagree). `Base.iscontiguous` is
# internal and errors on plain Arrays, so we test strides directly.
function _is_contiguous(a::AbstractArray)
    a isa StridedArray || return false   # transpose/adjoint/etc. → not strided
    expected = 1
    @inbounds for d in 1:ndims(a)
        stride(a, d) == expected || return false
        expected *= size(a, d)
    end
    return true
end

# ---- encode ----

"""
    openjph_encode(arr::AbstractArray{T}; kwargs...) -> Vector{UInt8}

Compress `arr` (2-D or 3-D, element type UInt8/Int8/UInt16/Int16/UInt32/Int32)
to an HTJ2K codestream.

The native memory pointer is passed to C without copying or permuting the data.
Dimension indices are reversed when reporting the shape to C (Julia is column-major,
C is row-major), so a Julia `(H, W)` array produces the same codestream as a
Python/NumPy `(W, H)` C-order array with the same pixels.

The output buffer is Julia-allocated (sized by `openjph_encode_bound`) and filled
by C — no wrapper-allocated memory crosses the FFI, so there is nothing to free
on the C side. If the bound is ever insufficient, C reports the exact required
size and the call retries once before `resize!`-ing to the used byte count.

# Keyword arguments
- `irreversible::Bool = false` — use lossy 9/7 wavelet transform
- `qstep::Union{Float32,Nothing} = nothing` — quantization step (irreversible mode only)
- `num_decompositions::Int = 5`
- `block_width::Int = 64`, `block_height::Int = 64`
- `progression_order::String = "LRCP"`
- `color_transform::Bool = false` — MCT for 3-component images
- `planar::Bool = true`
"""
function openjph_encode(arr::AbstractArray{T,N};
        irreversible::Bool = false,
        qstep::Union{Float32, Nothing} = nothing,
        num_decompositions::Int = 5,
        block_width::Int = 64,
        block_height::Int = 64,
        progression_order::String = "LRCP",
        color_transform::Bool = false,
        planar::Bool = true) where {T <: Union{UInt8, Int8, UInt16, Int16, UInt32, Int32}, N}

    N == 2 || N == 3 || throw(ArgumentError("arr must be 2-D or 3-D, got $(N)-D"))

    # We hand pointer(arr) to C and report size(arr), so the buffer must be
    # contiguous column-major. A view/transpose would otherwise have its pointer
    # reference the parent while size() describes the view → silently wrong data.
    # Contiguous inputs (Array/reshape/contiguous view) pass through with no copy.
    arr = _is_contiguous(arr) ? arr : Array(arr)

    # Pass the native memory pointer directly — no copy or permutation.
    #
    # 2-D: reverse the two dims so C reads the Julia column-major buffer as
    # C row-major with the correct spatial shape.
    #
    # 3-D without color transform: all three dims are reversed (same logic).
    # The C layer sees an arbitrary multi-component image with no assumption
    # about which axis holds channels.
    #
    # 3-D with color transform: the component axis (dim 1 in Julia, the fast
    # axis) must be passed first so C sees the correct component count. Only
    # the two spatial dims are reversed. Julia (C,H,W) column-major is
    # interleaved at the component level, so planar is forced to false.
    if N == 3 && color_transform
        d0 = Csize_t(size(arr, 1))   # C — component count (first Julia dim)
        d1 = Csize_t(size(arr, 3))   # W → C's "height" (spatial, reversed)
        d2 = Csize_t(size(arr, 2))   # H → C's "width"  (spatial, reversed)
        effective_planar = false
    elseif N == 3
        d0 = Csize_t(size(arr, 3))
        d1 = Csize_t(size(arr, 2))
        d2 = Csize_t(size(arr, 1))
        effective_planar = planar
    else
        d0 = Csize_t(size(arr, 2))
        d1 = Csize_t(size(arr, 1))
        d2 = Csize_t(0)
        effective_planar = planar
    end

    bd, sgn = _bit_depth_signed(T)

    img = OJPHArray(
        Ptr{Cvoid}(pointer(arr)),
        Csize_t(ndims(arr)),
        d0, d1, d2,
        bd, sgn
    )

    params = OJPHEncodeParams(
        Cint(irreversible),
        qstep === nothing ? 0f0 : Float32(qstep),
        Cint(qstep !== nothing),
        Cint(num_decompositions),
        Cint(block_width),
        Cint(block_height),
        _str_to_po(progression_order),
        Cint(color_transform),
        Cint(effective_planar)
    )

    bound = ccall((:openjph_encode_bound, libopenjph_c), Csize_t,
                  (Ref{OJPHArray},), Ref(img))
    bound == 0 && throw(ArgumentError("openjph_encode: invalid array descriptor"))

    out     = Vector{UInt8}(undef, Int(bound))
    used    = Ref{Csize_t}(0)
    err_buf = zeros(UInt8, 1024)

    encode_ccall(buf) = GC.@preserve arr buf err_buf ccall(
        (:openjph_encode, libopenjph_c), Cint,
        (Ref{OJPHArray}, Ref{OJPHEncodeParams},
         Ptr{UInt8}, Csize_t, Ref{Csize_t}, Ptr{UInt8}, Csize_t),
        Ref(img), Ref(params),
        pointer(buf), Csize_t(length(buf)), used, pointer(err_buf), Csize_t(1024)
    )

    ret = encode_ccall(out)
    if ret == _OPENJPH_ERR_BUFFER_TOO_SMALL
        # The bound is a generous estimate, not a guarantee; C reported the
        # exact required size, so a single retry always suffices.
        resize!(out, Int(used[]))
        ret = encode_ccall(out)
    end
    ret == _OPENJPH_OK || error("openjph_encode: $(unsafe_string(pointer(err_buf)))")

    resize!(out, Int(used[]))
    out
end

# ---- decode ----

function _get_info_raw(cs::Vector{UInt8})
    out_ndim      = Ref{Csize_t}(0)
    out_dims      = Ref{NTuple{3, Csize_t}}((0, 0, 0))
    out_bit_depth = Ref{Cuint}(0)
    out_is_signed = Ref{Cint}(0)
    err_buf       = zeros(UInt8, 1024)

    ret = GC.@preserve cs err_buf ccall(
        (:openjph_get_info, libopenjph_c), Cint,
        (Ptr{UInt8}, Csize_t,
         Ref{Csize_t}, Ref{NTuple{3, Csize_t}},
         Ref{Cuint}, Ref{Cint},
         Ptr{UInt8}, Csize_t),
        pointer(cs), Csize_t(length(cs)),
        out_ndim, out_dims,
        out_bit_depth, out_is_signed,
        pointer(err_buf), Csize_t(1024)
    )
    ret == _OPENJPH_OK || error("openjph_get_info: $(unsafe_string(pointer(err_buf)))")

    T = _type_from_bd_signed(out_bit_depth[], out_is_signed[])
    (T, Int(out_ndim[]), out_dims[])
end

# Reconstruct the Julia shape from the SIZ dimensions stored in the codestream.
# For 2-D and standard 3-D: all dims are reversed (column-major ↔ row-major swap).
# For 3-D with color_transform: component dim (dims[1]) stays first; only the
# two spatial dims are reversed, mirroring the encode-side convention.
function _shape_from_dims(ndim::Int, dims::NTuple{3, Csize_t},
                          color_transform::Bool)
    if ndim == 2
        (Int(dims[2]), Int(dims[1]))
    elseif color_transform
        (Int(dims[1]), Int(dims[3]), Int(dims[2]))   # (C, H, W)
    else
        (Int(dims[3]), Int(dims[2]), Int(dims[1]))
    end
end

"""
    openjph_get_info(codestream::AbstractVector{UInt8}; color_transform=false)
        -> (T, shape)

Read the element type and Julia-convention shape from the codestream SIZ marker
without decoding. `color_transform` selects the same shape reconstruction as
`openjph_decode`.

A 1-component codestream reports a 2-D shape: the SIZ marker cannot express a
trailing singleton axis (in Julia's column-major convention), so `(w, h, 1)`
and `(w, h)` encode identically. Callers that know the intended shape are the
source of truth — allocate at that shape and use `openjph_decode!`.
"""
function openjph_get_info(codestream::AbstractVector{UInt8};
                          color_transform::Bool = false)
    cs = codestream isa Vector{UInt8} ? codestream : collect(UInt8, codestream)
    T, ndim, dims = _get_info_raw(cs)
    (T, _shape_from_dims(ndim, dims, color_transform))
end

"""
    openjph_decode!(out::Array{T}, codestream::AbstractVector{UInt8}) -> out

Decompress an HTJ2K codestream into the caller-allocated `out`, zero-copy. `T`
must match the codestream's element type and `sizeof(out)` must exactly equal
the decoded byte count, but the shape of `out` is free — e.g. `(w, h, 1)` for
a codestream whose SIZ marker says `(w, h)`. On error the contents of `out`
are unspecified.
"""
function openjph_decode!(out::Array{T}, codestream::AbstractVector{UInt8}) where
        {T <: Union{UInt8, Int8, UInt16, Int16, UInt32, Int32}}
    cs = codestream isa Vector{UInt8} ? codestream : collect(UInt8, codestream)

    # The byte length is validated by C against the SIZ marker; the element
    # type must be validated here, since a type mismatch with equal byte size
    # (e.g. Int16 vs UInt16) would otherwise be silently misinterpreted.
    T_cs, _, _ = _get_info_raw(cs)
    T_cs === T || error(
        "openjph_decode!: element type mismatch — codestream has $T_cs, output array has $T")

    err_buf = zeros(UInt8, 1024)
    ret = GC.@preserve out cs err_buf ccall(
        (:openjph_decode, libopenjph_c), Cint,
        (Ptr{UInt8}, Csize_t, Ptr{Cvoid}, Csize_t, Ptr{UInt8}, Csize_t),
        pointer(cs), Csize_t(length(cs)),
        Ptr{Cvoid}(pointer(out)), Csize_t(sizeof(out)),
        pointer(err_buf), Csize_t(1024)
    )
    ret == _OPENJPH_OK || error("openjph_decode: $(unsafe_string(pointer(err_buf)))")
    out
end

"""
    openjph_decode(codestream::AbstractVector{UInt8}; color_transform=false) -> Array

Decompress an HTJ2K codestream. The element type and array shape are read from the
codestream SIZ marker — the caller does not need to supply them.

`color_transform` must match the value used in `openjph_encode`. When `true`, the
3-D output is reconstructed as `(C, H, W)` (component first); when `false` (default),
all dimensions are reversed from the SIZ marker as in the standard 2-D path.

The output array is Julia-allocated at the SIZ-derived shape and C writes decoded
pixels directly into it — no wrapper-allocated memory crosses the FFI and no copy
is made. To reuse an existing buffer (or to impose a shape the SIZ marker cannot
express, such as a trailing singleton axis), use `openjph_decode!`.
"""
function openjph_decode(codestream::AbstractVector{UInt8};
                        color_transform::Bool = false)
    cs = codestream isa Vector{UInt8} ? codestream : collect(UInt8, codestream)
    T, shape = openjph_get_info(cs; color_transform)
    openjph_decode!(Array{T}(undef, shape), cs)
end

export openjph_encode, openjph_decode, openjph_decode!, openjph_get_info

end # module
