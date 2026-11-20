"""Hardening tests for SVG and XML asset validation in `rezono_checker.assets`."""
import hashlib

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
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>\\40 import "https://example.org/x.css";</style></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><style>.a{fill:\\75 rl(https://example.org/x.svg#g)}</style></svg>',
    b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg"><svg:style>\\40 import "https://example.org/x.css";</svg:style></svg:svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:\\75 rl(https://example.org/x.svg#g)"/></svg>',
    b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="@IMPORT \'https://example.org/x.css\';"/></svg>',
])
def test_css_escapes_in_style_elements_and_attributes_are_refused(bad):
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
    b'<svg xmlns="http://www.w3.org/2000/svg">\xff</svg>',
])
def test_non_utf8_utf16_doctype_entity_and_declaration_bypasses_are_refused(bad):
    assert svg_problem(bad)
    assert _reasons(bad) == ["asset_unsafe"]


@pytest.mark.parametrize("good", [
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><style>.a{fill:#c00}</style><path class="a" d="M0 0h1"/></svg>',
    b'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:#c00"/></svg>',
    b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g"/></defs><rect style="fill:url(#g)"/></svg>',
    b'<svg:svg xmlns:svg="http://www.w3.org/2000/svg"><svg:defs><svg:linearGradient id="g"/></svg:defs><svg:style>.a{fill:url(#g)}</svg:style><svg:rect class="a"/></svg:svg>',
])
def test_clean_utf8_svgs_with_local_styles_still_pass(good):
    assert svg_problem(good) == ""
    assert _reasons(good) == []
