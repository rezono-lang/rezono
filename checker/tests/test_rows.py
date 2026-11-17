"""The check of a role's row trees (rezono_checker.proof.check_rows, O(page) step 3): each tree holds exactly
its snapshot, in key order, text ordered by its UTF-8 bytes. Trees made by hand here, not by the publisher."""

import hashlib
import json

from rezono_checker.proof import FORMAT, check_rows

# In UTF-16 (JavaScript's `<`) U+1F600 sorts before U+FFFF; in UTF-8 bytes after it. A key that begins
# another sorts first, element by element: ["a"] < ["a", "b"] < ["a b"].
KEYS = [["a"], ["a", "b"], ["a b"], ["￿"], ["\U0001F600"]]


def sha(b):
    return hashlib.sha256(b).hexdigest()


def dumps(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def snapshot(keys):
    return dumps([{"key": k} for k in keys])


def leaf(rel, keys):
    return dumps({"format": FORMAT, "tree": "rows", "relation": rel, "level": 0, "rows": [{"key": k} for k in keys]})


def tree(rel, keys):
    data = leaf(rel, keys)
    path = f"rows/{rel}/0/0.json"
    return {path: data}, {"file": path, "sha256": sha(data), "levels": 1, "count": len(keys)}


def test_the_exact_tree_passes_and_text_is_ordered_by_its_utf8_bytes():
    pieces, root = tree("r", KEYS)
    assert check_rows({"r": snapshot(KEYS), "empty": snapshot([])}, pieces, {"r": root, "empty": {"count": 0}}, 4096, 8) == []
    utf16 = sorted(KEYS, key=lambda k: json.dumps(k))  # code units, not bytes
    assert utf16 != KEYS
    pieces, root = tree("r", utf16)
    assert any("not the role's snapshot" in p for p in check_rows({"r": snapshot(KEYS)}, pieces, {"r": root}, 4096, 8))


def test_a_two_level_tree_passes_and_wrong_bounds_are_found():
    pieces, children = {}, []
    for n, part in enumerate([KEYS[:2], KEYS[2:]]):
        data = leaf("r", part)
        pieces[f"rows/r/0/{n}.json"] = data
        children.append({"first": part[0], "last": part[-1], "file": f"rows/r/0/{n}.json", "sha256": sha(data)})
    page = dumps({"format": FORMAT, "tree": "rows", "relation": "r", "level": 1, "children": children})
    pieces["rows/r/1/0.json"] = page
    root = {"file": "rows/r/1/0.json", "sha256": sha(page), "levels": 2, "count": len(KEYS)}
    assert check_rows({"r": snapshot(KEYS)}, pieces, {"r": root}, 4096, 8) == []
    children[0]["last"] = ["a"]
    page = dumps({"format": FORMAT, "tree": "rows", "relation": "r", "level": 1, "children": children})
    pieces["rows/r/1/0.json"] = page
    root["sha256"] = sha(page)
    assert any("bounds" in p for p in check_rows({"r": snapshot(KEYS)}, pieces, {"r": root}, 4096, 8))


def test_a_missing_row_a_wrong_count_an_empty_root_and_a_stray_tree_are_found():
    snap = {"r": snapshot(KEYS)}
    pieces, root = tree("r", KEYS[:-1])
    assert any("count" in p for p in check_rows(snap, pieces, {"r": root}, 4096, 8))
    root["count"] = len(KEYS)
    assert any("not the role's snapshot" in p for p in check_rows(snap, pieces, {"r": root}, 4096, 8))
    pieces, root = tree("r", KEYS)
    assert any("count of 0" in p for p in check_rows(snap | {"e": snapshot([])}, pieces, {"r": root, "e": {"count": 1}}, 4096, 8))
    assert any("no root" in p for p in check_rows(snap | {"e": snapshot([])}, pieces, {"r": root}, 4096, 8))
    assert any("has no snapshot" in p for p in check_rows(snap, pieces, {"r": root, "x": {"count": 0}}, 4096, 8))
    pieces["rows/r/0/1.json"] = b"{}"
    assert any("no tree reaches" in p for p in check_rows(snap, pieces, {"r": root}, 4096, 8))
    assert any("more than" in p for p in check_rows(snap, tree("r", KEYS)[0], {"r": root}, 40, 8))


def test_a_relation_with_two_columns_has_its_inverse_tree_exactly():
    arrows = [["x", "b"], ["y", "a"], ["z", "a"]]
    pieces, root = tree("arrow", arrows)
    back = sorted(arrows, key=lambda k: k[::-1])
    data = dumps({"format": FORMAT, "tree": "inverse", "relation": "arrow", "level": 0, "rows": [{"key": k} for k in back]})
    pieces["inverse/arrow/0/0.json"] = data
    inverse = {"arrow": {"file": "inverse/arrow/0/0.json", "sha256": sha(data), "levels": 1}}
    snap = {"arrow": snapshot(arrows)}
    assert check_rows(snap, pieces, {"arrow": root}, 4096, 8, inverse) == []
    assert any("no root for a relation with two columns" in p for p in check_rows(snap, pieces, {"arrow": root}, 4096, 8, {}))
    wrong = dumps({"format": FORMAT, "tree": "inverse", "relation": "arrow", "level": 0, "rows": [{"key": k} for k in arrows]})
    pieces["inverse/arrow/0/0.json"] = wrong
    inverse["arrow"]["sha256"] = sha(wrong)
    assert any("key reversed" in p for p in check_rows(snap, pieces, {"arrow": root}, 4096, 8, inverse))
    one = {"r": snapshot([["a"]])}
    p1, r1 = tree("r", [["a"]])
    assert any("without two columns" in p for p in check_rows(one, p1, {"r": r1}, 4096, 8, {"r": inverse["arrow"]}))
