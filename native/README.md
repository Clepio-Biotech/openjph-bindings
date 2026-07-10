# native

A thin C ABI wrapper around [OpenJPH](https://github.com/aous72/OpenJPH), producing
a self-contained shared library (`libopenjph_c.so`) that both the Python and Julia
packages depend on.

OpenJPH is embedded statically into the shared library at build time via
`--whole-archive`, so there is no runtime dependency on a separate OpenJPH installation.

## Build

```bash
cmake -B build . -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
# Produces: build/libopenjph_c.so
```

Requires cmake ≥ 3.24 (for `LINK_LIBRARY:WHOLE_ARCHIVE`). CMake downloads OpenJPH automatically
via FetchContent — no prior installation needed.

## API

All buffers cross the API in one direction: the caller allocates, the library
fills. No function returns memory the caller must free, so there is no
`openjph_free` and no allocator coupling between the library and its callers.

Four exported symbols:

- `openjph_encode_bound` — conservative upper bound on the encoded size of an
  array, for sizing the encode output buffer; returns 0 on an invalid
  descriptor
- `openjph_encode` — compress an array to an HTJ2K codestream, written at the
  start of the caller's buffer; returns the used byte count, or
  `OPENJPH_ERR_BUFFER_TOO_SMALL` with the exact required size so the caller
  can retry once (the bound is an estimate, not a guarantee)
- `openjph_get_info` — read element type and shape from the codestream SIZ
  marker without decoding, for sizing the decode output buffer; a 1-component
  codestream reports 2-D (the SIZ marker cannot express a singleton component
  axis — callers that know the intended shape are the source of truth)
- `openjph_decode` — decompress a codestream into the caller's buffer, whose
  byte length must exactly equal the SIZ-derived size

All functions returning `int` use the shared return codes `OPENJPH_OK` (0),
`OPENJPH_ERR` (-1, message in `err_buf`), and `OPENJPH_ERR_BUFFER_TOO_SMALL`
(-2, encode only). Error messages carry OpenJPH's detailed diagnostics
(message, source location); nothing is printed to the console.

See `include/openjph_c.h` for the full C interface.

## Tests

`tests/leak_check.c` exercises round-trips and every error path, built with
AddressSanitizer in CI (`OPENJPH_C_BUILD_TESTS=ON`); a clean LeakSanitizer run
proves no allocation crosses the FFI in either direction:

```bash
cmake -B build-asan . -DCMAKE_BUILD_TYPE=Debug -DOPENJPH_C_BUILD_TESTS=ON \
  -DCMAKE_C_FLAGS="-fsanitize=address -g" -DCMAKE_CXX_FLAGS="-fsanitize=address -g" \
  -DCMAKE_EXE_LINKER_FLAGS="-fsanitize=address" -DCMAKE_SHARED_LINKER_FLAGS="-fsanitize=address"
cmake --build build-asan -j
ASAN_OPTIONS=detect_leaks=1 ctest --test-dir build-asan --output-on-failure
```
