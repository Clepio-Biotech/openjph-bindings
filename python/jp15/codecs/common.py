from __future__ import annotations

from typing import Literal, cast

import numpy as np
from jp15._constants import PROGRESSION_ORDERS


Layout = Literal["yx", "zyx", "cyx", "yxc"]
ProgressionOrder = Literal["LRCP", "RLCP", "RPCL", "PCRL", "CPRL"]
_SUPPORTED_PROGRESSIONS = set(PROGRESSION_ORDERS)


def normalize_config(
    layout: Layout | str | None = None,
    irreversible: bool | None = None,
    qstep: float | None = None,
    num_decompositions: int | None = None,
    block_size: tuple[int, int] = (64, 64),
    progression_order: ProgressionOrder | str = "LRCP",
    color_transform: bool | None = None,
    planar: bool | None = None,
) -> dict:
    """Normalize the codec config and produce a dict."""
    # Normalizations
    layout = _normalize_layout(layout)
    block_size = _normalize_xy_pair("block_size", block_size)
    progression_order = _normalize_progression_order(progression_order)

    # Checks
    if qstep is not None and qstep <= 0:
        raise ValueError(f"qstep must be positive, got {qstep}")
    if num_decompositions is not None and num_decompositions < 0:
        raise ValueError(f"num_decompositions must be >= 0, got {num_decompositions}")
    # Fail eagerly for any non-irreversible setting (including the default
    # None, which evolve_from_array_spec resolves to False), so a bare codec
    # object raises at construction rather than only at array-creation time.
    if qstep is not None and irreversible is not True:
        raise ValueError("qstep is only valid for irreversible encoding")

    return {
        "layout": layout,
        "irreversible": irreversible,
        "qstep": qstep,
        "num_decompositions": num_decompositions,
        "block_size": block_size,
        "progression_order": progression_order,
        "color_transform": color_transform,
        "planar": planar,
    }


def validate_config(config, shape: tuple[int, ...], dtype) -> None:
    """Validate codec config for a specific block array."""

    layout = config["layout"] or _default_layout(shape)
    color_transform = config["color_transform"]
    qstep = config["qstep"]
    irreversible = config["irreversible"]

    native = dtype.to_native_dtype()

    if len(shape) not in {2, 3}:
        raise ValueError(
            f"OpenJPHCodec only supports 2-D or 3-D chunks, got shape {shape!r}"
        )
    if any(dim <= 0 for dim in shape):
        raise ValueError(
            f"OpenJPHCodec requires positive chunk dimensions, got {shape!r}"
        )
    if not _supported_native_dtype(native):
        raise ValueError(
            "OpenJPHCodec currently supports uint8, uint16, and int16 only; "
            f"got {native}"
        )

    if layout == "yx" and len(shape) != 2:
        raise ValueError(f"layout='yx' requires 2-D chunks, got shape {shape!r}")
    if layout != "yx" and len(shape) != 3:
        raise ValueError(f"layout={layout!r} requires 3-D chunks, got shape {shape!r}")

    components = _component_count(shape, layout)
    if components < 1:
        raise ValueError(
            f"OpenJPHCodec requires at least one component, got shape {shape!r}"
        )

    if color_transform:
        if layout == "zyx":
            raise ValueError(
                "color_transform=True is not valid for layout='zyx'; "
                "that layout is intended for volumetric stacks, not color components"
            )
        if components != 3:
            raise ValueError(
                f"color_transform=True requires exactly 3 components, got {components}"
            )

    if qstep is not None and irreversible is False:
        raise ValueError("qstep is only valid for irreversible encoding")


def resolve_config(config: dict, shape: tuple[int, ...]) -> dict:
    """Resolve defaults for codec config."""

    new_config = config.copy()

    new_config["layout"] = config["layout"] or _default_layout(shape)
    new_config["irreversible"] = config["irreversible"] or False  # None -> False
    new_config["num_decompositions"] = config["num_decompositions"] or 5
    new_config["color_transform"] = config["color_transform"] or False

    planar = config["planar"]
    if planar is None:
        planar = not new_config["color_transform"]
    new_config["planar"] = planar

    return new_config


