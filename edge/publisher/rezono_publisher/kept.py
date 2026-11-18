"""A kept publication: one made earlier in CI and kept in Git, as evidence that publishing reproduces
(docs/ci.md#8-vaste-versies). It is never replaced.

  python -m rezono_publisher.kept PACK            make it again with the code it was made with (replay)
  python -m rezono_publisher.kept PACK --current  make it again with the current code (see below)
  python -m rezono_publisher.kept PACK --make     make it, only if the pack has none yet

Next to it, expected/kept-source/<build record sha256>.tar.gz holds what it was made with: rezono-canon,
the compiler, the publisher, the contracts, the locks and the pack's own files, and <sha256>.sha256 pins
the archive's own bytes. A pack that imports other packs travels with them (`archive`): an import is a
path relative to the pack, so under pack/ the archive holds the pack and the definition files of every
pack it imports, at their places relative to each other. A pack without imports sits at pack/ itself.
Before anything archived runs, the current code checks the archive against the kept publication
(`verify`): the manifest's references and their hashes, the archive digest, that every member is a
regular file in the allowed set, that the code, contracts, locks and pack in it have exactly the hashes
the build record and manifest name, and that every imported pack in it has the hash its importer pins
and nothing else is under pack/ (`archived_pack`). So archived code cannot vouch for itself.
Only then the replay installs the archived dev lock (hash-checked; regen-goldens makes kept publications
with it) into a fresh virtualenv with scripts/install-python.sh, on the pinned runtime (its digest is
checked there), runs the archived publisher on the archived pack with the recorded inputs and profile,
and compares every file byte for byte. No subprocess sees PYTHONPATH, PYTHONHOME, PIP_* or a pip
configuration file, and the archived publisher runs without site hooks or cached bytecode (run_archived).

A publication with views (its build record names `views`) replays only from its private candidate
(--view-archive KEY=DIR, private_view_archive.read_candidate), never from kept-source: its role checkpoints
are private. Everything in it is checked before anything installs; then the archived npm lock is installed
too, the checkpoints go into the new store unchanged, and the archived publisher renders with --views on the
Node whose digest the build records (--node).

With --current the current code makes it again (as in the paragraph below), to show what a change of
the code would change in an old publication.

The kept publication lives in PACK/expected/published/ (a pack takes part with an empty directory and a
.gitkeep). The same inputs (epoch, knowledge time, sources, profile) are published again into a scratch
store. Only what names the build may differ, because the build itself is another commit of the compiler
or publisher, another library or another Python: the compiler hash, the build record's values, and the
store keys and URIs derived from them. Everything else is compared byte for byte, the manifest and the
build record included, with those values put back. A changed serializer, manifest layout, snapshot,
witness, bundle or rule IR is always a difference.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import io
import json
import ntpath
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .kept_views import CheckedViewExtension

from rezono_canon import canonical_sha256, sha256_hex

from . import publish, store

ARCHIVE = ("bundles", "builds")  # keys named after the build: compared through the manifest instead


def kept_dir(pack_dir) -> Path:
    return Path(pack_dir) / "expected" / "published"


# What the archive holds, from the repository root: (directory, suffixes of the files that count).
CODE = (("admission", "rezono_admission", {".py"}), ("canon", "rezono_canon", {".py"}), ("checker", "rezono_checker", {".py"}),
        ("compiler", "rezono_compiler", {".py", ".yaml"}), ("edge/publisher", "rezono_publisher", {".py"}))
SKIP = {"expected", "__pycache__"}
# The runtime pins: an archive holds them so a replay can tell it needs the same runtime.
PINS = (".python-artifact", ".python-digest", ".python-version")

# Build records come in three versions (docs/ci.md section 8). v3 ("format": "rezono.build/3") names the
# hash of everything that can change what is installed or run, pyproject.toml and the checker included,
# so its archive is checked against the record alone. v2 named no checker: its archive holds none (one
# that does is refused, as nothing binds it), and since the publisher needs the checker (R7) it
# installs but cannot replay. v1 (no "format") does not name pyproject.toml; its
# archives were made by `git archive` of one commit, so every member must be exactly the file at the
# same path in that commit's tree. This table is reviewed code: the commit is never taken from an
# archive or a record. Build record sha256 -> the commit its archives were made from.
V1_SOURCE = {
    "8ccc5b826087bf64a2098a502bd3747c2549fe3745d8cce967f34a8382c88611": "3931b35b7816e1602e1d63d447cfaf30415865ad",
}
FORMAT = "rezono.build/3"
V2 = "rede.build/2"
LEGACY_FORMATS = ("rede.build/3", V2)


def unsupported_views(record: dict, where: str) -> str | None:
    """The routes that cannot carry a view publication: the kept source archive in Git (`verify`: its role
    checkpoints are private), `--current` and `make`. A view publication replays only through `replay` with
    its private candidate (private_view_archive.read_candidate)."""
    if "views" in record:
        return (f"{where}: view-aware kept publications require view archive/replay support (C3 step 2); "
                "this route supports viewless publications only; replay one with its private view archive")
    return None


def source_dir(pack_dir) -> Path:
    return Path(pack_dir) / "expected" / "kept-source"


def archive(root, pack_dir) -> bytes:
    """A deterministic tar.gz of the code, contracts, locks and pack a publication is made with."""
    root, pack_dir = Path(root), Path(pack_dir)
    entries = []
    for project, package, suffixes in CODE:
        entries.append((f"{project}/pyproject.toml", root / project / "pyproject.toml"))
        for p in sorted((root / project / package).rglob("*")):
            if p.is_file() and p.suffix in suffixes and "__pycache__" not in p.parts:
                entries.append((p.relative_to(root).as_posix(), p))
    entries += [(f"contracts/{p.name}", p) for p in sorted((root / "contracts").glob("*.yaml"))]
    entries += [(f"requirements/{p.name}", p) for p in sorted((root / "requirements").iterdir())
                if p.is_file() and (p.suffix == ".txt" or p.name in PINS)]
    from rezono_compiler import modules

    # The pack with its import closure, so the imports resolve in the archive as they do here.
    entries += [(f"pack/{rel}", p) for rel, p in modules.closure_files(pack_dir)[1]]
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, p in sorted(entries):
            data = p.read_bytes()
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 0, 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def repo_root() -> Path:
    from rezono_compiler import pack as packs

    return packs.CONTRACTS.parent


def digest_path(tar: Path) -> Path:
    return tar.with_name(tar.name.removesuffix(".tar.gz") + ".sha256")


def digest_line(tar: Path, data: bytes) -> str:
    return f"{sha256_hex(data)}  {tar.name}\n"  # the format of sha256sum, so `sha256sum -c` checks it


def allowed(name: str, v1: bool = False) -> bool:
    """A member the archive may hold. Every one that can change what is installed or run is bound by a
    hash the build record or manifest names (code, pyproject.toml, contracts, locks, pack); the runtime
    pins must equal the current ones. Anything else is refused. A v1 archive also held the lock's
    sources; they are bound by the git tree instead (`git_tree`)."""
    parts = name.split("/")
    if name.startswith("/") or "" in parts or "." in parts or ".." in parts:
        return False
    for project, package, suffixes in CODE:
        if name == f"{project}/pyproject.toml":
            return True
        if name.startswith(f"{project}/{package}/"):
            return Path(name).suffix in suffixes and not SKIP.intersection(parts)
    if parts[0] == "contracts":
        return len(parts) == 2 and name.endswith(".yaml")
    if parts[0] == "requirements":
        return len(parts) == 2 and (v1 or name.endswith(".txt") or parts[1] in PINS)
    return parts[0] == "pack" and len(parts) > 1 and not SKIP.intersection(parts)


def archived_pack(root: Path) -> tuple[Path | None, list[str]]:
    """The pack an unpacked archive was made for, under its pack/ directory `root`, checked with the current
    code before anything runs: the one pack.yaml that no other pack there imports, every pack it imports
    inside `root` with the hash its importer pins, and no file under `root` outside that closure."""
    from rezono_compiler import modules

    root = root.resolve()
    found, imported = {}, set()
    for d in sorted(p.parent for p in root.rglob("pack.yaml")):
        try:
            found[d] = modules.closure(d)[1]
        except ValueError as e:
            return None, [f"pack/{d.relative_to(root).as_posix()}: {e}"]
        imported |= {i for _, i in found[d]}
    mains = [d for d in found if d not in imported]
    if len(mains) != 1:
        return None, [f"pack/: {len(mains)} packs that no other pack in the archive imports, not one"]
    main, imports = mains[0], found[mains[0]]
    out = [f"pack/: import {n} lies outside the archive" for n, d in imports if not d.is_relative_to(root)]
    if out:
        return None, out
    kept = {p for p in main.rglob("*") if p.is_file()} | {p for _, d in imports for p in modules.definition_files(d)}
    out += [f"pack/{p.relative_to(root).as_posix()}: neither the pack's nor a definition file of a pack it imports"
            for p in sorted(root.rglob("*")) if p.is_file() and p not in kept]
    if not out:  # The existing verified closure/inventory, never a second resolver or archived code.
        roots = sorted({main, *(d for _, d in imports)})
        out += [f"pack/{(d / 'views.yaml').relative_to(root).as_posix()}: "
                "theory views.yaml execution is not supported yet"
                for d in roots if (d / "views.yaml").exists()]
    return (None if out else main), out


def references(m: dict, old) -> list[str]:
    """Every file the manifest names with a hash is in the kept store with exactly that hash."""
    out = []
    todo = [m]
    while todo:
        v = todo.pop()
        if isinstance(v, dict):
            if isinstance(v.get("uri"), str) and isinstance(v.get("sha256"), str):
                data = old.get(key(v["uri"]))
                if data is None:
                    out.append(f"{v['uri']}: named in the manifest, not kept")
                elif sha256_hex(data) != v["sha256"]:
                    out.append(f"{v['uri']}: not the hash the manifest names")
            todo += v.values()
        elif isinstance(v, list):
            todo += v
    return sorted(out)


def pack_path(pack_dir) -> str:
    """Where the pack lives in the repository, as a path in a commit's tree."""
    return Path(pack_dir).resolve().relative_to(repo_root().resolve()).as_posix()


