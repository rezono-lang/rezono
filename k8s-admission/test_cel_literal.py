"""A rule constant becomes an exact CEL literal: decisions/k8s-admission-translator.md, "Literal"."""

import pytest
from translator_support import run_cel

EXACT = [
    ("web", "string", '"web"'),
    ("", "string", '""'),
    ('a"b\\c', "string", '"a\\"b\\\\c"'),
    ("it's ${x} in", "string", '"it\'s ${x} in"'),
    ("caf\u00e9\n", "string", '"caf\\u00e9\\u000a"'),
    ("\t\u007f", "string", '"\\u0009\\u007f"'),
    ("\U0001f600", "string", '"\\U0001f600"'),
    ("443", "integer", "443"),
    ("0", "integer", "0"),
    ("-42", "integer", "-42"),
    ("9223372036854775807", "integer", "9223372036854775807"),
    ("-9223372036854775808", "integer", "-9223372036854775808"),
]


@pytest.mark.xfail(
    strict=True,
    reason="Write cel_literal.literal as decisions/k8s-admission-translator.md specifies under Literal. "
           "Write in k8s-admission/cel_literal.py. Without Go the test checks the exact text; the CI also runs cel-go.",
)
def test_cel_literal():
    from cel_literal import literal

    for value, kind, text in EXACT:
        assert literal(value, kind) == text, (value, kind)
    for value, kind in [("007", "integer"), ("-0", "integer"), ("9223372036854775808", "integer"),
                        ("-9223372036854775809", "integer"), ("4.5", "integer"), ("web", "integer"),
                        ("\ud800", "string"), ("web", "boolean")]:
        with pytest.raises(ValueError):
            literal(value, kind)

    samples = []
    for value, kind, _ in EXACT:
        wire = int(value) if kind == "integer" else value
        samples.append(({"v": wire}, {}, f"object.v == {literal(value, kind)}"))
        other = str(int(value) - 1) if kind == "integer" and value.startswith("9") else (
            str(int(value) + 1) if kind == "integer" else value + "x")
        samples.append(({"v": wire}, {}, f"object.v != {literal(other, kind)}"))
    results = run_cel(samples)
    if results is not None:
        assert results == [True] * len(samples)