def pre_encode_reshape(data: np.ndarray, layout: Layout) -> np.ndarray:
    """If necessarry, reshape array before encoding."""
    if layout == "yxc":
        data = np.moveaxis(data, -1, 0)
    return np.ascontiguousarray(data)


def post_decode_reshape(arr: np.ndarray, layout: Layout, spec_shape, expected_dtype):
    """If necessarry, reshape array after decoding."""
    # A single-component codestream is ambiguous: the SIZ marker cannot
    # distinguish (h, w) from (1, h, w), so the backend returns 2-D and a
    # singleton component axis requested by the chunk spec must be restored
    # here. Only singleton axes are reconciled; any other mismatch still
    # fails the check below.
    expected_shape = _backend_shape(spec_shape, layout)
    if arr.shape != expected_shape and tuple(d for d in arr.shape if d != 1) == tuple(
        d for d in expected_shape if d != 1
    ):
        arr = arr.reshape(expected_shape)
    if layout == "yxc":
        arr = np.moveaxis(arr, 0, -1)
    arr = np.ascontiguousarray(arr)

    if arr.shape != expected_shape:
        raise ValueError(
            "OpenJPH backend returned an unexpected shape: "
            f"expected {expected_shape}, got {arr.shape} (layout {layout})"
        )
    # The backend infers dtype from the codestream's SIZ marker, so for a
    # validated array this astype is a no-op; it only guards against a
    # backend/metadata disagreement (and never silently widens, since the
    # codestream stores the exact bit-depth/signedness it was written with).
    if arr.dtype != expected_dtype:
        arr = arr.astype(expected_dtype, copy=False)
    return arr


# ----------------------------------------


def _normalize_layout(layout: Layout | str | None) -> Layout | None:
    if layout is None:
        return None
    normalized = layout.lower()
    if normalized not in {"yx", "zyx", "cyx", "yxc"}:
        raise ValueError(f"Unsupported OpenJPH layout: {layout!r}")
    return cast("Layout", normalized)


def _normalize_progression_order(name: str) -> str:
    normalized = name.upper()
    if normalized not in _SUPPORTED_PROGRESSIONS:
        raise ValueError(
            f"Unsupported progression order {name!r}; "
            f"expected one of {sorted(_SUPPORTED_PROGRESSIONS)}"
        )
    return normalized


def _normalize_xy_pair(name: str, value: tuple[int, int]) -> tuple[int, int]:
    if len(value) != 2:
        raise ValueError(f"{name} must be a pair of integers, got {value!r}")
    x, y = int(value[0]), int(value[1])
    if x <= 0 or y <= 0:
        raise ValueError(f"{name} values must be positive, got {value!r}")
    return (x, y)


def _default_layout(shape: tuple[int, ...]) -> Layout:
    if len(shape) == 2:
        return "yx"
    if len(shape) == 3:
        return "zyx"
    raise ValueError(
        f"OpenJPHCodec only supports 2-D or 3-D chunks, got shape {shape!r}"
    )


def _component_count(shape: tuple[int, ...], layout: Layout) -> int:
    if layout == "yx":
        return 1
    if layout in {"zyx", "cyx"}:
        return int(shape[0])
    return int(shape[-1])


def _backend_shape(shape: tuple[int, ...], layout: Layout) -> tuple[int, ...]:
    if layout == "yx":
        return shape
    if layout in {"zyx", "cyx"}:
        return shape
    c = shape[-1]
    y, x = shape[0], shape[1]
    return (c, y, x)


def _denormalize_from_backend(data: np.ndarray, layout: Layout) -> np.ndarray:
    if layout == "yxc":
        data = np.moveaxis(data, 0, -1)
    return np.ascontiguousarray(data)


def _supported_native_dtype(native: np.dtype) -> bool:
    # The codec deliberately restricts to uint8/uint16/int16 — the integer types
    # that are well-behaved through HTJ2K for imaging data. The low-level backend
    # additionally accepts int8/uint32/int32, but those are not exposed here.
    if np.issubdtype(native, np.integer):
        return native in {np.dtype("uint8"), np.dtype("uint16"), np.dtype("int16")}
    return False
