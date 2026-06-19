#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include "ojph_base.h"
#include "ojph_codestream.h"
#include "ojph_file.h"
#include "ojph_mem.h"
#include "ojph_message.h"
#include "ojph_params.h"

namespace nb = nanobind;

namespace {

enum class SampleType {
  UInt8,
  UInt16,
  Int16,
};

struct ArrayInfo {
  SampleType sample_type;
  size_t ndim;
  size_t components;
  size_t height;
  size_t width;
};

SampleType
parse_array_dtype(const nb::ndarray<nb::numpy, nb::c_contig> &array) {
  auto dtype = array.dtype();
  using nb::dlpack::dtype_code;

  if (dtype.code == static_cast<uint8_t>(dtype_code::UInt) && dtype.bits == 8)
    return SampleType::UInt8;
  if (dtype.code == static_cast<uint8_t>(dtype_code::UInt) && dtype.bits == 16)
    return SampleType::UInt16;
  if (dtype.code == static_cast<uint8_t>(dtype_code::Int) && dtype.bits == 16)
    return SampleType::Int16;

  throw std::runtime_error("OpenJPH backend currently supports uint8, uint16, "
                           "and int16 arrays only");
}

SampleType parse_dtype_name(const std::string &dtype_name) {
  if (dtype_name == "uint8")
    return SampleType::UInt8;
  if (dtype_name == "uint16")
    return SampleType::UInt16;
  if (dtype_name == "int16")
    return SampleType::Int16;

  throw std::runtime_error("OpenJPH backend currently supports decode to "
                           "uint8, uint16, and int16 only");
}

ArrayInfo inspect_array(const nb::ndarray<nb::numpy, nb::c_contig> &array) {
  if (array.device_type() != nb::device::cpu::value)
    throw std::runtime_error("OpenJPH backend requires a CPU array");

  if (array.ndim() == 2) {
    return ArrayInfo{
        parse_array_dtype(array), 2, 1, array.shape(0), array.shape(1),
    };
  }

  if (array.ndim() == 3) {
    return ArrayInfo{
        parse_array_dtype(array), 3, array.shape(0), array.shape(1),
        array.shape(2),
    };
  }

  throw std::runtime_error(
      "OpenJPH backend expects a 2-D or 3-D C-contiguous NumPy array");
}

size_t row_offset(const ArrayInfo &info, size_t component, size_t row) {
  if (info.ndim == 2)
    return row * info.width;
  return (component * info.height + row) * info.width;
}

uint32_t bit_depth_for(SampleType sample_type) {
  switch (sample_type) {
  case SampleType::UInt8:
    return 8;
  case SampleType::UInt16:
  case SampleType::Int16:
    return 16;
  }
  throw std::runtime_error("Unsupported sample type");
}

bool is_signed(SampleType sample_type) {
  return sample_type == SampleType::Int16;
}

uint32_t max_decompositions(size_t width, size_t height) {
  size_t v = std::min(width, height);
  uint32_t levels = 0;
  while (v >= 2) {
    ++levels;
    v >>= 1;
  }
  return levels;
}

template <typename Src>
void copy_to_linebuf_impl(const Src *src, size_t width, ojph::line_buf *line) {
  if ((line->flags & ojph::line_buf::LFT_32BIT) &&
      (line->flags & ojph::line_buf::LFT_INTEGER) == 0) {
    for (size_t i = 0; i < width; ++i)
      line->f32[i] = static_cast<float>(src[i]);
    return;
  }

  if (line->flags & ojph::line_buf::LFT_32BIT) {
    for (size_t i = 0; i < width; ++i)
      line->i32[i] = static_cast<ojph::si32>(src[i]);
    return;
  }

  if (line->flags & ojph::line_buf::LFT_64BIT) {
    for (size_t i = 0; i < width; ++i)
      line->i64[i] = static_cast<ojph::si64>(src[i]);
    return;
  }

  throw std::runtime_error("Unsupported OpenJPH line buffer format");
}

void copy_row_to_linebuf(const nb::ndarray<nb::numpy, nb::c_contig> &array,
                         const ArrayInfo &info, size_t component, size_t row,
                         ojph::line_buf *line) {
  const size_t offset = row_offset(info, component, row);

  switch (info.sample_type) {
  case SampleType::UInt8:
    copy_to_linebuf_impl(static_cast<const uint8_t *>(array.data()) + offset,
                         info.width, line);
    return;
  case SampleType::UInt16:
    copy_to_linebuf_impl(static_cast<const uint16_t *>(array.data()) + offset,
                         info.width, line);
    return;
  case SampleType::Int16:
    copy_to_linebuf_impl(static_cast<const int16_t *>(array.data()) + offset,
                         info.width, line);
    return;
  }

  throw std::runtime_error("Unsupported input sample type");
}

template <typename Dst, typename Src> inline Dst clamp_cast(Src v) {
  constexpr Src lo = static_cast<Src>(std::numeric_limits<Dst>::min());
  constexpr Src hi = static_cast<Src>(std::numeric_limits<Dst>::max());
  if (v < lo)
    return std::numeric_limits<Dst>::min();
  if (v > hi)
    return std::numeric_limits<Dst>::max();
  return static_cast<Dst>(v);
}

template <typename Dst>
void copy_from_linebuf_impl(const ojph::line_buf *line, Dst *dst,
                            size_t width) {
  if ((line->flags & ojph::line_buf::LFT_32BIT) &&
      (line->flags & ojph::line_buf::LFT_INTEGER) == 0) {
    for (size_t i = 0; i < width; ++i)
      dst[i] = clamp_cast<Dst>(line->f32[i]);
    return;
  }

  if (line->flags & ojph::line_buf::LFT_32BIT) {
    for (size_t i = 0; i < width; ++i)
      dst[i] = clamp_cast<Dst>(line->i32[i]);
    return;
  }

  if (line->flags & ojph::line_buf::LFT_64BIT) {
    for (size_t i = 0; i < width; ++i)
      dst[i] = clamp_cast<Dst>(line->i64[i]);
    return;
  }

  throw std::runtime_error("Unsupported OpenJPH line buffer format");
}

template <typename Dst>
void copy_linebuf_to_array(const ojph::line_buf *line, Dst *data,
                           const ArrayInfo &info, size_t component,
                           size_t row) {
  Dst *dst = data + row_offset(info, component, row);
  copy_from_linebuf_impl(line, dst, info.width);
}

template <typename T> nb::object make_array(T *data, const ArrayInfo &info) {
  auto owner =
      nb::capsule(data, [](void *p) noexcept { delete[] static_cast<T *>(p); });

  if (info.ndim == 2) {
    return nb::ndarray<nb::numpy, T>(data, {info.height, info.width}, owner)
        .cast();
  }

  return nb::ndarray<nb::numpy, T>(
             data, {info.components, info.height, info.width}, owner)
      .cast();
}

template <typename T>
T *decode_to_buffer(ojph::codestream &codestream, const ArrayInfo &info) {
  const size_t total = info.components * info.height * info.width;
  const size_t total_lines = info.components * info.height;
  T *data = new T[total];
  std::fill(data, data + total, T{});

  std::vector<size_t> rows(info.components, 0);
  for (size_t line_index = 0; line_index < total_lines; ++line_index) {
    ojph::ui32 component = 0;
    ojph::line_buf *line = codestream.pull(component);
    if (line == nullptr)
      throw std::runtime_error(
          "OpenJPH decode ended before the requested array was filled");
    const size_t row = rows[component]++;
    copy_linebuf_to_array(line, data, info, component, row);
  }

  return data;
}

nb::bytes encode_impl(const nb::ndarray<nb::numpy, nb::c_contig> &array,
                      bool irreversible, std::optional<float> qstep,
                      int num_decompositions,
                      const std::vector<int> &block_size,
                      const std::string &progression_order,
                      bool color_transform, bool planar) {
  if (block_size.size() != 2)
    throw std::runtime_error("block_size must contain exactly two integers");
  if (!irreversible && qstep.has_value())
    throw std::runtime_error("qstep is only valid when irreversible=True");

  ArrayInfo info = inspect_array(array);
  if (color_transform && info.components != 3)
    throw std::runtime_error(
        "color_transform=True requires exactly 3 components");

  ojph::mem_outfile outfile;
  outfile.open();

  {
    nb::gil_scoped_release release;

    ojph::codestream codestream;
    codestream.set_planar(planar);

    auto siz = codestream.access_siz();
    siz.set_image_extent(ojph::point(static_cast<ojph::ui32>(info.width),
                                     static_cast<ojph::ui32>(info.height)));
    siz.set_image_offset(ojph::point(0, 0));
    siz.set_tile_size(ojph::size(static_cast<ojph::ui32>(info.width),
                                 static_cast<ojph::ui32>(info.height)));
    siz.set_tile_offset(ojph::point(0, 0));
    siz.set_num_components(static_cast<ojph::ui32>(info.components));

    for (size_t component = 0; component < info.components; ++component) {
      siz.set_component(static_cast<ojph::ui32>(component), ojph::point(1, 1),
                        bit_depth_for(info.sample_type),
                        is_signed(info.sample_type));
    }

    auto cod = codestream.access_cod();
    uint32_t clamped_num_decomp =
        std::min<uint32_t>(static_cast<uint32_t>(num_decompositions),
                           max_decompositions(info.width, info.height));
    cod.set_num_decomposition(clamped_num_decomp);
    cod.set_block_dims(static_cast<ojph::ui32>(block_size[0]),
                       static_cast<ojph::ui32>(block_size[1]));
    cod.set_progression_order(progression_order.c_str());
    cod.set_color_transform(color_transform);
    cod.set_reversible(!irreversible);
    if (irreversible && qstep.has_value()) {
      auto qcd = codestream.access_qcd();
      qcd.set_irrev_quant(*qstep);
    }

    codestream.write_headers(&outfile);

    std::vector<size_t> rows(info.components, 0);
    ojph::ui32 component = 0;
    ojph::line_buf *line = codestream.exchange(nullptr, component);
    while (line != nullptr) {
      const size_t row = rows[component]++;
      copy_row_to_linebuf(array, info, component, row, line);
      line = codestream.exchange(line, component);
    }

    codestream.flush();
    codestream.close();
  }

  return nb::bytes(reinterpret_cast<const char *>(outfile.get_data()),
                   outfile.get_used_size());
}

nb::object decode_impl(const nb::bytes &encoded,
                       const std::vector<size_t> &shape,
                       const std::string &dtype_name) {
  if (shape.size() != 2 && shape.size() != 3)
    throw std::runtime_error("shape must describe a 2-D or 3-D array");

  const SampleType sample_type = parse_dtype_name(dtype_name);
  const ArrayInfo info{
      sample_type,
      shape.size(),
      shape.size() == 2 ? 1 : shape[0],
      shape.size() == 2 ? shape[0] : shape[1],
      shape.size() == 2 ? shape[1] : shape[2],
  };

  void *decoded = nullptr;
  {
    nb::gil_scoped_release release;

    ojph::mem_infile infile;
    infile.open(reinterpret_cast<const ojph::ui8 *>(encoded.data()),
                encoded.size());

    ojph::codestream codestream;
    codestream.set_planar(false);
    codestream.read_headers(&infile);

    auto siz = codestream.access_siz();
    if (siz.get_num_components() != info.components)
      throw std::runtime_error(
          "Decoded component count does not match requested shape");
    if (siz.get_image_extent().x != info.width ||
        siz.get_image_extent().y != info.height)
      throw std::runtime_error(
          "Decoded codestream dimensions do not match requested shape");

    codestream.create();

    switch (sample_type) {
    case SampleType::UInt8:
      decoded = decode_to_buffer<uint8_t>(codestream, info);
      break;
    case SampleType::UInt16:
      decoded = decode_to_buffer<uint16_t>(codestream, info);
      break;
    case SampleType::Int16:
      decoded = decode_to_buffer<int16_t>(codestream, info);
      break;
    }

    codestream.close();
  }

  switch (sample_type) {
  case SampleType::UInt8:
    return make_array(static_cast<uint8_t *>(decoded), info);
  case SampleType::UInt16:
    return make_array(static_cast<uint16_t *>(decoded), info);
  case SampleType::Int16:
    return make_array(static_cast<int16_t *>(decoded), info);
  }

  throw std::runtime_error("Unsupported decode sample type");
}

} // namespace

NB_MODULE(_openjph, m) {
  ojph::set_info_stream(nullptr);
  ojph::set_warning_stream(nullptr);
  ojph::set_error_stream(nullptr);

  m.def("encode", &encode_impl, nb::arg("array"), nb::kw_only(),
        nb::arg("irreversible"), nb::arg("qstep"),
        nb::arg("num_decompositions"), nb::arg("block_size"),
        nb::arg("progression_order"), nb::arg("color_transform"),
        nb::arg("planar"));

  m.def("decode", &decode_impl, nb::arg("data"), nb::kw_only(),
        nb::arg("shape"), nb::arg("dtype"));
}
