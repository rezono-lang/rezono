"""The environment a publication is made in is pinned and named (docs/ci.md#8-pinned-versions): every
locked distribution has a hash, the install refuses another Python (also one of the same version with
other bytes), insists on hashes and is not steered by the calling environment, a package outside the
lock is found, regen-goldens never replaces a kept publication, and the build record changes when the
publisher's source or the runtime does. The script tests run offline: a local wheel, no index."""

import base64
import hashlib
import importlib.util
import json
import marshal
import os
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
from rezono_canon import canonical_sha256

ROOT = Path(__file__).resolve().parents[3]
LOCKS = sorted((ROOT / "requirements").glob("*.txt"))


@pytest.mark.parametrize("lock", LOCKS, ids=lambda p: p.name)
def test_every_locked_distribution_has_a_hash(lock):
    entries = re.split(r"\n(?=[A-Za-z0-9])", lock.read_text("utf-8"))
    pinned = [e for e in entries if re.match(r"[A-Za-z0-9_.-]+(\[[^\]]*\])?==", e)]
    assert pinned, lock
    assert [e.split()[0] for e in pinned if "--hash=sha256:" not in e] == []


def test_the_install_refuses_another_python(tmp_path):
    fake = tmp_path / "python3"
    fake.write_text("#!/bin/sh\necho cpython 3.12.0 linux-x86_64\n")
    fake.chmod(0o755)
    env = os.environ | {"PYTHON": str(fake), "VENV": str(tmp_path / "venv")}
    r = subprocess.run([str(ROOT / "scripts" / "install-python.sh"), "requirements/run.txt", "canon"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "runtime digest" in r.stderr, r.stderr
    assert not (tmp_path / "venv").exists(), "nothing is installed with the wrong Python"


def _fake_runtime(tmp_path, version):
    """A runtime laid out like the real one that answers the version probe like the pinned Python."""
    prefix = tmp_path / "runtime"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "lib" / "python3.13").mkdir(parents=True)
    (prefix / "lib" / "python3.13" / "os.py").write_text("# not the standard library\n")
    fake = prefix / "bin" / "python3.13"
    fake.write_text(f"#!/bin/sh\necho cpython {version} linux-x86_64\n")
    fake.chmod(0o755)
    (prefix / "bin" / "python3").symlink_to("python3.13")
    return fake


def test_the_runtime_pins_agree():
    version = (ROOT / "requirements" / ".python-version").read_text().strip()
    spec = dict(line.split("=", 1) for line in (ROOT / "requirements" / ".python-artifact").read_text().splitlines())
    assert spec["url"].endswith(f"/python-{version}-linux-24.04-x64.tar.gz") and f"/{version}/" in spec["prefix"]
    assert re.fullmatch(r"[0-9a-f]{64}", spec["sha256"])
    assert re.fullmatch(r"[0-9a-f]{64}\n", (ROOT / "requirements" / ".python-digest").read_text())


def test_the_runtime_artifact_is_checked_before_it_is_unpacked(tmp_path):
    """scripts/python-runtime.sh: an artifact with another SHA-256 is never unpacked; one with the right
    SHA-256 that is not the pinned runtime is removed again."""
    fake = _fake_runtime(tmp_path, "3.13.0")
    tarball = tmp_path / "python.tar.gz"
    subprocess.run(["tar", "-czf", str(tarball), "-C", str(fake.parent.parent), "."], check=True)
    prefix = tmp_path / "installed"

    def install(sha):
        spec = tmp_path / "artifact"
        spec.write_text(f"url=file://{tarball}\nsha256={sha}\nprefix={prefix}\n")
        return subprocess.run([str(ROOT / "scripts" / "python-runtime.sh"), str(spec)], capture_output=True, text=True,
                              env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)})

    r = install("0" * 64)
    assert r.returncode == 1 and "nothing unpacked" in r.stderr and not prefix.exists(), r.stderr
    r = install(hashlib.sha256(tarball.read_bytes()).hexdigest())
    assert r.returncode == 1 and "requirements/.python-digest" in r.stderr and not prefix.exists(), r.stderr



