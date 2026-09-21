import pytest

from src.backends import dlss5_v10_app_security as security


class FakeProcess:
    def __init__(
        self,
        pid: int,
        *,
        name: str,
        exe: str,
        running: bool = True,
        children: list["FakeProcess"] | None = None,
    ):
        self.pid = pid
        self._name = name
        self._exe = exe
        self._running = running
        self._children = children or []

    def name(self):
        return self._name

    def exe(self):
        return self._exe

    def is_running(self):
        return self._running

    def children(self, recursive=False):
        if not recursive:
            return list(self._children)
        result = []
        pending = list(self._children)
        while pending:
            child = pending.pop(0)
            result.append(child)
            pending.extend(child._children)
        return result


def test_process_tree_allows_only_real_system_conhost(monkeypatch):
    conhost = FakeProcess(
        36912,
        name="conhost.exe",
        exe=r"C:\Windows\System32\conhost.exe",
    )
    root = FakeProcess(
        1234,
        name="python.exe",
        exe=r"E:\env\python.exe",
        children=[conhost],
    )
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    monkeypatch.setattr(security.psutil, "Process", lambda _pid: root)

    evidence = security.assert_no_host_descendants(1234, "app_after_hello")

    assert evidence["descendant_count"] == 0
    assert evidence["descendants"] == []
    assert evidence["allowed_console_hosts"] == [
        {"pid": 36912, "name": "conhost.exe"}
    ]


@pytest.mark.parametrize(
    ("name", "exe"),
    [
        ("powershell.exe", r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
        ("conhost.exe", r"E:\fake\conhost.exe"),
    ],
)
def test_process_tree_still_rejects_non_system_children(monkeypatch, name, exe):
    child = FakeProcess(55, name=name, exe=exe)
    root = FakeProcess(
        1234,
        name="python.exe",
        exe=r"E:\env\python.exe",
        children=[child],
    )
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    monkeypatch.setattr(security.psutil, "Process", lambda _pid: root)

    with pytest.raises(RuntimeError, match="unexpected child process"):
        security.assert_no_host_descendants(1234, "app_after_hello")
