"""Minimal dependency-free static PE metadata reader.

The parser reads bytes only.  It never maps or executes the inspected image.
It is intentionally limited to the metadata needed by runtime-candidate audits:
machine type, sections, imported DLL names, and named exports.
"""

from __future__ import annotations

from pathlib import Path
import struct


class PeFormatError(ValueError):
    pass


_MACHINE_NAMES = {
    0x014C: "x86",
    0x8664: "x86_64",
    0xAA64: "arm64",
}


def _need(data: bytes, offset: int, size: int, label: str) -> None:
    if offset < 0 or size < 0 or offset + size > len(data):
        raise PeFormatError(f"truncated PE while reading {label}")


def _u16(data: bytes, offset: int, label: str) -> int:
    _need(data, offset, 2, label)
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int, label: str) -> int:
    _need(data, offset, 4, label)
    return struct.unpack_from("<I", data, offset)[0]


def _cstring(data: bytes, offset: int, label: str, *, limit: int = 4096) -> str:
    _need(data, offset, 1, label)
    end = data.find(b"\0", offset, min(len(data), offset + limit))
    if end < 0:
        raise PeFormatError(f"unterminated PE string for {label}")
    return data[offset:end].decode("ascii", errors="replace")


def inspect_pe(path: str | Path) -> dict[str, object]:
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise PeFormatError("not a PE image: missing MZ header")

    pe_offset = _u32(data, 0x3C, "DOS e_lfanew")
    _need(data, pe_offset, 24, "PE signature/COFF header")
    if data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise PeFormatError("not a PE image: missing PE signature")

    coff = pe_offset + 4
    machine = _u16(data, coff, "COFF machine")
    section_count = _u16(data, coff + 2, "COFF section count")
    optional_size = _u16(data, coff + 16, "COFF optional-header size")
    optional = coff + 20
    _need(data, optional, optional_size, "optional header")
    magic = _u16(data, optional, "optional-header magic")
    if magic == 0x20B:
        pe32_plus = True
        number_of_dirs_offset = optional + 108
        directories_offset = optional + 112
    elif magic == 0x10B:
        pe32_plus = False
        number_of_dirs_offset = optional + 92
        directories_offset = optional + 96
    else:
        raise PeFormatError(f"unsupported PE optional-header magic 0x{magic:04X}")

    number_of_dirs = _u32(data, number_of_dirs_offset, "number of data directories")
    directory_count = min(number_of_dirs, 16)
    _need(data, directories_offset, directory_count * 8, "data directories")

    def directory(index: int) -> tuple[int, int]:
        if index >= directory_count:
            return 0, 0
        offset = directories_offset + index * 8
        return (
            _u32(data, offset, f"directory {index} RVA"),
            _u32(data, offset + 4, f"directory {index} size"),
        )

    section_table = optional + optional_size
    _need(data, section_table, section_count * 40, "section table")
    sections: list[dict[str, int | str]] = []
    for index in range(section_count):
        offset = section_table + index * 40
        raw_name = data[offset:offset + 8].split(b"\0", 1)[0]
        name = raw_name.decode("ascii", errors="replace")
        virtual_size = _u32(data, offset + 8, f"section {index} virtual size")
        virtual_address = _u32(data, offset + 12, f"section {index} RVA")
        raw_size = _u32(data, offset + 16, f"section {index} raw size")
        raw_offset = _u32(data, offset + 20, f"section {index} raw offset")
        sections.append(
            {
                "name": name,
                "virtual_address": virtual_address,
                "virtual_size": virtual_size,
                "raw_offset": raw_offset,
                "raw_size": raw_size,
            }
        )

    def rva_to_offset(rva: int, label: str) -> int:
        if rva == 0:
            raise PeFormatError(f"{label} has null RVA")
        for section in sections:
            start = int(section["virtual_address"])
            span = max(int(section["virtual_size"]), int(section["raw_size"]))
            if start <= rva < start + span:
                delta = rva - start
                if delta >= int(section["raw_size"]):
                    raise PeFormatError(f"{label} points outside section raw data")
                result = int(section["raw_offset"]) + delta
                _need(data, result, 1, label)
                return result
        # Header RVAs can legally point before the first section.
        if rva < section_table:
            _need(data, rva, 1, label)
            return rva
        raise PeFormatError(f"{label} RVA 0x{rva:X} does not map to a section")

    imports: list[str] = []
    import_symbols: dict[str, list[str]] = {}
    import_rva, import_size = directory(1)
    if import_rva and import_size:
        descriptor = rva_to_offset(import_rva, "import directory")
        max_descriptors = min(4096, max(1, import_size // 20 + 1))
        for index in range(max_descriptors):
            offset = descriptor + index * 20
            _need(data, offset, 20, f"import descriptor {index}")
            fields = struct.unpack_from("<IIIII", data, offset)
            if fields == (0, 0, 0, 0, 0):
                break
            lookup_rva, _timestamp, _forwarder, name_rva, first_thunk_rva = fields
            name = _cstring(data, rva_to_offset(name_rva, f"import name {index}"), f"import name {index}")
            imports.append(name)

            thunk_rva = lookup_rva or first_thunk_rva
            symbols: list[str] = []
            if thunk_rva:
                thunk_offset = rva_to_offset(thunk_rva, f"import thunk table {index}")
                thunk_size = 8 if pe32_plus else 4
                ordinal_flag = 0x8000000000000000 if pe32_plus else 0x80000000
                value_mask = 0x7FFFFFFFFFFFFFFF if pe32_plus else 0x7FFFFFFF
                unpack = "<Q" if pe32_plus else "<I"
                for symbol_index in range(65536):
                    entry_offset = thunk_offset + symbol_index * thunk_size
                    _need(data, entry_offset, thunk_size, f"import thunk {index}:{symbol_index}")
                    value = struct.unpack_from(unpack, data, entry_offset)[0]
                    if value == 0:
                        break
                    if value & ordinal_flag:
                        symbols.append(f"#{value & 0xFFFF}")
                        continue
                    hint_name_rva = value & value_mask
                    hint_name = rva_to_offset(
                        hint_name_rva,
                        f"import hint/name {index}:{symbol_index}",
                    )
                    _need(data, hint_name, 2, f"import hint {index}:{symbol_index}")
                    symbols.append(
                        _cstring(
                            data,
                            hint_name + 2,
                            f"import symbol {index}:{symbol_index}",
                        )
                    )
                else:
                    raise PeFormatError("import thunk table is not terminated")
            import_symbols[name] = sorted(set(symbols))
        else:
            raise PeFormatError("import descriptor table is not terminated")

    exports: list[str] = []
    export_rva, export_size = directory(0)
    if export_rva and export_size:
        export_offset = rva_to_offset(export_rva, "export directory")
        _need(data, export_offset, 40, "export directory")
        number_of_names = _u32(data, export_offset + 24, "export name count")
        names_rva = _u32(data, export_offset + 32, "export names RVA")
        if number_of_names > 65536:
            raise PeFormatError(f"unreasonable export name count: {number_of_names}")
        if number_of_names:
            names_offset = rva_to_offset(names_rva, "export name pointer table")
            _need(data, names_offset, number_of_names * 4, "export name pointer table")
            for index in range(number_of_names):
                name_rva = _u32(data, names_offset + index * 4, f"export name RVA {index}")
                exports.append(
                    _cstring(
                        data,
                        rva_to_offset(name_rva, f"export name {index}"),
                        f"export name {index}",
                    )
                )

    return {
        "machine": f"0x{machine:04X}",
        "architecture": _MACHINE_NAMES.get(machine, "unknown"),
        "pe32_plus": pe32_plus,
        "sections": sections,
        "imports": sorted(set(imports), key=str.casefold),
        "import_symbols": {
            name: import_symbols[name]
            for name in sorted(import_symbols, key=str.casefold)
        },
        "exports": sorted(set(exports)),
    }
