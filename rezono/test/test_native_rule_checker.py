"""Check hand-authored native clauses independently of the source reader."""

import json
from pathlib import Path
import subprocess

import pytest


SCHEMA = {
    "rezono": "1.0", "pack": "sample", "base": "https://example.org/sample/",
    "kinds": {"Item": {
        "id": {"type": "Text"}, "world": "closed",
        "slots": {
            "weight": {"type": "Integer", "card": "1", "states": ["known"]},
            "status": {"type": "Text", "card": "?", "states": ["known", "unknown"], "world": "open"},
        },
    }},
}
CLAUSE = "/decls/0/clauses/"


def variable(name):
    return {"var": name}


def atom(relation, *terms, field=None):
    return {"relation": relation, "arguments": [
        {"value": term, **({"field": field} if field is not None else {})} for term in terms
    ]}


ITEM = variable("item")
WEIGHT = variable("weight")
ITEM_BODY = {"atom": atom("Item", ITEM)}
WEIGHT_BODY = {"atom": atom("Item.weight", ITEM, WEIGHT)}


def head(relation, term=ITEM):
    return atom(relation, term, field="item")


def clause(relation, *body, term=ITEM):
    return {"head": head(relation, term), "body": list(body)}


def comparison(literal_type, value):
    return {"compare": {"left": WEIGHT, "op": ">",
                        "right": {"lit": {"type": literal_type, "value": value}}}}


def authored_span(source, token, last=False):
    start = (source.rindex if last else source.index)(token)
    return {"text": token, "start": start, "end": start + len(token)}


def clause_spans(lines, clauses, offset):
    """Locate the already written form's tokens without asking the parser to fill any field."""
    spans = []
    for index, (line, authored) in enumerate(zip(lines, clauses, strict=True)):
        prefix = CLAUSE + str(index)
        cursor = 0

        def mark(path, text):
            nonlocal cursor
            start = line.index(text, cursor)
            end = start + len(text)
            cursor = end
            return record(path, start, end)

        def record(path, start, end):
            spans.append({"at": prefix + path, "line": str(index + 4),
                          "start": str(offset + start), "end": str(offset + end)})
            return start, end

        def term(path, value):
            if "var" in value:
                return mark(path, "?" + value["var"])
            if "wild" in value:
                return mark(path, "_")
            literal = value["lit"]
            text = json.dumps(literal["value"]) if literal["type"] == "text" else literal["value"]
            start, end = mark(path, text)
            record(path + "/lit", start, end)
            return start, end

        def atom_marks(path, value, place_atom=True):
            start, end = mark(path + "/relation", value["relation"])
            if place_atom:
                record(path, start, end)
            for n, argument in enumerate(value["arguments"]):
                arg = path + f"/arguments/{n}"
                field = mark(arg + "/field", argument["field"]) if "field" in argument else None
                location = term(arg + "/value", argument["value"])
                record(arg, *(field or location))
            return start, end

        record("", *atom_marks("/head", authored["head"]))
        for n, part in enumerate(authored["body"]):
            body = f"/body/{n}"
            if "atom" in part:
                record(body, *atom_marks(body + "/atom", part["atom"]))
            elif "not" in part:
                record(body, *mark(body + "/not", "not"))
                atom_marks(body + "/not", part["not"], place_atom=False)
            else:
                value = part["compare"]
                term(body + "/compare/left", value["left"])
                location = mark(body + "/compare/op", value["op"])
                record(body, *location)
                record(body + "/compare", *location)
                term(body + "/compare/right", value["right"])
        offset += len(line) + 3  # two spaces of indent and the line ending
    return spans


