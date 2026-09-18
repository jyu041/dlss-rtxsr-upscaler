import numpy as np

from src.backends.dlss5_v10_protocol import OutputEvidence
import tools.validate_dlss5_v10_bounded as bounded


class FakeClient:
    def __init__(self, **kwargs):
        self.aborted = False
        self.pid = 4242

    def start_native_experimental(self, runtime, preflight, *, acknowledgement):
        assert acknowledgement == bounded.EXPERIMENT_ACK
        return {
            "native_loaded": False,
            "experimental_native_mode": True,
            "normal_backend_enabled": False,
        }

    def create(self, request):
        assert request.input_width == 256
        assert request.input_height == 256
        assert request.processing_scale == 1.0
        return {
            "native_loaded": True,
            "output_size": [256, 256],
            "initialization": {
                "gpu_name": "NVIDIA GeForce RTX 3070 Ti",
                "bridge_abi_version": 6,
                "gpu_ordinal": request.gpu_ordinal,
            },
        }

    def process_frame(self, frame):
        source = np.frombuffer(frame.rgba, dtype=np.uint8).reshape(256, 256, 4).copy()
        source[..., 0] = np.bitwise_xor(source[..., 0], 0x0F)
        return OutputEvidence(
            width=256,
            height=256,
            timestamp=frame.timestamp,
            ngx_create_result=1,
            ngx_evaluate_result=1,
            cuda_result=0,
            scene_reset=int(frame.reset),
            scene_score=0.1,
            upload_bytes=256 * 256 * 4,
            download_bytes=256 * 256 * 4,
            rgba=source.tobytes(),
        )

    def close(self):
        return "CLOSED"

    def abort(self):
        self.aborted = True
        return "TERMINATED_OWNED_HOST"


def test_bounded_v10_cli_is_blocked_without_explicit_ack(monkeypatch, tmp_path):
    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True
        return {"status": "PASS"}

    monkeypatch.setattr(bounded, "run_bounded", fake_run)
    assert bounded.main([]) == 2
    assert called["value"] is False
    assert (
        bounded.main(["--execute", "--ack", "wrong", "--output", str(tmp_path / "x.json")])
        == 2
    )
    assert called["value"] is False