def test_a_cached_runtime_artifact_is_checked_like_a_download(tmp_path):
    """REZONO_PYTHON_CACHE: a cached artifact with the pinned SHA-256 is used without a download and still goes
    through the digest check; one with other bytes is dropped and downloaded again, and only verified bytes
    are kept."""
    fake = _fake_runtime(tmp_path, "3.13.0")
    tarball = tmp_path / "python.tar.gz"
    subprocess.run(["tar", "-czf", str(tarball), "-C", str(fake.parent.parent), "."], check=True)
    sha = hashlib.sha256(tarball.read_bytes()).hexdigest()
    prefix, cache = tmp_path / "installed", tmp_path / "cache"
    kept = cache / f"python-{sha}.tar.gz"

    def install(url):
        spec = tmp_path / "artifact"
        spec.write_text(f"url={url}\nsha256={sha}\nprefix={prefix}\n")
        return subprocess.run([str(ROOT / "scripts" / "python-runtime.sh"), str(spec)], capture_output=True, text=True,
                              env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), "REZONO_PYTHON_CACHE": str(cache)})

    r = install(f"file://{tarball}")
    assert "downloaded" in r.stderr and kept.read_bytes() == tarball.read_bytes(), r.stderr
    r = install(f"file://{tmp_path / 'gone.tar.gz'}")
    assert "from the cache" in r.stderr and "downloaded" not in r.stderr, r.stderr
    assert r.returncode == 1 and "requirements/.python-digest" in r.stderr and not prefix.exists(), r.stderr
    kept.write_bytes(b"other bytes")
    r = install(f"file://{tarball}")
    assert "dropped" in r.stderr and "downloaded" in r.stderr and kept.read_bytes() == tarball.read_bytes(), r.stderr

def test_the_install_refuses_a_same_version_replacement(tmp_path):
    """Version and platform right, other bytes: refused by the runtime digest (requirements/.python-digest)."""
    pinned = (ROOT / "requirements" / ".python-version").read_text().strip()
    fake = _fake_runtime(tmp_path, pinned)
    env = os.environ | {"PYTHON": str(fake), "VENV": str(tmp_path / "venv")}
    r = subprocess.run([str(ROOT / "scripts" / "install-python.sh"), "requirements/run.txt", "canon"],
                       env=env, capture_output=True, text=True)
    assert r.returncode == 1 and "runtime digest" in r.stderr, r.stderr
    assert not (tmp_path / "venv").exists(), "nothing is installed with another build of Python"


def test_the_runtime_digest_covers_the_standard_library_not_site_packages(tmp_path):
    fake = _fake_runtime(tmp_path, "3.13.0")
    lib = fake.parent.parent / "lib" / "python3.13"
    digest = lambda: subprocess.run([str(ROOT / "scripts" / "python-digest.sh"), str(fake)],
                                    capture_output=True, text=True, check=True).stdout.strip()
    base = digest()
    assert re.fullmatch(r"[0-9a-f]{64}", base)
    (lib / "site-packages").mkdir()
    (lib / "site-packages" / "anything.py").write_text("x = 1\n")
    (lib / "__pycache__").mkdir()
    (lib / "__pycache__" / "os.cpython-313.pyc").write_bytes(b"\0")
    assert digest() == base, "installed packages and byte code are not the runtime"
    (lib / "os.py").write_text("# another standard library\n")
    assert digest() != base


def _base_python():
    """The pinned runtime this test runs on (the base of the virtualenv), or skip: the install needs it."""
    py = getattr(sys, "_base_executable", "") or sys.executable
    found = subprocess.run([str(ROOT / "scripts" / "python-digest.sh"), py], capture_output=True, text=True)
    if found.stdout.strip() != (ROOT / "requirements" / ".python-digest").read_text().strip():
        pytest.skip("not on the pinned runtime (requirements/.python-digest)")
    return py


def _wheelhouse(tmp_path, hashed=True):
    """A lock that installs one local wheel without an index, with or without its hash."""
    files = {"probe_pkg/__init__.py": b"VALUE = 1\n",
             "probe_pkg-1.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: probe-pkg\nVersion: 1.0\n",
             "probe_pkg-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"}
    b64 = lambda d: base64.urlsafe_b64encode(hashlib.sha256(d).digest()).rstrip(b"=").decode()
    record = "".join(f"{n},sha256={b64(d)},{len(d)}\n" for n, d in files.items()) + "probe_pkg-1.0.dist-info/RECORD,,\n"
    house = tmp_path / "wheels"
    house.mkdir(exist_ok=True)
    whl = house / "probe_pkg-1.0-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as z:
        for n, d in [*files.items(), ("probe_pkg-1.0.dist-info/RECORD", record.encode())]:
            z.writestr(zipfile.ZipInfo(n, (2020, 1, 1, 0, 0, 0)), d)
    lock = tmp_path / ("hashed.txt" if hashed else "unhashed.txt")
    entry = "probe-pkg==1.0" + (f" \\\n    --hash=sha256:{hashlib.sha256(whl.read_bytes()).hexdigest()}" if hashed else "")
    lock.write_text(f"--no-index\n--find-links {house}\n{entry}\n")
    return lock


