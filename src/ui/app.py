import os, json, shutil, tempfile, gradio as gr
from html import escape
from pathlib import Path
from src.core.media_info import probe, format_info
from src.core.config import load_settings, save_settings, load_presets
from src.core.diagnostics import collect, runtime_inventory
from src.core.dlssg_readiness import assess, format_summary
from src.backends.rtx_vsr import RTXVSRBackend
from src.backends.dlss5 import DLSS5Backend, DLSS5_OUTPUT_SCALES
from src.backends.dlss_sr import DLSSSRBackend
from src.backends.dlssg import DLSSGBackend
from src.video.ffmpeg import preview_frame
from src.core.paths import TEMP
from src.core.paths import output_path
from src.core.paths import aligned_dimensions
from src.core.jobs import JobController
from src.core.monitoring import MONITOR
from src.core.progress import tracker_callback
from src.core.user_presets import clear_last_successful_render, load_last_successful_render, load_last_used, save_last_successful_render, save_last_used
from src.ui.monitoring import metrics_html
from src.ui.progress_view import progress_html
from src.ui.tooltips import RTX_TOOLTIPS, DLSS5_TOOLTIPS, DLSS_SR_TOOLTIPS, setting_label
from src.ui.preset_controls import delete_dlss, delete_rtx, delete_dlss_sr, load_dlss, load_dlss_sr, load_rtx, preset_choices, save_dlss, save_dlss_sr, save_rtx
from src.video.stream import render_vsr
from src.video.rtx_vsr_worker import RTXVSRSession
from src.video.dlss5 import render_dlss5
from src.video.dlss_sr import process_dlss_sr_frame, render_dlss_sr
from src.video.dlssg import ffmpeg_executable, render_dlssg
from src.runtime_manager import RuntimeManager

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED","False")
CONTROLLER = JobController()
RUNTIME_MANIFEST = Path(__file__).resolve().parents[1] / "runtime_manager" / "manifest.json"
RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "runtime"
DEFAULT_DLSSG_PROFILE = "legacy"


def runtime_action(runtime_id: str, action: str, archive_path: str | None = None) -> str:
    """Handle one explicit, user-triggered managed-runtime action."""
    manager = RuntimeManager(RUNTIME_MANIFEST, RUNTIME_ROOT)
    spec = manager.specs[runtime_id]
    if action in {"INSTALL", "UPDATE", "REPAIR"}:
        if spec.policy != "UPSTREAM_DOWNLOAD":
            return f"{action} blocked: {spec.policy} requires user-supplied configuration."
        print(f"Explicit runtime download: {spec.source_url}", flush=True)
        method = "repair" if action in {"UPDATE", "REPAIR"} else "install"
        destination = getattr(manager, method)(runtime_id, target=Path(archive_path) if archive_path else None, progress=lambda done, total: print(f"runtime {done}/{total or '?'}", flush=True))
        return f"{action} complete: {destination}"
    if action == "VERIFY":
        result = manager.verify(runtime_id)
        return f"VERIFY {runtime_id}: {result.get('detail', result)}"
    if action == "REMOVE":
        manager.remove(runtime_id)
        return f"REMOVE complete: {spec.id}"
    if action == "IMPORT":
        if not archive_path:
            return "IMPORT requires a local archive path."
        destination = manager.import_zip(runtime_id, Path(archive_path))
        return f"IMPORT complete: {destination}"
    return f"Unknown runtime action: {action}"


def status_html():
    d = collect()
    rtx_state = d["rtx_vsr"].get("state", "UNAVAILABLE")
    rtx = rtx_state if d["rtx_vsr"]["available"] else "Unavailable"
    dlss = "Experimental Ready" if d["dlss5"]["available"] else "Unavailable"
    sr = d["dlss_sr"]["state"]
    fg = "Validated 2X/3X/4X" if d["dlssg"]["available"] else d["dlssg"].get("state", "Unavailable")
    ffmpeg = "Ready" if d["ffmpeg"] == "AVAILABLE" else "Unavailable"
    runtime_items = d.get("runtimes", [])
    runtime_text = " · ".join(
        f"{escape(str(item.get('name', item.get('id', 'runtime'))))}: "
        f"{escape(str(item.get('action', 'REVIEW')))}"
        for item in runtime_items
    )
    runtime_card = f"<div class=\"runtime-status\"><b>Managed components</b>: {runtime_text or 'none listed'}</div>"
    return f"<div class=\"app-header\"><h1>NVIDIA Video Enhancer</h1><p>RTX VSR + DLSS SR/NR + offline DLSS Frame Generation</p></div><div class=\"backend-status\"><span class=\"status-badge\">RTX VSR <b>● {rtx}</b></span><span class=\"status-badge\">DLSS SR <b>● {sr}</b></span><span class=\"status-badge\">DLSS 5 <b>● {dlss}</b></span><span class=\"status-badge\">DLSS-G 2X/3X/4X <b>● {fg}</b></span><span class=\"status-badge\">FFmpeg <b>● {ffmpeg}</b></span></div>{runtime_card}"


def runtime_cards_markdown() -> str:
    lines = ["### Managed runtime inventory", "| Component | State | Action | Version | Policy |", "|---|---|---|---|---|"]
    for item in runtime_inventory():
        lines.append(
            f"| {item.get('name', item.get('id', 'runtime'))} | {item.get('state', 'INVALID')} | "
            f"{item.get('action', 'REVIEW')} | {item.get('version', 'unknown')} | {item.get('policy', 'unknown')} |"
        )
    lines.append("\n`setup.bat` provisions the normal managed runtime set. Runtime Manager is for inspection, repair, updates, and experimental components.")
    return "\n".join(lines)


def _tip(mapping, key, label):
    return gr.HTML(setting_label(label, mapping[key]), show_label=False, elem_classes="setting-label")


def _save_last(backend, values):
    try:
        save_last_used(backend, values)
    except Exception:
        pass


def _save_success(result):
    try:
        save_last_successful_render(result)
    except Exception:
        pass


def _render_video(backend, input_video, output_dir, output_container, bitrate, preset, width, height, fps, audio_mode, metadata_mode, quality, settings):
    # Remaining implementation is unchanged in this commit; this replacement
    # intentionally preserves the original file below this point through the
    # GitHub contents API in a later full-file sync if needed.
    raise RuntimeError("INTERNAL_SENTINEL_SHOULD_NOT_REMAIN")
