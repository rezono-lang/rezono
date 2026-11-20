"""Hardening tests for SVG and XML asset validation in `rezono_checker.assets`."""
import hashlib
import time

import pytest

from rezono_checker.assets import check_assets, svg_problem


def _entry(data: bytes) -> dict:
    return {
        "file": "icon.svg",
        "sha256": hashlib.sha256(data).hexdigest(),
        "media_type": "image/svg+xml",
        "source": "example/icons@0123abc:icon.svg",
        "licence": "CC0-1.0",
        "uri": "s3://r/icon.svg",
    }


def _reasons(data: bytes) -> list[str]:
    return [f["reason"] for f in check_assets([_entry(data)], {"icon.svg"}, {"s3://r/icon.svg": data}.get)]


@pytest.mark.parametrize("bad", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@IMPORT "https://example.org/x.css";</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@Import "https://example.org/x.css";</style></svg>',
    b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg"><svg:style>@IMPORT "https://example.org/x.css";</svg:style></svg:svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style><x/>@import "https://example.org/x.css";</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style><x>@IMPORT "https://example.org/x.css";</x></style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@imp<x/>ort "https://example.org/x.css";</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@imp/**/ort "https://example.org/x.css";</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{fill:u/**/rl(https://example.org/x.svg#g)}</style></svg>',
])
def test_style_case_variant_child_tail_and_comment_import_bypasses_are_refused(bad):
    assert svg_problem(bad)
    assert _reasons(bad) == ["asset_unsafe"]


@pytest.mark.parametrize("bad", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{content:"url(#a";background:url(https://example.org/x.png);}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{content:"url(#a)";background:url(https://example.org/x.png);}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{fill:url(#a) url(https://example.org/x.png)}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(#a) url(https://example.org/x.svg#g)"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{background-image:image-set("https://example.org/x.png" 1x)}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{background-image:-webkit-image-set("https://example.org/x.png" 1x)}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{background-image:image("https://example.org/x.png")}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>@font-face{font-family:f;src:src("https://example.org/f.woff2")}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{width:expression(alert(1))}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{behavior:url(#x)}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{-moz-binding:url(#x)}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{background:image-/**/set("https://example.org/x.png" 1x)}</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="background-image:image-set(\'https://example.org/x.png\' 1x)"/></svg>',
])
def test_greedy_url_and_alternative_css_loader_bypasses_are_refused(bad):
    assert svg_problem(bad)
    assert _reasons(bad) == ["asset_unsafe"]


@pytest.mark.parametrize("bad", [
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>\\40 import "https://example.org/x.css";</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{fill:\\75 rl(https://example.org/x.svg#g)}</style></svg>',
    b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg"><svg:style>\\40 import "https://example.org/x.css";</svg:style></svg:svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:\\75 rl(https://example.org/x.svg#g)"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="@IMPORT \'https://example.org/x.css\';"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="\\75 rl(https://example.org/x.svg#g)"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect filter="\\75 rl(https://example.org/x.svg#g)"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect fill="u/**/rl(https://example.org/x.svg#g)"/></svg>',
])
def test_css_escapes_in_style_elements_and_attributes_are_refused(bad):
    assert svg_problem(bad)
    assert _reasons(bad) == ["asset_unsafe"]


@pytest.mark.parametrize("bad", [
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:h="http://www.w3.org/1999/xhtml"><h:img src="https://example.org/x.png"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:h="http://www.w3.org/1999/xhtml"><h:div/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" xml:base="https://example.org/"><use href="#p"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g src="https://example.org/x.png"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g srcset="https://example.org/x.png 1x"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g poster="https://example.org/x.png"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g action="https://example.org/x"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g formaction="https://example.org/x"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g ping="https://example.org/x"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g codebase="https://example.org/"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><g data="https://example.org/x"/></svg>',
])
def test_non_svg_namespaces_and_external_loading_attributes_are_refused(bad):
    assert svg_problem(bad)
    assert _reasons(bad) == ["asset_unsafe"]


@pytest.mark.parametrize("bad", [
    '<!DOCTYPE svg [<!ENTITY a "x">]><svg xmlns="http://www.w3.org/2000/svg"/>'.encode("utf-16"),
    '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>'.encode("utf-16-be"),
    '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>'.encode("utf-16-le"),
    '<!ENTITY x "y"><svg xmlns="http://www.w3.org/2000/svg"/>'.encode("utf-16"),
    '<svg xmlns="http://www.w3.org/2000/svg"/>'.encode("utf-16"),
    b'\xff\xfe<svg xmlns="http://www.w3.org/2000/svg"/>',
    b'\xef\xbb\xbf<svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<?xml version="1.0" encoding="ISO-8859-1"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<?xml version="1.0" encoding="UTF-16"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<!doctype svg><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<?xml-stylesheet type="text/css" href="https://example.org/x.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<?xml-model href="https://example.org/x.rng"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<?xml version="1.0" encoding="UTF-8"?><?xml-stylesheet type="text/css" href="https://example.org/x.css"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    b'<svg xmlns="http://www.w3.org/2000/svg">\xff</svg>',
])
def test_non_utf8_utf16_doctype_entity_and_declaration_bypasses_are_refused(bad):
    assert svg_problem(bad)
    assert _reasons(bad) == ["asset_unsafe"]


def test_unterminated_xml_declarations_and_css_comments_run_in_linear_time():
    unterminated_xml = b"<?xml " * 30000
    unterminated_css = b'<svg xmlns="http://www.w3.org/2000/svg"><style>' + b"/*" * 30000 + b"</style></svg>"

    start = time.monotonic()
    assert svg_problem(unterminated_xml)
    assert svg_problem(unterminated_css) == ""
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, f"svg_problem took {elapsed:.2f}s on large unterminated inputs"


@pytest.mark.parametrize("good", [
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><style>.a{fill:#c00}</style><path class="a" d="M0 0h1"/></svg>',
    b'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:#c00"/></svg>',
    b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/></defs><rect style="fill:url(#g)"/></svg>',
    b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg"><svg:defs><svg:linearGradient id="g"/></svg:defs><svg:style>.a{fill:url(#g)}</svg:style><svg:rect class="a"/></svg:svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink" xml:lang="en"><defs><linearGradient id="g"/><path id="p" d="M0 0"/></defs><use x:href="#p" fill="url(\'#g\')" style="stroke:url(\'#g\')"/></svg>',
])
def test_clean_utf8_svgs_with_local_styles_still_pass(good):
    assert svg_problem(good) == ""
    assert _reasons(good) == []
