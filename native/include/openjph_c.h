#pragma once
#include <stddef.h>
#include <stdint.h>

/* All buffers cross this API in one direction only: the caller allocates,
   the library fills. No function allocates memory the caller must free, so
   there is no openjph_free and no allocator coupling between the library and
   its callers. */

/* Return codes shared by all functions returning int. */
#define OPENJPH_OK 0
#define OPENJPH_ERR (-1)
#define OPENJPH_ERR_BUFFER_TOO_SMALL (-2)

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

/* Conservative upper bound on the encoded size of img, for sizing the
   out_buf passed to openjph_encode. OpenJPH provides no exact bound, so this
   is a generous estimate; correctness does not depend on it because
   openjph_encode reports the required size when the buffer is too small.
   Returns 0 if img is invalid (ndim not 2/3, zero dimension, bit_depth
   outside [1, 32]) or the size computation would overflow. */
OPENJPH_API size_t openjph_encode_bound(const openjph_array_t *img);

/* Encode an array to an HTJ2K codestream, writing it at the start of the
   caller-allocated out_buf.
   Returns OPENJPH_OK and sets *used_bytes to the codestream length;
   OPENJPH_ERR_BUFFER_TOO_SMALL if out_buf_len is insufficient, with
   *used_bytes set to the required size so the caller can retry once;
   OPENJPH_ERR on any other failure, with a null-terminated message in
   err_buf. err_buf must be non-NULL and err_buf_len > 0. out_buf contents
   are unspecified on failure. */
OPENJPH_API int openjph_encode(const openjph_array_t *img,
                               const openjph_encode_params_t *params,
                               uint8_t *out_buf, size_t out_buf_len,
                               size_t *used_bytes, char *err_buf,
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

#ifdef __cplusplus
}
#endif
