from __future__ import annotations

import ctypes
import os
import sys
import platform
from pathlib import Path

import numpy as np

from openjph._constants import PROGRESSION_ORDERS


# The release of the native lib to use. Tagged in the repo as e.g. 'C-v0.29.0.1'.
# When bumping this, also run ``python tools/download_native.py --update-checksums``.
NATIVE_VERSION = "0.29.0.2"


def find_lib() -> Path:
    # Local-dev override (the wgpu-py WGPU_LIB_PATH pattern): point at a custom
    # build of libopenjph_c without reinstalling the package.
    lib_override = os.environ.get("PYOPENJPH_LIB_PATH")
    if lib_override:
        return Path(lib_override)

    os_name = {"linux": "linux", "darwin": "macos", "win32": "windows"}[sys.platform]

    arch = {
        "x86_64": "x86_64",
        "amd64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }[platform.machine().lower()]

    lib_name = {
        "windows": "openjph_c.dll",
        "macos": "libopenjph_c.dylib",
        "linux": "libopenjph_c.so",
    }[os_name]

    pkg_dir = Path(__file__).parent

    lib_paths = []
    lib_paths.append((pkg_dir / lib_name, ""))
    if (pkg_dir.parents[2] / ".git").is_dir():
        # Local dev env
        p1 = (
            pkg_dir.parents[1]
            / "build"
            / f"C-v{NATIVE_VERSION}"
            / f"{os_name}-{arch}"
            / lib_name
        )
        p2 = pkg_dir.parents[2] / "native" / "build" / lib_name
        lib_paths.append((p1, f"Using openjph from dev install: {p1}"))
        lib_paths.append((p2, f"!! Using openjph from local build: {p2}"))

    for lib_path, msg in lib_paths:
        if lib_path.is_file():
            if msg:
                print(msg)
            return lib_path
    else:
        raise RuntimeError(f"Could not find lib path from {lib_paths}")


lib_path = find_lib()

# On Windows, ctypes searches PATH but not the package directory for transitive DLLs.
if sys.platform == "win32" and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(str(lib_path.parent))

try:
    _lib = ctypes.CDLL(lib_path)
except OSError as e:
    raise ImportError(f"Could not load {lib_path}: {e}") from e

# ---- C struct mirrors ----


class _Array(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("ndim", ctypes.c_size_t),
        ("dim0", ctypes.c_size_t),  # dims[0]
        ("dim1", ctypes.c_size_t),  # dims[1]
        ("dim2", ctypes.c_size_t),  # dims[2]
        ("bit_depth", ctypes.c_uint32),
        ("is_signed", ctypes.c_int32),
    ]


class _EncodeParams(ctypes.Structure):
    _fields_ = [
        ("irreversible", ctypes.c_int),
        ("qstep", ctypes.c_float),
        ("use_qstep", ctypes.c_int),
        ("num_decompositions", ctypes.c_int),
        ("block_width", ctypes.c_int),
        ("block_height", ctypes.c_int),
        ("progression_order", ctypes.c_char * 8),
        ("color_transform", ctypes.c_int),
        ("planar", ctypes.c_int),
    ]


# ---- dtype lookup tables ----

_DTYPE_TO_BD_SIGNED: dict[np.dtype, tuple[int, int]] = {
    np.dtype("uint8"): (8, 0),
    np.dtype("int8"): (8, 1),
    np.dtype("uint16"): (16, 0),
    np.dtype("int16"): (16, 1),
    np.dtype("uint32"): (32, 0),
    np.dtype("int32"): (32, 1),
}

_BD_SIGNED_TO_DTYPE: dict[tuple[int, int], np.dtype] = {
    v: k for k, v in _DTYPE_TO_BD_SIGNED.items()
}

# ---- C return codes (openjph_c.h) ----

_OPENJPH_OK = 0

# ---- configure function signatures ----
# encode/free are unchanged: C still allocates the codestream buffer and the
# caller still releases it via openjph_free.

_lib.openjph_encode.restype = ctypes.c_int
_lib.openjph_encode.argtypes = [
    ctypes.POINTER(_Array),
    ctypes.POINTER(_EncodeParams),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.c_char_p,
    ctypes.c_size_t,
]

_lib.openjph_free.restype = None
_lib.openjph_free.argtypes = [ctypes.c_void_p]

_lib.openjph_version.restype = ctypes.c_char_p
_lib.openjph_c_version.restype = ctypes.c_char_p

# decode is caller-allocated: get_info probes the SIZ marker so the caller can
# size a buffer, then decode writes into it directly. Nothing C-allocated
# crosses the FFI on this path, so there is no free to call.

_lib.openjph_get_info.restype = ctypes.c_int
_lib.openjph_get_info.argtypes = [
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.POINTER(ctypes.c_size_t),  # out_dims[3] decays to size_t*
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_int32),
    ctypes.c_char_p,
    ctypes.c_size_t,
]

