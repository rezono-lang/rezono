"""The check `rezono:assets` (docs/gui.md#icons-and-images): the images one role gets.

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
SVG_NS = "http://www.w3.org/2000/svg"
SVG = f"{{{SVG_NS}}}"
XLINK = "{http://www.w3.org/1999/xlink}"
# An image is drawn with <image href>, which runs no script and loads nothing, and served with a CSP that
# allows none; still nothing that could act or reach outside the file is allowed in it.
FORBIDDEN = {"script", "foreignObject", "image", "iframe", "embed", "object", "a", "animate", "animateMotion",
             "animateTransform", "set", "handler", "listener", "feImage"}
FORBIDDEN_LOWER = {name.lower() for name in FORBIDDEN}
FORBIDDEN_ATTRS = {"base", "src", "srcset", "poster", "action", "formaction", "ping", "codebase", "data"}
BOMS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
XML_ENCODING = re.compile(r"""\bencoding\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
UNSAFE_CSS_TOKEN = re.compile(
    r"(?:(?:-webkit-)?image-set|image|src|expression)\s*\(|(?:behavior|-moz-binding)\s*:",
    re.IGNORECASE,
)
URL_OPEN = re.compile(r"url\s*\(", re.IGNORECASE)
URL_FRAGMENT = re.compile(r"""\s*(?:"#[^"()\\\r\n]+"|'#[^'()\\\r\n]+'|#[^\s"'()\\]+)\s*\)""")
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
    if data.startswith(BOMS) or b"\x00" in data:
        return "non-UTF-8 encoding or BOM"
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "not valid UTF-8"
    lowered = text.lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return "DOCTYPE or ENTITY"
    rest = text
    if text[:5].lower() == "<?xml" and len(text) > 5 and text[5].isspace():
        end = text.find("?>", 5)
        if end == -1:
            return "unterminated XML declaration"
        body = text[5:end]
        if "encoding" in body.lower():
            encs = [a or b for a, b in XML_ENCODING.findall(body)]
            if len(encs) != 1 or encs[0].lower() != "utf-8":
                return "non-UTF-8 XML declaration"
        rest = text[end + 2:]
    if "<?" in rest:
        return "processing instruction"
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return f"not well-formed ({e})"
    if root.tag not in ("svg", f"{SVG}svg"):
        return "the root is not <svg>"
    for el in root.iter():
        if el.tag.startswith("{"):
            ns, tag = el.tag[1:].split("}", 1)
        else:
            ns, tag = "", el.tag
        if ns not in ("", SVG_NS):
            return f"element in namespace {ns}"
        tag_lower = tag.lower()
        if tag_lower in FORBIDDEN_LOWER:
            return f"element <{tag}>"
        for name, value in el.attrib.items():
            local = name.rsplit("}", 1)[-1].lower()
            if local.startswith("on"):
                return f"event attribute {local}"
            if local in FORBIDDEN_ATTRS:
                return f"forbidden attribute {local}"
            if local == "href" and not value.startswith("#"):
                return "a reference outside the file"
            if unsafe_css(value):
                return f"a reference outside the file in {local}"
        if tag_lower == "style" and unsafe_css("".join(el.itertext())):
            return "a reference outside the file in <style>"
    return ""


def _strip_css_comments(text: str) -> str:
    """Remove CSS /* ... */ comments in linear time; an unclosed /* runs to the end."""
    out: list[str] = []
    pos = 0
    while True:
        start = text.find("/*", pos)
        if start == -1:
            out.append(text[pos:])
            return "".join(out)
        out.append(text[pos:start])
        end = text.find("*/", start + 2)
        if end == -1:
            return "".join(out)
        pos = end + 2


def unsafe_css(text: str) -> bool:
    """CSS that uses escapes, @import, unsafe CSS functions/properties, or an external reference."""
    if "\\" in text:
        return True
    stripped = _strip_css_comments(text)
    for candidate in (text, stripped):
        lowered = candidate.lower()
        if "@import" in lowered or UNSAFE_CSS_TOKEN.search(lowered) or external(lowered):
            return True
    return False


def external(text: str) -> bool:
    """A url(...) to anything but a fragment of the same file, or a javascript: or data: URL."""
    lowered = text.lower()
    if "javascript:" in lowered or "data:" in lowered:
        return True
    for match in URL_OPEN.finditer(lowered):
        if URL_FRAGMENT.match(lowered, match.end()) is None:
            return True
    return False


def png_problem(data: bytes) -> str:
    """Why a PNG may not be served, or ''."""
    if not data.startswith(PNG) or data[12:16] != b"IHDR" or len(data) < 24:
        return "not a PNG"
    width, height = struct.unpack(">II", data[16:24])
    if width * height > MAX_PIXELS:
        return f"{width}x{height} pixels"
    return ""
