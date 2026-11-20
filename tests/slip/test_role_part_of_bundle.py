"""The role's part of the bundle in the local reader (decisions/viewer-slip.md, "The role's part of the bundle").

`tests/fixtures/slip` has two roles: `reader` reads everything, `summary` reads no link. Every id below is named
by hand from the fixture's own sources (rules/*.dl, labels/*.yaml, messages/*.mf2, channels.yaml).
"""

import re

import pytest
from slip_support import PACK, ask, publish_main


class MissingRolePartOfBundle(AssertionError):
    """GET /<pack>/bundle gives the role's catalogue only, not its part of the rest of the bundle."""


PARTS = ("rules", "labels", "messages", "home", "questions")
# What every role reads: items, groups, holds and what follows from them alone.
SHARED_RULES = {"held", "flagged", "recorded_amount", "group_size", "busy", "too_large"}
SHARED_LABELS = {"item", "item.group", "item.amount", "group", "hold", "hold.item", "held", "flagged", "group_size",
                 "busy", "recorded_amount", "too_large"}
SHARED_MESSAGES = {"rule.held", "rule.flagged", "rule.recorded_amount", "rule.group_size", "rule.busy"}
# What only `reader` reads: links, the rule over them, and the fourth read rule, whose body names `link`.
LINK_RULES = {"linked", "may_read_4"}
LINK_LABELS = {"link", "link.tail", "link.head", "linked"}
LINK_MESSAGES = {"rule.linked"}
QUESTIONS = {"grounds", "reach", "sweep", "scenario"}


def message_ids(resource: str) -> set[str]:
    body = resource.split("\n---\n", 1)[1] if "\n---\n" in resource else resource
    return {m.group(1) for m in re.finditer(r"^([A-Za-z0-9_.-]+)\s*=", body, re.MULTILINE)}


def part(store, role, manifest_id) -> dict:
    [answer] = ask(store, role, f"/{PACK}/bundle?m={manifest_id}")
    assert answer["status"] == 200, answer
    body = answer["body"]
    missing = [name for name in PARTS if name not in body]
    if missing:
        raise MissingRolePartOfBundle(f"{role}: GET /{PACK}/bundle has no {', '.join(missing)}")
    return body


@pytest.mark.xfail(
    strict=True,
    raises=(MissingRolePartOfBundle, AssertionError),
    reason=(
        "M3: decisions/viewer-slip.md: Give the role's part of the bundle at GET /<pack>/bundle?m= in edge/gate/src/catalogue.ts and "
        "edge/gate/src/local.ts: the rules, labels, messages, home claim and questions of what the role reads, "
        "as decisions/viewer-slip.md, section The role's part of the bundle, says. A role reads a relation when "
        "its snapshot is full or holds a row, and the catalogue follows the same rule, so a kind the role does "
        "not read is absent as if it did not exist. Expectation: tests/fixtures/slip, ids named by hand."
    ),
)
def test_role_part_of_bundle(tmp_path):
    store, manifest = publish_main(tmp_path)
    reader, summary = (part(store, role, manifest["id"]) for role in ("reader", "summary"))

    def rules(p):
        return {rule["id"] for rule in p["rules"]}

    def labels(p, lang):
        return {label["element"] for label in p["labels"] if label["lang"] == lang}

    def messages(p, lang):
        return {i for resource in p["messages"] if resource["lang"] == lang for i in message_ids(resource["resource"])}

    assert SHARED_RULES | LINK_RULES <= rules(reader)
    assert SHARED_RULES <= rules(summary) and not LINK_RULES & rules(summary)
    for lang in ("en", "nl"):
        assert SHARED_LABELS | LINK_LABELS <= labels(reader, lang)
        assert SHARED_LABELS <= labels(summary, lang) and not LINK_LABELS & labels(summary, lang)
        assert SHARED_MESSAGES | LINK_MESSAGES <= messages(reader, lang)
        assert SHARED_MESSAGES <= messages(summary, lang) and not LINK_MESSAGES & messages(summary, lang)
    for p in (reader, summary):
        assert p["home"] == {"claim": ["flagged"]}
        assert QUESTIONS <= {q["term"] for q in p["questions"]}
    # A rule comes with its body, as the bundle has it.
    flagged = next(rule for rule in summary["rules"] if rule["id"] == "flagged")
    assert [literal["kind"] for literal in flagged["body"]] == ["atom", "comparison", "atom"]
    # Absent looks the same as not there: no kind, slot or relation of a link in summary's catalogue.
    assert "link" not in {kind["id"] for kind in summary["kinds"]}
    assert "linked" not in {relation["id"] for relation in summary["relations"]}
    assert not {arrow["id"] for arrow in summary["arrows"]} & {"link.tail", "link.head"}
    assert "link" in {kind["id"] for kind in reader["kinds"]}