def git_tree(commit: str) -> dict[str, str] | None:
    """Path -> blob hash of every regular file in `commit`, from this repository's own history; None
    when the commit is not here (a shallow clone: fetch the history, as CI does)."""
    r = subprocess.run(["git", "-C", str(repo_root()), "ls-tree", "-r", "-z", "--full-tree", commit],
                       capture_output=True, env=isolated_env())
    if r.returncode:
        return None
    out = {}
    for entry in r.stdout.decode("utf-8").split("\0"):
        if entry:
            meta, path = entry.split("\t", 1)
            mode, kind, blob = meta.split()
            if kind == "blob" and mode in ("100644", "100755"):
                out[path] = blob
    return out


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()  # how git names a file's bytes


@dataclass(frozen=True)
class ArchiveInspection:
    """Checked bytes relative to a supplied kept target, not permission or replay capability."""
    members: tuple[tuple[str, bytes], ...]
    main: str
    extension: CheckedViewExtension | None = None


def _kept_target(old, k):
    m = json.loads(old.get(k))
    sha = m["build"]["sha256"]
    out = [f"{k}: {p}" for p in references(m, old)]
    if not key(m["build"]["uri"]).endswith(f"/builds/{sha}.json"):
        out.append(f"{k}: the build record is not named by its hash")
    return m, None if out else json.loads(old.get(key(m["build"]["uri"]))), out


