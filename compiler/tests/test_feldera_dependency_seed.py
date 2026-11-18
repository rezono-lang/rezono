"""Only successful, lock-owned Feldera dependency artifacts can cross runners."""

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest


EXPORT = Path(__file__).resolve().parents[1] / "ci" / "export_feldera_dependencies.py"
UNIT = "0123456789abcdef"
DBSP = f"deps/libdbsp-{UNIT}.rlib"
NATIVE = f"build/libc-{UNIT}/out/config.h"
FINGERPRINT = f".fingerprint/libc-{UNIT}/lib-libc.json"
OPERATOR = f"deps/libfeldera_pipe_operator_{UNIT}-{UNIT}.rlib"
MAIN = "feldera_pipe_pipeline_nil_main"


def archive(*entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as target:
        for entry in entries:
            if isinstance(entry, tarfile.TarInfo):
                target.addfile(entry)
            else:
                item = tarfile.TarInfo(entry)
                item.size = 4
                target.addfile(item, io.BytesIO(b"test"))
    return stream.getvalue()


def execute(arguments, source):
    return subprocess.run([sys.executable, EXPORT, *arguments], input=source, capture_output=True, check=False)


def members(source):
    with tarfile.open(fileobj=io.BytesIO(source), mode="r:") as result:
        return result.getnames()


def test_seed_selects_only_successful_lock_owned_dependencies(tmp_path):
    registry = "registry+https://github.com/rust-lang/crates.io-index"
    packages = [
        ("dbsp", None, "/home/ubuntu/feldera/crates/dbsp/Cargo.toml"),
        ("libc", registry, "/home/ubuntu/.cargo/registry/src/cache/libc-1.0.0/Cargo.toml"),
        (MAIN, None, f"/home/ubuntu/.feldera/compiler/rust-compilation/crates/{MAIN}/Cargo.toml"),
        ("wrong_manifest", None, "/home/ubuntu/untrusted/wrong_manifest/Cargo.toml"),
        ("unlocked", None, "/home/ubuntu/feldera/crates/unlocked/Cargo.toml"),
    ]
    lock = tmp_path / "Cargo.lock"
    registry_fields = f'source = "{registry}"\nchecksum = "{"a" * 64}"\n'
    lock.write_text("\n".join(f'[[package]]\nname = "{name}"\nversion = "1.0.0"\n'
                             + (registry_fields if source else "")
                             for name, source, _ in packages if name != "unlocked"), encoding="utf-8")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(json.dumps({"packages": [
        dict(name=name, version="1.0.0", source=source, manifest_path=path, id=name)
        for name, source, path in packages]}), encoding="utf-8")
    messages = tmp_path / "cargo.log"
    events = [
        dict(reason="compiler-artifact", package_id=name, target=dict(kind=["lib"], name=name))
        for name, _, _ in packages
    ]
    events.append(dict(reason="build-finished", success=True))
    messages.write_text("\n".join(map(json.dumps, events)), encoding="utf-8")
    source = archive(DBSP, NATIVE, FINGERPRINT, f"deps/liblibc-{UNIT}.rlib", f"deps/libc-{UNIT}.d",
                     OPERATOR, MAIN, f".fingerprint/{MAIN}-{UNIT}/info",
                     f"deps/libwrong_manifest-{UNIT}.rlib", f"deps/libunlocked-{UNIT}.rlib",
                     "compiled.sql", "results.xml", "collection.txt", "pipeline-binaries/work")
    result = execute(["export", lock, metadata, messages], source)
    assert result.returncode == 0, result.stderr.decode()
    assert set(members(result.stdout)) == {DBSP, NATIVE, FINGERPRINT, f"deps/liblibc-{UNIT}.rlib", f"deps/libc-{UNIT}.d"}
    result = execute(["verify"], result.stdout)
    assert result.returncode == 0, result.stderr.decode()
    events[-1]["success"] = False
    messages.write_text("\n".join(map(json.dumps, events)), encoding="utf-8")
    assert execute(["export", lock, metadata, messages], source).returncode != 0


@pytest.mark.parametrize("extra", [DBSP, OPERATOR, MAIN, "/etc/passwd", f"build/libc-{UNIT}/../../receipt",
                                  "results.xml", "collected.txt", "incremental/libc/artifact.o"])
def test_restore_rejects_generated_duplicate_or_escaping_entries(extra):
    assert execute(["verify"], archive(DBSP, NATIVE, extra)).returncode != 0


def test_restore_rejects_incomplete_or_linked_dependencies():
    assert execute(["verify"], archive(NATIVE)).returncode != 0
    link = tarfile.TarInfo(f"build/libc-{UNIT}/out/link")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../../../outside"
    assert execute(["verify"], archive(DBSP, link)).returncode != 0
