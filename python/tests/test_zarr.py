from __future__ import annotations

import io

import numpy as np
import pytest

from openjph.zarr import OpenJPHCodec, OpenJPHCodecUnavailableError

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
    codec = OpenJPHCodec()
    assert codec.layout is None
    assert codec.irreversible is None
    assert codec.qstep is None
    assert codec.num_decompositions is None
    assert codec.block_size == (64, 64)
    assert codec.progression_order == "CPRL"
    assert codec.color_transform is None
    assert codec.planar is None


def test_to_dict_roundtrip() -> None:
    codec = OpenJPHCodec(
        layout="cyx",
        irreversible=True,
        qstep=0.025,
        num_decompositions=4,
        block_size=(32, 64),
        progression_order="LRCP",
        color_transform=True,
        planar=False,
    )
    restored = OpenJPHCodec.from_dict(codec.to_dict())
    assert restored == codec


def test_roundtrip_2d(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zarr

    from openjph import zarr as openjph_zarr

    monkeypatch.setattr(openjph_zarr, "_get_backend", lambda: _FakeOpenJPHBackend())

    shape = (64, 96)
    data = _make_uint16(shape)
    codec = OpenJPHCodec(layout="yx")

    arr = zarr.create(
        store=str(tmp_path / "test_2d.zarr"),
        shape=shape,
        chunks=shape,
        dtype="uint16",
        codecs=[codec],
    )
    arr[:] = data
    result = arr[:]

    assert result.shape == shape
    assert result.dtype == np.uint16
    np.testing.assert_array_equal(result, data)


def test_roundtrip_channel_last(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zarr

    from openjph import zarr as openjph_zarr

    monkeypatch.setattr(openjph_zarr, "_get_backend", lambda: _FakeOpenJPHBackend())

    shape = (24, 40, 3)
    data = _make_uint16(shape)
    codec = OpenJPHCodec(layout="yxc", color_transform=True, planar=False)

    arr = zarr.create(
        store=str(tmp_path / "test_yxc.zarr"),
        shape=shape,
        chunks=shape,
        dtype="uint16",
        codecs=[codec],
    )
    arr[:] = data
    result = arr[:]

    assert result.shape == shape
    np.testing.assert_array_equal(result, data)


def test_backend_missing_raises(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zarr

    from openjph import zarr as openjph_zarr

    def _raise() -> _FakeOpenJPHBackend:
        raise OpenJPHCodecUnavailableError("backend missing")

    monkeypatch.setattr(openjph_zarr, "_get_backend", _raise)

    shape = (16, 16)
    arr = zarr.create(
        store=str(tmp_path / "missing_backend.zarr"),
        shape=shape,
        chunks=shape,
        dtype="uint16",
        codecs=[OpenJPHCodec(layout="yx")],
    )

    with pytest.raises(OpenJPHCodecUnavailableError, match="backend missing"):
        arr[:] = _make_uint16(shape)


def test_rejects_float64(tmp_path) -> None:
    import zarr

    with pytest.raises(ValueError, match="uint8, uint16, and int16"):
        zarr.create(
            store=str(tmp_path / "bad_dtype.zarr"),
            shape=(32, 32),
            chunks=(32, 32),
            dtype="float64",
            codecs=[OpenJPHCodec(layout="yx")],
        )
