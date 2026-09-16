"""Pinned DLSS-G runtime profiles and compatibility identity policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


C55_WORKER_SHA256 = "C55A7BD1E39D59DF58C73783648EB9BD49D51BD6AAD21F1D7C8BE4D13D9B6916"
LEGACY_RUNTIME_SHA256 = "C844646D835A7B88ED1382EEA80403D38B433F8AC09CF92581C73698C44AE7C2"
LEGACY_RUNTIME_SIZE = 15667520
LEGACY_INI_SHA256 = "FD7F0722194E6E8D8C085327D9826EFFB411925A69A5E7549D70EFF26A9F18B5"
LEGACY_INI_SIZE = 581
CANDIDATE_SOURCE_COMMIT = "117faf5c70333b34160f5d21d01c222261cc5af1"
CANDIDATE_RUNTIME_SHA256 = "3D4C7D537A6E71E3A9D41FFC6487E054B26C56D27B7C0825D39EAA7EF0C7E86D"
CANDIDATE_RUNTIME_SIZE = 29676832
CANDIDATE_INI_SHA256 = "231574047C4989D292E592802102D2437FC636B56E535E8D70D403F20D4CCAFC"
CANDIDATE_INI_SIZE = 2727
CANDIDATE_NOTICE_SHA256 = "AC3B44AB30A4235EDD18FECA1AB4F802D57C8D3D0EE4878DC77B81A6B127155F"
CANDIDATE_NOTICE_SIZE = 3349


@dataclass(frozen=True)
class DlssgRuntimeProfile:
    name: str
    runtime_sha256: str
    runtime_size: int
    ini_sha256: str | None
    ini_size: int | None
    source_commit: str | None
    multipliers: tuple[int, ...]
    compatibility_required: bool
    validation_state: str


PROFILES = {
    "legacy": DlssgRuntimeProfile(
        "legacy", LEGACY_RUNTIME_SHA256, LEGACY_RUNTIME_SIZE,
        LEGACY_INI_SHA256, LEGACY_INI_SIZE, "5f62ff44a9c08f9841fa605e7b7160f79ccd2c40",
        (2, 3, 4), False, "NATIVE_VALIDATED",
    ),
    "candidate-0.3.1": DlssgRuntimeProfile(
        "candidate-0.3.1", CANDIDATE_RUNTIME_SHA256, CANDIDATE_RUNTIME_SIZE,
        CANDIDATE_INI_SHA256, CANDIDATE_INI_SIZE, CANDIDATE_SOURCE_COMMIT,
        (2, 3, 4), True, "COMPATIBILITY_TEST_REQUIRED",
    ),
}


def profile(name: str) -> DlssgRuntimeProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown DLSS-G runtime profile: {name}") from exc


def managed_runtime_paths(root: Path, name: str) -> tuple[Path, Path]:
    folder = "legacy" if name == "legacy" else "candidate-0.3.1"
    base = root / "runtime" / "dlssg" / folder
    return base / "version.dll", base / "dlssg_sm86.ini"
