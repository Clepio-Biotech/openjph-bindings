"""
Test combining the zarr and simplezarr codecs.
"""

import json

import numpy as np
import pytest
import simplezarr
import zarr

from jp15.codecs.zarr import OpenJPHCodec

RNG = np.random.default_rng(42)


def _make_uint16(shape: tuple[int, ...]) -> np.ndarray:
    return RNG.integers(0, 60_000, size=shape, dtype=np.uint16)


layout_shape_list = [
    ("yx", (64, 96)),
    ("zyx", (4, 32, 48)),
    ("cyx", (3, 32, 48)),
    ("yxc", (32, 48, 3)),
    # Singleton component axes: 1-component codestreams whose SIZ marker is
    # indistinguishable from 2-D — the codec must restore the singleton axis.
    ("zyx", (1, 32, 48)),
    ("cyx", (1, 32, 48)),
    ("yxc", (32, 48, 1)),
]


@pytest.mark.parametrize("layout,shape", layout_shape_list)
def test_roundtrip_zarrpy_to_simplezarr(tmp_path, layout, shape) -> None:

    path = tmp_path / f"real_{layout}.zarr"
    data = _make_uint16(shape)

    # Write
    arr = zarr.create(
        store=str(path),
        shape=shape,
        chunks=shape,
        dtype="uint16",
        codecs=[OpenJPHCodec(layout=layout)],
    )
    arr[:] = data

    # Read
    arr = simplezarr.open_zarr(simplezarr.LocalStore(path))
    result = arr[...].get_now()

    # Check
    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)


@pytest.mark.parametrize("layout,shape", layout_shape_list)
def test_roundtrip_simplezarr_to_zarrpy(tmp_path, layout, shape) -> None:

    path = tmp_path / f"real_{layout}.zarr"
    data = _make_uint16(shape)

    # Write
    codec = dict(
        name="openjph_htj2k",
        configuration=dict(layout=layout),
    )
    store = simplezarr.LocalStore(path)
    arr = simplezarr.ZarrArray.create(
        store, "", shape=shape, dtype="uint16", chunk_shape=shape, codecs=[codec]
    )
    arr[...].set_now(data)

    # Read
    arr = zarr.open(store=str(path))
    result = arr[:]

    # Checlk
    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)


# Simple shapes that can be resolved without the help of layout or planar
shape_list_simple = [
    (64, 96),
    (4, 32, 48),
    (3, 32, 48),
]


@pytest.mark.parametrize("shape", shape_list_simple)
def test_noconfig_roundtrip_zarrpy_to_simplezarr(tmp_path, shape) -> None:

    shape_str = "x".join(str(i) for i in shape)
    path = tmp_path / f"real_{shape_str}.zarr"
    data = _make_uint16(shape)

    # Write
    arr = zarr.create(
        store=str(path),
        shape=shape,
        chunks=shape,
        dtype="uint16",
        codecs=[OpenJPHCodec()],
    )
    arr[:] = data

    # Clear codec config
    json_path = path / "zarr.json"
    with open(json_path, "rb") as f:
        d = json.loads(f.read().decode())
    d["codecs"][0]["configuration"].clear()
    with open(json_path, "wb") as f:
        d = f.write(json.dumps(d).encode())

    # Read
    arr = simplezarr.open_zarr(simplezarr.LocalStore(path))
    result = arr[...].get_now()

    # Check
    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)


@pytest.mark.parametrize("shape", shape_list_simple)
def test_noconfig_roundtrip_simplezarr_to_zarrpy(tmp_path, shape) -> None:

    shape_str = "x".join(str(i) for i in shape)
    path = tmp_path / f"real_{shape_str}.zarr"
    data = _make_uint16(shape)

    # Write
    codec = dict(
        name="openjph_htj2k",
        configuration=dict(),
    )
    store = simplezarr.LocalStore(path)
    arr = simplezarr.ZarrArray.create(
        store, "", shape=shape, dtype="uint16", chunk_shape=shape, codecs=[codec]
    )
    arr[...].set_now(data)

    # Clear codec config
    json_path = path / "zarr.json"
    with open(json_path, "rb") as f:
        d = json.loads(f.read().decode())
    d["codecs"][0]["configuration"].clear()
    with open(json_path, "wb") as f:
        d = f.write(json.dumps(d).encode())

    # Read
    arr = zarr.open(store=str(path))
    result = arr[:]

    # Check
    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)
