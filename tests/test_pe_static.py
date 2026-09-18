import struct

from src.core.pe_static import inspect_pe


def _synthetic_pe(path):
    data = bytearray(0x800)
    data[0:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\0\0"
    coff = 0x84
    struct.pack_into("<H", data, coff, 0x8664)  # AMD64
    struct.pack_into("<H", data, coff + 2, 1)   # one section
    struct.pack_into("<H", data, coff + 16, 0xF0)
    optional = coff + 20
    struct.pack_into("<H", data, optional, 0x20B)
    struct.pack_into("<I", data, optional + 108, 16)
    # Export directory RVA 0x1100, size 0x80.
    struct.pack_into("<II", data, optional + 112, 0x1100, 0x80)
    # Import directory RVA 0x1200, size 0x40.
    struct.pack_into("<II", data, optional + 120, 0x1200, 0x40)

    section = optional + 0xF0
    data[section:section + 8] = b".rdata\0\0"
    struct.pack_into("<I", data, section + 8, 0x600)
    struct.pack_into("<I", data, section + 12, 0x1000)
    struct.pack_into("<I", data, section + 16, 0x600)
    struct.pack_into("<I", data, section + 20, 0x200)

    # Export directory at file offset 0x300.
    export = 0x300
    struct.pack_into("<I", data, export + 24, 1)      # NumberOfNames
    struct.pack_into("<I", data, export + 32, 0x1140) # AddressOfNames
    struct.pack_into("<I", data, 0x340, 0x1160)
    data[0x360:0x360 + len(b"dlss5nr_test\0")] = b"dlss5nr_test\0"

    # Import descriptor at file offset 0x400.
    # OriginalFirstThunk RVA 0x1280, DLL name RVA 0x1260.
    struct.pack_into("<IIIII", data, 0x400, 0x1280, 0, 0, 0x1260, 0)
    data[0x460:0x460 + len(b"KERNEL32.dll\0")] = b"KERNEL32.dll\0"
    # One PE32+ import-by-name thunk, then a zero terminator.
    struct.pack_into("<Q", data, 0x480, 0x12A0)
    struct.pack_into("<Q", data, 0x488, 0)
    struct.pack_into("<H", data, 0x4A0, 0)
    data[0x4A2:0x4A2 + len(b"CreateProcessW\0")] = b"CreateProcessW\0"
    path.write_bytes(data)


def test_static_pe_reader_extracts_architecture_imports_and_exports(tmp_path):
    path = tmp_path / "bridge.dll"
    _synthetic_pe(path)
    report = inspect_pe(path)
    assert report["architecture"] == "x86_64"
    assert report["pe32_plus"] is True
    assert report["imports"] == ["KERNEL32.dll"]
    assert report["import_symbols"] == {"KERNEL32.dll": ["CreateProcessW"]}
    assert report["exports"] == ["dlss5nr_test"]
    assert report["sections"][0]["name"] == ".rdata"
