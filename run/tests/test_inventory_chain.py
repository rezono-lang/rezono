import pytest

from offline_cases import implementation, case


def test_inventory_chain():
    traverse = implementation("inventory_chain.py", "resources")
    before, root, tail = case()["inventory"]
    tagged = before["resources"][0]
    after_tail = dict(tail, resources=[tagged])
    expected = root["resources"] + [tagged]
    assert traverse([before, after_tail, root], "after", "root") == expected
    assert traverse([root, tail], "after", "root") == root["resources"]
    for pages in ([root], [tail], [root, root, tail], [root, dict(tail, next_page_id="root")],
                  [root, dict(tail, sweep_id="other")], [root, tail, dict(tail, page_id="extra")]):
        assert traverse(pages, "after", "root") is None
