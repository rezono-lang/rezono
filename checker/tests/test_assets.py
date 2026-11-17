"""The check rede:assets (decision B10): the images one role gets are exactly those its cells name, intact,
with source and licence, and unable to act or reach outside the file."""
import hashlib
import json
import struct
import zlib

import pytest

from rede_checker.assets import check_assets, check_role_assets, png_problem, svg_problem

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><style>.a{fill:#c00}</style><path class="a" d="M0 0h1"/></svg>'


def entry(file, data, media_type="image/svg+xml", **changes):
    return {"file": file, "sha256": hashlib.sha256(data).hexdigest(), "media_type": media_type,
            "source": "example/x@0123abc:a.svg", "licence": "CC0-1.0", "uri": f"s3://r/{file}"} | changes


def reasons(index, named, objects):
    return [f["reason"] for f in check_assets(index, set(named), objects.get)]


def png(width, height):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))


def test_an_index_of_exactly_the_named_files_passes():
    assert reasons([entry("a.svg", SVG)], {"a.svg"}, {"s3://r/a.svg": SVG}) == []


def test_an_image_no_cell_names_or_a_named_image_missing_blocks():
    assert reasons([entry("a.svg", SVG)], set(), {"s3://r/a.svg": SVG}) == ["asset_not_named"]
    assert reasons([], {"a.svg"}, {}) == ["asset_missing"]


def test_a_changed_object_or_one_without_source_blocks():
    assert reasons([entry("a.svg", SVG)], {"a.svg"}, {"s3://r/a.svg": SVG + b" "}) == ["asset_hash_mismatch"]
    assert reasons([entry("a.svg", SVG, licence=" ")], {"a.svg"}, {"s3://r/a.svg": SVG}) == ["asset_without_source"]
    assert reasons([entry("a.svg", SVG, media_type="text/html")], {"a.svg"}, {"s3://r/a.svg": SVG}) == ["asset_media_type"]


@pytest.mark.parametrize("bad", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink"><use x:href="https://e/x.svg#a"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://e/x.svg#g)"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://e/x.css";</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AA"/></svg>',
    b'<!DOCTYPE svg [<!ENTITY a "a">]><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<html/>',
])
def test_an_svg_that_could_act_or_reach_outside_blocks(bad):
    assert svg_problem(bad)
    assert reasons([entry("a.svg", bad)], {"a.svg"}, {"s3://r/a.svg": bad}) == ["asset_unsafe"]


def test_an_svg_with_its_own_styles_gradients_and_fragments_passes():
    ok = (b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink"><defs>'
          b'<linearGradient id="g"><stop offset="0"/></linearGradient><path id="p" d="M0 0"/></defs>'
          b'<use x:href="#p" fill="url(#g)"/><style>.a{fill:url(#g)}</style></svg>')
    assert svg_problem(ok) == ""


def test_a_png_of_bounded_size_passes_and_anything_else_blocks():
    assert png_problem(png(64, 64)) == ""
    assert png_problem(png(4096, 4096))
    assert png_problem(b"GIF89a....................")


BUNDLE = {"attributes": [{"id": "node.image", "table": "node__image"}], "channels": {"images": [{"kind": "node", "slot": "node.image"}]}}


def snapshot(*rows):
    return json.dumps([{"key": list(r)} for r in rows]).encode()


def test_the_named_files_come_from_the_role_s_own_snapshot_bytes():
    """The checker derives what the role's cells name itself: an index the publisher filled from rows the
    role does not get (here `secret`) is refused, whatever the publisher thought it selected."""
    secret = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>'
    index = [entry("a.svg", SVG), entry("secret.svg", secret)]
    objects = {"s3://r/a.svg": SVG, "s3://r/secret.svg": secret}
    guest = {"node__image": snapshot(["a", "a.svg"])}
    assert [f["reason"] for f in check_role_assets(index, BUNDLE, guest, objects.get)] == ["asset_not_named"]
    assert check_role_assets(index[:1], json.dumps(BUNDLE), guest, objects.get) == []
    assert [f["reason"] for f in check_role_assets(index[:1], BUNDLE, {}, objects.get)] == ["asset_not_named"]
    bad = {"node__image": snapshot(["a"])}
    assert [f["reason"] for f in check_role_assets(index[:1], BUNDLE, bad, objects.get)] == ["asset_cells_unreadable"]