def _portable_component(part: str) -> bool:
    # Windows aliases must not turn two regular archive files into one host file/device.
    return bool(part) and not ntpath.isreserved(part)


def _import_boundaries(members):
    """Bound paths lexically before modules.closure can read any import destination."""
    import yaml

    for name, body in members.items():
        if not name.startswith("pack/") or not name.endswith("/pack.yaml"):
            continue
        try:
            meta = yaml.safe_load(body) or {}
        except yaml.YAMLError:
            raise ValueError("archive pack.yaml is malformed") from None
        imports = meta.get("imports") or []
        if not isinstance(imports, list):
            raise ValueError("archive pack imports must be a list")
        for entry in imports:
            path = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or ":" in path:
                raise ValueError("archive import path is not relative portable text")
            parts = list(PurePosixPath(name).parent.parts)
            for part in path.split("/"):
                if part in ("", "."):
                    continue
                if part == "..":
                    if len(parts) == 1:
                        raise ValueError("archive import path escapes pack/")
                    parts.pop()
                elif not _portable_component(part):
                    raise ValueError("archive import path has a host alias")
                else:
                    parts.append(part)


def _materialise(members, tree: Path):
    if tree.is_symlink() or tree.is_junction():
        raise ValueError("archive destination is linked")
    if tree.exists() and any(tree.iterdir()):
        raise ValueError("archive destination is not empty")
    tree.mkdir(parents=True, exist_ok=True)
    for name, body in members.items():
        if any(not _portable_component(p) for p in PurePosixPath(name).parts):
            raise ValueError("archive member has a host alias")
        path = tree / name
        relative = path.relative_to(tree)
        parents = [relative, *relative.parents]
        if not path.resolve().is_relative_to(tree.resolve()) or any(
                p.is_symlink() or p.is_junction() for p in (tree / p for p in parents)):
            raise ValueError("archive member escapes or follows a linked path")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(body)


