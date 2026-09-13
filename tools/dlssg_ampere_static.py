#!/usr/bin/env python3
"""Read-only structural analyzer for NVIDIA DLSS-G provider candidates.

This program parses bytes from a PE file into a private virtual image.  It never
loads the DLL, executes its exports, initializes a graphics API, or writes a
provider file.  The layout checks are independently implemented from the public
contracts in RTX30MFG-Unlock (21a2b993) and MFGAmpereUnlock-RenoDx (a111c62e).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANALYZER_VERSION = "2A.1"
FATBIN_MAGIC = 0xBA55ED50
MAX_IMAGE = 1 << 30
MAX_FATBIN = 64 << 20
MAX_PTX = 32 << 20
SUPPORTED_VERSIONS = {(310, 1, 0), (310, 2, 0), (310, 2, 1), (310, 3, 0),
                      (310, 4, 0), (310, 5, 0), (310, 5, 2), (310, 5, 3),
                      (310, 6, 0), (310, 7, 0), (310, 7, 128), (310, 7, 129),
                      (310, 8, 0), (310, 9, 0), (310, 9, 1)}
UNSUPPORTED_SM86 = ("wgmma.", "tcgen05.", "tensormap.", "cp.async.bulk",
                    ".e4m3", ".e5m2", ".e2m1")


class FormatError(ValueError):
    pass


def u16(data: bytes | bytearray, at: int) -> int:
    if at < 0 or at + 2 > len(data): raise FormatError("u16 out of range")
    return struct.unpack_from("<H", data, at)[0]


def u32(data: bytes | bytearray, at: int) -> int:
    if at < 0 or at + 4 > len(data): raise FormatError("u32 out of range")
    return struct.unpack_from("<I", data, at)[0]


def u64(data: bytes | bytearray, at: int) -> int:
    if at < 0 or at + 8 > len(data): raise FormatError("u64 out of range")
    return struct.unpack_from("<Q", data, at)[0]


@dataclass(frozen=True)
class Section:
    va: int; virtual_size: int; raw_size: int; raw_offset: int


class PEImage:
    """Validated PE32+ raw file and its manually constructed virtual image."""
    def __init__(self, raw: bytes):
        self.raw = raw
        if len(raw) < 0x40 or raw[:2] != b"MZ": raise FormatError("missing DOS header")
        nt = u32(raw, 0x3C)
        if nt + 24 > len(raw) or raw[nt:nt + 4] != b"PE\0\0": raise FormatError("missing PE signature")
        count, opt_size = u16(raw, nt + 6), u16(raw, nt + 20)
        opt = nt + 24
        if count == 0 or opt_size < 112 or opt + opt_size > len(raw) or u16(raw, opt) != 0x20B:
            raise FormatError("not a valid PE32+ optional header")
        self.size_image, self.size_headers = u32(raw, opt + 56), u32(raw, opt + 60)
        if not self.size_image or self.size_image > MAX_IMAGE or self.size_headers > len(raw) or self.size_headers > self.size_image:
            raise FormatError("invalid image/header size")
        if opt_size < 112 + 8 or u32(raw, opt + 108) < 1: raise FormatError("missing data directories")
        self.export_rva, self.export_size = u32(raw, opt + 112), u32(raw, opt + 116)
        table = opt + opt_size
        if table + count * 40 > len(raw): raise FormatError("section table outside file")
        self.sections: list[Section] = []
        image = bytearray(self.size_image); image[:self.size_headers] = raw[:self.size_headers]
        for i in range(count):
            at = table + i * 40
            vs, va, rs, ro = u32(raw, at + 8), u32(raw, at + 12), u32(raw, at + 16), u32(raw, at + 20)
            span = max(vs, rs)
            if va >= self.size_image or span > self.size_image - va or rs > 0 and (ro > len(raw) or rs > len(raw) - ro):
                raise FormatError("section bounds invalid")
            if rs: image[va:va + rs] = raw[ro:ro + rs]
            self.sections.append(Section(va, vs, rs, ro))
        self.image = image

    def contains(self, rva: int, size: int = 1) -> bool:
        return rva >= 0 and size >= 0 and rva <= len(self.image) and size <= len(self.image) - rva

    def file_offset(self, rva: int) -> int | None:
        if rva < self.size_headers: return rva if rva < len(self.raw) else None
        for s in self.sections:
            if s.va <= rva < s.va + s.raw_size:
                return s.raw_offset + rva - s.va
        return None

    def cstring(self, rva: int, limit: int = 4096) -> bytes:
        if not self.contains(rva): raise FormatError("string RVA outside image")
        end = min(len(self.image), rva + limit)
        nul = self.image.find(0, rva, end)
        if nul < 0: raise FormatError("unterminated export string")
        return bytes(self.image[rva:nul])

    def exports(self) -> dict[str, int]:
        if not self.export_rva: return {}
        if not self.contains(self.export_rva, 40): raise FormatError("export directory outside image")
        d = self.image; at = self.export_rva; functions, names = u32(d, at + 20), u32(d, at + 24)
        funcs_rva, names_rva, ords_rva = u32(d, at + 28), u32(d, at + 32), u32(d, at + 36)
        if names > 1_000_000 or functions > 1_000_000 or not self.contains(funcs_rva, functions * 4) or not self.contains(names_rva, names * 4) or not self.contains(ords_rva, names * 2):
            raise FormatError("export arrays outside image")
        result: dict[str, int] = {}
        for i in range(names):
            name = self.cstring(u32(d, names_rva + 4 * i)).decode("ascii", "strict")
            ordinal = u16(d, ords_rva + 2 * i)
            if ordinal >= functions: raise FormatError("export ordinal outside functions")
            result[name] = u32(d, funcs_rva + 4 * ordinal)
        return result


def lz4_decompress(src: bytes, output_size: int, wanted: int | None = None) -> tuple[bytes, int | None]:
    """Strict raw-LZ4 decoder; optional result identifies a literal source byte."""
    if output_size < 0 or output_size > MAX_PTX: raise FormatError("LZ4 output size out of policy")
    i = 0; out = bytearray(); literal = None
    def extend(n: int) -> int:
        nonlocal i
        if n != 15: return n
        while True:
            if i >= len(src): raise FormatError("truncated LZ4 length")
            b = src[i]; i += 1; n += b
            if n > output_size: raise FormatError("LZ4 length exceeds output")
            if b != 255: return n
    while i < len(src):
        token = src[i]; i += 1; literals = extend(token >> 4)
        if literals > len(src) - i or literals > output_size - len(out): raise FormatError("invalid LZ4 literals")
        if wanted is not None and len(out) <= wanted < len(out) + literals: literal = i + wanted - len(out)
        out.extend(src[i:i + literals]); i += literals
        if i == len(src): break
        if len(src) - i < 2: raise FormatError("truncated LZ4 match")
        distance = src[i] | (src[i + 1] << 8); i += 2
        match = extend(token & 15) + 4
        if distance == 0 or distance > len(out) or match > output_size - len(out): raise FormatError("invalid LZ4 match")
        for _ in range(match): out.append(out[-distance])
    if len(out) != output_size: raise FormatError("LZ4 decoded size mismatch")
    return bytes(out), literal


@dataclass(frozen=True)
class FatEntry:
    offset: int; header_size: int; payload_size: int; kind: int; arch: int; compressed_size: int; flags: int; unpacked_size: int
    @property
    def payload_offset(self) -> int: return self.offset + self.header_size
    @property
    def end(self) -> int: return self.payload_offset + self.payload_size


def parse_fatbin(data: bytes | bytearray, start: int) -> tuple[int, list[FatEntry]]:
    if start < 0 or len(data) - start < 16 or u32(data, start) != FATBIN_MAGIC or u16(data, start + 4) != 1 or u16(data, start + 6) != 16:
        raise FormatError("invalid fatbin header")
    payload = u64(data, start + 8)
    if payload == 0 or payload > MAX_FATBIN - 16 or payload > len(data) - start - 16: raise FormatError("invalid fatbin size")
    total = 16 + payload; end = start + total; at = start + 16; entries: list[FatEntry] = []
    while at < end:
        if end - at < 64 or len(entries) >= 32: raise FormatError("invalid fatbin entry bounds")
        kind, tag, header, stored = u16(data, at), u16(data, at + 2), u32(data, at + 4), u64(data, at + 8)
        if kind not in (1, 2) or tag != 0x101 or header < 64 or header > 4096 or header % 8 or stored % 8 or header > end - at or stored > end - at - header:
            raise FormatError("unreviewed fatbin entry layout")
        entry = FatEntry(at - start, header, stored, kind, u32(data, at + 28), u32(data, at + 16), u64(data, at + 40), u64(data, at + 56))
        if entry.compressed_size > entry.payload_size or entry.unpacked_size > MAX_PTX: raise FormatError("fatbin entry size invalid")
        entries.append(entry); at += header + stored
    if at != end or not entries: raise FormatError("empty/misaligned fatbin")
    return total, entries


def clean_ptx(raw: bytes) -> str | None:
    nul = raw.find(b"\0")
    if nul < 0: return None
    try: text = raw[:nul].decode("utf-8")
    except UnicodeDecodeError: return None
    text = re.sub(r'/\*.*?\*/', lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()), text, flags=re.S)
    text = re.sub(r'//[^\n]*', lambda m: ' ' * len(m.group()), text)
    text = re.sub(r'"(?:\\.|[^"\\\n])*"', lambda m: ' ' * len(m.group()), text)
    return text


def ptx_audit(raw: bytes) -> dict[str, Any]:
    text = clean_ptx(raw)
    if text is None: return {"result": "UNKNOWN", "nvidia_isa_sm86": "unknown", "reno_policy": {"accepted": False, "reason": "missing NUL or invalid UTF-8"}, "matches": {}}
    versions = re.findall(r'^\s*\.version\s+([^\s]+)\s*$', text, re.M)
    targets = list(re.finditer(r'^\s*\.target\s+(sm_\d+)\s*$', text, re.M))
    addresses = re.findall(r'^\s*\.address_size\s+([^\s]+)\s*$', text, re.M)
    matches = {token: [text.count('\n', 0, m.start()) + 1 for m in re.finditer(re.escape(token), text)] for token in UNSUPPORTED_SM86}
    bad = {k: v[:5] for k, v in matches.items() if v}
    target_ok = len(targets) == 1 and targets[0].group(1) == "sm_89"
    reno_ok = len(versions) == 1 and bool(re.fullmatch(r"8\.[0-7]", versions[0]))
    reno_reason = "accepted reviewed PTX version" if reno_ok else "version outside RenoDx reviewed range 8.0-8.7"
    # This is deliberately an ISA-level screen, not a claim that every PTX
    # mnemonic has been independently modelled.  Explicit post-SM86 families
    # are rejected; ordinary 7.8/8.x headers are permitted because PTX 7.8
    # explicitly supports both sm_86 and sm_89.
    isa_ok = target_ok and len(versions) == 1 and bool(re.fullmatch(r"[78]\.\d+", versions[0])) and len(addresses) == 1 and addresses[0] == "64" and ".entry" in text and not bad
    isa_result = "compatible" if isa_ok else ("incompatible" if bad else "unknown" if not target_ok or not versions or not addresses else "incompatible")
    result = "SM86_STATIC_COMPATIBLE" if isa_result == "compatible" else "SM86_STATIC_INCOMPATIBLE" if isa_result == "incompatible" else "UNKNOWN"
    return {"result": result, "nvidia_isa_sm86": isa_result, "reno_policy": {"accepted": reno_ok, "reason": reno_reason}, "versions": versions, "targets": [m.group(1) for m in targets], "addresses": addresses, "matches": bad,
            "rule": "MFGAmpereUnlock-RenoDx a111c62e ampere_ptx.hpp: reject wgmma., tcgen05., tensormap., cp.async.bulk, .e4m3, .e5m2, .e2m1; require exactly one .version 8.0-8.7, .target sm_89, .address_size 64, .entry"}


def requirements_store(image: bytearray, rva: int, arch: int) -> dict[str, Any]:
    if rva <= 0 or rva + 0x600 > len(image): return {"valid": False, "reason": "export/window outside virtual image"}
    hits = [rva + i for i in range(0x600 - 7) if image[rva+i:rva+i+3] == b"\xC7\x44\x24" and u32(image, rva+i+4) == arch]
    return {"valid": len(hits) == 1, "matches": hits, "reason": None if len(hits) == 1 else "architecture stack-store is not unique"}


def analyze(path: Path) -> dict[str, Any]:
    raw = path.read_bytes(); pe = PEImage(raw); exports = pe.exports()
    result: dict[str, Any] = {"analyzer_version": ANALYZER_VERSION, "path": str(path), "file_size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
        "exports": {}, "architecture": {}, "fatbins": [], "ptx_payloads": [], "simulated_edits": [],
        "upstream_reference": {"mcsoderh": "21a2b9931f0c13f46a4b3b8a5856620d9698f88e", "nefh": "a111c62e7a3f10ca5dc392d23382775f15138822"}}
    wanted = ["NVSDK_NGX_GetGPUArchitecture", "NVSDK_NGX_D3D12_GetFeatureRequirements", "NVSDK_NGX_VULKAN_GetFeatureRequirements"]
    for name in wanted: result["exports"][name] = {"rva": exports.get(name), "file_offset": pe.file_offset(exports[name]) if name in exports else None}
    arch_rva = exports.get(wanted[0]); arch = None
    if arch_rva is not None and pe.contains(arch_rva, 6) and pe.image[arch_rva] == 0xB8 and pe.image[arch_rva+5] == 0xC3:
        arch = u32(pe.image, arch_rva + 1); result["architecture"] = {"valid": arch > 0x170 and (arch & ~0xff) == 0x100, "original": hex(arch), "site_rva": arch_rva, "site_file_offset": pe.file_offset(arch_rva + 1), "simulated_target": "0x170"}
        result["simulated_edits"].append({"mapped_rva": arch_rva + 1, "file_offset": pe.file_offset(arch_rva + 1), "before": pe.image[arch_rva+1], "after": 0x70, "reason": "simulate architecture immediate low byte -> 0x170"})
    else: result["architecture"] = {"valid": False, "reason": "GetGPUArchitecture is not recognizable B8 imm32 C3"}
    gates_ok = bool(result["architecture"].get("valid"))
    for name in wanted[1:]:
        rva = exports.get(name)
        gate = requirements_store(pe.image, rva, arch) if rva is not None and arch is not None else {"valid": False, "reason": "missing prerequisite"}
        result["exports"][name]["requirements_store"] = gate
        if name.endswith("D3D12_GetFeatureRequirements"): gates_ok &= gate["valid"]
        if gate.get("valid"):
            at = gate["matches"][0] + 4
            result["simulated_edits"].append({"mapped_rva": at, "file_offset": pe.file_offset(at), "before": pe.image[at], "after": 0x70, "reason": "simulate requirements architecture immediate low byte -> 0x170"})
    fatbin_errors = []; ptx_ok = []; found = 0; fatbin_index = 0
    for rva in range(0, len(pe.image) - 3, 4):
        if u32(pe.image, rva) != FATBIN_MAGIC: continue
        try: total, entries = parse_fatbin(pe.image, rva)
        except FormatError as e: fatbin_errors.append({"rva": rva, "error": str(e)}); continue
        found += 1; fatbin_index += 1
        container = {"index": fatbin_index - 1, "mapped_rva": rva, "file_offset": pe.file_offset(rva), "total_size": total, "entries": []}
        for entry in entries:
            item = {"kind": "ptx" if entry.kind == 1 else "cubin", "architecture": entry.arch, "mapped_rva": rva+entry.offset, "payload_rva": rva+entry.payload_offset, "file_offset": pe.file_offset(rva+entry.offset), "compressed": bool(entry.flags & 0x2000), "compressed_size": entry.compressed_size, "unpacked_size": entry.unpacked_size}
            container["entries"].append(item)
            if entry.kind == 1 and entry.arch == 89:
                payload = bytes(pe.image[rva+entry.payload_offset:rva+entry.payload_offset+entry.compressed_size])
                report: dict[str, Any] = {"fatbin_index": fatbin_index - 1, "container_rva": rva, "entry_rva": rva+entry.offset, "payload_rva": rva+entry.payload_offset, "file_offset": pe.file_offset(rva+entry.payload_offset), "compressed_size": entry.compressed_size, "unpacked_size": entry.unpacked_size, "compressed_sha256": hashlib.sha256(payload).hexdigest()}
                try:
                    # RTX30MFG-Unlock's current general contract requires the
                    # compression bit, while RenoDx's narrower profile uses
                    # 0x2041 for its reviewed layouts.  Record the exact value
                    # in inventory; do not reject another compressed layout here.
                    if not (entry.flags & 0x2000) or not entry.compressed_size or not entry.unpacked_size: raise FormatError("requires compressed PTX with a declared size")
                    decoded, _ = lz4_decompress(payload, entry.unpacked_size); report["sha256"] = hashlib.sha256(decoded).hexdigest(); report["audit"] = ptx_audit(decoded)
                    report["version"] = report["audit"].get("versions", []); report["target"] = report["audit"].get("targets", []); report["address_size"] = report["audit"].get("addresses", [])
                    report["entry_names"] = re.findall(r"\.entry\s+([A-Za-z_.$][\w.$]*)", decoded.decode("utf-8", "ignore"))
                    report["instruction_mnemonics"] = sorted(set(re.findall(r"^\s*([A-Za-z][\w.]*)\s+", decoded.decode("utf-8", "ignore"), re.M)))
                    directive = b".target sm_89"; hits = [m.start() for m in re.finditer(re.escape(directive), decoded)]
                    if len(hits) != 1 or (hits[0] and decoded[hits[0]-1] != 10): raise FormatError(".target sm_89 is not unique at a line start")
                    digit = hits[0] + len(directive) - 1; _, literal = lz4_decompress(payload, entry.unpacked_size, digit)
                    if literal is None or payload[literal] != ord("9"): raise FormatError("target digit is not a literal")
                    changed = bytearray(payload); changed[literal] = ord("6"); decoded_changed, _ = lz4_decompress(bytes(changed), entry.unpacked_size)
                    expected = bytearray(decoded); expected[digit] = ord("6")
                    if decoded_changed != expected: raise FormatError("literal edit changes more than target digit")
                    report["target_validation"] = "valid"; report["simulation"] = "valid"; ptx_ok.append(report["audit"]["result"] == "SM86_STATIC_COMPATIBLE")
                    result["simulated_edits"].extend([{ "mapped_rva": rva+entry.payload_offset+literal, "file_offset": pe.file_offset(rva+entry.payload_offset+literal), "before": ord("9"), "after": ord("6"), "reason": "independent LZ4 literal producing final digit of .target sm_89"}, {"mapped_rva": rva+entry.offset+28, "file_offset": pe.file_offset(rva+entry.offset+28), "before": 89, "after": 86, "reason": "simulate fatbin PTX architecture 89 -> 86"}])
                    following = entries[entries.index(entry)+1:]
                    if following and all(x.kind == 2 for x in following):
                        report["hidden_cubins"] = len(following); report["simulated_container_payload_size"] = entry.end - 16
                    elif following: raise FormatError("entries after sm89 PTX are not all cubins")
                except FormatError as e: report["target_validation"] = "invalid"; report["simulation"] = str(e); ptx_ok.append(False)
                result["ptx_payloads"].append(report)
        result["fatbins"].append(container)
    result["fatbin_errors"] = fatbin_errors
    result["ptxas_sm86"] = offline_ptxas(result["ptx_payloads"], pe)
    for item, compiler_result in zip(result["ptx_payloads"], result["ptxas_sm86"].get("results", [])):
        item["ptxas_sm86"] = {k: v for k, v in compiler_result.items() if k != "index"}
    audit_incompatible = any(p.get("audit", {}).get("result") == "SM86_STATIC_INCOMPATIBLE" for p in result["ptx_payloads"])
    structural = gates_ok and found > 0 and bool(ptx_ok) and all(ptx_ok)
    result["structure_passes"] = structural
    result["verdict"] = ("COMPATIBLE_FOR_SM86_STATIC_RESEARCH" if structural else
                         "INCOMPATIBLE_ARCHITECTURE_LAYOUT" if not gates_ok else
                         "INCOMPATIBLE_PTX" if audit_incompatible else "INCOMPATIBLE_FATBIN_LAYOUT")
    reno_all = all(p.get("audit", {}).get("reno_policy", {}).get("accepted", False) for p in result["ptx_payloads"])
    mcsoderh_structural = bool(ptx_ok) and all(ptx_ok)
    result["reno_policy"] = {"accepted": reno_all, "reason": "all payloads in 8.0-8.7" if reno_all else "one or more payloads outside 8.0-8.7 reviewed range"}
    result["mcsoderh_policy"] = {"accepted": mcsoderh_structural, "reason": "container/LZ4/target literal structure passes" if mcsoderh_structural else "one or more structural retarget checks failed"}
    if result["ptxas_sm86"].get("tested") and result["ptxas_sm86"].get("passed") is True and gates_ok and mcsoderh_structural:
        result["verdict"] = "COMPATIBLE_BUT_OUTSIDE_RENO_REVIEWED_POLICY" if not reno_all else "COMPATIBLE_FOR_SM86_STATIC_RESEARCH"
    return result


def offline_ptxas(payloads: list[dict[str, Any]], pe: PEImage) -> dict[str, Any]:
    """Compile decompressed PTX in a temporary directory, if ptxas exists."""
    exe = shutil.which("ptxas")
    if not exe: return {"tested": False, "passed": None, "status": "PTXAS_UNAVAILABLE"}
    results = []
    with tempfile.TemporaryDirectory(prefix="dlssg-ptxas-") as td:
        for index, item in enumerate(payloads):
            rva = item["payload_rva"]; size = item["compressed_size"]; raw_size = item["unpacked_size"]
            try:
                # Recover the mapped payload and decode it from the private image.
                payload = bytes(pe.image[rva:rva + size]); decoded, _ = lz4_decompress(payload, raw_size)
                # Provider PTX payloads are NUL-terminated; ptxas expects
                # source text, so omit only that container terminator.
                text = decoded.split(b"\0", 1)[0].decode("utf-8")
                text, count = re.subn(r"(?m)^(\s*\.target\s+)sm_89(\s*)$", r"\1sm_86\2", text, count=1)
                if count != 1: raise FormatError("target replacement was not unique")
                ptx = os.path.join(td, f"payload-{index}.ptx"); cubin = os.path.join(td, f"payload-{index}.cubin")
                Path(ptx).write_text(text, encoding="utf-8", newline="")
                proc = subprocess.run([exe, "-arch=sm_86", ptx, "-o", cubin], capture_output=True, text=True, timeout=60)
                results.append({"index": index, "passed": proc.returncode == 0, "exit_code": proc.returncode, "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-4000:]})
            except Exception as exc: results.append({"index": index, "passed": False, "reason": str(exc)})
    return {"tested": True, "passed": bool(results) and all(x.get("passed") for x in results), "compiled": sum(x.get("passed", False) for x in results), "total": len(results), "version": "ptxas NVIDIA CUDA 13.1 V13.1.80", "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only static DLSS-G Ampere compatibility analyzer")
    parser.add_argument("--dll", required=True, type=Path); parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try: report = analyze(args.dll)
    except (OSError, FormatError) as e:
        report = {"analyzer_version": ANALYZER_VERSION, "path": str(args.dll), "verdict": "UNKNOWN", "error": str(e)}
    if args.json: print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"{report['path']}: {report['verdict']}")
        print(f"sha256={report.get('sha256', 'n/a')} fatbins={len(report.get('fatbins', []))} sm89_ptx={len(report.get('ptx_payloads', []))} simulated_edits={len(report.get('simulated_edits', []))}")
        if report.get('error'): print(f"error: {report['error']}")
    return 0 if "error" not in report else 2

if __name__ == "__main__": raise SystemExit(main())
