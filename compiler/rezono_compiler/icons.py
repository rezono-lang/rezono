"""Icons per kind (decision B10, docs/gui.md#icons-and-images): an SVG in a pack's `icons/`, listed in
`icons/sources.yaml` with its hash, a pinned source and a licence. The compiler checks every icon against a
strict safe list and gives the viewer a tree of elements, never SVG text: the viewer draws the tree in ink
(`currentColor`), so an icon never carries a status colour and never runs anything.
"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

SVG = "{http://www.w3.org/2000/svg}"
# Elements and attributes an icon may hold: line art, nothing that refers outside itself (no id, use, href,
# style or class, which would reach the page it is drawn in).
ELEMENTS = {"svg", "g", "path", "circle", "ellipse", "rect", "line", "polyline", "polygon", "title"}
ATTRIBUTES = {
    "viewBox", "fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit",
    "stroke-dasharray", "fill-rule", "clip-rule", "opacity", "transform",
    "d", "x", "y", "width", "height", "rx", "ry", "cx", "cy", "r", "x1", "y1", "x2", "y2", "points",
}
# The root's own size is the viewer's to set; only its viewBox and inherited paint count.
ROOT_IGNORED = {"width", "height", "version"}
PAINT = {"fill", "stroke"}
INK = {"none", "currentColor"}
MAX_BYTES = 16384
SOURCES = "sources.yaml"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# A pinned source: `<repository>@<commit>:<path>`, or a URL.
PINNED = re.compile(r"^([\w.-]+/[\w.-]+@[0-9a-f]{7,40}:\S+|https://\S+)$")


def sources(pack_dir: Path, where: str, errors: list[str]) -> dict[str, dict]:
    """The listed icons of one pack, by file (relative to the pack): `{file, sha256, source, licence}` each."""
    path = pack_dir / "icons" / SOURCES
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out: dict[str, dict] = {}
    for e in data if isinstance(data, list) else [data]:
        if not isinstance(e, dict) or set(e) != {"file", "sha256", "source", "licence"}:
            errors.append(f"{where}: icons/{SOURCES}: entry {e} needs exactly file, sha256, source and licence")
            continue
        if not SHA256.match(str(e["sha256"])) or not PINNED.match(str(e["source"])) or not str(e["licence"]).strip():
            errors.append(f"{where}: icons/{SOURCES}: {e['file']} needs a sha256, a pinned source and a licence")
            continue
        if e["file"] in out:
            errors.append(f"{where}: icons/{SOURCES}: {e['file']} is listed twice")
        out[str(e["file"])] = {k: str(v) for k, v in e.items()}
    return out


def icon(pack_dir: Path, file: str, listed: dict[str, dict], where: str, errors: list[str]) -> dict | None:
    """The icon a kind sign names (`icons/<name>.svg`), checked, as the bundle carries it (contracts/bundle.yaml,
    `Icon`); None after an error."""
    path = pack_dir / file
    if not file.startswith("icons/") or ".." in Path(file).parts or not file.endswith(".svg"):
        errors.append(f"{where}: icon '{file}' must be an .svg file under icons/")
        return None
    if not path.is_file():
        errors.append(f"{where}: icon '{file}' does not exist")
        return None
    entry = listed.get(file)
    if entry is None:
        errors.append(f"{where}: icon '{file}' is not listed in icons/{SOURCES} with its source and licence")
        return None
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"]:
        errors.append(f"{where}: icon '{file}' has sha256 {digest}, icons/{SOURCES} lists {entry['sha256']}")
        return None
    if len(data) > MAX_BYTES:
        errors.append(f"{where}: icon '{file}' is {len(data)} bytes, more than {MAX_BYTES}")
        return None
    tree = parse(data, f"{where}: icon '{file}'", errors)
    if tree is None:
        return None
    return {"sha256": digest, "file": file, "source": entry["source"], "licence": entry["licence"]} | tree


def parse(data: bytes, where: str, errors: list[str]) -> dict | None:
    """An SVG as a tree of safe elements: `{view_box, attributes, children}`, each child `{tag, attributes,
    children}`, attributes as `{name, value}` sorted by name. Anything outside the safe list is an error."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        errors.append(f"{where}: a DOCTYPE or ENTITY is not allowed")
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        errors.append(f"{where}: not well-formed XML ({e})")
        return None
    found: list[str] = []

    def walk(el: ET.Element, is_root: bool) -> dict:
        tag = el.tag[len(SVG):] if el.tag.startswith(SVG) else el.tag
        if tag not in ELEMENTS or (tag == "svg") != is_root:
            found.append(f"element <{tag}>")
        attributes = []
        for name, value in sorted(el.attrib.items()):
            if is_root and name in ROOT_IGNORED:
                continue
            if name not in ATTRIBUTES:
                found.append(f"attribute {name}")
            elif name in PAINT and value not in INK:
                found.append(f"{name}='{value}' (an icon is drawn in ink: none or currentColor)")
            attributes.append({"name": name, "value": value})
        children = [walk(c, False) for c in el]
        if (el.text or "").strip() and tag != "title":
            found.append(f"text in <{tag}>")
        return {"tag": tag, "attributes": attributes, "children": children}

    tree = walk(root, True)
    if found:
        errors.append(f"{where}: not on the safe list: {', '.join(sorted(set(found)))}")
        return None
    view_box = next((a["value"] for a in tree["attributes"] if a["name"] == "viewBox"), None)
    if view_box is None:
        errors.append(f"{where}: needs a viewBox")
        return None
    return {
        "view_box": view_box,
        "attributes": [a for a in tree["attributes"] if a["name"] != "viewBox"],
        "children": [c for c in tree["children"] if c["tag"] != "title"],
    }
