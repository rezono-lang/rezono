"""The local reader serves the difference of a variant of a sweep through `scenario`, for a filtered role that
reads every relation in full (decisions/viewer-slip.md, "What if, on the line").

tests/fixtures/slip, the stop at 20 (index 4) against main, where item-a has amount 12. Written here by hand:
the amount, the recorded amount and the flag change in place; the calculated row is keyed by its value, so it is
removed and added, as `DifferenceChange` says. `summary` does not read every relation in full and gets none.
"""

import json

import pytest
from slip_support import PACK, ask, publish_sweeps


class MissingVariantDifference(AssertionError):
    """The local reader does not answer scenario for a variant of a sweep."""


EXPECTED = [
    {"relation": "calc__capped_amount", "key": ["item-a", "12", "known", ""], "change": "removed"},
    {"relation": "calc__capped_amount", "key": ["item-a", "20", "known", ""], "change": "added"},
    {"relation": "flagged", "key": ["item-a", "20"], "change": "changed", "was": ["item-a", "12"]},
    {"relation": "item__amount", "key": ["item-a", "20"], "change": "changed", "was": ["item-a", "12"]},
    {"relation": "recorded_amount", "key": ["item-a", "20"], "change": "changed", "was": ["item-a", "12"]},
]


def key(value):
    return json.loads(value) if isinstance(value, str) else value


def entries(body: dict) -> list[dict]:
    out = []
    for entry in body["difference"].get("entries", []):
        row = {"relation": entry["relation"], "key": key(entry["key"]), "change": entry["change"]}
        if "was" in entry:
            row["was"] = key(entry["was"])
        out.append(row)
    return sorted(out, key=lambda e: (e["relation"], e["key"]))


@pytest.mark.xfail(
    strict=True,
    raises=(MissingVariantDifference, AssertionError),
    reason=(
        "extra: decisions/viewer-slip.md: Serve scenario for a variant of a sweep in the local reader (edge/gate/src/local.ts) from the difference "
        "the publisher writes per filtered role, for a role that reads every relation in full, and shorten "
        "blocked/edge-gate-variant-queries.txt by what then works (decisions/viewer-slip.md, What if, on the "
        "line). Expectation: tests/fixtures/slip at amount 20, rows by hand."
    ),
)
def test_variant_difference_local(tmp_path):
    store, manifest, done = publish_sweeps(tmp_path)
    variant = next(vid for vid, what in done if vid.startswith("v-item_amount-04-") and what == "manifest")
    query = f"/{PACK}/{manifest['id']}/ask/scenario?variant={variant}"
    [answer] = ask(store, "reader", query)
    if answer["status"] != 200:
        raise MissingVariantDifference(f"{query}: {answer}"[:400])
    body = answer["body"]
    assert body["delta"]["kind"] == "variant" and body["delta"]["id"] == variant
    assert entries(body) == EXPECTED
    counts = {c["relation"]: (c["added"], c["removed"], c["changed"]) for c in body["difference"]["counts"]}
    assert counts == {"calc__capped_amount": (1, 1, 0), "flagged": (0, 0, 1), "item__amount": (0, 0, 1),
                      "recorded_amount": (0, 0, 1)}
    [other] = ask(store, "summary", query)
    assert other["status"] != 200 or not other["body"].get("difference", {}).get("entries")
