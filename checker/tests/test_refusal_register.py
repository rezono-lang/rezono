"""Every refusal of the checker is a registered code with named arguments and a sentence in English and Dutch
(decisions/checker-refusal-register.md)."""

import ast
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "checker" / "rezono_checker"
REGISTER = ROOT / "contracts" / "checker-refusal.yaml"
CATALOGUES = {language: PACKAGE / "messages" / f"{language}.json" for language in ("en", "nl")}
ALLOWED = {
    "relation", "rule", "kind", "role", "column", "variable", "field", "fields",  # names from the definition
    "witness", "premise", "position", "index", "count", "limit", "size", "level", "bound",  # numbers, positions
    "file", "path", "tree",  # files of the publication
    "key", "value", "bindings",  # content of the snapshots the check read
}
SCOPES = {"role", "epoch"}
CODE_FORMS = ("find", "Unverified", "Refused")  # the first argument is the code
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class MissingRegister(AssertionError):
    """contracts/checker-refusal.yaml or a catalogue of checker/rezono_checker/messages is not there."""


def _name(node) -> str | None:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def literal_codes(text: str) -> set[str]:
    """The codes a module writes literally: `"reason": code`, and the first argument of find, Unverified and
    Refused."""
    found = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Dict):
            found |= {v.value for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant)
                      and k.value == "reason" and isinstance(v, ast.Constant) and isinstance(v.value, str)}
        elif isinstance(node, ast.Call) and _name(node.func) in CODE_FORMS and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.add(first.value)
    return found


def sentences(text: str) -> list[int]:
    """The lines where a module refuses with a sentence: `problems.append(...)` of anything but a Refusal, and
    `ValueError(...)`."""
    lines = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        name = _name(node.func)
        if name == "ValueError":
            lines.append(node.lineno)
        elif (name == "append" and isinstance(node.func, ast.Attribute) and _name(node.func.value) == "problems"
              and not (node.args and isinstance(node.args[0], ast.Call) and _name(node.args[0].func) == "Refusal")):
            lines.append(node.lineno)
    return sorted(lines)


def refusals(text: str) -> list[tuple[int, object, set[str]]]:
    """Every Refusal(code, **arguments) a module makes: its line, its code (None if not a literal) and the names
    of its arguments."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and _name(node.func) == "Refusal":
            first = node.args[0] if node.args else None
            code = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None
            out.append((node.lineno, code, {k.arg for k in node.keywords}))
    return out


def register() -> dict[str, dict]:
    """{code: {"arguments": set, "scope": str}} from the contract, with both catalogues checked against it."""
    absent = [p.relative_to(ROOT).as_posix() for p in (REGISTER, *CATALOGUES.values()) if not p.exists()]
    if absent:
        raise MissingRegister(f"missing: {', '.join(absent)}")
    values = yaml.safe_load(REGISTER.read_text("utf-8"))["enums"]["RefusalCode"]["permissible_values"]
    out = {}
    for code, value in values.items():
        notes = (value or {}).get("annotations") or {}
        out[code] = {"arguments": set(str(notes.get("arguments") or "").split()), "scope": notes.get("scope")}
    return out


def holds(text: str, codes: dict) -> None:
    """A module refuses only with registered codes and their own arguments, never with a sentence."""
    assert sentences(text) == [], "refusals written as a sentence, at these lines"
    for line, code, names in refusals(text):
        assert code in codes, f"line {line}: {code!r} is not in {REGISTER.name}"
        assert names <= codes[code]["arguments"], f"line {line}: {code} has no argument {names - codes[code]['arguments']}"


def test_the_scan_finds_each_form():
    """The tests below can fail: each form of a code and of a sentence is found."""
    text = "\n".join([
        'findings.append({"reason": "a_code", "relation": r})', 'find("b_code", w)', 'raise Unverified("c_code")',
        'raise Refused("d_code", x)', 'findings.append({"reason": reason})',
        'problems.append(f"{path}: missing")', 'self.problems.append(Refusal("piece_missing", path=path))',
        'raise ValueError(f"unknown rule {r}")', 'raise RefusalError(Refusal("unknown_rule", rule=r))'])
    assert literal_codes(text) == {"a_code", "b_code", "c_code", "d_code"}
    assert sentences(text) == [6, 8]
    assert refusals(text) == [(7, "piece_missing", {"path"}), (9, "unknown_rule", {"rule"})]


@pytest.mark.xfail(
    strict=True,
    raises=(MissingRegister, AssertionError),
    reason=(
        "extra: decisions/checker-refusal-register.md: Write contracts/checker-refusal.yaml with the enum "
        "RefusalCode: every code checker/rezono_checker writes literally today (\"reason\": code, find, "
        "Unverified, Refused), each with a description and the annotations arguments and scope, as the decision "
        "gives; and checker/rezono_checker/messages/en.json and nl.json with one sentence per code, whose "
        "placeholders are its arguments. A new file in contracts/ follows the form of the others."
    ),
)
def test_every_code_is_registered_with_a_sentence_in_both_languages():
    codes = register()
    for code, entry in sorted(codes.items()):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), code
        assert entry["arguments"] <= ALLOWED, f"{code}: arguments outside the decision: {entry['arguments'] - ALLOWED}"
        assert entry["scope"] in SCOPES, f"{code}: scope {entry['scope']!r}"
    for language, path in CATALOGUES.items():
        catalogue = json.loads(path.read_text("utf-8"))
        assert sorted(catalogue) == sorted(codes), language
        for code, sentence in catalogue.items():
            assert sentence.strip(), (language, code)
            assert set(PLACEHOLDER.findall(sentence)) <= codes[code]["arguments"], (language, code)
    written = set().union(*(literal_codes(p.read_text("utf-8")) for p in sorted(PACKAGE.rglob("*.py"))))
    assert sorted(written - set(codes)) == []


@pytest.mark.xfail(
    strict=True,
    raises=(MissingRegister, AssertionError),
    reason=(
        "extra: decisions/checker-refusal-register.md: Waits for checker/tests/test_refusal_register.py--"
        "test_every_code_is_registered_with_a_sentence_in_both_languages. Then add rezono_checker.refusals with "
        "Refusal (a str whose text is the English sentence, with code and arguments) and RefusalError (a "
        "ValueError), and make every problem of checker/rezono_checker/proof.py a Refusal with a registered code: "
        "its English sentence is today's sentence, so the text a caller reads stays the same."
    ),
)
def test_proof_refuses_with_registered_codes():
    holds((PACKAGE / "proof.py").read_text("utf-8"), register())


@pytest.mark.xfail(
    strict=True,
    raises=(MissingRegister, AssertionError),
    reason=(
        "extra: decisions/checker-refusal-register.md: Waits for checker/tests/test_refusal_register.py--"
        "test_proof_refuses_with_registered_codes (rezono_checker.refusals). Then make every problem of "
        "checker/rezono_checker/views.py a Refusal with a registered code; its English sentence is today's "
        "sentence."
    ),
)
def test_views_refuses_with_registered_codes():
    holds((PACKAGE / "views.py").read_text("utf-8"), register())
