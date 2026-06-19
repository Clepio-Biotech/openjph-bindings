# pyopenjph

Python bindings for OpenJPH HTJ2K encode/decode, with an optional Zarr v3 codec.

```python
import openjph

encoded = openjph.encode(
    array,
    irreversible=False,
    qstep=None,
    num_decompositions=5,
    block_size=(64, 64),
    progression_order="CPRL",
    color_transform=False,
    planar=True,
)
decoded = openjph.decode(encoded, shape=array.shape, dtype=array.dtype.name)
```

## Zarr

Install Zarr support with:

```bash
pip install "pyopenjph[zarr]"
```

`OpenJPHCodec` is a Zarr v3 array-to-bytes codec, so it is passed in the array's `codecs` pipeline.

```python
from openjph.zarr import OpenJPHCodec

import numpy as np
import zarr

data = np.arange(64 * 96, dtype=np.uint16).reshape(64, 96)

array = zarr.create(
    store="example.zarr",
    shape=data.shape,
    chunks=data.shape,
    dtype=data.dtype,
    codecs=[OpenJPHCodec(layout="yx")],
    zarr_format=3,
)

array[:] = data
roundtrip = array[:]

np.testing.assert_array_equal(roundtrip, data)
```