_lib.openjph_decode.restype = ctypes.c_int
_lib.openjph_decode.argtypes = [
    ctypes.c_char_p,
    ctypes.c_size_t,
    ctypes.c_void_p,  # out_buf (caller-allocated)
    ctypes.c_size_t,  # out_buf_len
    ctypes.c_char_p,
    ctypes.c_size_t,
]


# ---- public API ----


def encode(
    array: np.ndarray,
    *,
    irreversible: bool = False,
    qstep: float | None = None,
    num_decompositions: int = 5,
    block_size: tuple[int, int] = (64, 64),
    progression_order: str = "LRCP",
    color_transform: bool = False,
    planar: bool = True,
) -> bytes:
    if progression_order not in PROGRESSION_ORDERS:
        raise ValueError(
            f"Unsupported progression_order {progression_order!r}; "
            f"expected one of {list(PROGRESSION_ORDERS)}"
        )
    if num_decompositions < 0:
        raise ValueError(f"num_decompositions must be >= 0, got {num_decompositions}")
    if block_size[0] <= 0 or block_size[1] <= 0:
        raise ValueError(f"block_size values must be positive, got {block_size!r}")

    arr = np.ascontiguousarray(array)
    bd_sgn = _DTYPE_TO_BD_SIGNED.get(arr.dtype)
    if bd_sgn is None:
        raise ValueError(
            f"Unsupported dtype {arr.dtype}; expected one of {list(_DTYPE_TO_BD_SIGNED)}"
        )
    bit_depth, is_signed_val = bd_sgn

    ndim = arr.ndim
    if ndim == 2:
        d0, d1, d2 = arr.shape[0], arr.shape[1], 0
    elif ndim == 3:
        d0, d1, d2 = arr.shape[0], arr.shape[1], arr.shape[2]
    else:
        raise ValueError(f"array must be 2-D or 3-D, got {ndim}-D")

    img = _Array(
        data=arr.ctypes.data,
        ndim=ndim,
        dim0=d0,
        dim1=d1,
        dim2=d2,
        bit_depth=bit_depth,
        is_signed=is_signed_val,
    )
    params = _EncodeParams(
        irreversible=int(irreversible),
        qstep=float(qstep) if qstep is not None else 0.0,
        use_qstep=int(qstep is not None),
        num_decompositions=num_decompositions,
        block_width=block_size[0],
        block_height=block_size[1],
        progression_order=progression_order.encode("ascii")[:8],
        color_transform=int(color_transform),
        planar=int(planar),
    )

    out_ptr = ctypes.c_void_p(0)
    out_len = ctypes.c_size_t(0)
    err_buf = ctypes.create_string_buffer(1024)

    ret = _lib.openjph_encode(
        ctypes.byref(img),
        ctypes.byref(params),
        ctypes.byref(out_ptr),
        ctypes.byref(out_len),
        err_buf,
        ctypes.c_size_t(1024),
    )
    if ret != 0:
        raise RuntimeError(f"openjph_encode: {err_buf.value.decode(errors='replace')}")

    result = bytes(ctypes.string_at(out_ptr.value, int(out_len.value)))
    _lib.openjph_free(out_ptr)
    return result


