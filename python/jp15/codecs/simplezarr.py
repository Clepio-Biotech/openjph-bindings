import numpy as np
import simplezarr

from jp15.codecs.common import (
    normalize_config,
    validate_config,
    resolve_config,
    pre_encode_reshape,
    post_decode_reshape,
)
from jp15 import _backend as backend


class OpenJPHSimplezarrCodec(simplezarr.codecs.BaseCodec):
    """OpenJPH codec for simplezarr."""

    name = "openjph_htj2k"
    kind = "a->b"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._normalized_config = normalize_config(self.configuration)

    def encode(self, value: np.ndarray) -> memoryview:
        validate_config(self._normalized_config, value.shape, value.dtype)
        resolved_config = resolve_config(self._normalized_config, value.shape)

        normalized_array = pre_encode_reshape(value, resolved_config["layout"])

        result = backend.encode(normalized_array, **resolved_config)
        return memoryview(result)

    def decode(
        self, value: memoryview, decoded_representation_type: type
    ) -> memoryview:
        assert issubclass(decoded_representation_type, np.ndarray)
        result_shape = decoded_representation_type.shape
        result_dtype = decoded_representation_type.dtype

        validate_config(self._normalized_config, result_shape, result_dtype)
        resolved_config = resolve_config(self._normalized_config, value.shape)
        layout = resolved_config["layout"]

        decoded = backend.decode(value)

        arr = np.asarray(decoded)
        arr = post_decode_reshape(arr, layout, result_shape, result_dtype)

        return arr
