"""
Test combining the zarr and simplezarr codecs.
"""

import zarr
import simplezarr
from jp15.codecs.zarr import OpenJPHCodec
import numpy as np
import pytest


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

    data = _make_uint16(shape)

    arr = zarr.create(
        store=str(tmp_path / f"real_{layout}.zarr"),
        shape=shape,
        chunks=shape,
        dtype="uint16",
        codecs=[OpenJPHCodec(layout=layout)],
    )
    arr[:] = data

    arr = simplezarr.open_zarr(simplezarr.LocalStore(tmp_path / f"real_{layout}.zarr"))
    result = arr[...].get_now()

    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)


@pytest.mark.parametrize("layout,shape", layout_shape_list)
def test_roundtrip_simplezarr_to_zarrpy(tmp_path, layout, shape) -> None:

    data = _make_uint16(shape)

    codec = codec = dict(
        name="openjph_htj2k",
        configuration=dict(layout=layout),
    )

    store = simplezarr.LocalStore(tmp_path / f"real_{layout}.zarr")
    arr = simplezarr.ZarrArray.create(
        store, "", shape=shape, dtype="uint16", chunk_shape=shape, codecs=[codec]
    )
    arr[...].set_now(data)

    arr = zarr.open(store=str(tmp_path / f"real_{layout}.zarr"))
    result = arr[:]

    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)
