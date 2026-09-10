"""Bounded, inspect-only NVENC capability checks."""

from __future__ import annotations

import subprocess
from typing import Any

from src.core.process_utils import tool

CODEC_ENCODERS = {"H.264": "h264_nvenc", "HEVC": "hevc_nvenc", "AV1": "av1_nvenc"}


def build_preflight_command(codec: str, width: int, height: int, ffmpeg: str = "ffmpeg") -> list[str]:
    encoder = CODEC_ENCODERS.get(codec)
    if encoder is None:
        raise ValueError(f"Unsupported NVENC codec: {codec}")
    if int(width) < 1 or int(height) < 1:
        raise ValueError("NVENC dimensions must be positive")
    return [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", f"color=size={int(width)}x{int(height)}:rate=1:color=black", "-frames:v", "2", "-an", "-c:v", encoder, "-f", "null", "-"]


def nvenc_preflight(codec: str, width: int, height: int, *, timeout: float = 15.0, runner=subprocess.run) -> dict[str, Any]:
    encoder = CODEC_ENCODERS.get(codec)
    ffmpeg = tool("ffmpeg")
    result: dict[str, Any] = {"available": False, "codec": codec, "encoder": encoder, "width": int(width), "height": int(height), "ffmpeg_version": None, "return_code": None, "stderr_tail": ""}
    if encoder is None:
        result["stderr_tail"] = f"Unsupported codec: {codec}"
        return result
    if not ffmpeg:
        result["stderr_tail"] = "ffmpeg was not found on PATH"
        return result
    try:
        version = runner([ffmpeg, "-version"], capture_output=True, text=True, timeout=timeout, check=False)
        result["ffmpeg_version"] = (version.stdout or "").splitlines()[0] if version.returncode == 0 else None
        checked = runner(build_preflight_command(codec, width, height, ffmpeg), capture_output=True, text=True, timeout=timeout, check=False)
        result["return_code"] = checked.returncode
        result["stderr_tail"] = (checked.stderr or "")[-2000:]
        result["available"] = checked.returncode == 0
    except subprocess.TimeoutExpired as exc:
        result["stderr_tail"] = f"FFmpeg NVENC preflight timed out after {timeout:g}s: {exc}"
    except OSError as exc:
        result["stderr_tail"] = str(exc)
    return result


def format_preflight_failure(result: dict[str, Any]) -> str:
    return ("DLSS5 Feature-18 processing reached output successfully, but the selected "
            f"FFmpeg/NVENC encoder failed its preflight ({result.get('codec')} "
            f"{result.get('width')}x{result.get('height')}, {result.get('encoder')}): "
            f"{result.get('stderr_tail') or 'unknown FFmpeg error'}")