def get_info(data: bytes | np.ndarray) -> tuple[tuple[int, ...], np.dtype]:
    cs = bytes(data) if not isinstance(data, bytes) else data

    out_ndim = ctypes.c_size_t(0)
    out_dims = (ctypes.c_size_t * 3)(0, 0, 0)
    out_bit_depth = ctypes.c_uint32(0)
    out_is_signed = ctypes.c_int32(0)
    err_buf = ctypes.create_string_buffer(1024)

    ret = _lib.openjph_get_info(
        cs,
        ctypes.c_size_t(len(cs)),
        ctypes.byref(out_ndim),
        out_dims,
        ctypes.byref(out_bit_depth),
        ctypes.byref(out_is_signed),
        err_buf,
        ctypes.c_size_t(1024),
    )
    if ret != _OPENJPH_OK:
        raise RuntimeError(
            f"openjph_get_info: {err_buf.value.decode(errors='replace')}"
        )

    key = (int(out_bit_depth.value), int(out_is_signed.value))
    dtype = _BD_SIGNED_TO_DTYPE.get(key)
    if dtype is None:
        raise RuntimeError(
            f"openjph_get_info: unknown output type bit_depth={key[0]}, "
            f"is_signed={key[1]}"
        )

    # A 1-component codestream reports 2-D: the SIZ marker cannot express a
    # leading singleton axis, so (1, h, w) and (h, w) encode identically.
    shape = tuple(int(out_dims[i]) for i in range(int(out_ndim.value)))
    return shape, dtype


def decode(data: bytes | np.ndarray, *, out: np.ndarray | None = None) -> np.ndarray:
    cs = bytes(data) if not isinstance(data, bytes) else data

    shape, dtype = get_info(cs)
    expected_nbytes = int(np.prod(shape)) * dtype.itemsize

    if out is None:
        out = np.empty(shape, dtype=dtype)
    else:
        # out's shape is free (e.g. (1, h, w) for a codestream whose SIZ says
        # (h, w)) as long as dtype and total byte size match exactly.
        if out.dtype != dtype:
            raise ValueError(
                f"out has dtype {out.dtype}, codestream decodes to {dtype}"
            )
        if not out.flags["C_CONTIGUOUS"] or not out.flags["WRITEABLE"]:
            raise ValueError("out must be C-contiguous and writeable")
        if out.nbytes != expected_nbytes:
            raise ValueError(
                f"out has {out.nbytes} bytes, codestream decodes to "
                f"{expected_nbytes} bytes (shape {shape})"
            )

    err_buf = ctypes.create_string_buffer(1024)
    ret = _lib.openjph_decode(
        cs,
        ctypes.c_size_t(len(cs)),
        out.ctypes.data_as(ctypes.c_void_p),
        ctypes.c_size_t(out.nbytes),
        err_buf,
        ctypes.c_size_t(1024),
    )
    if ret != _OPENJPH_OK:
        raise RuntimeError(f"openjph_decode: {err_buf.value.decode(errors='replace')}")

    return out


# ---- self-test ----


# ctypes resolves symbols by name only and never checks the real signature, so
# a library built from the wrong C release would corrupt memory silently. A
# tiny round-trip at import time turns that into an immediate, clear error.
def _self_test() -> None:
    probe = np.array([[0, 1], [2, 3]], dtype=np.uint8)
    try:
        result = decode(encode(probe))
    except Exception as e:
        raise ImportError(
            "openjph self-test failed: libopenjph_c does not match this "
            "package's expected C ABI"
        ) from e
    if not np.array_equal(result, probe):
        raise ImportError(
            "openjph self-test produced incorrect output: libopenjph_c does "
            "not match this package's expected C ABI"
        )


_self_test()