def test_bounded_v10_fake_pass_installs_and_removes_firewall(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(bounded, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(bounded, "V10ProtocolClient", FakeClient)
    monkeypatch.setattr(
        bounded,
        "assert_no_host_descendants",
        lambda pid, stage: {"stage": stage, "host_pid": pid, "descendant_count": 0, "descendants": []},
    )
    monkeypatch.setattr(
        bounded,
        "install_temporary_firewall_block",
        lambda program, name: calls.append(("install", str(program), name)),
    )
    monkeypatch.setattr(
        bounded,
        "remove_temporary_firewall_block",
        lambda name: calls.append(("remove", name)),
    )

    report = bounded.run_bounded(runtime, preflight, gpu_ordinal=0)

    assert report["status"] == "PASS"
    assert report["native_executed"] is True
    assert report["normal_backend_changed"] is False
    assert report["nr_effect_observed"] is True
    assert report["feature_evidence"]["ngx_create_result"] == 1
    assert report["feature_evidence"]["ngx_evaluate_result"] == 1
    assert report["firewall_installed"] is True
    assert report["firewall_removed"] is True
    assert [item["stage"] for item in report["process_tree_checks"]] == [
        "after_hello", "after_create", "after_frame"
    ]
    assert calls[0][0] == "install"
    assert calls[-1][0] == "remove"


def test_bounded_v10_failure_before_create_keeps_native_executed_false(monkeypatch, tmp_path):
    class FailingClient(FakeClient):
        def create(self, request):
            raise RuntimeError("synthetic create failure")

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")
    calls = []

    monkeypatch.setattr(bounded, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(bounded, "V10ProtocolClient", FailingClient)
    monkeypatch.setattr(
        bounded,
        "assert_no_host_descendants",
        lambda pid, stage: {"stage": stage, "host_pid": pid, "descendant_count": 0, "descendants": []},
    )
    monkeypatch.setattr(
        bounded,
        "install_temporary_firewall_block",
        lambda program, name: calls.append(("install", name)),
    )
    monkeypatch.setattr(
        bounded,
        "remove_temporary_firewall_block",
        lambda name: calls.append(("remove", name)),
    )

    report = bounded.run_bounded(runtime, preflight, gpu_ordinal=0)

    assert report["status"] == "FAIL"
    assert report["native_executed"] is False
    assert "synthetic create failure" in report["error"]
    assert report["firewall_removed"] is True
    assert calls[-1][0] == "remove"



def test_bounded_v10_rejects_spawned_descendant(monkeypatch):
    class Child:
        pid = 99
        def is_running(self):
            return True
        def name(self):
            return "unexpected.exe"

    class Root:
        def children(self, recursive=True):
            return [Child()]

    monkeypatch.setattr(bounded.psutil, "Process", lambda pid: Root())
    with pytest.raises(RuntimeError, match="unexpected child process"):
        bounded.assert_no_host_descendants(1234, "after_create")


def test_bounded_v10_rejects_wrong_bridge_abi(monkeypatch, tmp_path):
    class WrongAbiClient(FakeClient):
        def create(self, request):
            value = super().create(request)
            value["initialization"]["bridge_abi_version"] = 5
            return value

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(bounded, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(bounded, "V10ProtocolClient", WrongAbiClient)
    monkeypatch.setattr(
        bounded,
        "assert_no_host_descendants",
        lambda pid, stage: {"stage": stage, "host_pid": pid, "descendant_count": 0, "descendants": []},
    )
    monkeypatch.setattr(bounded, "install_temporary_firewall_block", lambda *args: None)
    monkeypatch.setattr(bounded, "remove_temporary_firewall_block", lambda *args: None)

    report = bounded.run_bounded(runtime, preflight, gpu_ordinal=0)
    assert report["status"] == "FAIL"
    assert "bridge ABI 6" in report["error"]


def test_bounded_v10_rejects_unclean_close(monkeypatch, tmp_path):
    class BadCloseClient(FakeClient):
        def close(self):
            return "TERMINATED_AFTER_CLOSE_FAILURE"

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(bounded, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(bounded, "V10ProtocolClient", BadCloseClient)
    monkeypatch.setattr(
        bounded,
        "assert_no_host_descendants",
        lambda pid, stage: {"stage": stage, "host_pid": pid, "descendant_count": 0, "descendants": []},
    )
    monkeypatch.setattr(bounded, "install_temporary_firewall_block", lambda *args: None)
    monkeypatch.setattr(bounded, "remove_temporary_firewall_block", lambda *args: None)

    report = bounded.run_bounded(runtime, preflight, gpu_ordinal=0)
    assert report["status"] == "FAIL"
    assert "did not close cleanly" in report["error"]


def test_bounded_v10_cleanup_failure_forces_fail(monkeypatch, tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(bounded, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(bounded, "V10ProtocolClient", FakeClient)
    monkeypatch.setattr(
        bounded,
        "assert_no_host_descendants",
        lambda pid, stage: {"stage": stage, "host_pid": pid, "descendant_count": 0, "descendants": []},
    )
    monkeypatch.setattr(bounded, "install_temporary_firewall_block", lambda *args: None)

    def fail_cleanup(*args):
        raise RuntimeError("synthetic firewall cleanup failure")

    monkeypatch.setattr(bounded, "remove_temporary_firewall_block", fail_cleanup)

    report = bounded.run_bounded(runtime, preflight, gpu_ordinal=0)
    assert report["status"] == "FAIL"
    assert report["firewall_removed"] is False
    assert "firewall cleanup failed" in report["error"]

def test_bounded_v10_rejects_non_3070_path(monkeypatch, tmp_path):
    class OtherGpuClient(FakeClient):
        def create(self, request):
            value = super().create(request)
            value["initialization"]["gpu_name"] = "NVIDIA GeForce RTX 4090"
            return value

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    preflight = tmp_path / "preflight.json"
    preflight.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(bounded, "validate_preflight_report", lambda *args: {})
    monkeypatch.setattr(bounded, "V10ProtocolClient", OtherGpuClient)
    monkeypatch.setattr(
        bounded,
        "assert_no_host_descendants",
        lambda pid, stage: {"stage": stage, "host_pid": pid, "descendant_count": 0, "descendants": []},
    )
    monkeypatch.setattr(
        bounded, "install_temporary_firewall_block", lambda program, name: None
    )
    monkeypatch.setattr(
        bounded, "remove_temporary_firewall_block", lambda name: None
    )

    report = bounded.run_bounded(runtime, preflight, gpu_ordinal=0)
    assert report["status"] == "FAIL"
    assert "requires the RTX 3070/3070 Ti path" in report["error"]