def inspect_archive(pack_dir: Path, old, k: str, data: bytes, pin_text: str) -> ArchiveInspection:
    """Bounded archive-only inspection; private scratch is removed on every outcome.

    The caller supplies the reviewed local target, not authenticated history. Existing
    base bindings and optional view commitments are checked; no archived code, Node or
    installer runs. Runtime metadata is not evidence of a provisioned replay environment.
    """
    from . import kept_views

    try:
        if len(data) > kept_views.MAX_ARCHIVE_BYTES:
            raise ValueError("compressed archive exceeds verification bounds")
        m, record, out = _kept_target(old, k)
        sha = m["build"]["sha256"]
        if out:
            raise ValueError("; ".join(out))
        if pin_text != digest_line(Path(f"{sha}.tar.gz"), data):
            raise ValueError("archive digest differs")
        if not m["compiler_sha256"] == record["compiler_sha256"] == canonical_sha256(record["compiler"]):
            raise ValueError("compiler_sha256 does not match the build record's compiler")
        v1 = "format" not in record
        if not v1 and record["format"] not in (FORMAT, *LEGACY_FORMATS):
            raise ValueError("build record format is not known")
        extra = set()
        if "views" in record:
            pack, target, _, specs, roles = kept_views._target(old, k)
            extra = set(specs) | {kept_views.input_member(pack, target["id"], role) for role in roles}
        members = kept_views._members(data, allow=lambda p: allowed(p, v1) or p in extra)
        if v1:
            commit = V1_SOURCE.get(sha)
            files = git_tree(commit) if commit else None
            if commit is None:
                raise ValueError("a v1 build record without a reviewed source commit (V1_SOURCE)")
            if files is None:
                raise ValueError(f"commit {commit} is not in this clone (shallow?); the archive cannot be checked")
            prefix = pack_path(pack_dir)
            for name, body in members.items():
                path = prefix + name[len("pack"):] if name.startswith("pack/") else name
                if files.get(path) != blob_hash(body):
                    raise ValueError(f"member {name!r} is not the file {path} of {commit[:12]}")
        base = {p: b for p, b in members.items() if p not in extra}
        _import_boundaries(base)
        with tempfile.TemporaryDirectory(prefix="rezono-kept-inspect-") as tmp:
            tree = Path(tmp)
            _materialise(base, tree)
            main, out = _check_tree_bindings(m, record, k, tree, v1)
            if out:
                raise ValueError("; ".join(out))
            main_path = main.relative_to(tree).as_posix()
        if extra - members.keys():
            raise ValueError("view archive: missing or extra source/capture members")
        extension = kept_views._checked({p: members[p] for p in extra}, old, k) if extra else None
        return ArchiveInspection(tuple(sorted(base.items())), main_path, extension)
    except (KeyError, TypeError, AttributeError, ValueError, OSError, RecursionError, tarfile.TarError) as error:
        raise kept_views.ArchiveError(f"archive inspection refused: {error}") from None


def verify(pack_dir, old, k: str, tree: Path) -> list[str]:
    """Replay capability remains guarded before archive decoding or private scratch."""
    m, record, out = _kept_target(old, k)
    if out:
        return out
    if error := unsupported_views(record, k):
        return [error]
    tar = source_dir(pack_dir) / f"{m['build']['sha256']}.tar.gz"
    if not tar.is_file():
        return [f"{tar}: no archive of what {k} was made with"]
    pin = digest_path(tar)
    if not pin.is_file():
        return [f"{tar}: no archive digest in {pin.name}"]
    from .kept_views import ArchiveError, MAX_ARCHIVE_BYTES

    try:
        with tar.open("rb") as stream:
            data = stream.read(MAX_ARCHIVE_BYTES + 1)
        with pin.open("r", encoding="utf-8") as stream:
            pin_text = stream.read(256)
        checked = inspect_archive(pack_dir, old, k, data, pin_text)
        _materialise(dict(checked.members), tree)
        return []
    except (ArchiveError, OSError, ValueError) as error:
        return [f"{k}: archive not allowed: {error}"]


