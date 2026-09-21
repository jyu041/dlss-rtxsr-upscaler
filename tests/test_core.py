import json
from pathlib import Path
import pytest
from src.core.config import valid_dlss
from src.core.paths import output_path
from src.core.paths import aligned_dimensions
from src.core.jobs import Job
from src.video.ffmpeg import validate

def test_dlss_validation():
    assert valid_dlss({"dlss_intensity":.5,"local_tone":0,"local_structure":2,"skin_structure":-1})
    assert not valid_dlss({"dlss_intensity":2.1,"local_tone":0,"local_structure":0,"skin_structure":0})
def test_output_is_timestamped_and_does_not_overwrite_source(monkeypatch, tmp_path):
    from src.core import paths
    monkeypatch.setattr(paths, "OUTPUTS", tmp_path)
    monkeypatch.setattr(paths, "_output_timestamp", lambda: "20260922_015301")
    p=output_path(Path("clip.mp4"),"RTX VSR only","MP4",2)
    assert p.name == "clip_20260922_015301_rtxvsr_2x.mp4"
    assert p.parent == tmp_path


def test_output_same_second_uses_collision_counter(monkeypatch, tmp_path):
    from src.core import paths
    monkeypatch.setattr(paths, "OUTPUTS", tmp_path)
    monkeypatch.setattr(paths, "_output_timestamp", lambda: "20260922_015301")
    first = output_path(Path("clip.mp4"), "DLSS 5 only", "MP4", 1)
    first.write_bytes(b"old generation")
    second = output_path(Path("clip.mp4"), "DLSS 5 only", "MP4", 1)
    second.write_bytes(b"new generation")
    third = output_path(Path("clip.mp4"), "DLSS 5 only", "MP4", 1)
    assert first.name == "clip_20260922_015301_dlss5.mp4"
    assert second.name == "clip_20260922_015301_2_dlss5.mp4"
    assert third.name == "clip_20260922_015301_3_dlss5.mp4"
    assert first.read_bytes() == b"old generation"
    assert second.read_bytes() == b"new generation"


@pytest.mark.parametrize(
    ("mode", "scale", "multiplier", "expected_tag"),
    [
        ("DLSS 5 only", 1.0, 2, "dlss5"),
        ("DLSS SR only", 1.0, 2, "dlss_sr"),
        ("DLSS Frame Generation 2X", 1.0, 4, "dlssg_4x"),
        ("RTX VSR only", 3.0, 2, "rtxvsr_3x"),
    ],
)
def test_output_timestamp_precedes_enhancement_tag(monkeypatch, tmp_path, mode, scale, multiplier, expected_tag):
    from src.core import paths
    monkeypatch.setattr(paths, "OUTPUTS", tmp_path)
    monkeypatch.setattr(paths, "_output_timestamp", lambda: "20260922_015301")
    p = output_path(Path("inputA.mp4"), mode, "MP4", scale, multiplier)
    assert p.name == f"inputA_20260922_015301_{expected_tag}.mp4"
def test_invalid_codec_container():
    with pytest.raises(ValueError): validate("ProRes","MP4")
    with pytest.raises(ValueError): validate("AV1","MOV")
def test_cancel_state():
    j=Job(); assert not j.cancel_event.is_set(); j.cancel(); assert j.cancel_event.is_set()
def test_aligned_dimensions():
    assert aligned_dimensions(721, 405, 2) == (1440, 808)
    assert aligned_dimensions(721, 405, target=(1921,1081)) == (1920,1080)
