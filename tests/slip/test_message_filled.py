"""One module fills a message for the page, the REPL and the MCP server (decisions/viewer-slip.md, "Filling a
message"). The texts are written here by hand from tests/fixtures/slip/messages/*.mf2."""

import pytest
from slip_support import FIXTURE, MissingMessageFiller, fill

RESOURCES = [{"lang": lang, "resource": (FIXTURE / "messages" / f"{lang}.mf2").read_text(encoding="utf-8")}
             for lang in ("en", "nl")]
FLAGGED = {"i": "item-a", "a": "12"}


@pytest.mark.xfail(
    strict=True,
    raises=(MissingMessageFiller, AssertionError),
    reason=(
        "extra: decisions/viewer-slip.md: Write viewer/messages/src/fill.ts, in a folder of its own with its own package.json and outside "
        "viewer/src/lib: fill(resources, lang, id, args) returns the text with every {$name} replaced, undefined "
        "for a message that is not there, and throws an error named MissingMessageArgument for a variable "
        "without a value, never an empty text (decisions/viewer-slip.md, Filling a message). "
        "tests/slip/fill.mjs drives it."
    ),
)
def test_message_filled():
    got = fill([
        {"resources": RESOURCES, "lang": "en", "id": "rule.flagged", "args": FLAGGED},
        {"resources": RESOURCES, "lang": "nl", "id": "rule.flagged", "args": FLAGGED},
        {"resources": RESOURCES, "lang": "en", "id": "rule.group_size", "args": {"g": "group-a", "n": "2"}},
        {"resources": RESOURCES, "lang": "en", "id": "rule.group_size", "args": {"g": "group-a"}},
        {"resources": RESOURCES, "lang": "nl", "id": "rule.held", "args": {"i": "item-b"}},
        {"resources": RESOURCES, "lang": "en", "id": "rule.not_there", "args": {}},
    ])
    assert got == [
        {"text": "Item item-a is flagged with amount 12, and nothing holds it."},
        {"text": "Item item-a is gemarkeerd met bedrag 12, en niets blokkeert het."},
        {"text": "Group group-a has 2 items."},
        {"error": "MissingMessageArgument"},
        {"error": "MissingMessageArgument"},
        {"absent": True},
    ]
