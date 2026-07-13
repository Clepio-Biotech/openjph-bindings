#pragma once
#include <stddef.h>
#include <stdint.h>

/* Return codes shared by openjph_get_info and openjph_decode. */
#define OPENJPH_OK 0
#define OPENJPH_ERR (-1)

/* Input array descriptor for openjph_encode.
   bit_depth and is_signed match OpenJPH's native (bit_depth, is_signed) pair
   from SIZ marker parameters — no intermediate dtype enum. */
typedef struct {
  const void *data;
  size_t ndim;        /* 2 or 3 */
  size_t dims[3];     /* (H,W) or (C,H,W); unused dims set to 0 */
  uint32_t bit_depth; /* 8, 16, or 32 */
  int32_t is_signed;  /* 0 = unsigned, 1 = signed */
} openjph_array_t;

typedef struct {
  int irreversible; /* 0 = lossless, 1 = lossy */
  float qstep;      /* quantization step, valid only when use_qstep=1 */
  int use_qstep;
  int num_decompositions;
  int block_width;
  int block_height;
  char progression_order[8]; /* e.g. "LRCP\0" */
  int color_transform;
  int planar;
} openjph_encode_params_t;

#if defined(_MSC_VER)
#ifdef OPENJPH_C_EXPORTS
#define OPENJPH_API __declspec(dllexport)
#else
#define OPENJPH_API __declspec(dllimport)
#endif
#elif defined(__GNUC__) || defined(__clang__)
#define OPENJPH_API __attribute__((visibility("default")))
#else
#define OPENJPH_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

/* Encode an array to an HTJ2K codestream.
   On success returns 0, sets *out and *out_len. Caller must free *out with
   openjph_free(). On failure returns -1, writes a null-terminated message into
   err_buf. err_buf must be non-NULL and err_buf_len > 0. */
OPENJPH_API int openjph_encode(const openjph_array_t *img,
                               const openjph_encode_params_t *params,
                               uint8_t **out, size_t *out_len, char *err_buf,
                               size_t err_buf_len);

/* Read shape and element type from the codestream SIZ marker without
   decoding, for sizing the out_buf passed to openjph_decode.
   Sets *out_ndim, out_dims, *out_bit_depth, *out_is_signed. A 1-component
   codestream reports ndim == 2: the SIZ marker cannot express a leading
   singleton axis, so (1,H,W) and (H,W) encode identically — callers that
   know the intended shape are the source of truth.
   Returns OPENJPH_OK, or OPENJPH_ERR with a message in err_buf. */
OPENJPH_API int openjph_get_info(const uint8_t *codestream,
                                 size_t codestream_len, size_t *out_ndim,
                                 size_t out_dims[3], uint32_t *out_bit_depth,
                                 int32_t *out_is_signed, char *err_buf,
                                 size_t err_buf_len);

/* Decode an HTJ2K codestream into the caller-allocated out_buf.
   out_buf_len must EXACTLY equal components * height * width *
   bytes_per_sample as reported by openjph_get_info, where bytes_per_sample
   is 1 for bit_depth <= 8, 2 for <= 16, and 4 otherwise; any mismatch is an
   error (the expected size is reported in err_buf). Pixels are written
   row-major as (H,W) or (C,H,W).
   Returns OPENJPH_OK, or OPENJPH_ERR with a message in err_buf. out_buf
   contents are unspecified on failure. */
OPENJPH_API int openjph_decode(const uint8_t *codestream, size_t codestream_len,
                               void *out_buf, size_t out_buf_len, char *err_buf,
                               size_t err_buf_len);

/* Free a buffer returned by openjph_encode. */
OPENJPH_API void openjph_free(void *ptr);

#ifdef __cplusplus
}
#endif
