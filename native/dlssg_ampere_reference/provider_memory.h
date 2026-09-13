#pragma once

#include <windows.h>

namespace ampere_provider::memory {

inline bool IsReadableProtection(DWORD protect) noexcept {
  if ((protect & (PAGE_GUARD | PAGE_NOACCESS)) != 0) return false;
  switch (protect & 0xFFu) {
    case PAGE_READONLY:
    case PAGE_READWRITE:
    case PAGE_WRITECOPY:
    case PAGE_EXECUTE_READ:
    case PAGE_EXECUTE_READWRITE:
    case PAGE_EXECUTE_WRITECOPY:
      return true;
    default:
      return false;
  }
}

inline bool RegionCovers(uintptr_t address, uintptr_t region_base,
                         SIZE_T region_size, SIZE_T requested) noexcept {
  if (address < region_base) return false;
  const uintptr_t offset = address - region_base;
  return offset <= region_size && requested <= region_size - offset;
}

} // namespace ampere_provider::memory
