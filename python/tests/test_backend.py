from __future__ import annotations

import importlib

import numpy as np
import pytest

openjph_backend = pytest.importorskip("openjph._backend")

RNG = np.random.default_rng(123)


def _make_uint16(shape: tuple[int, ...]) -> np.ndarray:
    return RNG.integers(0, 60_000, size=shape, dtype=np.uint16)


def test_backend_module_importable() -> None:
    mod = importlib.import_module("openjph._backend")
    assert hasattr(mod, "encode")
    assert hasattr(mod, "decode")


def test_public_api_importable() -> None:
    import openjph

    from openjph import _backend

    assert openjph.encode is _backend.encode
    assert openjph.decode is _backend.decode


def test_roundtrip_2d() -> None:
    data = _make_uint16((32, 48))

    encoded = openjph_backend.encode(
        data,
        irreversible=False,
        qstep=None,
        num_decompositions=5,
        block_size=(64, 64),
        progression_order="CPRL",
        color_transform=False,
        planar=True,
    )
    decoded = openjph_backend.decode(encoded)

    np.testing.assert_array_equal(decoded, data)


def test_roundtrip_3d() -> None:
    data = _make_uint16((4, 24, 32))

    encoded = openjph_backend.encode(
        data,
        irreversible=False,
        qstep=None,
        num_decompositions=5,
        block_size=(64, 64),
        progression_order="CPRL",
        color_transform=False,
        planar=True,
    )
    decoded = openjph_backend.decode(encoded)

    np.testing.assert_array_equal(decoded, data)


def test_irreversible_uint16_roundtrip() -> None:
    data = _make_uint16((32, 48))

    encoded = openjph_backend.encode(
        data,
        irreversible=True,
        qstep=0.01,
        num_decompositions=5,
        block_size=(64, 64),
        progression_order="CPRL",
        color_transform=False,
        planar=True,
    )
    decoded = openjph_backend.decode(encoded)

    assert decoded.shape == data.shape
    assert decoded.dtype == np.uint16
    assert not np.array_equal(decoded, data)
    diff = np.abs(decoded.astype(np.int64) - data.astype(np.int64))
    assert diff.mean() < 250
    assert diff.max() < 1000
