from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from openjph._backend import decode, encode, get_info

try:
    __version__ = version("pyopenjph")
except PackageNotFoundError:
    __version__ = "0+unknown"

__all__ = ["decode", "encode", "get_info", "__version__"]
