import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
import dlssg_ampere_static as sut


def put(b, at, fmt, value): struct.pack_into(fmt, b, at, value)


def literal_block(text):
    b = bytearray(); n = len(text); b.append(min(n, 15) << 4)
    if n >= 15:
        n -= 15
        while n >= 255: b.append(255); n -= 255
        b.append(n)
    b += text
    return bytes(b)


def fatbin(ptx=b".version 8.7\n.target sm_89\n.address_size 64\n.entry x() {}\n\0", extra=False):
    comp = literal_block(ptx); size = 80 + ((len(comp) + 7) & ~7)
    if extra: size += 64 + 8
    b = bytearray(size); put(b, 0, "<I", sut.FATBIN_MAGIC); put(b, 4, "<H", 1); put(b, 6, "<H", 16); put(b, 8, "<Q", size-16)
    put(b, 16, "<H", 1); put(b, 18, "<H", 0x101); put(b, 20, "<I", 64); put(b, 24, "<Q", ((len(comp)+7)&~7)); put(b, 32, "<I", len(comp)); put(b, 44, "<I", 89); put(b, 56, "<Q", 0x2041); put(b, 72, "<Q", len(ptx)); b[80:80+len(comp)] = comp
    if extra:
        at = 80 + ((len(comp)+7)&~7); put(b, at, "<H", 2); put(b, at+2, "<H", 0x101); put(b, at+4, "<I", 64); put(b, at+8, "<Q", 8); put(b, at+28, "<I", 89)
    return bytes(b)


def pe_with_exports(exports):
    # Small PE32+ image whose .text and export tables share one raw section.
    raw = bytearray(0x1000); raw[:2] = b"MZ"; put(raw, 0x3c, "<I", 0x80); raw[0x80:0x84] = b"PE\0\0"; put(raw, 0x86, "<H", 1); put(raw, 0x94, "<H", 0xF0)
    opt = 0x98; put(raw, opt, "<H", 0x20b); put(raw, opt+56, "<I", 0x2000); put(raw, opt+60, "<I", 0x200); put(raw, opt+108, "<I", 16); put(raw, opt+112, "<I", 0x1100); put(raw, opt+116, "<I", 0x200)
    sec = opt+0xF0; raw[sec:sec+5] = b".all\0"; put(raw, sec+8, "<I", 0x1000); put(raw, sec+12, "<I", 0x1000); put(raw, sec+16, "<I", 0xE00); put(raw, sec+20, "<I", 0x200)
    def rvaoff(rva): return rva - 0x1000 + 0x200
    names = list(exports); funcs = list(exports.values()); d = rvaoff(0x1100); put(raw, d+20, "<I", len(funcs)); put(raw, d+24, "<I", len(names)); put(raw, d+28, "<I", 0x1140); put(raw, d+32, "<I", 0x1160); put(raw, d+36, "<I", 0x1180)
    for i, rva in enumerate(funcs): put(raw, rvaoff(0x1140)+4*i, "<I", rva)
    for i, name in enumerate(names):
        at = 0x1200+i*80; raw[rvaoff(at):rvaoff(at)+len(name)+1] = name.encode()+b"\0"; put(raw, rvaoff(0x1160)+4*i, "<I", at); put(raw, rvaoff(0x1180)+2*i, "<H", i)
    return raw, rvaoff


def test_valid_pe_virtual_image_and_export_lookup():
    raw, off = pe_with_exports({"x": 0x1300}); raw[off(0x1300):off(0x1306)] = b"\xB8\x90\x01\0\0\xC3"
    pe = sut.PEImage(bytes(raw)); assert pe.exports()["x"] == 0x1300; assert pe.file_offset(0x1300) == off(0x1300)


def test_invalid_pe_bounds_rejected():
    try: sut.PEImage(b"MZ" + b"\0" * 100)
    except sut.FormatError: pass
    else: assert False


def test_architecture_and_unique_requirements_store():
    image = bytearray(0x1000); image[10:16] = b"\xB8\x90\x01\0\0\xC3"; image[100:108] = b"\xC7\x44\x24\x20\x90\x01\0\0"
    assert sut.requirements_store(image, 100, 0x190)["valid"]
    image[120:128] = image[100:108]; assert not sut.requirements_store(image, 100, 0x190)["valid"]


def test_fatbin_valid_and_invalid():
    data = fatbin(); total, entries = sut.parse_fatbin(data, 0); assert total == len(data) and entries[0].arch == 89
    bad = bytearray(data); bad[6] = 0
    try: sut.parse_fatbin(bad, 0)
    except sut.FormatError: pass
    else: assert False


def test_lz4_literals_overlap_and_malformed():
    assert sut.lz4_decompress(literal_block(b"abc"), 3)[0] == b"abc"
    assert sut.lz4_decompress(bytes([0x14, ord('a'), 1, 0, 0]), 9)[0] == b"a" * 9
    try: sut.lz4_decompress(b"\0\0\0", 4)
    except sut.FormatError: pass
    else: assert False


def test_ptx_audit_and_unique_target():
    good = b".version 8.7\n.target sm_89\n.address_size 64\n.entry x() {}\n\0"
    assert sut.ptx_audit(good)["result"] == "SM86_STATIC_COMPATIBLE"
    assert sut.ptx_audit(good[:-1] + b"wgmma.foo\n\0")["result"] == "SM86_STATIC_INCOMPATIBLE"
    assert sut.ptx_audit(good.replace(b"sm_89", b"sm_86"))["result"] == "UNKNOWN"


def test_ptx78_policy_and_isa_dimensions_are_independent():
    ptx78 = b".version 7.8\n.target sm_89\n.address_size 64\n.entry x() {}\n\0"
    report = sut.ptx_audit(ptx78)
    assert report["reno_policy"]["accepted"] is False
    assert report["nvidia_isa_sm86"] == "compatible"
    assert report["result"] == "SM86_STATIC_COMPATIBLE"
    post_ampere = ptx78[:-1] + b"wgmma.mma_async;\n\0"
    assert sut.ptx_audit(post_ampere)["nvidia_isa_sm86"] == "incompatible"


def test_target_literal_simulation_changes_exactly_one_output_byte():
    ptx = b".version 8.7\n.target sm_89\n.address_size 64\n.entry x() {}\n\0"; comp = literal_block(ptx); digit = ptx.index(b"sm_89") + 4
    original, source = sut.lz4_decompress(comp, len(ptx), digit); changed = bytearray(comp); changed[source] = ord('6'); updated, _ = sut.lz4_decompress(changed, len(ptx))
    assert sum(a != b for a, b in zip(original, updated)) == 1 and updated[digit] == ord('6')


def test_duplicate_target_and_shared_literal_rejected():
    assert sut.ptx_audit(b".version 8.7\n.target sm_89\n.target sm_89\n.address_size 64\n.entry x\n\0")["result"] == "UNKNOWN"
    # literal '9' is copied by the match, hence not an independent edit.
    src = b".target sm_89"; block = bytearray(literal_block(src)); block[0] |= 5; block += bytes([5, 0, 0])
    decoded, literal = sut.lz4_decompress(bytes(block), len(src)+9, src.index(b"9")); assert literal is not None
    changed = bytearray(block); changed[literal] = ord('6'); after, _ = sut.lz4_decompress(changed, len(decoded)); assert sum(a != b for a, b in zip(decoded, after)) > 1