# A build backend in the project itself, so an editable install needs nothing from an index. It notes
# the environment it was started in: the second install command (editable, no build isolation) runs it.
BACKEND = '''
import base64, hashlib, json, os, zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def get_requires_for_build_editable(config_settings=None):
    return []


def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    (HERE / "seen.json").write_text(json.dumps({k: v for k, v in os.environ.items() if k.startswith(("PYTHON", "PIP_"))}))
    info = "rezono_probe_edit-1.0.dist-info"
    files = {info + "/METADATA": b"Metadata-Version: 2.1\\nName: rezono-probe-edit\\nVersion: 1.0\\n",
             info + "/WHEEL": b"Wheel-Version: 1.0\\nGenerator: test\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n",
             "rezono_probe_edit.pth": (str(HERE) + "\\n").encode()}
    b64 = lambda d: base64.urlsafe_b64encode(hashlib.sha256(d).digest()).rstrip(b"=").decode()
    record = "".join(f"{n},sha256={b64(d)},{len(d)}\\n" for n, d in files.items()) + info + "/RECORD,,\\n"
    name = "rezono_probe_edit-1.0-py3-none-any.whl"
    with zipfile.ZipFile(os.path.join(wheel_directory, name), "w") as z:
        for n, d in [*files.items(), (info + "/RECORD", record.encode())]:
            z.writestr(n, d)
    return name
'''


def _editable_project(tmp_path):
    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "pyproject.toml").write_text('[build-system]\nrequires = []\nbuild-backend = "backend"\nbackend-path = ["."]\n\n'
                                         '[project]\nname = "rezono-probe-edit"\nversion = "1.0"\n')
    (proj / "backend.py").write_text(BACKEND)
    (proj / "rezono_probe_edit.py").write_text("VALUE = 'editable'\n")
    return proj


def _install(tmp_path, lock, *editable, **env):
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "PYTHON": _base_python(),
           "VENV": str(tmp_path / "venv")} | env
    return subprocess.run([str(ROOT / "scripts" / "install-python.sh"), str(lock), *map(str, editable)], env=env,
                          capture_output=True, text=True)


def test_the_install_requires_hashes(tmp_path):
    """The same lock installs with its hash and is refused without: --require-hashes is in force."""
    r = _install(tmp_path, _wheelhouse(tmp_path, hashed=True))
    assert r.returncode == 0, r.stderr
    r = _install(tmp_path, _wheelhouse(tmp_path, hashed=False))
    assert r.returncode != 0 and "hash" in r.stderr.lower(), r.stderr


