/* Correctness exercise for the public C API across the full (bit_depth,
 * is_signed) x shape matrix that openjph_get_info/openjph_decode must
 * support. leak_check.c covers error paths and memory ownership under
 * LeakSanitizer with a single representative type; this file covers
 * everything decode_into's dispatch and get_info's SIZ reporting can
 * produce, plain (no sanitizer needed, though it's harmless to run under
 * one too).
 *
 * Test data is generated and compared at the byte level rather than through
 * a typed pointer: lossless (irreversible=0) encode/decode must preserve the
 * sample bytes exactly regardless of how bit_depth/is_signed says to
 * interpret them, so one generic byte-pattern round-trip validates every
 * (bit_depth, is_signed) combination without needing a separate typed
 * function per case.
 */

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "openjph_c.h"

#define CHECK(cond)                                                            \
  do {                                                                         \
    if (!(cond)) {                                                             \
      fprintf(stderr, "FAILED at %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
      exit(1);                                                                 \
    }                                                                          \
  } while (0)

static openjph_encode_params_t default_params(void) {
  openjph_encode_params_t p;
  memset(&p, 0, sizeof(p));
  p.irreversible = 0;
  p.qstep = 0.0f;
  p.use_qstep = 0;
  p.num_decompositions = 5;
  p.block_width = 64;
  p.block_height = 64;
  memcpy(p.progression_order, "LRCP", 5);
  p.color_transform = 0;
  p.planar = 1;
  return p;
}

static size_t bytes_per_sample_for(uint32_t bit_depth) {
  return (bit_depth <= 8) ? 1u : (bit_depth <= 16) ? 2u : 4u;
}

/* Deterministic, non-repeating-per-byte-lane fill: cheap decorrelation so
   multi-byte samples exercise real bit patterns, not just a single repeated
   byte value. Content has no semantic meaning — only exact preservation
   through lossless encode/decode is being checked. */
static uint8_t *make_gradient_bytes(size_t n_bytes) {
  uint8_t *data = (uint8_t *)malloc(n_bytes);
  CHECK(data != NULL || n_bytes == 0);
  for (size_t i = 0; i < n_bytes; ++i)
    data[i] = (uint8_t)((i * 2654435761u) >> 24);
  return data;
}

static openjph_array_t make_array(const void *data, size_t ndim, size_t d0,
                                  size_t d1, size_t d2, uint32_t bit_depth,
                                  int32_t is_signed) {
  openjph_array_t a;
  memset(&a, 0, sizeof(a));
  a.data = data;
  a.ndim = ndim;
  a.dims[0] = d0;
  a.dims[1] = d1;
  a.dims[2] = d2;
  a.bit_depth = bit_depth;
  a.is_signed = is_signed;
  return a;
}

/* Encode img (old C-allocated-buffer ABI), probe with get_info (checking it
   reports back exactly what was encoded), decode into an exactly-sized
   caller buffer, and verify the decoded bytes exactly match the input. */
static void roundtrip(const openjph_array_t *img) {
  openjph_encode_params_t params = default_params();
  char err[1024];

  uint8_t *cs = NULL;
  size_t cs_len = 0;
  CHECK(openjph_encode(img, &params, &cs, &cs_len, err, sizeof(err)) == 0);
  CHECK(cs != NULL && cs_len > 0);

  size_t ndim = 0, dims[3] = {0, 0, 0};
  uint32_t bd = 0;
  int32_t sgn = 0;
  CHECK(openjph_get_info(cs, cs_len, &ndim, dims, &bd, &sgn, err,
                         sizeof(err)) == OPENJPH_OK);
  CHECK(bd == img->bit_depth && sgn == img->is_signed);

  size_t comp = (img->ndim == 3) ? img->dims[0] : 1;
  size_t h = (img->ndim == 3) ? img->dims[1] : img->dims[0];
  size_t w = (img->ndim == 3) ? img->dims[2] : img->dims[1];
  size_t total = comp * h * w;
  /* A 1-component codestream reports 2-D: the SIZ marker cannot express a
     leading singleton axis. */
  if (comp == 1) {
    CHECK(ndim == 2 && dims[0] == h && dims[1] == w);
  } else {
    CHECK(ndim == 3 && dims[0] == comp && dims[1] == h && dims[2] == w);
  }

  size_t bytes_per_sample = bytes_per_sample_for(img->bit_depth);
  size_t total_bytes = total * bytes_per_sample;
  uint8_t *out = (uint8_t *)malloc(total_bytes);
  CHECK(out != NULL);
  CHECK(openjph_decode(cs, cs_len, out, total_bytes, err, sizeof(err)) ==
        OPENJPH_OK);

  CHECK(memcmp(out, img->data, total_bytes) == 0);

  free(out);
  openjph_free(cs);
}

int main(void) {
  static const uint32_t bit_depths[] = {8, 16, 32};
  static const int32_t signedness[] = {0, 1};
  static const size_t shapes[][4] = {
      /* ndim, d0, d1, d2 */
      {2, 64, 96, 0}, /* 2-D */
      {3, 3, 32, 48}, /* 3-D multi-component */
      {3, 1, 32, 48}, /* 3-D singleton component */
  };

  for (size_t bd_i = 0; bd_i < sizeof(bit_depths) / sizeof(bit_depths[0]);
       ++bd_i) {
    for (size_t sg_i = 0; sg_i < sizeof(signedness) / sizeof(signedness[0]);
         ++sg_i) {
      uint32_t bit_depth = bit_depths[bd_i];
      int32_t is_signed = signedness[sg_i];
      size_t bytes_per_sample = bytes_per_sample_for(bit_depth);

      for (size_t s = 0; s < sizeof(shapes) / sizeof(shapes[0]); ++s) {
        size_t ndim = shapes[s][0];
        size_t d0 = shapes[s][1], d1 = shapes[s][2], d2 = shapes[s][3];
        size_t total = (ndim == 2) ? d0 * d1 : d0 * d1 * d2;

        uint8_t *data = make_gradient_bytes(total * bytes_per_sample);
        openjph_array_t img =
            make_array(data, ndim, d0, d1, d2, bit_depth, is_signed);
        roundtrip(&img);
        free(data);
      }
    }
  }

  printf("roundtrip_test: all %zu (bit_depth, is_signed) x shape "
         "combinations passed\n",
         (sizeof(bit_depths) / sizeof(bit_depths[0])) *
             (sizeof(signedness) / sizeof(signedness[0])) *
             (sizeof(shapes) / sizeof(shapes[0])));
  return 0;
}
