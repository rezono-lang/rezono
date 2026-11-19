"""Check one product's default listening transport against its pinned vendor page.

The expected rows and the cited line come from the vendor page itself, never from the engine.
Read decisions/platform-vendor-transport-evidence.md.
"""

from rezono_compiler import sources
from rules_support import states

from query_fixture import ROOT

RELATION = "published_default_transport"
FIELDS = ("product", "series", "protocol", "port", "source_url", "source_sha256")
INSPECTION = "Vendor transport inspection"


def published_for(product):
    """The published default transports of one product, as text tuples."""
    _, _, (state,) = states(ROOT)
    assert RELATION in state.derived, f"Missing derived relation: {RELATION}"
    return {row for row in state.derived[RELATION] if row[0] == product}


def check_vendor_transport(stem, expected, revision, line, fragment_sha256):
    """Every expected row is published for its product, and nothing else is.

    The source fact file `facts/<stem>_source.yaml` holds one row per expected transport. Its
    sidecar cites the inspected line of the same page: the release ref, the line and the SHA-256 of
    that line's exact bytes including its terminator.
    """
    products = {row[0] for row in expected}
    assert len(products) == 1, "one product per transport task"
    product, = products
    want = {tuple(str(value) for value in row) for row in expected}
    assert published_for(product) == want, f"published default transports for {product}"

    path = ROOT / "facts" / f"{stem}_source.yaml"
    assert path.is_file(), f"Missing vendor evidence: facts/{path.name}"
    model, _, _ = states(ROOT)
    entries = sources.file_entries(model, path)
    assert len(entries) == len(expected) * (1 + len(FIELDS)), "one source row per expected transport"
    url, = {row[4] for row in expected}
    cited = {
        "kind": "tool",
        "name": INSPECTION,
        "revision": revision,
        "position": f"L{line}",
        "url": url,
        "fragment_sha256": fragment_sha256,
    }
    for entry in entries:
        assert entry["sources"] == [cited], entry["row"]
