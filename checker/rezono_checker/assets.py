"""The check `rezono:assets` (decision B10, docs/gui.md#icons-and-images): the images one role gets.

Input is plain data: the role's asset index (a list of `{file, sha256, media_type, source, licence, uri}`),
the schema bundle, the bytes of the role's published snapshots by relation, and a function that returns an
object's bytes by URI. Independent of the publisher: it derives the files the role's image cells name
itself, from the bundle's image bindings and the very snapshot bytes the role gets, never from what the
publisher selected; its own parse of every SVG against the safe list, its own PNG reading. Every finding
blocks.

- The index names exactly the files the role's image cells name: no more (an image only a hidden row names
  would tell about that row, O8) and no fewer (a cell would point at nothing).
- Every object has the hash it is listed with, a media type the viewer draws, a source and a licence.
- An SVG holds no script, event, embedded document or external reference; a PNG is a PNG of bounded size.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import xml.etree.ElementTree as ET

from .snapshots import read_rows

MEDIA_TYPES = {"image/svg+xml", "image/png"}
MAX_BYTES = 262144
MAX_PIXELS = 4194304
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}"
# An image is drawn with <image href>, which runs no script and loads nothing, and served with a CSP that
# allows none; still nothing that could act or reach outside the file is allowed in it.
FORBIDDEN = {"script", "foreignObject", "image", "iframe", "embed", "object", "a", "animate", "animateMotion",
             "animateTransform", "set", "handler", "listener", "feImage"}
PNG = b"\x89PNG\r\n\x1a\n"


def check_role_assets(index: list, bundle, snapshots: dict, read_object) -> list[dict]:
    """The findings for one role: its index against the files its own published snapshots name."""
    try:
        named = named_files(bundle, snapshots)
    except ValueError as err:
        return [{"reason": "asset_cells_unreadable", "severity": "error", "file": "", "detail": str(err)}]
    return check_assets(index, named, read_object)


def named_files(bundle, snapshots: dict) -> set:
    """The files the image cells name in these snapshots: for every slot the bundle binds as an image
    (`channels.images`, by element id, through `attributes` to its table), the value of each row of that
    table the role has, `[id, file]`. A binding to an unknown slot or a row of another shape is an error."""
    doc = json.loads(bundle) if isinstance(bundle, (str, bytes)) else bundle
    table = {a["id"]: a["table"] for a in doc.get("attributes") or []}
    named = set()
    for b in (doc.get("channels") or {}).get("images") or []:
        if b.get("slot") not in table:
            raise ValueError(f"image binding to unknown slot {b.get('slot')!r}")
        data = snapshots.get(table[b["slot"]])
        if data is None:
            continue  # the role has no snapshot of it: it reads no such cell
        for parts, _ in read_rows(data, "json").values():
            if len(parts) != 2:
                raise ValueError(f"an image cell is [id, file], not {list(parts)!r}")
            named.add(parts[1])
    return named


def check_assets(index: list, named: set, read_object) -> list[dict]:
    """The findings for one role, sorted; none when the role's images are as they should be."""
    findings: list[dict] = []

    def finding(reason: str, file: str, detail: str = "") -> None:
        findings.append({"reason": reason, "severity": "error", "file": file, **({"detail": detail} if detail else {})})

    files = [str(e.get("file")) for e in index]
    for f in sorted({f for f in files if files.count(f) > 1}):
        finding("asset_listed_twice", f)
    if files != sorted(files):
        finding("asset_index_order", "", "the index is not in file order")
    for f in sorted(set(files) - named):
        finding("asset_not_named", f)
    for f in sorted(named - set(files)):
        finding("asset_missing", f)
    for e in index:
        f = str(e.get("file"))
        if set(e) != {"file", "sha256", "media_type", "source", "licence", "uri"}:
            finding("asset_entry_shape", f)
            continue
        if not SHA256.match(str(e["sha256"])) or not str(e["source"]).strip() or not str(e["licence"]).strip():
            finding("asset_without_source", f)
        if e["media_type"] not in MEDIA_TYPES:
            finding("asset_media_type", f, str(e["media_type"]))
            continue
        data = read_object(e["uri"])
        if data is None:
            finding("asset_object_missing", f)
            continue
        if hashlib.sha256(data).hexdigest() != e["sha256"]:
            finding("asset_hash_mismatch", f)
            continue
        if len(data) > MAX_BYTES:
            finding("asset_too_large", f, f"{len(data)} bytes")
            continue
        problem = svg_problem(data) if e["media_type"] == "image/svg+xml" else png_problem(data)
        if problem:
            finding("asset_unsafe", f, problem)
    return sorted(findings, key=lambda x: (x["reason"], x["file"]))


def svg_problem(data: bytes) -> str:
    """Why an SVG may not be served, or ''."""
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return "DOCTYPE or ENTITY"
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        return f"not well-formed ({e})"
    if root.tag not in ("svg", f"{SVG}svg"):
        return "the root is not <svg>"
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in FORBIDDEN:
            return f"element <{tag}>"
        for name, value in el.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on"):
                return f"event attribute {local}"
            if local == "href" and not value.startswith("#"):
                return "a reference outside the file"
            if external(value):
                return f"a reference outside the file in {local}"
        if tag == "style" and (external(el.text or "") or "@import" in (el.text or "")):
            return "a reference outside the file in <style>"
    return ""


def external(text: str) -> bool:
    """A url(...) to anything but a fragment of the same file, or a javascript: or data: URL."""
    lowered = text.lower()
    if "javascript:" in lowered or "data:" in lowered:
        return True
    return any(not u.strip(" '\"").startswith("#") for u in re.findall(r"url\(([^)]*)\)", lowered))


def png_problem(data: bytes) -> str:
    """Why a PNG may not be served, or ''."""
    if not data.startswith(PNG) or data[12:16] != b"IHDR" or len(data) < 24:
        return "not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    if width * height > MAX_PIXELS:
        return f"{width}x{height} pixels"
    return ""
