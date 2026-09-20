"""Application-facing facade for the isolated DLSS5 Visual Enhancer v10 path."""

from __future__ import annotations

from pathlib import Path

from .base import Backend, BackendStatus
from .dlss5_v10_protocol import CreateRequest
from .dlss5_v10_security import validate_preflight_report


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V10_RUNTIME = (
    ROOT
    / "runtime"
    / "dlss5"
    / "neuroframe-v10-candidate"
    / "bin"
    / "runtime"
    / "dlssnr"
)
DEFAULT_V10_PREFLIGHT = ROOT / "runtime" / "audit" / "dlss5-v10-preflight.json"
APP_MAX_LONG_EDGE = 1920
APP_MAX_SHORT_EDGE = 1080
APP_SUPPORTED_SCALE = 1.0

STYLE_MAP = {
    "Default": 0,
    "Natural": 1,
    "Cinematic": 2,
}


class DLSS5V10ExperimentalBackend(Backend):
    """Fail-closed v10 backend for the explicit experimental UI mode."""

    def __init__(
        self,
        runtime_dir: str | Path = DEFAULT_V10_RUNTIME,
        preflight_report: str | Path = DEFAULT_V10_PREFLIGHT,
        *,
        gpu_ordinal: int = 0,
    ) -> None:
        self.runtime_dir = Path(runtime_dir).expanduser().resolve()
        self.preflight_report = Path(preflight_report).expanduser().resolve()
        self.gpu_ordinal = int(gpu_ordinal)

    def status(self) -> BackendStatus:
        if not self.runtime_dir.is_dir():
            return BackendStatus(
                "DLSS 5 v10 Experimental",
                False,
                "RUNTIME NOT STAGED",
                f"staged v10 runtime is missing: {self.runtime_dir}",
            )
        if not self.preflight_report.is_file():
            return BackendStatus(
                "DLSS 5 v10 Experimental",
                False,
                "PREFLIGHT REQUIRED",
                "run the explicit v10 preflight/Defender refresh before application use",
            )
        try:
            report = validate_preflight_report(
                self.runtime_dir,
                self.preflight_report,
            )
        except Exception as exc:
            return BackendStatus(
                "DLSS 5 v10 Experimental",
                False,
                "PREFLIGHT REQUIRED",
                str(exc),
            )
        age = float(report.get("preflight_age_seconds", 0.0))
        return BackendStatus(
            "DLSS 5 v10 Experimental",
            True,
            "EXPERIMENTAL READY",
            (
                "isolated Feature-18 v10 application path is ready at 1.0x "
                f"with a clean preflight {age / 60.0:.1f} minutes old"
            ),
        )

    def require_ready(self) -> None:
        status = self.status()
        if not status.available:
            raise RuntimeError(
                f"DLSS 5 v10 experimental backend unavailable: {status.reason}"
            )

    @staticmethod
    def validate_geometry(width: int, height: int, scale: float = 1.0) -> None:
        if float(scale) != APP_SUPPORTED_SCALE:
            raise RuntimeError(
                "DLSS 5 v10 experimental application mode currently supports only 1.0x"
            )
        long_edge = max(int(width), int(height))
        short_edge = min(int(width), int(height))
        if (
            long_edge > APP_MAX_LONG_EDGE
            or short_edge > APP_MAX_SHORT_EDGE
        ):
            raise RuntimeError(
                "DLSS 5 v10 experimental application mode currently supports "
                f"up to {APP_MAX_LONG_EDGE}x{APP_MAX_SHORT_EDGE}-equivalent input"
            )

    def create_request(
        self,
        width: int,
        height: int,
        *,
        scale: float = APP_SUPPORTED_SCALE,
        style: str = "Natural",
        intensity: float = 0.60,
        local_tone: float = 0.40,
        local_structure: float = 0.40,
        skin_structure: float = 0.15,
        automatic_mask: bool = False,
        nr_passes: int = 1,
        color_strength: float = 1.0,
        tone_preservation: float = 0.0,
        face_skin_protection: float = 0.0,
        grain_preservation: float = 0.0,
        shimmer_suppression: float = 0.70,
        prefer_nvof: bool = False,
    ) -> CreateRequest:
        self.validate_geometry(width, height, scale)
        if style not in STYLE_MAP:
            raise ValueError(f"unsupported v10 style: {style}")
        return CreateRequest(
            int(width),
            int(height),
            gpu_ordinal=self.gpu_ordinal,
            processing_scale=float(scale),
            style=STYLE_MAP[style],
            intensity=float(intensity),
            nr_passes=int(nr_passes),
            local_tone=float(local_tone),
            local_structure=float(local_structure),
            skin_structure=float(skin_structure),
            color_strength=float(color_strength),
            tone_preservation=float(tone_preservation),
            face_skin_protection=float(face_skin_protection),
            grain_preservation=float(grain_preservation),
            shimmer_suppression=float(shimmer_suppression),
            automatic_mask=bool(automatic_mask),
            prefer_nvof=bool(prefer_nvof),
        ).validate()

    def close(self) -> None:
        return None