def test_only_installs_one_locked_wheel_and_builds_nothing(tmp_path):
    """--only NAME (the promotion gates): of a lock with a wheel and an sdist, only the stanza NAME
    goes in, with its hash; an sdist is never built, also when its stanza is the one named; a name the lock
    does not pin, or this repository's packages beside it, are refused."""
    lock = _wheelhouse(tmp_path)
    sdist = tmp_path / "wheels" / "probe_sdist-1.0.tar.gz"
    with tarfile.open(sdist, "w:gz") as t:
        setup = tmp_path / "setup.py"
        setup.write_text("raise SystemExit('built')\n")
        t.add(setup, "probe_sdist-1.0/setup.py")
    lock.write_text(lock.read_text() + f"probe-sdist==1.0 \\\n    --hash=sha256:{hashlib.sha256(sdist.read_bytes()).hexdigest()}\n")
    r = _install(tmp_path, lock)
    assert r.returncode != 0, "the whole lock builds the sdist"
    r = _install(tmp_path, "--only", "Probe_Pkg", lock)
    assert r.returncode == 0, r.stderr
    got = subprocess.run([str(tmp_path / "venv" / "bin" / "python"), "-I", "-c",
                          "import importlib.metadata as m; print(sorted(d.metadata['Name'] for d in m.distributions()))"],
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert got.stdout == "['pip', 'probe-pkg']\n", got.stdout + got.stderr
    r = _install(tmp_path, "--only", "probe-sdist", lock)
    assert r.returncode != 0 and "matching distribution" in r.stderr.lower() and "built" not in r.stderr, r.stderr
    r = _install(tmp_path, "--only", "absent", lock)
    assert r.returncode == 1 and "absent is not pinned" in r.stderr, r.stderr
    r = _install(tmp_path, "--only", "probe-pkg", lock, _editable_project(tmp_path))
    assert r.returncode == 2 and "--only installs one locked distribution" in r.stderr, r.stderr


def test_a_polluted_environment_does_not_reach_the_install(tmp_path):
    """PYTHONPATH, PYTHONHOME, PIP_* and a pip configuration file, and an existing virtualenv: none of
    them changes what is installed, and no Python started by the install imports from them."""
    lock = _wheelhouse(tmp_path)
    marker = tmp_path / "imported"
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "sitecustomize.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    (poison / "probe_pkg.py").write_text("VALUE = 'from PYTHONPATH'\n")
    conf = tmp_path / "pip.conf"
    conf.write_text("[global]\nno-index = false\nindex-url = http://127.0.0.1:9/\n[install]\ndry-run = true\n")
    venv = tmp_path / "venv"
    (venv / "lib").mkdir(parents=True)
    (venv / "lib" / "left-over").write_text("from an earlier environment\n")
    proj = _editable_project(tmp_path)
    r = _install(tmp_path, lock, proj, PYTHONPATH=str(poison), PYTHONHOME=str(tmp_path / "nowhere"),
                 PYTHONSTARTUP=str(poison / "sitecustomize.py"), PIP_CONFIG_FILE=str(conf),
                 PIP_DRY_RUN="1", PIP_NO_INDEX="0", PIP_INDEX_URL="http://127.0.0.1:9/",
                 PIP_REQUIRE_HASHES="0", PIP_TARGET=str(tmp_path / "elsewhere"))
    assert r.returncode == 0, r.stderr
    assert not marker.exists(), "a Python of the install imported from PYTHONPATH"
    assert not (venv / "lib" / "left-over").exists(), "the virtualenv is made fresh"
    assert not (tmp_path / "elsewhere").exists()
    got = subprocess.run([str(venv / "bin" / "python"), "-I", "-c",
                          "import probe_pkg, rezono_probe_edit; print(probe_pkg.VALUE, rezono_probe_edit.VALUE)"],
                         capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert got.stdout == "1 editable\n", got.stderr
    seen = json.loads((proj / "seen.json").read_text())
    assert seen.pop("PIP_CONFIG_FILE", None) == "/dev/null", seen
    assert not {k for k in seen if k.startswith("PYTHON") or k in {"PIP_DRY_RUN", "PIP_NO_INDEX", "PIP_INDEX_URL",
                                                                    "PIP_REQUIRE_HASHES", "PIP_TARGET"}}, seen


def test_the_archived_publisher_runs_without_the_environment_site_hooks_or_planted_bytecode(tmp_path, monkeypatch):
    """rezono_publisher.kept.run_archived, offline with a stand-in publisher: nothing from the calling
    environment, no .pth file or sitecustomize, and no planted .pyc reaches the archived run."""
    from rezono_publisher import kept

    tree = tmp_path / "tree"
    subprocess.run([sys.executable, "-I", "-m", "venv", "--without-pip", str(tree / ".venv")], check=True)
    python = str(tree / ".venv" / "bin" / "python")
    site = Path(subprocess.run([python, "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
                               capture_output=True, text=True, check=True).stdout.strip())
    markers = tmp_path / "markers"
    markers.mkdir()
    (site / "hook.pth").write_text(f"import os; open({str(markers / 'pth')!r}, 'w').close()\n")
    (site / "sitecustomize.py").write_text(f"open({str(markers / 'sitecustomize')!r}, 'w').close()\n")
    src = site / "planted.py"
    src.write_text("VALUE = 'source'\n")
    st = src.stat()  # a .pyc valid for this source's time and size, with other code
    pyc = site / "__pycache__" / f"planted.{sys.implementation.cache_tag}.pyc"
    pyc.parent.mkdir(exist_ok=True)
    pyc.write_bytes(importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little")
                    + (int(st.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little") + (st.st_size & 0xFFFFFFFF).to_bytes(4, "little")
                    + marshal.dumps(compile("VALUE = 'planted'\n", str(src), "exec")))
    plain = subprocess.run([python, "-I", "-c", "import planted; print(planted.VALUE)"], capture_output=True, text=True)
    assert plain.stdout == "planted\n" and (markers / "pth").exists(), "the poison works on a plain run"
    for m in markers.iterdir():
        m.unlink()
    package = tree / "edge" / "publisher" / "rezono_publisher"
    package.mkdir(parents=True)
    (tree / "canon").mkdir()
    (tree / "compiler").mkdir()
    (package / "__init__.py").write_text("")
    (package / "__main__.py").write_text(
        "import json, os, sys\nimport planted\n"
        "json.dump({'value': planted.VALUE, 'flags': [sys.flags.isolated, sys.flags.no_site, sys.flags.dont_write_bytecode],"
        " 'env': sorted(os.environ), 'file': __file__, 'argv': sys.argv[1:]}, open(sys.argv[1], 'w'))\n")
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "sitecustomize.py").write_text(f"open({str(markers / 'pythonpath')!r}, 'w').close()\n")
    for k, v in {"PYTHONPATH": str(poison), "PYTHONHOME": str(tmp_path / "nowhere"),
                 "PYTHONSTARTUP": str(poison / "sitecustomize.py"), "PIP_INDEX_URL": "http://127.0.0.1:9/"}.items():
        monkeypatch.setenv(k, v)
    report = tmp_path / "report.json"
    r = kept.run_archived(tree, [str(report), "--epoch", "1"])
    assert r.returncode == 0, r.stderr
    got = json.loads(report.read_text())
    assert got["value"] == "source", "a planted .pyc was used"
    assert got["flags"] == [1, 1, 1]
    assert [k for k in got["env"] if k.startswith(("PYTHON", "PIP_")) and k != "PIP_CONFIG_FILE"] == []
    assert got["file"] == str(package / "__main__.py") and got["argv"] == [str(report), "--epoch", "1"]
    assert list(markers.iterdir()) == [], "a site hook ran"


def test_regen_goldens_never_replaces_a_kept_publication(tmp_path):
    """scripts/regen-goldens.sh in a sandbox with stand-ins for Python and npx: a pack with a kept
    publication is checked with `kept --make`, which never replaces one, and its kept files stay as
    they are; when that check fails, the run stops."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "regen-goldens.sh", repo / "scripts")
    pack = repo / "examples" / "demo"
    for d in ("facts", "expected/published/demo/manifests", "expected/kept-source", "expected/compiled"):
        (pack / d).mkdir(parents=True)
    (pack / "pack.yaml").write_text("id: demo\n")
    kept = {pack / "expected/published/demo/manifests/m-1.json": "{}\n",
            pack / "expected/kept-source/a.tar.gz": "archive\n", pack / "expected/kept-source/a.sha256": "pin\n"}
    for p, text in kept.items():
        p.write_text(text)
    (repo / "compiler").mkdir()
    (repo / "viewer" / "node_modules").mkdir(parents=True)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    log = tmp_path / "calls"
    stand_in = {
        "python": f'''#!/bin/sh
echo "$*" >> {log}
case "$*" in
  "-m rezono_compiler --help") echo "compile" ;;
  "-m rezono_compiler compile "*) mkdir -p "$4" ;;
  "-m rezono_publisher.kept "*) exit "${{KEPT_EXIT:-0}}" ;;
esac
''',
        "npx": "#!/bin/sh\nexit 0\n",
    }
    for name, text in stand_in.items():
        (bin_ / name).write_text(text)
        (bin_ / name).chmod(0o755)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = {"PATH": f"{bin_}:{os.environ['PATH']}", "HOME": str(tmp_path), "PYTHON": str(bin_ / "python")}
    for exit_code in ("0", "1"):
        r = subprocess.run(["bash", str(repo / "scripts" / "regen-goldens.sh")], env=env | {"KEPT_EXIT": exit_code},
                           capture_output=True, text=True)
        assert (r.returncode == 0) == (exit_code == "0"), r.stdout + r.stderr
        assert "-m rezono_publisher.kept examples/demo --make" in log.read_text().splitlines()
        assert {p: p.read_text() if p.exists() else None for p in kept} == kept, "a kept publication was touched"


def test_a_package_outside_the_lock_is_found(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("# nothing pinned\n")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check-pinned.py"), str(empty)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "not in empty.txt" in r.stderr


def test_the_build_record_names_the_publisher_source_and_the_runtime(monkeypatch):
    pytest.importorskip("rezono_compiler")
    from rezono_publisher import batch

    base = canonical_sha256(batch.build_record())
    tree = batch.tree_sha256
    publisher = Path(batch.__file__).parent
    monkeypatch.setattr(batch, "tree_sha256", lambda root, suffixes=None: "0" * 64 if Path(root) == publisher else tree(root, suffixes))
    assert canonical_sha256(batch.build_record()) != base, "another publisher source is another build"
    monkeypatch.setattr(batch, "tree_sha256", tree)
    assert canonical_sha256(batch.build_record()) == base
    monkeypatch.setattr(batch.platform, "python_version", lambda: "3.13.0")
    assert canonical_sha256(batch.build_record()) != base, "another Python is another build"
    monkeypatch.undo()
    monkeypatch.setattr(batch.platform, "python_build", lambda: ("other", "Jan  1 2026 00:00:00"))
    assert canonical_sha256(batch.build_record()) != base, "another build of Python is another build"