def _check_tree_bindings(m, record, k: str, tree: Path, v1: bool) -> tuple[Path | None, list[str]]:
    from . import batch

    out = []
    main, refused = (tree / "pack", []) if v1 else archived_pack(tree / "pack")
    if refused:
        return None, out + refused
    tree_hash = lambda d, suffixes=None: batch.tree_sha256(tree / d, suffixes) if (tree / d).is_dir() else None
    flat = lambda d, pattern: {p.name: sha256_hex(p.read_bytes()) for p in sorted((tree / d).glob(pattern))}
    found = {
        "install": {n: sha256_hex((tree / n).read_bytes()) for n in batch.INSTALL if (tree / n).is_file()},
        "compiler": tree_hash("compiler/rezono_compiler", {".py", ".yaml"}),
        "canon": tree_hash("canon/rezono_canon", {".py"}),
        "admission": tree_hash("admission/rezono_admission", {".py"}),
        "checker": tree_hash("checker/rezono_checker", {".py"}),
        "contracts": flat("contracts", "*.yaml"),
        "publisher": tree_hash("edge/publisher/rezono_publisher", {".py"}),
        "locks": flat("requirements", "*.txt"),
        "pack": batch.tree_sha256(main),
    }
    named = {**{f: record["compiler"][f] for f in ("compiler", "canon", "contracts")},
             "admission": record["compiler"].get("admission"),  # none before admission was the compiler's
             "publisher": record["publisher"], "checker": record.get("checker"), "locks": record["locks"],
             "pack": m["pack_sha256"],
             "install": record.get("install")}
    if v1:  # bound by the git tree above; a v1 record does not name them
        del found["install"], named["install"], found["checker"], named["checker"]
    out += [f"{k}: the archived {f} is not the {f} its build record and manifest name"
            for f in found if found[f] != named[f]]
    # The runtime: the replay installs on the pinned one (requirements/.python-version and
    # .python-digest, checked by scripts/install-python.sh), so the publication must be made with it.
    for pin_file in PINS:
        current = (repo_root() / "requirements" / pin_file).read_text("utf-8")
        archived = tree / "requirements" / pin_file
        if archived.is_file() and archived.read_text("utf-8") != current:
            out.append(f"{k}: made with another runtime (requirements/{pin_file}) than the pinned one")
    if record["python"]["version"] != (repo_root() / "requirements" / ".python-version").read_text("utf-8").strip():
        out.append(f"{k}: made with Python {record['python']['version']}, not the pinned one")
    exe = record["python"].get("executable_sha256")
    if exe and exe != sha256_hex(Path(runtime()).resolve().read_bytes()):
        out.append(f"{k}: made with another Python executable than the one the replay would use")
    return main, out


def isolated_env() -> dict[str, str]:
    """The environment of every subprocess of a replay: nothing that steers Python or pip. One exception: the
    pinned runtime's own library directory, when its libpython lies there. The runtime is built for the prefix
    /opt/hostedtoolcache; unpacked elsewhere (a self-hosted runner's tool cache, scripts/python-runtime.sh) its
    interpreter finds libpython only through LD_LIBRARY_PATH, and without it the archived environment does
    not install. Only that directory, never the caller's LD_LIBRARY_PATH."""
    env = {k: os.environ[k] for k in ("PATH", "HOME", "TMPDIR") if k in os.environ}
    lib = Path(runtime()).resolve().parent.parent / "lib"
    if any(lib.glob(f"libpython{sys.version_info.major}.{sys.version_info.minor}*.so*")):
        env["LD_LIBRARY_PATH"] = str(lib)
    return env | {"PIP_CONFIG_FILE": os.devnull}


def runtime() -> str:
    """The interpreter this one was made from (the base of a virtualenv): install-python.sh checks its
    version and digest against the pins and refuses another."""
    return getattr(sys, "_base_executable", "") or sys.executable


# Starts the archived publisher without site (-S): the path is exactly the archived packages, the
# standard library, then the virtualenv's site-packages, so no .pth file or sitecustomize runs. argv: how
# many paths go before and after the standard library, those paths, then the publisher's arguments.
BOOT = ("import runpy, sys; f, b = int(sys.argv[1]), int(sys.argv[2]); p = sys.argv[3:3 + f + b]; "
        "sys.path[:0] = p[:f]; sys.path += p[f:]; sys.argv = ['rezono_publisher'] + sys.argv[3 + f + b:]; "
        "runpy.run_module('rezono_publisher', run_name='__main__', alter_sys=True)")


