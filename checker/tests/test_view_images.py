"""Published image marks are bound, readable cells of their own element, never hidden ends or URLs."""

import copy
import json

import pytest

from rede_checker.views import _node
from test_views import BUNDLE, BOXES, LINES, PAYLOAD, SNAPSHOTS, STUB, STUB_SHOWS, problems, view


def snap(*rows):
    return json.dumps([{"key": row} for row in rows]).encode()


IMAGE = {"relation": "node__picture", "value": "pictures/a.svg"}
BINDING = {"kind": "node", "slot": "node.picture"}
IMAGES = BUNDLE | {
    "attributes": [*BUNDLE["attributes"], {"id": "node.picture", "table": "node__picture", "kind": "node", "type": "text"}],
    "channels": {"images": [BINDING]},
}
READ = SNAPSHOTS | {"node__picture": snap(["a", "pictures/a.svg"], ["b/c", "pictures/b.svg"])}


def with_image(image=IMAGE, node="node/a"):
    payload = copy.deepcopy(PAYLOAD)
    payload[node]["image"] = image
    return view(payload=payload)


def test_a_tile_carries_its_bound_image_cell_and_old_tiles_still_pass():
    assert problems(*with_image(), snapshots=READ, bundle=IMAGES) == []
    assert problems(*view(), snapshots=READ, bundle=IMAGES) == []


@pytest.mark.parametrize("image", [
    None, "pictures/a.svg", [], {}, IMAGE | {"uri": "s3://private/file"},
    {"relation": [], "value": "pictures/a.svg"},
    IMAGE | {"relation": "node__label"}, IMAGE | {"value": "pictures/b.svg"},
])
def test_an_image_that_is_not_exactly_the_own_bound_cell_is_refused(image):
    got = problems(*with_image(image), snapshots=READ, bundle=IMAGES)
    assert any("image that is no bound cell the role reads" in p for p in got), got


def test_a_hidden_image_cell_and_an_unbound_readable_text_cell_are_refused():
    assert problems(*with_image(), snapshots=SNAPSHOTS, bundle=IMAGES)
    assert problems(*with_image(), snapshots=READ, bundle=BUNDLE)
    # Reading another element's identical file is no evidence of this element's cell.
    hidden = SNAPSHOTS | {"node__picture": snap(["b/c", "pictures/a.svg"])}
    assert problems(*with_image(), snapshots=hidden, bundle=IMAGES)


@pytest.mark.parametrize("file", ["https://example.invalid/a.svg", "s3://private/a", "/a.svg", "../a.svg", "a\\b.svg"])
def test_the_cell_holds_a_relative_pack_file_never_a_raw_address(file):
    read = READ | {"node__picture": snap(["a", file])}
    assert problems(*with_image(IMAGE | {"value": file}), snapshots=read, bundle=IMAGES)


@pytest.mark.parametrize("node", ["screened/node/a/node__to", "unknown/node/b/c/node__from"])
def test_a_hidden_or_unknown_end_never_carries_an_image(node):
    assert problems(*with_image(node=node), snapshots=READ, bundle=IMAGES)


def test_a_stub_never_carries_an_image_even_if_its_source_can_read_that_file():
    boxes = BOXES | {STUB: [100, 0, 10, 10]}
    clean = PAYLOAD | {STUB: {"status": "valid", "stub": STUB_SHOWS}}
    payload = PAYLOAD | {STUB: {**clean[STUB], "image": IMAGE}}
    lines = LINES | {"node/b/c->node__to": LINES["node/b/c->node__to"] | {"target": STUB}}
    assert problems(*view(boxes, clean, lines), snapshots=READ, bundle=IMAGES, stubs={STUB: STUB_SHOWS}) == []
    got = problems(*view(boxes, payload, lines), snapshots=READ, bundle=IMAGES, stubs={STUB: STUB_SHOWS})
    assert any(f"stub {STUB} shows" in p for p in got), got


def test_the_nearest_inherited_binding_wins_and_a_matrix_head_uses_its_element():
    read = {"node__picture": {("a", "pictures/a.svg")}, "leaf__picture": {("a", "pictures/leaf.svg")}}
    bundle = IMAGES | {"kinds": [{"id": "node"}, {"id": "leaf", "parent": "node"}]}
    node = {"id": "rows/leaf/a", "of": "leaf/a", "status": "valid", "image": IMAGE}
    assert _node(node, read, {}, bundle) == []
    bundle = bundle | {
        "attributes": [*bundle["attributes"], {"id": "leaf.picture", "table": "leaf__picture", "kind": "leaf", "type": "text"}],
        "channels": {"images": [BINDING, {"kind": "leaf", "slot": "leaf.picture"}]},
    }
    assert _node(node, read, {}, bundle)
    assert _node(node | {"image": {"relation": "leaf__picture", "value": "pictures/leaf.svg"}}, read, {}, bundle) == []
