"""
Test the simplezarr codec.
"""

from __future__ import annotations

import io

import numpy as np
import simplezarr
import pytest

from jp15.codecs import simplezarr as jp15_zarr
from jp15.codecs.simplezarr import OpenJPHSimplezarrCodec

RNG = np.random.default_rng(42)


class _FakeOpenJPHBackend:
    def encode(self, array: np.ndarray, **config: object) -> bytes:
        del config
        buf = io.BytesIO()
        np.save(buf, np.asarray(array), allow_pickle=False)
        return buf.getvalue()

    def decode(self, data: bytes) -> np.ndarray:
        return np.load(io.BytesIO(data), allow_pickle=False)


def _make_uint16(shape: tuple[int, ...]) -> np.ndarray:
    return RNG.integers(0, 60_000, size=shape, dtype=np.uint16)


def test_defaults() -> None:
    codec = OpenJPHSimplezarrCodec()
    assert codec._normalized_config["irreversible"] is None
    assert codec._normalized_config["qstep"] is None
    assert codec._normalized_config["num_decompositions"] is None
    assert codec._normalized_config["block_size"] == (64, 64)
    assert codec._normalized_config["progression_order"] == "LRCP"
    assert codec._normalized_config["color_transform"] is None
    assert codec._normalized_config["planar"] is None


def test_roundtrip_2d(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr(jp15_zarr, "backend", _FakeOpenJPHBackend())

    shape = (64, 96)
    data = _make_uint16(shape)
    codec = codec = dict(
        name="openjph_htj2k",
        configuration=dict(layout="yx"),
    )

    store = simplezarr.LocalStore(tmp_path / "test_2d.zarr")
    arr = simplezarr.ZarrArray.create(
        store, "", shape=shape, dtype=data.dtype, chunk_shape=shape, codecs=[codec]
    )
    arr[...].set_now(data)
    result = arr[...].get_now()

    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)


def test_roundtrip_channel_last(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr(jp15_zarr, "backend", _FakeOpenJPHBackend())

    shape = (24, 40, 3)
    data = _make_uint16(shape)

    codec = codec = dict(
        name="openjph_htj2k",
        configuration=dict(layout="yxc", color_transform=True, planar=False),
    )

    store = simplezarr.LocalStore(tmp_path / "test_yxc.zarr")
    arr = simplezarr.ZarrArray.create(
        store, "", shape=shape, dtype=data.dtype, chunk_shape=shape, codecs=[codec]
    )
    arr[...].set_now(data)
    result = arr[...].get_now()

    assert result.shape == shape
    np.testing.assert_array_equal(result, data)


def test_rejects_float64(tmp_path) -> None:

    codec = dict(
        name="openjph_htj2k",
        configuration=dict(layout="yx"),
    )

    store = simplezarr.LocalStore(tmp_path / "bad_dtype.zarr")
    arr = simplezarr.ZarrArray.create(
        store,
        "",
        shape=(32, 32),
        dtype="float64",
        chunk_shape=(32, 32),
        codecs=[codec],
    )

    # Simplezarr only creates the codec when it's time to encode/decode
    with pytest.raises(ValueError, match="uint8, uint16, and int16"):
        arr[...].set_now(32)


def test_rejects_bad_progression_order() -> None:
    with pytest.raises(ValueError, match="progression order"):
        OpenJPHSimplezarrCodec(progression_order="NOPE")


# ---- real-backend integration (skipped if the native library isn't built) ----


@pytest.mark.parametrize(
    "layout,shape",
    [
        ("yx", (64, 96)),
        ("zyx", (4, 32, 48)),
        ("cyx", (3, 32, 48)),
        ("yxc", (32, 48, 3)),
        # Singleton component axes: 1-component codestreams whose SIZ marker is
        # indistinguishable from 2-D — the codec must restore the singleton axis.
        ("zyx", (1, 32, 48)),
        ("cyx", (1, 32, 48)),
        ("yxc", (32, 48, 1)),
    ],
)
def test_real_backend_roundtrip(tmp_path, layout, shape) -> None:

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
    result = arr[...].get_now()

    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)


def test_real_backend_singleton_chunks(tmp_path) -> None:
    # The PR #3 bug shape: a non-singleton array stored with chunks whose
    # component axis is 1, so every chunk encodes to a 1-component codestream
    # that decodes 2-D and previously failed the codec shape check at read time.

    shape = (4, 64, 96)
    data = _make_uint16(shape)

    codec = codec = dict(
        name="openjph_htj2k",
        configuration=dict(layout="zyx"),
    )

    store = simplezarr.LocalStore(tmp_path / "real_singleton_chunks.zarr")
    arr = simplezarr.ZarrArray.create(
        store, "", shape=shape, dtype="uint16", chunk_shape=(1, 64, 96), codecs=[codec]
    )
    arr[...].set_now(data)
    result = arr[...].get_now()

    assert result.shape == shape
    np.testing.assert_array_equal(result, data)


def test_real_backend_lossy(tmp_path) -> None:

    shape = (64, 96)
    data = _make_uint16(shape)

    codec = codec = dict(
        name="openjph_htj2k",
        configuration=dict(layout="yx", irreversible=True, qstep=0.01),
    )

    store = simplezarr.LocalStore(tmp_path / "real_lossy.zarr")
    arr = simplezarr.ZarrArray.create(
        store, "", shape=shape, dtype="uint16", chunk_shape=shape, codecs=[codec]
    )
    arr[...].set_now(data)
    result = arr[...].get_now()

    assert result.shape == shape
    assert result.dtype == np.uint16
    diff = np.abs(result.astype(np.int64) - data.astype(np.int64))
    assert diff.mean() < 250
