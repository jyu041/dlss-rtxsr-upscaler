from dataclasses import replace
import io

import pytest

from src.backends.dlss5_v10_protocol import OutputEvidence
from src.video import dlss5_v10 as video


class ShortReadStream:
    def __init__(self, data: bytes, chunk: int):
        self.stream = io.BytesIO(data)
        self.chunk = chunk

    def read(self, size: int) -> bytes:
        return self.stream.read(min(size, self.chunk))


def evidence(*, reset=0, create=1, evaluate=1, cuda=0, timestamp=7, width=4, height=3):
    return OutputEvidence(
        width=width,
        height=height,
        timestamp=timestamp,
        ngx_create_result=create,
        ngx_evaluate_result=evaluate,
        cuda_result=cuda,
        scene_reset=reset,
        scene_score=0.0,
        upload_bytes=width * height * 4,
        download_bytes=width * height * 4,
        rgba=bytes(width * height * 4),
    )


def test_v10_app_frame_reader_handles_short_pipe_reads():
    expected = bytes(range(48))
    stream = ShortReadStream(expected, 5)
    assert video._read_exact_frame(stream, len(expected)) == expected
    assert video._read_exact_frame(stream, len(expected)) == b""


def test_v10_app_frame_reader_rejects_truncated_frame():
    with pytest.raises(RuntimeError, match="truncated RGBA frame"):
        video._read_exact_frame(ShortReadStream(b"short", 2), 16)


def test_v10_app_output_validation_accepts_success():
    video._validate_output(
        evidence(reset=1),
        width=4,
        height=3,
        timestamp=7,
        reset=True,
    )


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("ngx_create_result", -1, "create did not return success"),
        ("ngx_evaluate_result", -1, "evaluate did not return success"),
        ("cuda_result", 1, "CUDA result"),
        ("scene_reset", 1, "scene_reset"),
        ("timestamp", 8, "timestamp"),
    ],
)
def test_v10_app_output_validation_rejects_invalid_evidence(field, value, match):
    output = replace(evidence(reset=0), **{field: value})
    with pytest.raises(RuntimeError, match=match):
        video._validate_output(
            output,
            width=4,
            height=3,
            timestamp=7,
            reset=False,
        )


def test_v10_app_encoder_forces_sdr_420_compatibility():
    source = open("src/video/dlss5_v10.py", encoding="utf-8").read()
    assert video.SDR_ENCODER_PIXEL_FORMAT == "yuv420p"
    assert '"-pix_fmt",' in source
    assert "SDR_ENCODER_PIXEL_FORMAT" in source


def test_v10_app_renderer_supports_shared_reduced_resolution_pipeline():
    source = open("src/video/dlss5_v10.py", encoding="utf-8").read()
    assert "resolve_working_scale" in source
    assert "compute_working_dimensions" in source
    assert "downsample_for_nr" in source
    assert "residual_recompose_cpu" in source
    assert "CudaResidualCompositor" in source
    assert "TemporalResidualStabilizer" in source
    assert "nr_working_scale_requested" in source
    assert "nr_working_scale_resolved" in source
    assert "recompose_backend_used" in source
    assert "temporal_stabilization" in source


def test_v10_app_renderer_source_preserves_containment_and_scene_resets():
    source = open("src/video/dlss5_v10.py", encoding="utf-8").read()
    assert "install_temporary_firewall_block" in source
    assert "remove_temporary_firewall_block" in source
    assert "start_native_application_experimental" in source
    assert "assert_no_host_descendants" in source
    assert "scene_cut_metrics" in source
    assert 'if bool(cut["is_cut"])' in source
    assert "client.close()" in source
    assert "client.abort()" in source
    assert "output.ngx_create_result" in source
    assert "output.ngx_evaluate_result" in source
    assert "output.cuda_result" in source


def test_v10_app_host_source_has_dynamic_geometry_but_1x_cap():
    source = open("src/backends/dlss5_v10_host.py", encoding="utf-8").read()
    assert "--experimental-native-app-serve" in source
    assert "experimental_application_server" in source
    assert "APP_MAX_LONG_EDGE = 1920" in source
    assert "APP_MAX_SHORT_EDGE = 1080" in source
    assert "create.processing_scale != 1.0" in source
    assert "create.input_width" in source
    assert "create.input_height" in source
    assert "FrameRequest.decode(" in source
