"""Exercise the profile question reader against known pages. No gate service is required."""

import pytest


class Pages:
    """A gate that answers an ask with the pages it is given, and records what it was sent."""

    def __init__(self, *pages):
        self.pages, self.sent = list(pages), []

    def call(self, path, method="GET", body=None, headers=None):
        self.sent.append((path, method, body, headers))
        return self.pages.pop(0)


def page(rows, question="ask A where x > 1", manifest="m-3", **more):
    return 200, {"format": "rezono.answer/1", "question": "ask", "manifest_id": manifest, "output_schema": "s#A",
                 "expression": {"hash": "h", "text": question}, "dataset": {"$schema": "s#A", "rows": rows}, **more}


@pytest.mark.xfail(strict=True, raises=ImportError,
                   reason="Implement asked in deploy/profiles/edge/pilot.py: follow the supplied cursor and validate every response against its question. Read this test.")
def test_ask_pages_keep_the_question_manifest_and_schema():
    from pilot import asked

    gate = Pages(page([{"id": "a"}], next="c1"), page([{"id": "b"}]))
    assert asked(gate, "viewer", "p", "m-3", "ask A where x > 1") == [{"id": "a"}, {"id": "b"}]
    assert [s[2] for s in gate.sent] == [{"ask": "ask A where x > 1"}, {"ask": "ask A where x > 1", "after": "c1"}]
    assert all(s[0] == "/p/m-3/ask" and s[1] == "POST" and s[3] == {"Content-Type": "application/json"} for s in gate.sent)

    other_answers = [
        (422, {"cut": {"budget": "steps", "limit": 1}}),
        (200, {**page([])[1], "manifest_id": "m-2"}),
        (200, {**page([])[1], "expression": {"hash": "h", "text": "ask B where x > 1"}}),
        (200, {**page([])[1], "output_schema": "s#B"}),
        (200, {**page([])[1], "format": "rezono.answer/2"}),
    ]
    for answer in other_answers:
        with pytest.raises(SystemExit, match="ask"):
            asked(Pages(answer), "viewer", "p", "m-3", "ask A where x > 1")
