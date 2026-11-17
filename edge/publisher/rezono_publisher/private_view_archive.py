"""Opt-in local private candidates of a kept view publication: written by `commit_archive`, read back for a
C3 replay by `read_candidate`. They live outside Git (the checkpoints hold role-private inputs); a path check
is not a permission, and nothing here fetches from a production store."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex
from . import kept, kept_views, views


@dataclass(frozen=True)
class Receipt:
    directory: Path
    sha256: str


def _snapshot(target, checkpoints):
    if any(type(d) is not dict for d in (target, checkpoints)):
        raise ValueError("private candidate requires explicit byte dictionaries")
    if len(target) + len(checkpoints) > kept_views.MAX_MEMBERS:
        raise ValueError("private candidate input count exceeds verification bounds")
    copies = target.copy(), checkpoints.copy()
    if any(type(k) is not str or type(v) is not bytes for d in copies for k, v in d.items()):
        raise ValueError("private candidate inputs must be named immutable bytes")
    if sum(4 * len(k) + len(v) for d in copies for k, v in d.items()) > kept_views.MAX_ARCHIVE_BYTES:
        raise ValueError("private candidate input bytes exceed verification bounds")
    return copies


def _unlinked(path):
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError("private candidate path is linked")


def _destination(root, pack_dir, destination):
    path = Path(destination)
    if not path.is_absolute() or ".." in path.parts or path.anchor.startswith(("\\\\", "//")):
        raise ValueError("private candidate needs an explicit local destination")
    components = path.parts[1:] if path.anchor else path.parts
    if any(not kept._portable_component(part) for part in components):
        raise ValueError("private candidate destination has a nonportable component")
    _unlinked(path)
    resolved = path.resolve()
    if not path.is_dir() or any(resolved.is_relative_to(Path(p).resolve()) for p in (root, pack_dir)) \
            or {"expected", "published"}.intersection(p.lower() for p in (*path.parts, *resolved.parts)) \
            or any((p / ".git").exists() for p in (resolved, *resolved.parents)):
        raise ValueError("private candidate destination is missing or inside Git/public output")
    return resolved


def _same(path, body):
    _unlinked(path)
    if not path.exists():
        return False
    with path.open("rb") as stream:
        if stream.read(len(body) + 1) != body:
            raise ValueError("private candidate has conflicting bytes")
    return True


def _put_new(path, body):
    _unlinked(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".candidate-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not _same(path, body):
                raise ValueError("private candidate disappeared during conditional write")
    finally:
        Path(temporary).unlink()


def commit_archive(root: Path, pack_dir: Path, target: dict[str, bytes], manifest_key: str,
                   checkpoints: dict[str, bytes], destination: Path) -> Receipt:
    """The caller authorises an exclusive private location for all captured historical roles.

    Path checks are not permissions. No Store, network, public output, archived execution
    or activation is involved. The final receipt is a logical commit, not power-loss durability.
    """
    frozen, private = _snapshot(target, checkpoints)
    destination = _destination(root, pack_dir, destination)
    data = kept_views.archive(root, pack_dir, frozen, manifest_key, private)
    if len(data) > kept_views.MAX_ARCHIVE_BYTES:
        raise ValueError("private candidate archive exceeds verification bounds")
    manifest = json.loads(frozen[manifest_key])
    build = manifest["build"]["sha256"]
    archive_name, digest_name = f"{build}.tar.gz", f"{build}.sha256"
    pin = kept.digest_line(Path(archive_name), data).encode("utf-8")
    checked = kept.inspect_archive(pack_dir, frozen, manifest_key, data, pin.decode("utf-8"))
    if checked.extension is None:
        raise ValueError("private candidate requires a checked view extension")
    payloads = {archive_name: data, digest_name: pin}
    receipt = canonical_bytes({"format": "rede.private-view-archive/1", "manifest_key": manifest_key,
        "manifest_sha256": sha256_hex(frozen[manifest_key]), "build_sha256": build,
        "target_sha256": canonical_sha256({k: sha256_hex(v) for k, v in frozen.items()}),
        "captures": {k: {"checkpoint_sha256": sha256_hex(v),
                          "capture_sha256": canonical_sha256(json.loads(v)["capture"])}
                     for k, v in checked.extension.checkpoints},
        "files": {k: {"sha256": sha256_hex(v), "size": str(len(v))} for k, v in payloads.items()}})
    candidate = destination / sha256_hex(receipt)
    _unlinked(candidate)
    committed = _same(candidate / "receipt.json", receipt)
    present = {name: _same(candidate / name, body) for name, body in payloads.items()}
    if committed and not all(present.values()):
        raise ValueError("committed private candidate is incomplete")
    candidate.mkdir(exist_ok=True)
    for name, body in payloads.items():
        if not present[name]:
            _put_new(candidate / name, body)
    for name, body in payloads.items():
        if not _same(candidate / name, body):
            raise ValueError("private candidate write is incomplete")
    _put_new(candidate / "receipt.json", receipt)
    return Receipt(candidate, sha256_hex(receipt))


RECEIPT_BYTES = 1024 * 1024


def _read(path: Path, limit: int) -> bytes:
    _unlinked(path)
    if not path.is_file():
        raise ValueError(f"private candidate has no {path.name}")
    with path.open("rb") as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"private candidate {path.name} exceeds verification bounds")
    return body


def read_candidate(pack_dir: Path, old, manifest_key: str, candidate: Path) -> "kept.ArchiveInspection":
    """A committed private candidate for one kept view manifest, checked completely before anything is
    installed or run (C3 replay). The receipt must be named by its own hash and bind exactly this kept target
    (the manifest, its build and every kept file); the archive and digest must have the bytes it names; then
    the existing base and extension inspection binds every source to the build's inventory and every
    checkpoint to its role's completed index. Only main manifests rendered without relayout are replayed."""
    candidate = Path(candidate)
    _unlinked(candidate)
    if not candidate.is_dir() or not kept_views.SHA.fullmatch(candidate.name):
        raise ValueError("private candidate directory is missing or not named by a receipt hash")
    body = _read(candidate / "receipt.json", RECEIPT_BYTES)
    if sha256_hex(body) != candidate.name:
        raise ValueError("private candidate receipt is not the one its directory names")
    receipt = json.loads(body)
    manifest = old.get(manifest_key)
    if manifest is None:
        raise ValueError(f"kept target has no {manifest_key}")
    build = json.loads(manifest)["build"]["sha256"]
    target = canonical_sha256({k: sha256_hex(v) for k, v in kept.files(old).items()})
    names = {f"{build}.tar.gz", f"{build}.sha256"}
    if (receipt.get("format") != "rede.private-view-archive/1" or receipt.get("manifest_key") != manifest_key
            or receipt.get("manifest_sha256") != sha256_hex(manifest) or receipt.get("build_sha256") != build
            or receipt.get("target_sha256") != target or set(receipt.get("files") or {}) != names):
        raise ValueError("private candidate receipt belongs to another kept target, manifest or build")
    payloads = {}
    for name, spec in receipt["files"].items():
        payloads[name] = _read(candidate / name, kept_views.MAX_ARCHIVE_BYTES)
        if spec != {"sha256": sha256_hex(payloads[name]), "size": str(len(payloads[name]))}:
            raise ValueError(f"private candidate {name} does not have the bytes its receipt names")
    checked = kept.inspect_archive(pack_dir, old, manifest_key, payloads[f"{build}.tar.gz"],
                                   payloads[f"{build}.sha256"].decode("utf-8"))
    if checked.extension is None:
        raise ValueError("private candidate requires a checked view extension")
    captures = {k: {"checkpoint_sha256": sha256_hex(v), "capture_sha256": canonical_sha256(json.loads(v)["capture"])}
                for k, v in checked.extension.checkpoints}
    if receipt.get("captures") != captures:
        raise ValueError("private candidate receipt names other captures than its archive holds")
    pack, m, _, _, roles = kept_views._target(old, manifest_key)
    for role in roles:
        index = json.loads(old.get(views.index_key(pack, m["id"], role)))
        if index.get("relayout") is not False:
            raise ValueError(f"private candidate: role {role} was rendered with relayout, which replay cannot repeat")
    return checked
