"""C3: static view implementation identity and private, immutable layout inputs.

Only the static component enters the shared build record. Per-role capture hashes belong to that
role's view index; the bytes stay private for the later kept-archive/replay step.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

from rezono_canon import canonical_bytes, sha256_hex

ROOT = Path(__file__).resolve().parents[3]
FORMAT = "rede.view-build/1"
CAPTURE = "rede.view-capture/1"
CHECKPOINT = "rede.view-inputs/1"


def node_env() -> dict[str, str]:
    """No injected Node module, option or alternate ICU data participates in layout."""
    return {k: v for k, v in os.environ.items() if not k.upper().startswith("NODE_")}


def inventory(root: Path = ROOT) -> list[dict[str, str]]:
    """One conservative source set, shared with future archival; no import-parser approximation."""
    paths = [root / "viewer/scripts/views.ts", root / "viewer/package.json", root / "viewer/package-lock.json"]
    for directory in (root / "viewer/src/lib", root / "packs/std-view"):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"view build: missing or linked source directory {directory}")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"view build: linked source {path}")
            if path.is_file() and "expected" not in path.relative_to(directory).parts:
                # Test-only files never participate in the plain-Node entry.
                if not path.name.endswith((".test.ts", ".spec.ts")):
                    paths.append(path)
    out = []
    for path in sorted(set(paths), key=lambda p: p.relative_to(root).as_posix()):
        if path.is_symlink() or not path.is_file() or any(p.is_symlink() for p in path.parents if p != root.parent):
            raise ValueError(f"view build: missing or linked source {path}")
        out.append({"path": path.relative_to(root).as_posix(), "sha256": sha256_hex(path.read_bytes())})
    return out


def executable(node: str | None = None) -> str:
    found = shutil.which(node or os.environ.get("REZONO_NODE", "node"))
    if not found:
        raise ValueError("view build: Node executable not found")
    return str(Path(found).resolve())


def runtime(node: str, expected: dict | None = None) -> dict:
    digest = sha256_hex(Path(node).read_bytes())
    if expected is not None and digest != expected.get("executable_sha256"):
        raise ValueError("view build: Node executable differs from the recorded build")
    expression = "JSON.stringify({version:process.version,versions:process.versions,platform:process.platform,architecture:process.arch})"
    r = subprocess.run([node, "--eval", f"console.log({expression})"], check=True, capture_output=True,
                       text=True, env=node_env())
    d = json.loads(r.stdout)
    return {"executable_sha256": digest, "version": d["version"], "platform": d["platform"],
            "architecture": d["architecture"],
            "versions": [{"name": k, "version": v} for k, v in sorted(d["versions"].items())]}


def component(node: str, root: Path = ROOT, expected: dict | None = None) -> dict:
    files = inventory(root)
    if expected is not None and files != expected.get("files"):
        raise ValueError("view build: source or npm lock differs from the recorded build")
    out = {"format": FORMAT, "files": files, "node": runtime(node, expected.get("node") if expected else None)}
    if expected is not None and out != expected:
        raise ValueError("view build: implementation differs from the recorded build")
    return out


@dataclass(frozen=True)
class CapturedRole:
    pack: str
    manifest: str
    role: str
    relayout: bool
    previous: str = ""
    index: bytes = b""
    layouts: tuple[tuple[str, bytes], ...] = ()

    def descriptor(self) -> dict:
        return {"format": CAPTURE, "pack": self.pack, "manifest": self.manifest, "role": self.role,
                "relayout": self.relayout,
                "layouts": [{"path": s, "sha256": sha256_hex(b)} for s, b in self.layouts],
                **({"previous": {"manifest": self.previous, "sha256": sha256_hex(self.index)}} if self.previous else {})}

    @property
    def sha256(self) -> str:
        return sha256_hex(canonical_bytes(self.descriptor()))

    def checkpoint(self, build: dict) -> bytes:
        """Private conditional object: original bytes survive a process failure before the role index."""
        encode = lambda b: base64.b64encode(b).decode("ascii")
        return canonical_bytes({"format": CHECKPOINT, "build": build, "capture": self.descriptor(),
                                "index": encode(self.index),
                                "layouts": [{"path": k, "bytes": encode(v)} for k, v in self.layouts]})


def restore(body: bytes, build: dict, pack: str, manifest: str, role: str, relayout: bool) -> CapturedRole:
    """Check the private object's shape, binding and payload hashes before any captured bytes are used."""
    try:
        d = json.loads(body)
        if set(d) != {"format", "build", "capture", "index", "layouts"} or d["format"] != CHECKPOINT or d["build"] != build:
            raise ValueError("component or shape differs")
        descriptor = d["capture"]
        if ((descriptor["pack"], descriptor["manifest"], descriptor["role"]) != (pack, manifest, role)
                or type(descriptor["relayout"]) is not bool or descriptor["relayout"] != relayout):
            raise ValueError("capture binding differs")
        layout_bytes = tuple((e["path"], base64.b64decode(e["bytes"], validate=True)) for e in d["layouts"])
        if (any(set(e) != {"path", "bytes"} for e in d["layouts"])
                or any(not isinstance(k, str) or not k or "/" in k or "\\" in k or k.startswith(".") for k, _ in layout_bytes)
                or [k for k, _ in layout_bytes] != sorted({k for k, _ in layout_bytes})):
            raise ValueError("layout paths differ")
        previous = descriptor.get("previous", {}).get("manifest", "")
        result = CapturedRole(pack, manifest, role, relayout, previous,
                              base64.b64decode(d["index"], validate=True), layout_bytes)
        if result.descriptor() != descriptor or (not previous and (result.index or result.layouts)) or (relayout and previous):
            raise ValueError("capture payload hashes differ")
        return result
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"view build: invalid private input checkpoint for {role}: {error}") from None


@dataclass(frozen=True)
class PreparedViews:
    component_bytes: bytes
    node: str
    pack: str
    manifest: str
    captures: tuple[CapturedRole, ...]

    @property
    def component(self) -> dict:
        return json.loads(self.component_bytes)

    def capture(self, role: str) -> CapturedRole:
        found = [c for c in self.captures if c.role == role]
        if len(found) != 1 or (found[0].pack, found[0].manifest) != (self.pack, self.manifest):
            raise ValueError(f"view build: no unique prepared inputs for role {role}")
        return found[0]

    def verify(self, expected: dict | None = None) -> None:
        old = self.component
        if expected is not None and old != expected:
            raise ValueError("view build: prepared component differs from the manifest's build")
        if inventory() != old.get("files"):
            raise ValueError("view build: source or npm lock differs from the recorded build")
        if runtime(self.node, old.get("node")) != old.get("node"):
            raise ValueError("view build: Node runtime differs from the recorded build")
