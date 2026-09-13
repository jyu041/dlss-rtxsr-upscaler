/*
 * Adapted from MFGAmpereUnlock-RenoDx fatbin.hpp, pinned at
 * c88b208e3f8f12e86a261f06aef1da3a77adef27.
 * SPDX-License-Identifier: MIT
 */
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace ampere_provider::donor_lz4 {
inline bool Decompress(const unsigned char* src, size_t src_bytes,
                       unsigned char* dst, size_t dst_bytes,
                       size_t wanted = (std::numeric_limits<size_t>::max)(),
                       size_t* literal = nullptr) {
  size_t in = 0;
  size_t out = 0;
  if (literal != nullptr) *literal = (std::numeric_limits<size_t>::max)();
  auto extend = [&](size_t& length) {
    if (length != 15) return true;
    unsigned int extra = 0;
    do {
      if (in == src_bytes) return false;
      extra = src[in++];
      if (length > dst_bytes || extra > dst_bytes - length) return false;
      length += extra;
    } while (extra == 255);
    return true;
  };
  while (in < src_bytes) {
    const unsigned int token = src[in++];
    size_t length = token >> 4;
    if (!extend(length) || length > src_bytes - in || length > dst_bytes - out) return false;
    if (literal != nullptr && wanted >= out && wanted - out < length)
      *literal = in + wanted - out;
    if (length != 0) std::memcpy(dst + out, src + in, length);
    in += length;
    out += length;
    if (in == src_bytes) return out == dst_bytes;
    if (src_bytes - in < 2) return false;
    const size_t distance = static_cast<size_t>(src[in]) | (static_cast<size_t>(src[in + 1]) << 8);
    in += 2;
    length = token & 15;
    if (!extend(length) || length > (std::numeric_limits<size_t>::max)() - 4) return false;
    length += 4;
    if (length > dst_bytes - out) return false;
    for (size_t i = 0; i < length; ++i) {
      if (i >= dst_bytes - out) return false;
      const size_t dst_index = out + i;
      if (distance > dst_index) return false;
      dst[dst_index] = dst[dst_index - distance];
    }
    out += length;
  }
  return out == dst_bytes;
}
}
