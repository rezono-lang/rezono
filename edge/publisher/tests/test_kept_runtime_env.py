"""The environment of a replay's subprocesses: nothing that steers Python or pip, except the pinned runtime's own
library directory when it holds its libpython (a runtime unpacked away from the prefix it was built for)."""

import sys

from rede_publisher import kept


def runtime_in(tmp_path, with_lib: bool) -> str:
    prefix = tmp_path / "tool" / "Python" / "x64"
    (prefix / "bin").mkdir(parents=True)
    exe = prefix / "bin" / "python3"
    exe.write_bytes(b"")
    if with_lib:
        (prefix / "lib").mkdir()
        (prefix / "lib" / f"libpython{sys.version_info.major}.{sys.version_info.minor}.so.1.0").write_bytes(b"")
    return str(exe)


def test_the_runtime_s_own_libpython_directory_is_the_only_library_path(tmp_path, monkeypatch):
    exe = runtime_in(tmp_path, with_lib=True)
    monkeypatch.setattr(kept, "runtime", lambda: exe)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/somewhere/else")
    monkeypatch.setenv("PYTHONPATH", "/planted")
    env = kept.isolated_env()
    assert env["LD_LIBRARY_PATH"] == str((tmp_path / "tool" / "Python" / "x64" / "lib").resolve())
    assert "PYTHONPATH" not in env and env["PIP_CONFIG_FILE"]


def test_a_runtime_without_its_own_libpython_gets_no_library_path(tmp_path, monkeypatch):
    exe = runtime_in(tmp_path, with_lib=False)
    monkeypatch.setattr(kept, "runtime", lambda: exe)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/somewhere/else")
    assert "LD_LIBRARY_PATH" not in kept.isolated_env()
