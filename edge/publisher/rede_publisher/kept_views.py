"""C3 view archive primitives: the extension of a kept view publication's archive.

The extension is checked against the kept role indexes by current code, without running archived
Node, npm or Python. These checks supplement, never replace, kept's Python/source archive checks.
Private checkpoint bytes are supplied explicitly, not fetched from a production store or exported.
A replay reads them from a private candidate (private_view_archive.read_candidate); kept.replay runs it.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import quote

from rede_canon import sha256_hex

from . import kept, view_build, views

SHA = re.compile(r"[0-9a-f]{64}")
PRIVATE = "view-inputs/"
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 50000
CORE = {"viewer/scripts/views.ts", "viewer/package.json", "viewer/package-lock.json",
        "packs/std-view/pack.yaml", "packs/std-view/palette.yaml", "packs/std-view/key.yaml", "packs/std-view/sheets.yaml"}
# Only descriptive/path PAX fields: no size override, sparse extension or unknown parser dialect.
PAX_KEYS = {b"path", b"linkpath", b"mtime", b"atime", b"ctime", b"uid", b"gid", b"uname", b"gname",
            b"comment", b"charset", b"hdrcharset"}
PAX_FIELD = re.compile(rb"([1-9][0-9]{0,9}) ([^=\n]+)=")
METADATA = {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}


class ArchiveError(ValueError):
    """A view archive extension is incomplete, unbound or unsafe."""


def _path(path: str) -> bool:
    return (isinstance(path, str) and bool(path) and "\\" not in path and ":" not in path
            and not path.startswith("/") and all(p not in ("", ".", "..") for p in path.split("/"))
            and PurePosixPath(path).as_posix() == path)


def _source_path(path: str) -> bool:
    return _path(path) and (path in ("viewer/scripts/views.ts", "viewer/package.json", "viewer/package-lock.json")
                           or path.startswith(("viewer/src/lib/", "packs/std-view/")))


def _build(component: dict) -> dict[str, str]:
    """Strictly inspect the known static component; do not execute the recorded runtime."""
    if not isinstance(component, dict) or set(component) != {"format", "files", "node"} or component["format"] != view_build.FORMAT:
        raise ArchiveError("view archive: unsupported or malformed view build")
    specs = component["files"]
    if not isinstance(specs, list) or not specs:
        raise ArchiveError("view archive: source inventory is empty")
    paths = {}
    for entry in specs:
        if (not isinstance(entry, dict) or set(entry) != {"path", "sha256"} or not _source_path(entry["path"])
                or not isinstance(entry["sha256"], str) or not SHA.fullmatch(entry["sha256"]) or entry["path"] in paths):
            raise ArchiveError("view archive: invalid or duplicate source inventory member")
        paths[entry["path"]] = entry["sha256"]
    if (list(paths) != sorted(paths) or not CORE <= paths.keys()
            or not any(p.startswith("viewer/src/lib/") and p.endswith(".ts") for p in paths)
            or not any(p.startswith("packs/std-view/messages/") and p.endswith(".mf2") for p in paths)):
        raise ArchiveError("view archive: source inventory is unordered or lacks critical source roots")
    node = component["node"]
    if (not isinstance(node, dict) or set(node) != {"executable_sha256", "version", "platform", "architecture", "versions"}
            or not isinstance(node["executable_sha256"], str) or not SHA.fullmatch(node["executable_sha256"])
            or any(not isinstance(node[k], str) or not node[k] for k in ("version", "platform", "architecture"))
            or not isinstance(node["versions"], list) or not node["versions"]):
        raise ArchiveError("view archive: malformed Node identity")
    versions = []
    for version in node["versions"]:
        if (not isinstance(version, dict) or set(version) != {"name", "version"}
                or any(not isinstance(v, str) or not v for v in version.values())):
            raise ArchiveError("view archive: malformed Node component version")
        versions.append(version["name"])
    if versions != sorted(set(versions)):
        raise ArchiveError("view archive: duplicate or unordered Node component version")
    return paths


def _target(old, manifest_key: str):
    if not _path(manifest_key):
        raise ArchiveError("view archive: invalid target manifest path")
    parts = manifest_key.split("/")
    if len(parts) != 3 or parts[1] != "manifests" or not parts[2].endswith(".json"):
        raise ArchiveError("view archive: target is not a pack's manifest")
    pack, _, name = parts
    m = json.loads(old.get(manifest_key))
    if not views.MAIN.fullmatch(m["id"]) or name != m["id"] + ".json" or m.get("proposal") or m.get("variant"):
        raise ArchiveError("view archive: target is not the named main manifest")
    key = views.key_of(m["build"]["uri"])
    body = old.get(key)
    if body is None or sha256_hex(body) != m["build"]["sha256"] or key != f"{pack}/builds/{m['build']['sha256']}.json":
        raise ArchiveError("view archive: target build is missing or has another hash")
    record = json.loads(body)
    component = record.get("views")
    specs = _build(component)
    roles = sorted({s["role"] for s in m["snapshots"] if s.get("complete") is False})
    if any(not isinstance(r, str) or not r or "/" in r or "\\" in r or r in (".", "..") for r in roles):
        raise ArchiveError("view archive: invalid rendered role")
    return pack, m, component, specs, roles


def trusted_node(component: dict, node: str | None = None) -> str:
    """The Node executable a replay renders with: the one whose bytes the recorded view build names. Checked by
    its digest only, before anything is installed; nothing of it runs here."""
    try:
        path = view_build.executable(node)
        digest = sha256_hex(Path(path).read_bytes())
    except (ValueError, OSError) as error:
        raise ArchiveError(f"view replay: {error}") from None
    if digest != component["node"]["executable_sha256"]:
        raise ArchiveError(f"view replay: Node {path} is not the executable the recorded view build names")
    return path


def input_member(pack: str, manifest: str, role: str) -> str:
    return f"{PRIVATE}{pack}/{manifest}/{quote(role, safe='')}.json"


@dataclass(frozen=True)
class CheckedViewExtension:
    """Bytes bound to the trusted kept inventory, not independently proven dependency closure/capability."""
    sources: tuple[tuple[str, bytes], ...]
    checkpoints: tuple[tuple[str, bytes], ...]


def _checked(members: dict[str, bytes], old, manifest_key: str) -> CheckedViewExtension:
    pack, m, component, specs, roles = _target(old, manifest_key)
    private = {input_member(pack, m["id"], role): views.checkpoint_key(pack, m["id"], role) for role in roles}
    if set(members) != set(specs) | set(private):
        raise ArchiveError("view archive: missing or extra source/capture members")
    for path, digest in specs.items():
        if sha256_hex(members[path]) != digest:
            raise ArchiveError(f"view archive: source hash differs for {path}")
    checkpoints = {key: members[path] for path, key in private.items()}

    class Inputs:
        def get(self, key):
            return checkpoints.get(key)

    for role in roles:
        key = views.index_key(pack, m["id"], role)
        body = old.get(key)
        if body is None:
            raise ArchiveError(f"view archive: target has no completed view index for {role}")
        index = json.loads(body)
        if (index.get("format") != views.FORMAT
                or (index.get("pack"), index.get("manifest"), index.get("role")) != (pack, m["id"], role)
                or type(index.get("relayout")) is not bool):
            raise ArchiveError("view archive: target index belongs to another role/manifest or has no mode")
        capture = views.restored_capture(Inputs(), component, pack, m["id"], role, index["relayout"])
        if capture is None or index.get("capture_sha256") != capture.sha256 or index.get("previous") != capture.descriptor().get("previous"):
            raise ArchiveError(f"view archive: private capture differs from target role index {role}")
    return CheckedViewExtension(tuple((p, members[p]) for p in sorted(specs)), tuple(sorted(checkpoints.items())))


def _pax_fields(data: bytes) -> None:
    """Inspect bounded record framing/keys, leaving value decoding to tarfile after the safety pass."""
    offset = 0
    while offset < len(data):
        field = PAX_FIELD.match(data, offset)
        if field is None:
            raise ArchiveError("view archive: malformed PAX record")
        end = offset + int(field[1])
        if end <= field.end() or end > len(data) or data[end - 1] != 10:
            raise ArchiveError("view archive: malformed PAX record length")
        if field[2] not in PAX_KEYS:
            raise ArchiveError("view archive: unsupported PAX field changes the archive protocol")
        offset = end


def _tar_bytes(data: bytes) -> bytes:
    """Bound decompression and every physical header before tarfile processes PAX/GNU metadata."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArchiveError("view archive: compressed archive exceeds verification bounds")
    # The archive protocol is tar.gz. Never try another decoder after a malformed gzip stream.
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        raw = gz.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise ArchiveError("view archive: expanded tar stream exceeds verification bounds")
    offset, count, metadata = 0, 0, 0
    while offset < len(raw):
        header = raw[offset:offset + tarfile.BLOCKSIZE]
        if header == b"\0" * tarfile.BLOCKSIZE:
            if any(memoryview(raw)[offset:]):
                raise ArchiveError("view archive: nonzero data after the tar terminator")
            break
        # frombuf inspects only this fixed-size header; it does not expand extended metadata.
        entry = tarfile.TarInfo.frombuf(header, "utf-8", "strict")
        count += 1
        if count > MAX_MEMBERS or entry.size < 0 or entry.size > MAX_MEMBER_BYTES:
            raise ArchiveError("view archive: physical members/metadata exceed verification bounds")
        if entry.type not in METADATA | {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.CONTTYPE}:
            raise ArchiveError("view archive: unsupported physical member type")
        payload = offset + tarfile.BLOCKSIZE
        end = payload + entry.size
        if end > len(raw):
            raise ArchiveError("view archive: truncated tar member or metadata")
        if entry.type in (tarfile.XHDTYPE, tarfile.XGLTYPE):
            _pax_fields(raw[payload:end])
        if entry.type in METADATA:
            metadata += 1
            if metadata > 16:
                raise ArchiveError("view archive: extended metadata chain exceeds verification bounds")
        else:
            metadata = 0
        offset += tarfile.BLOCKSIZE + ((entry.size + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE) * tarfile.BLOCKSIZE
        if offset > len(raw):
            raise ArchiveError("view archive: truncated tar member or metadata")
    return raw


def _members(data: bytes, *, allow=None) -> dict[str, bytes]:
    raw = _tar_bytes(data)
    result = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        for member in tar:
            total += member.size
            if member.size < 0 or member.size > MAX_MEMBER_BYTES or total > MAX_ARCHIVE_BYTES or len(result) >= MAX_MEMBERS:
                raise ArchiveError("view archive: members exceed verification bounds")
            if not member.isreg() or not _path(member.name) or member.name in result:
                raise ArchiveError("view archive: unsafe or duplicate archive member")
            if not (allow(member.name) if allow is not None else
                    (_source_path(member.name) or member.name.startswith(PRIVATE) or kept.allowed(member.name))):
                raise ArchiveError(f"view archive: unexpected archive member {member.name}")
            result[member.name] = tar.extractfile(member).read()
    return result


def verify(data: bytes, old, manifest_key: str) -> CheckedViewExtension:
    """Check the view extension in memory, without unpacking, installing or executing anything.

    The inventory is trusted only through the kept target's build hash. This does not independently
    establish that an edited inventory contains every runtime dependency. Critical roots are required,
    but are not a closure proof. The caller must also run kept's base checks; its replay guard stays active.
    """
    try:
        members = _members(data)
        extension = {p: b for p, b in members.items() if _source_path(p) or p.startswith(PRIVATE)}
        return _checked(extension, old, manifest_key)
    except (KeyError, TypeError, AttributeError, ValueError, tarfile.TarError, OSError) as error:
        raise ArchiveError(f"view archive extension refused: {error}") from None


def archive(root: Path, pack_dir: Path, old, manifest_key: str, checkpoints: dict[str, bytes]) -> bytes:
    """Build an opt-in private archive from explicit local inputs. No production fetch or output write."""
    try:
        pack, m, component, _, roles = _target(old, manifest_key)
        if view_build.inventory(root) != component["files"]:
            raise ArchiveError("view archive: current source inventory differs from the recorded build")
        expected = {views.checkpoint_key(pack, m["id"], r) for r in roles}
        if set(checkpoints) != expected:
            raise ArchiveError("view archive: explicit checkpoint set differs from the rendered roles")
        extension = {e["path"]: (root / e["path"]).read_bytes() for e in component["files"]}
        extension |= {input_member(pack, m["id"], r): checkpoints[views.checkpoint_key(pack, m["id"], r)] for r in roles}
        _checked(extension, old, manifest_key)
        members = _members(kept.archive(root, pack_dir))
        if set(members) & set(extension):
            raise ArchiveError("view archive: source/input member collides with the base archive")
        members |= extension
        out = io.BytesIO()
        with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for name, body in sorted(members.items()):
                entry = tarfile.TarInfo(name)
                entry.size, entry.mtime, entry.mode = len(body), 0, 0o644
                tar.addfile(entry, io.BytesIO(body))
        data = out.getvalue()
        verify(data, old, manifest_key)
        return data
    except (KeyError, TypeError, AttributeError, ValueError, OSError) as error:
        raise ArchiveError(f"view archive creation refused: {error}") from None
