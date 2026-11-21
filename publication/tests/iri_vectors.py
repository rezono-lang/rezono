"""The IRI vectors both readers run: contracts/fixtures/iri/vectors.json, written from this side.

`rezono_publication.rdf` is the reference: every expectation below is what it gives, or that it refuses, and the
gate's `edge/gate/src/iri.ts` and `roleSchema` (edge/gate/test/iri-vectors.test.ts) must give the same. The
conclusion spaces come from a schema bundle and a role's snapshots, as each side builds the role's schema:
`publication.schema_document` here, `roleSchema` in the gate (decisions/publication-conclusion-addresses.md §1).
A case listed as refused that this side accepts stops the generator: no case is dropped quietly.

  python publication/tests/iri_vectors.py      writes the file again (test_iri_vectors.py holds it current)
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

from rezono_publication import publication, rdf

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(ROOT))
from publication.tests.subkind_fixture import BUNDLE  # noqa: E402

VECTORS = ROOT / "contracts" / "fixtures" / "iri" / "vectors.json"

D1 = "d-" + "0123456789abcdef" * 4
D2 = "d-" + "f" * 64
BASE = "https://example.org/tree/"
ITEM = "https://example.org/tree/Item/p1"

SPELL = ["abc", "A-Z_09.x", ".", "..", "...", "tilde~here", "~2E", '["run-1","a/b"]', "café € 12", "a b",
         "100%", "\U0001F600", "x?y#z@w", ""]
SPELL_REFUSED = ["\ud800", "a\udc00b"]
UNSPELL_REFUSED = ["~41", "~2e", "a b", "~", "~4", "%41", "~C3", "~C3~28", "~2E~2E~2E", ".", "..", "é", "a/b",
                   "~7E~", "~2F~", "~ED~A0~80"]
IRIS = [ITEM, "urn:x:y", "https://example.org/a/b~20c", "rezono:w/abc"]
PIN_REFUSED = [
    (ITEM, D1, "m-01"),
    (ITEM, D1, "m-"),
    (ITEM, D1, "m-1x"),
    (ITEM, "d-" + "A" * 64, None),
    (ITEM, "0" * 64, None),
    (ITEM + "?x", D1, None),
    (ITEM + "#f", D1, None),
    ("no-scheme/p1", D1, None),
    ("https://example.org/a b", D1, None),
]
PARSE_ACCEPTED = [
    ITEM,
    f"{ITEM}?pin={D1}",
    f"{ITEM}?pin=m-0@{D1}",
    f"{ITEM}?pin=m-12@{D2}",
    f"urn:x:y?pin={D2}",
    "https://example.org/a﻿b",
]
PARSE_REFUSED = [
    f"{ITEM}?pin=m-1",
    f"{ITEM}?pin=m-01",
    f"{ITEM}?pin=m-01@{D1}",
    f"{ITEM}?pin=m-1@d-" + "0" * 63,
    f"{ITEM}?pin={D1.upper()}",
    f"{ITEM}?pin={D1[2:]}",
    f"{ITEM}?pin={D1}&x=1",
    f"{ITEM}?other=1",
    f"{ITEM}?pin={D1}?",
    f"{ITEM}#frag",
    f"{ITEM}?pin={D1}#frag",
    f"?pin={D1}",
    "not an iri",
    "https://example.org/a\u001fb",
    "",
]
WITNESSES = [
    {"conclusion": {"relation": "eligible", "key": '["p-1"]'}, "rule_id": "r_income",
     "bindings": [{"variable": "?p", "value": "p-1"}],
     "premises": [{"row": {"relation": "member", "key": '["p-1"]'}, "polarity": "positive", "stratum": 0},
                  {"row": {"relation": "income_ok", "key": '["p-1"]'}, "polarity": "positive", "stratum": 0}],
     "aggregates": []},
    {"conclusion": {"relation": "group_size", "key": '["group-a","2"]'}, "rule_id": "group_size",
     "bindings": [{"variable": "?g", "value": "group-a"}, {"variable": "?n", "value": "2"}],
     "premises": [{"row": {"relation": "group", "key": '["group-a"]'}, "polarity": "positive", "stratum": 0}],
     "aggregates": [{"relation": "item__group", "position": 0, "group_key": '["group-a"]', "count": 2,
                     "contributors_sha256": "0" * 64, "result": "known:2"}]},
    {"conclusion": {"relation": "café", "key": '["é"]'}, "rule_id": "ré", "bindings": [],
     "premises": [], "aggregates": []},
]
BASES = [BASE, "https://rezono.example/slip/", "urn://x/"]
BASES_REFUSED = ["https://example.org/tree", "HTTPS://example.org/tree/", "urn:x/", "https://example.org/a b/",
                 "https://example.org/a b/", "https://example.org/a\u001fb/", "https:///", "",
                 "1http://example.org/"]

# A role's snapshots: the relations it reads, each with whether it reads it in full.
ROLES = {
    "every relation": {t: True for t in ("item", "part", "spare", "tool", "holder", "item__label", "part__size",
                                         "item__inside", "holder__keeps", "kept_part")},
    "a subkind without its root": {"part": True, "spare": True, "part__size": True},
    "a part of the tree, in part": {"spare": False, "tool": False, "kept_part": False},
}
# One id per kind, spelled with what §3.4 escapes.
IDS = {"Item": "i1", "Part": "p 1", "Spare": "s.1", "Tool": "..", "Holder": "h~1", "KeptPart": '["h1","p1"]'}


def _schema(base: str) -> dict:
    return {"rezono": "1.0", "pack": "tree-fixture", "base": base, "kinds": {}}


def _refused(cases: list, call) -> list:
    """`cases`, each of which `call` refuses: a case this side accepts is an error here, never left out."""
    for case in cases:
        try:
            call(*case) if isinstance(case, tuple) else call(case)
        except Exception:  # an L0Error, or Python refusing a lone surrogate on the way to UTF-8
            continue
        raise AssertionError(f"rezono_publication.rdf accepts {case!r}, listed as refused")
    return cases


def _bundles() -> list[tuple[str, dict]]:
    named = copy.deepcopy(BUNDLE)
    named["pack"]["base"] = BASE
    by_id = {k["id"]: k for k in named["kinds"]}
    by_id["item"]["iri"] = "https://example.org/things/Item"  # the root's own space: every kind of its tree uses it
    by_id["part"]["iri"] = "https://example.org/things/Part"  # a subkind's own iri names its class, not its space
    by_id["holder"]["iri"] = f"{BASE}Holder"  # the default, written out
    return [("default base, no kind iri", BUNDLE), ("base and kind iris", named)]


def _spaces() -> list[dict]:
    out = []
    for about, bundle in _bundles():
        cls = {k["id"]: k["class"] for k in bundle["kinds"]}
        cls |= {r["id"]: publication.pascal(r["id"]) for r in bundle.get("relations", [])}
        for role, reads in ROLES.items():
            doc, _ = publication.schema_document(bundle, {t for t, full in reads.items() if full})
            out.append({
                "about": f"{about}; {role}",
                "bundle": bundle,
                "snapshots": [{"relation": t, "complete": False, "full": full} for t, full in sorted(reads.items())],
                "conclusions": [{"kind": k, "id": IDS[k], "iri": rdf.conclusion_iri(doc, k, IDS[k]),
                                 "pinned": rdf.conclusion_iri(doc, k, IDS[k], manifest="m-3", dataset=D2)}
                                for k in sorted(cls[t] for t in reads if t in cls)],
            })
    return out


def generate() -> dict:
    return {
        "description": (
            "Canonical IRI vectors (docs/publication/l0.md 3.4 and 6.4; decisions/publication-conclusion-addresses.md"
            " 1-3). Written by publication/tests/iri_vectors.py from rezono_publication.rdf, never by hand; the gate"
            " (edge/gate/src/iri.ts and roleSchema) must give the same. `spaces` gives, per schema bundle and role,"
            " the conclusion IRI of one id of each kind the role reads."
        ),
        "spell": [{"id": i, "segment": rdf.spell(i)} for i in SPELL],
        "spell_refused": _refused(SPELL_REFUSED, rdf.spell),
        "unspell_refused": _refused(UNSPELL_REFUSED, rdf.unspell),
        "pin": [{"iri": i, "dataset": d, **({"manifest": m} if m else {}),
                 "pinned": rdf.pin_iri(i, dataset=d, manifest=m)}
                for i in IRIS for d, m in ((D1, None), (D2, "m-0"), (D1, "m-42"))],
        "pin_refused": [{"iri": i, "dataset": d, **({"manifest": m} if m else {})}
                        for i, d, m in _refused(PIN_REFUSED, lambda i, d, m: rdf.pin_iri(i, dataset=d, manifest=m))],
        "parse": [{"iri": i, "unpinned": u, **({"pin": p} if p else {})}
                  for i in PARSE_ACCEPTED for u, p in [rdf.parse_pin(i)]],
        "parse_refused": _refused(PARSE_REFUSED, rdf.parse_pin),
        "witness": [{"base": b, "witness": w, "iri": rdf.canonical_witness_iri(_schema(b), w),
                     "pinned": rdf.canonical_witness_iri(_schema(b), w, manifest="m-1", dataset=D1)}
                    for b in BASES for w in WITNESSES],
        "base_refused": _refused(BASES_REFUSED, lambda b: rdf.canonical_witness_iri(_schema(b), {})),
        "spaces": _spaces(),
    }


def text() -> str:
    # ASCII with escapes: a lone surrogate (spell_refused) has no UTF-8 form, and JSON keeps it as an escape.
    return json.dumps(generate(), indent=1, ensure_ascii=True, sort_keys=True) + "\n"


if __name__ == "__main__":
    VECTORS.parent.mkdir(parents=True, exist_ok=True)
    VECTORS.write_text(text(), encoding="utf-8", newline="\n")
