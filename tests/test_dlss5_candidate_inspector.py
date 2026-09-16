import json
import subprocess
import sys
import zipfile

import pytest

from tools.inspect_dlss5_candidate import inspect


def test_inspector_reports_binary_and_license_inventory(tmp_path):
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("bin/runtime/neuroframe.dll", b"dll")
        handle.writestr("LICENSE-MIT.txt", b"license")
    report = inspect(archive)
    assert report["binary_count"] == 1
    assert report["licenses_and_notices"] == ["LICENSE-MIT.txt"]
    assert report["executed"] is False and report["extracted"] is False


def test_inspector_rejects_traversal(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../outside.dll", b"bad")
    with pytest.raises(ValueError, match="unsafe"):
        inspect(archive)
