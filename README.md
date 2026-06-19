# openjph-bindings

Shared bindings around OpenJPH for Python and Julia.

Current layout:

- `native/`: placeholder for a small C ABI used by language wrappers
- `python/`: `pyopenjph`, Python bindings and optional Zarr codec
- `julia/`: placeholder for a Julia wrapper around the native ABI

The Python package can be built from `python/`:

```bash
cd python
python -m pip install -e ".[test,zarr]"
pytest tests
python -m pip wheel . -w /tmp/pyopenjph-wheel --no-deps
```