def checker_case(lines, clauses, diagnostic=None):
    header = "rezono 0\npack sample\nrules evidence\n"
    source = header + "".join(f"  {line}\n" for line in lines)
    start = header.index("evidence")
    spans = [{"at": "/decls/0", "line": "3", "start": str(start), "end": str(start + len("evidence"))}]
    spans += clause_spans(lines, clauses, len(header) + 2)
    if diagnostic is None:
        expected = None
    else:
        code, pointer, token, from_end, args = diagnostic
        expected_span = authored_span(source, token, from_end)
        marked, = [span for span in spans if span["at"] == CLAUSE + pointer]
        assert (int(marked["start"]), int(marked["end"])) == (expected_span["start"], expected_span["end"])
        expected = (code, expected_span, args)
    form = {"format": "rezono.module/2",
            "module": {"rezono": "0", "pack": "sample", "use": [],
                       "decls": [{"rules": "evidence", "clauses": clauses}]},
            "spans": sorted(spans, key=lambda span: span["at"])}
    return {"source": source, "form": form, "schema": SCHEMA}, expected


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Check hand-authored module/2 native clauses without reparsing. Read decisions/language-native-rules.md. "
    "Expose checkModuleRules(form, schema, source) from rezono/src, returning diagnostics, "
    "and supply the new catalog entries in rezono/messages."
))
def test_native_rule_names_types_and_dependencies():
    listed = "listed(item: ?item) if Item(?item)"
    cases = [
        checker_case(["heavy(item: ?item) if Item.weight(?item, ?weight) and ?weight > 2"],
                     [clause("heavy", WEIGHT_BODY, comparison("integer", "2"))]),
        checker_case(
            [listed, "eligible(item: ?item) if Item(?item) and not listed(item: ?item)"],
            [clause("listed", ITEM_BODY), clause("eligible", ITEM_BODY, {"not": head("listed")})],
        ),
        checker_case(
            ["heavy(item: ?item) if Item(?item) and Item.missing(?item, _)"],
            [clause("heavy", ITEM_BODY, {"atom": atom("Item.missing", ITEM, {"wild": True})})],
            ("R001", "0/body/1/atom/relation", "Item.missing", False, ("Item.missing", "missing")),
        ),
        checker_case(
            ['heavy(item: ?item) if Item.weight(?item, ?weight) and ?weight > "two"'],
            [clause("heavy", WEIGHT_BODY, comparison("text", "two"))],
            ("R003", "0/body/1/compare/right", '"two"', False, None),
        ),
        checker_case(
            ["eligible(item: ?item) if Item(?item) and not Item.status(?item, _)"],
            [clause("eligible", ITEM_BODY, {"not": atom("Item.status", ITEM, {"wild": True})})],
            ("R004", "0/body/1/not/relation", "Item.status", False, ("Item.status",)),
        ),
        checker_case(
            ["unresolved(item: ?item) if unresolved(item: ?item)"],
            [clause("unresolved", {"atom": head("unresolved")})],
            ("R013", "0/head/arguments/0/value", "?item", False, ("item", "?item")),
        ),
        checker_case(
            ["heavy(item: ?unbound) if Item.weight(?item, ?weight)"],
            [clause("heavy", WEIGHT_BODY, term=variable("unbound"))],
            ("R032", "0/head/arguments/0/value", "?unbound", False, ("unbound", "?unbound")),
        ),
        checker_case(
            ["looped(item: ?item) if Item(?item) and not looped(item: ?item)"],
            [clause("looped", ITEM_BODY, {"not": head("looped")})],
            ("R033", "0/body/1/not/relation", "looped", True, ("looped",)),
        ),
        checker_case(
            ["copied(item: ?item) if listed(wrong: ?item)", listed],
            [clause("copied", {"atom": atom("listed", ITEM, field="wrong")}), clause("listed", ITEM_BODY)],
            ("R034", "0/body/0/atom/arguments/0/field", "wrong", False, ("listed",)),
        ),
    ]
    probe = Path(__file__).with_name("native_rule_checker.mjs")
    result = subprocess.run(["node", str(probe)], check=True, capture_output=True, text=True, encoding="utf-8",
                            input=json.dumps([case for case, _ in cases]))
    actual = json.loads(result.stdout)
    assert actual is not None, "the language exports no checker for hand-authored native rule forms"
    messages = Path(__file__).resolve().parents[1] / "messages"
    for language in ("en", "nl"):
        catalog = json.loads((messages / f"{language}.json").read_text(encoding="utf-8"))
        for code, arity in (("R032", 1), ("R033", 2), ("R034", 1)):
            assert code in catalog and all("{" + str(n) + "}" in catalog[code] for n in range(arity))
    assert len(actual) == len(cases)
    for (case, expected), diagnostics in zip(cases, actual, strict=True):
        if expected is None:
            assert diagnostics == [], case["source"]
            continue
        code, span, args = expected
        matches = [d for d in diagnostics if d["code"] == code and d["span"] == span]
        assert matches, (case["source"], expected, diagnostics)
        if code == "R003":
            assert any(len(d["args"]) == 2 and d["args"][0] != d["args"][1] for d in matches)
        elif code == "R033":
            assert any(d["args"] == ["looped", "looped"] for d in matches)
        else:
            assert any(len(d["args"]) == 1 and d["args"][0] in args for d in matches), matches
