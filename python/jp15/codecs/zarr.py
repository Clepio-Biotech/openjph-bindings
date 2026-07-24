from __future__ import annotations

import asyncio
import importlib
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol, cast

import numpy as np

from zarr.abc.codec import ArrayBytesCodec
from zarr.core.common import JSON, parse_named_configuration

from jp15.codecs.common import (
    normalize_config,
    validate_config,
    resolve_config,
    pre_encode_reshape,
    post_decode_reshape,
)

if TYPE_CHECKING:
    from typing import Self

    from zarr.core.array_spec import ArraySpec
    from zarr.core.buffer import Buffer, NDBuffer
    from zarr.core.chunk_grids import ChunkGrid
    from zarr.core.dtype.wrapper import TBaseDType, TBaseScalar, ZDType

    from jp15.codecs.common import (
        Layout,
        ProgressionOrder,
    )

_BACKEND_MODULE_NAME = "jp15._backend"


class OpenJPHCodecUnavailableError(RuntimeError):
    pass


class _OpenJPHBackend(Protocol):
    def encode(
        self,
        array: np.ndarray,
        *,
        irreversible: bool,
        qstep: float | None,
        num_decompositions: int,
        block_size: tuple[int, int],
        progression_order: str,
        color_transform: bool,
        planar: bool,
    ) -> bytes: ...

    def decode(self, data: bytes) -> np.ndarray: ...


_backend_cache: _OpenJPHBackend | None = None
_backend_attempted = False


def _get_backend() -> _OpenJPHBackend:
    global _backend_cache, _backend_attempted

    if _backend_cache is not None:
        return _backend_cache

    if not _backend_attempted:
        _backend_attempted = True
        try:
            module = importlib.import_module(_BACKEND_MODULE_NAME)
        except ImportError:
            module = None
        if module is not None:
            _backend_cache = cast("_OpenJPHBackend", module)
            return _backend_cache

    raise OpenJPHCodecUnavailableError(
        "OpenJPHCodec requires the native jp15._backend module."
    )


@dataclass(frozen=True)
class OpenJPHCodec(ArrayBytesCodec):
    is_fixed_size = False

    layout: Layout | None
    irreversible: bool | None
    qstep: float | None
    num_decompositions: int | None
    block_size: tuple[int, int]
    progression_order: str
    color_transform: bool | None
    planar: bool | None

    def __init__(
        self,
        *,
        layout: Layout | str | None = None,
        irreversible: bool | None = None,
        qstep: float | None = None,
        num_decompositions: int | None = None,
        block_size: tuple[int, int] = (64, 64),
        progression_order: ProgressionOrder | str = "LRCP",
        color_transform: bool | None = None,
        planar: bool | None = None,
    ) -> None:
        config = normalize_config(
            layout,
            irreversible,
            qstep,
            num_decompositions,
            block_size,
            progression_order,
            color_transform,
            planar,
        )
        for key, val in config.items():
            object.__setattr__(self, key, val)

    @classmethod
    def from_dict(cls, data: dict[str, JSON]) -> Self:
        _, configuration_parsed = parse_named_configuration(
            data, "openjph_htj2k", require_configuration=False
        )
        configuration_parsed = configuration_parsed or {}
        if "block_size" in configuration_parsed:
            block_size = configuration_parsed["block_size"]
            if isinstance(block_size, list):
                configuration_parsed["block_size"] = tuple(block_size)
        return cls(**configuration_parsed)  # type: ignore[arg-type]

    def _to_normalized_config(self):
        return dict(
            layout=self.layout,
            irreversible=self.irreversible,
            qstep=self.qstep,
            num_decompositions=self.num_decompositions,
            block_size=self.block_size,
            progression_order=self.progression_order,
            color_transform=self.color_transform,
            planar=self.planar,
        )

    def to_dict(self) -> dict[str, JSON]:
        conf: dict[str, JSON] = {
            "block_size": [self.block_size[0], self.block_size[1]],
            "progression_order": self.progression_order,
        }
        if self.layout is not None:
            conf["layout"] = self.layout
        if self.irreversible is not None:
            conf["irreversible"] = self.irreversible
        if self.qstep is not None:
            conf["qstep"] = self.qstep
        if self.num_decompositions is not None:
            conf["num_decompositions"] = self.num_decompositions
        if self.color_transform is not None:
            conf["color_transform"] = self.color_transform
        if self.planar is not None:
            conf["planar"] = self.planar
        return {"name": "openjph_htj2k", "configuration": conf}

    def evolve_from_array_spec(self, array_spec: ArraySpec) -> Self:
        cur_config = self._to_normalized_config()
        new_config = resolve_config(cur_config, array_spec.shape)
        if new_config == cur_config:
            return self
        else:
            return replace(self, **new_config)

    def validate(
        self,
        *,
        shape: tuple[int, ...],
        dtype: ZDType[TBaseDType, TBaseScalar],
        chunk_grid: ChunkGrid,
    ) -> None:
        validate_config(self._to_normalized_config(), shape, dtype)

    async def _encode_single(
        self,
        chunk_array: NDBuffer,
        chunk_spec: ArraySpec,
    ) -> Buffer | None:
        effective = self.evolve_from_array_spec(chunk_spec)
        layout = cast("Layout", effective.layout)
        backend = _get_backend()

        data = chunk_array.as_numpy_array()
        native_dtype = chunk_spec.dtype.to_native_dtype()
        if data.dtype != native_dtype:
            data = data.astype(native_dtype, copy=False)
        normalized = pre_encode_reshape(data, layout)

        encoded = await asyncio.to_thread(
            backend.encode,
            normalized,
            irreversible=cast("bool", effective.irreversible),
            qstep=effective.qstep,
            num_decompositions=cast("int", effective.num_decompositions),
            block_size=effective.block_size,
            progression_order=effective.progression_order,
            color_transform=cast("bool", effective.color_transform),
            planar=cast("bool", effective.planar),
        )
        return chunk_spec.prototype.buffer.from_bytes(encoded)

    async def _decode_single(
        self,
        chunk_bytes: Buffer,
        chunk_spec: ArraySpec,
    ) -> NDBuffer:
        effective = self.evolve_from_array_spec(chunk_spec)
        layout = cast("Layout", effective.layout)
        backend = _get_backend()

        native_dtype = chunk_spec.dtype.to_native_dtype()
        decoded = await asyncio.to_thread(
            backend.decode,
            chunk_bytes.to_bytes(),
        )
        arr = np.asarray(decoded)
        arr = post_decode_reshape(arr, layout, chunk_spec.shape, native_dtype)
        return chunk_spec.prototype.nd_buffer.from_ndarray_like(arr)

    def compute_encoded_size(
        self,
        _input_byte_length: int,
        _chunk_spec: ArraySpec,
    ) -> int:
        # HTJ2K output is variable-length, so the encoded size is not known ahead
        # of time. Raising NotImplementedError is the documented contract for a
        # variable-length codec (cf. zarr's built-in vlen codecs) and is never
        # called on the normal read/write path. The codec works fine as a chunk
        # data codec, including inside a shard; it simply cannot serve as a shard
        # *index* codec (which must be fixed-size).
        raise NotImplementedError("OpenJPH produces variable-length codestreams")
