"""Alternative support (docs/semantics/witness-alternatives.md, S11, B20), on the hand-written cases of
docs/semantics/witness-alternatives-cases.yaml.

Two things are tested, both without the compiler or the publisher:
- a small least fixpoint of its own, written from the page, gives every expectation of the cases (height,
  chosen alternative, well-founded and cyclic alternatives, per role);
- today's checker accepts a proof through each well-founded alternative and refuses one through cyclic
  support (`cycle`). It refuses two alternatives of one row in one proof (`duplicate_witness`): the gap
  that the sketched `Proof.alternatives` closes.
"""

import hashlib
import itertools
import json
import re
from pathlib import Path

import pytest
import yaml

from rezono_checker.canon import encode_key
from rezono_checker.check import check
from rezono_checker.rules import load_rules

CASES = yaml.safe_load((Path(__file__).resolve().parents[2] / "docs/semantics/witness-alternatives-cases.yaml")
                       .read_text("utf-8"))["cases"]

# The program of the cases: (rule id, head, body); a term starting with ? is a variable.
PROGRAM = [
    ("reach_edge", ("reach", "?x", "?y"), [("edge", "?x", "?y")]),
    ("reach_step", ("reach", "?x", "?z"), [("reach", "?x", "?y"), ("edge", "?y", "?z")]),
    ("near_out", ("near", "?a", "?b"), [("edge", "?a", "?b")]),
    ("near_in", ("near", "?a", "?b"), [("edge", "?b", "?a")]),
    ("p_left", ("p", "?x"), [("left", "?x")]),
    ("p_q", ("p", "?x"), [("q", "?x")]),
    ("q_right", ("q", "?x"), [("right", "?x")]),
    ("q_p", ("q", "?x"), [("p", "?x")]),
]
BASE = {"edge": 2, "left": 1, "right": 1}
DERIVED = {"reach": 2, "near": 2, "p": 1, "q": 1}


def variables(rule):
    """The variables of a rule, in alphabetical order: the order of the binding values in a case's names."""
    _, head, body = rule
    return sorted({t for atom in (head, *body) for t in atom[1:] if t.startswith("?")})


def _columns(k):
    return [{"name": f"c{i}", "type": "string"} for i in range(k)]


IR = {"format": "rezono.rules/1", "pack": "alternatives",
      "relations": [{"name": n, "role": "base", "key": _columns(k)} for n, k in BASE.items()]
                   + [{"name": n, "role": "derived", "module": "m", "explain": "materialize", "key": _columns(k)}
                      for n, k in DERIVED.items()],
      "rules": [{"id": rid, "module": "m", "stratum": "1", "head": {"relation": head[0], "terms": list(head[1:])},
                 "body": [{"relation": a[0], "terms": list(a[1:]), "polarity": "positive",
                           "stratum": "1" if a[0] in DERIVED else "0"} for a in body],
                 "witness": {"relation": f"{rid}__witness", "variables": variables((rid, head, body))},
                 "origin": {"file": "cases.dl", "line": str(n + 1)}}
                for n, (rid, head, body) in enumerate(PROGRAM)]}
RULES = load_rules(IR)


def row(text):
    name, args = re.fullmatch(r"(\w+)\((.*)\)", text).groups()
    return (name, *args.split(","))


# --- The reference: grounding and least fixpoints, written from the page ------------------------------------

def instances(facts):
    """Every ground rule instance over the constants of the facts whose base premises are facts:
    (name, rule id, θ values, head, premises)."""
    constants = sorted({c for f in facts for c in f[1:]})
    out = []
    for rule in PROGRAM:
        rid, head, body = rule
        vs = variables(rule)
        for values in itertools.product(constants, repeat=len(vs)):
            theta = dict(zip(vs, values))
            premises = [(a[0], *(theta.get(t, t) for t in a[1:])) for a in body]
            if all(p in facts for p in premises if p[0] in BASE):
                out.append((f"{rid}({','.join(values)})", rid, values, (head[0], *(theta[t] for t in head[1:])),
                            premises))
    return out


def heights(alternatives):
    """Each supported derived row with its stage in the least fixpoint."""
    height, stage = {}, 0
    while True:
        stage += 1
        new = {head for _, _, _, head, premises in alternatives if head not in height
               and all(p in height for p in premises if p[0] in DERIVED)}
        if not new:
            return height
        height |= {r: stage for r in new}


