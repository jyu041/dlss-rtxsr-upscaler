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
def test_output_does_not_overwrite_source():
    p=output_path(Path("clip.mp4"),"RTX VSR only","MP4",2)
    assert p.name == "clip_rtxvsr_2x.mp4" and p.parent.name == "outputs"
def test_invalid_codec_container():
    with pytest.raises(ValueError): validate("ProRes","MP4")
    with pytest.raises(ValueError): validate("AV1","MOV")
def test_cancel_state():
    j=Job(); assert not j.cancel_event.is_set(); j.cancel(); assert j.cancel_event.is_set()
def test_aligned_dimensions():
    assert aligned_dimensions(721, 405, 2) == (1440, 808)
    assert aligned_dimensions(721, 405, target=(1921,1081)) == (1920,1080)
