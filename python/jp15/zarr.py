import warnings
from .codecs.zarr import *  # noqa: F403

# TODO: backwards compat (juli 2026); remove this file after a while
warnings.warn(
    "jp15.zarr has moved to jp15.codecs.zarr - jp15.zarr still works but will be removed in a future version"
)