def evaluate(case):
    """Per derived row the case names: height, chosen, founded and cyclic, as the page defines them."""
    facts = {row(f) for f in case["facts"]}
    model = heights(instances(facts))
    readable = facts if "reads" not in case else {row(f) for f in case["reads"]}
    # Usable: an alternative of the epoch (its premises hold) whose base premises the role reads.
    usable = [a for a in instances(facts) if all(p in model for p in a[4] if p[0] in DERIVED)
              and all(p in readable for p in a[4] if p[0] in BASE)]
    height = heights(usable)
    out = {}
    for text in case["rows"]:
        r = row(text)
        mine = [a for a in usable if a[3] == r]
        founded = [a for a in mine if r in heights([b for b in usable if b[3] != r] + [a])]
        out[text] = {"founded": sorted(a[0] for a in founded), "cyclic": sorted(a[0] for a in mine if a not in founded)}
        if r in height:
            ranked = sorted((1 + max([height[p] for p in a[4] if p[0] in DERIVED], default=0), a[1], a[2], a[0])
                            for a in mine if all(p in height for p in a[4] if p[0] in DERIVED))
            out[text] |= {"height": height[r], "chosen": ranked[0][3]}
    return out, usable


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_the_reference_gives_every_expectation_of_the_case(case):
    got, _ = evaluate(case)
    want = {text: {k: (sorted(v) if isinstance(v, list) else v) for k, v in expect.items()}
            for text, expect in case["rows"].items()}
    assert got == want


# --- Today's checker on the proofs of the cases ---------------------------------------------------------------

def witness(a):
    _, rid, values, head, premises = a
    rule = next(r for r in PROGRAM if r[0] == rid)
    return {"conclusion": {"relation": head[0], "key": encode_key(list(head[1:]))}, "rule_id": rid,
            "bindings": [{"variable": v, "value": x} for v, x in zip(variables(rule), values)],
            "premises": [{"row": {"relation": p[0], "key": encode_key(list(p[1:]))}, "polarity": "positive",
                          "stratum": 1 if p[0] in DERIVED else 0} for p in premises]}


def world(case):
    facts = {row(f) for f in case["facts"]}
    rows = {n: [] for n in [*BASE, *DERIVED]}
    for r in sorted(facts | set(heights(instances(facts)))):
        rows[r[0]].append(list(r[1:]))
    snaps = {n: json.dumps([{"key": k} for k in rs]).encode() for n, rs in rows.items()}
    manifest = {"id": "m-1", "snapshots": [{"relation": n, "role": "all", "complete": True, "uri": n, "format": "json",
                                            "sha256": hashlib.sha256(b).hexdigest()} for n, b in snaps.items()]}
    return manifest, snaps.__getitem__


def proof_through(first, usable):
    """The proof whose root row takes the alternative `first` and nothing else; every other derived row takes
    its least-height alternative among `usable`, or, without a height (circular support only), its first."""
    usable = [a for a in usable if a[3] != first[3]] + [first]
    height = heights(usable)

    def pick(r):
        alts = sorted((a for a in usable if a[3] == r),
                      key=lambda a: (max([height.get(p, 10**6) for p in a[4] if p[0] in DERIVED], default=0), a[1], a[2]))
        return alts[0] if alts else None

    chosen, todo = {first[3]: first}, [first]
    while todo:
        for p in todo.pop()[4]:
            if p[0] in DERIVED and p not in chosen and (b := pick(p)) is not None:
                chosen[p] = b
                todo.append(b)
    root = first[3]
    return {"root": {"relation": root[0], "key": encode_key(list(root[1:]))}, "manifest_id": "m-1",
            "witnesses": [witness(a) for _, a in sorted(chosen.items())]}


def errors(report):
    return sorted({f["reason"] for f in report["findings"] if f["severity"] == "error"})


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_the_checker_accepts_each_well_founded_alternative_and_refuses_cyclic_support(case):
    expected, usable = evaluate(case)
    manifest, read = world(case)
    named = {a[0]: a for a in usable}
    for text, e in expected.items():
        for name in e["founded"]:  # a well-founded alternative has a finite proof of its own
            report = check(proof_through(named[name], usable), manifest, RULES, read)
            assert report["valid"], (text, name, report["findings"])
        for name in e["cyclic"]:  # cyclic support has only a circular proof
            report = check(proof_through(named[name], usable), manifest, RULES, read)
            assert "cycle" in errors(report), (text, name, report["findings"])


def test_two_alternatives_of_one_row_cannot_share_a_proof_today():
    """The gap: a proof has one witness per conclusion, so a retained alternative needs a field of its own."""
    case = next(c for c in CASES if c["id"] == "and-or-two-rules")
    _, usable = evaluate(case)
    named = {a[0]: a for a in usable}
    p = proof_through(named["near_in(a,b)"], usable)
    p["witnesses"].append(witness(named["near_out(a,b)"]))
    manifest, read = world(case)
    assert errors(check(p, manifest, RULES, read)) == ["duplicate_witness"]