def run_archived(tree: Path, args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run the archived publisher in `tree` with its virtualenv: isolated (-I), without site hooks (-S),
    and with no bytecode read from or written next to any source (-B and a fresh pycache prefix, so a
    planted .pyc is never used), in an environment with nothing that steers Python or pip (plus `env`: for
    a view replay only REZONO_NODE, the verified Node executable)."""
    import sysconfig

    venv = str(tree / ".venv")
    front = [str(tree / p) for p, _, _ in CODE]
    # Without site, Python does not switch to the virtualenv's prefix: name its site-packages here.
    back = sorted({sysconfig.get_path(n, "posix_prefix", {"base": venv, "platbase": venv}) for n in ("purelib", "platlib")})
    with tempfile.TemporaryDirectory() as cache:
        argv = [str(tree / ".venv" / "bin" / "python"), "-I", "-B", "-S", "-X", f"pycache_prefix={cache}",
                "-c", BOOT, str(len(front)), str(len(back)), *front, *back, *args]
        return subprocess.run(argv, cwd=tree, env=isolated_env() | (env or {}), capture_output=True, text=True)


def install_python(tree: Path) -> str | None:
    """The archived dev lock (regen-goldens makes kept publications with it, and the build record's libraries
    depend on what is installed: docs/ci.md section 8) in a fresh virtualenv on the pinned runtime."""
    env = isolated_env() | {"PYTHON": runtime(), "VENV": str(tree / ".venv")}
    r = subprocess.run(["bash", str(repo_root() / "scripts" / "install-python.sh"), str(tree / "requirements" / "dev.txt")]
                       + [str(tree / p) for p, _, _ in CODE if (tree / p).is_dir()], env=env, capture_output=True, text=True)
    if r.returncode:
        said = "\n".join(line for line in (r.stdout + r.stderr).splitlines() if not line.startswith("[notice]"))
        return f"the archived environment does not install: {said[-2000:]}"
    return None


def install_views(tree: Path, node: str) -> str | None:
    """The viewer's archived npm lock, exactly (`npm ci`, no install scripts), next to the archived view
    sources; npm is the one installed with the verified Node."""
    npm = Path(node).with_name("npm")
    env = isolated_env() | {"PATH": f"{Path(node).parent}{os.pathsep}{os.environ.get('PATH', '')}"}
    r = subprocess.run([str(npm), "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=tree / "viewer",
                       env=env, capture_output=True, text=True)
    return f"the archived view dependencies do not install: {(r.stdout + r.stderr)[-2000:]}" if r.returncode else None


def view_inputs(pack_dir, old, k: str, candidate, tree: Path, node: str | None):
    """A view manifest's private candidate, checked completely (private_view_archive.read_candidate) and its
    Node pinned by digest; then the verified base and view sources are laid out in `tree`. The checked
    extension and the Node path, or the reasons nothing may run."""
    from . import kept_views, private_view_archive

    if candidate is None:
        return None, None, [f"{k}: a view-aware kept publication replays only with its private view archive "
                            f"(--view-archive {k}=DIR)"]
    try:
        checked = private_view_archive.read_candidate(pack_dir, old, k, Path(candidate))
        record = json.loads(old.get(key(json.loads(old.get(k))["build"]["uri"])))
        binary = kept_views.trusted_node(record["views"], node)
        if not tree.exists():
            _materialise(dict(checked.members) | dict(checked.extension.sources), tree)
        return checked.extension, binary, []
    except (ValueError, OSError, KeyError, TypeError) as error:
        return None, None, [f"{k}: view archive not allowed: {error}"]


def replay(pack_dir, old, new_root: Path, view_archives: dict | None = None, node: str | None = None,
           seeded: dict | None = None) -> list[str]:
    """Make every manifest of `old` again with the archived code, in a fresh virtualenv. Every archive is
    verified first; if one fails, nothing is installed or run and the reasons are returned. A manifest whose
    build record names views replays only from its private candidate (`view_archives`: manifest key -> the
    candidate directory): its sources are laid out with the code, its role checkpoints are put into the new
    store (and into `seeded`), and the archived publisher renders with `--views` on the recorded Node."""
    from . import batch

    work = new_root / "work"
    trees, extensions, nodes = {}, {}, {}
    out = []
    for k in manifests(old):
        m = json.loads(old.get(k))
        tree = work / m["build"]["sha256"]
        uri = m["build"].get("uri")
        body = old.get(key(uri)) if isinstance(uri, str) and uri.count("/") >= 3 else None
        record = json.loads(body) if body is not None else {}  # checked in full by verify or read_candidate
        if "views" in record:
            extensions[k], nodes[k], refused = view_inputs(pack_dir, old, k, (view_archives or {}).get(k), tree, node)
            out += refused
        elif tree not in trees.values():
            out += verify(pack_dir, old, k, tree)
        trees[k] = tree
    if out:
        return out
    # Old archived publishers may predate theory packs. Check verified metadata with current trusted code
    # before installing or running any archive; never import the archive's compiler to make this decision.
    from rezono_compiler import pack as packs
    for tree in sorted(set(trees.values())):
        main, refused = archived_pack(tree / "pack")
        if refused:
            return [f"{tree.name}: {reason}" for reason in refused]
        try:
            meta = packs.read_meta(main)
        except packs.CompileError as error:
            return [f"{tree.name}: {error}"]
        if meta["theory"]:
            return [f"{tree.name}: a theory pack cannot publish an instance"]
    for tree in sorted(set(trees.values())):
        if said := install_python(tree):
            return [f"{tree.name}: {said}"]
    for tree in sorted({trees[k] for k in extensions}):
        if said := install_views(tree, next(nodes[k] for k in extensions if trees[k] == tree)):
            return [f"{tree.name}: {said}"]
    new = store.FileStore(new_root / "store")
    for k, extension in sorted(extensions.items()):
        for name, body in extension.checkpoints:  # the frozen role inputs, never captured again
            new.put_new(name, body)
            if seeded is not None:
                seeded[name] = body
    for k, tree in trees.items():
        m = json.loads(old.get(k))
        roles = json.loads(old.get(key(m["build"]["uri"])))["profile"]["roles"]
        # Checked again after the install, right before the run: the pack and its closure as verified.
        main, refused = archived_pack(tree / "pack")
        if not refused and batch.tree_sha256(main) != m["pack_sha256"]:
            refused = [f"{k}: the archived pack is not the pack the manifest names"]
        if refused:
            return [f"{tree.name}: {r}" for r in refused]
        args = [str(main), "--store", f"file://{new_root / 'store'}", "--epoch", str(m["epoch"]),
                "--knowledge-time", m["knowledge_time"]]
        args += [a for r, mode in sorted(roles.items()) for a in ("--role", f"{r}={mode}")]
        args += [a for x in m["sources"] for a in ("--source", f"{x['source_id']}={x['position']}")]
        if m.get("proposal"):
            args += ["--proposal", m["proposal"], "--base-manifest", m.get("base_manifest", "")]
        if k in extensions:
            args.append("--views")
        r = run_archived(tree, args, {"REZONO_NODE": nodes[k]} if k in extensions else None)
        if r.returncode:
            raise RuntimeError(f"the archived publisher failed for {k}: {r.stderr[-2000:]}")
    return []


def files(s) -> dict[str, bytes]:
    """Every file of a store by key, without placeholders such as .gitkeep."""
    return {k: s.get(k) for k in s.list("") if not k.rsplit("/", 1)[-1].startswith(".")}


def manifests(s) -> list[str]:
    return [k for k in files(s) if k.split("/")[1:2] == ["manifests"]]


def key(uri: str) -> str:
    return uri.split("/", 3)[3]  # s3://<bucket>/<key>


def remake(pack_dir, old, new) -> None:
    """Publish every manifest of `old` again into `new`, from the inputs and profile it recorded."""
    from . import batch  # needs the compiler with DuckDB

    for k in manifests(old):
        m = json.loads(old.get(k))
        record = json.loads(old.get(key(m["build"]["uri"])))
        if error := unsupported_views(record, k):
            raise ValueError(error)
        e = batch.epoch(pack_dir, epoch=m["epoch"], knowledge_time=m["knowledge_time"],
                        sources=[(x["source_id"], x["position"]) for x in m["sources"]],
                        proposal=m.get("proposal", ""), base_manifest=m.get("base_manifest", ""))
        publish.publish(e, new, record["profile"]["roles"])


def differences(old, new) -> list[str]:
    """Where `new` differs from `old`, beyond the values that name the build. Empty: reproduced."""
    a, b = files(old), files(new)
    out = []
    plain = lambda fs: {k for k in fs if (k.split("/") + [""])[1] not in ARCHIVE}
    for k in sorted(plain(a) | plain(b)):
        if a.get(k) != b.get(k):
            out.append(f"{k}: {'missing' if k not in b else 'extra' if k not in a else 'other bytes'}")
    archived = lambda fs: sorted(k for k in fs if k not in plain(fs))
    if len(archived(a)) != len(archived(b)):
        out.append(f"archive: {len(archived(a))} files kept, {len(archived(b))} made")
    for k in manifests(old):
        if k not in b:
            continue
        m_old, m_new = json.loads(a[k]), json.loads(b[k])
        # The build named by the new manifest, put back to the old names; then every byte must match.
        renamed = m_new | {"compiler_sha256": m_old.get("compiler_sha256"), "build": m_old.get("build")}
        old_files = {c["file"]: c for c in m_old.get("compiled", [])}
        new_files = {c["file"]: c for c in m_new.get("compiled", [])}
        if set(old_files) != set(new_files):
            out.append(f"{k}: compiled files {sorted(old_files)} != {sorted(new_files)}")
            continue
        for name, c in new_files.items():
            if b.get(key(c["uri"])) != a.get(key(old_files[name]["uri"])):
                out.append(f"{k}: {name}: other bytes")
        if "compiled" in m_new:
            renamed["compiled"] = [c | {"uri": old_files[c["file"]]["uri"]} for c in m_new["compiled"]]
        if publish.canonical(renamed) != a[k]:
            out.append(f"{k}: manifest bytes")
        r_old, r_new = json.loads(a[key(m_old["build"]["uri"])]), json.loads(b[key(m_new["build"]["uri"])])
        if publish.canonical(r_new | {f: r_old[f] for f in r_old if f != "profile"}) != a[key(m_old["build"]["uri"])]:
            out.append(f"{k}: build record layout or profile")
    return out


def check(pack_dir, current: bool = False, view_archives: dict | None = None, node: str | None = None) -> list[str]:
    """The replay (default): every byte the same. With `current`: every byte beyond the build names. A view
    publication replays from its private candidates (`view_archives`); the role checkpoints put into the new
    store are not part of the kept publication and must come out unchanged."""
    old = store.FileStore(kept_dir(pack_dir))
    if not manifests(old):
        return [f"{kept_dir(pack_dir)}: no kept publication; make it with --make (regen-goldens does)"]
    if current:
        # --current skips archived-code verification, but cannot silently drop a recorded view capability.
        for k in manifests(old):
            m = json.loads(old.get(k))
            record = json.loads(old.get(key(m["build"]["uri"])))
            if error := unsupported_views(record, k):
                return [error]
    with tempfile.TemporaryDirectory() as tmp:
        if current:
            new = store.FileStore(tmp)
            remake(pack_dir, old, new)
            return differences(old, new)
        seeded = {}
        refused = replay(pack_dir, old, Path(tmp), view_archives, node, seeded)
        if refused:
            return refused
        new = store.FileStore(Path(tmp) / "store")
        a, b = files(old), files(new)
        changed = [k for k, body in seeded.items() if b.get(k) != body]
        if changed:
            return [f"{k}: the archived publisher changed a frozen role checkpoint" for k in sorted(changed)]
        b = {k: v for k, v in b.items() if k not in seeded or k in a}
        out = [f"{k}: {'missing' if k not in b else 'extra' if k not in a else 'other bytes'}"
               for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        for k in manifests(old):  # name what differs in the build, to say why
            r_old = json.loads(a[key(json.loads(a[k])["build"]["uri"])])
            r_new = json.loads(b[key(json.loads(b[k])["build"]["uri"])]) if k in b else {}
            out += [f"{k}: build differs at {path}" for path in _diff(r_old, r_new)]
        return out


def _diff(a, b, at="") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        return [p for k in sorted(set(a) | set(b)) for p in _diff(a.get(k), b.get(k), f"{at}.{k}")]
    return [] if a == b else [f"{at}: {json.dumps(a)[:80]} -> {json.dumps(b)[:80]}"]


def make(pack_dir, roles: dict[str, str]) -> None:
    """The first kept publication of a pack. Never over an existing one: that is history."""
    from . import batch

    s = store.FileStore(kept_dir(pack_dir))
    if manifests(s):
        raise ValueError(f"{kept_dir(pack_dir)} already holds a publication; it is never replaced")
    from rezono_compiler import pack as packs

    e = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("facts", "kept")])
    if error := unsupported_views(e.build, str(kept_dir(pack_dir))):
        raise ValueError(error)  # Refuse before publishing or writing an incomplete source archive.
    m = publish.publish(e, s, roles)
    source_dir(pack_dir).mkdir(parents=True, exist_ok=True)
    tar = source_dir(pack_dir) / f"{m['build']['sha256']}.tar.gz"
    data = archive(packs.CONTRACTS.parent, pack_dir)
    tar.write_bytes(data)
    digest_path(tar).write_text(digest_line(tar, data), "utf-8")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_publisher.kept")
    p.add_argument("pack")
    p.add_argument("--make", action="store_true", help="make the kept publication if there is none yet")
    p.add_argument("--current", action="store_true", help="make it again with the current code instead")
    p.add_argument("--view-archive", action="append", default=[], metavar="MANIFEST_KEY=DIR",
                   help="the private candidate (private_view_archive) of a kept view manifest, for its replay")
    p.add_argument("--node", help="the Node executable for a view replay (default REZONO_NODE or node on PATH); "
                   "its digest must be the recorded one")
    args = p.parse_args(argv)
    if args.make and not manifests(store.FileStore(kept_dir(args.pack))):
        make(args.pack, {"checker": "complete", "viewer": "may_read"})
        return 0
    archives = dict(a.split("=", 1) for a in args.view_archive)
    found = check(args.pack, current=args.current, view_archives=archives, node=args.node)
    for d in found:
        print(d, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
