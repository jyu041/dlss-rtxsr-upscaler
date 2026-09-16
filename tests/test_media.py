import json
import subprocess

from src.core import media_info
from src.core.media_info import format_info


def test_media_format():
    s=format_info({"filename":"中 文.mp4","width":720,"height":405,"fps":30,"duration":3,"codec":"h264","pixel_format":"yuv420p","bit_depth":"8","audio_codec":"aac","frames":90})
    assert "720 x 405" in s and "中 文.mp4" in s


def test_probe_decodes_utf8_json_for_unicode_path(tmp_path, monkeypatch):
    source = tmp_path / "synthetic_unicode_тест.mp4"
    source.touch()
    payload = {
        "streams": [
            {"codec_type": "video", "width": 128, "height": 128, "avg_frame_rate": "30/1", "codec_name": "h264", "pix_fmt": "yuv420p"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "3.0", "size": "1234"},
    }
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, json.dumps(payload, ensure_ascii=False), "")

    monkeypatch.setattr(media_info, "run", fake_run)
    monkeypatch.setattr(media_info, "tool", lambda name: "ffprobe")
    result = media_info.probe(source)
    assert result["filename"] == source.name
    assert result["path"] == str(source.resolve())
    assert result["width"] == 128 and result["audio_codec"] == "aac"
    assert seen["kwargs"]["encoding"] == "utf-8"
    assert seen["kwargs"]["errors"] == "replace"
