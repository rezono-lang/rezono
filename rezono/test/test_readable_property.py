"""A rule with the shape of a property gives W107 with the property as its hint (decisions/language-readable-rules.md,
section 1). The sources and the expected spans are written from that decision."""

import json

import pytest
from reader_probe import at, read_modules

KINDS = ("rezono 0\npack sample\n\nkind Offer world closed\n  price: Int\n\nkind Product world closed\n"
         "  offers: Offer*\n\nkind Demand world closed\n  product: Product\n  budget: Int\n")
PROPERTY = KINDS + "\nextend Demand\n  derived offers: Offer* = product.offers\n"
SHAPED = KINDS + "\nrule offers(d: Demand, o: Offer) when o in d.product.offers\n"
# Counter-cases: a further condition, and a third column, keep a rule without a warning.
FILTERED = KINDS + "\nrule affordable(d: Demand, o: Offer) when o in d.product.offers and o.price <= d.budget\n"
THREE = KINDS + "\nrule priced(d: Demand, o: Offer, p: Int) when o in d.product.offers and p = o.price\n"


class MissingPropertyHint(AssertionError):
    """The reader did not warn at a rule with the shape of a property, or warned elsewhere."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingPropertyHint,
    reason="extra: decisions/language-readable-rules.md: In the module reader (rezono/src/module-native-rule.ts or "
           "a new rezono/src/module-readable.ts), give W107 at the name of a rule whose head has two typed columns, "
           "the first a kind, and whose body is exactly one `v in E` or `v = E` with E a path from the first "
           "column; keep the form unchanged. Add W107 to rezono/messages/en.json and nl.json with the hint "
           "`derived name: T* = E` under `extend K`. Read section 1, The old form.",
)
def test_readable_property():
    prop, shaped, filtered, three = read_modules(PROPERTY, SHAPED, FILTERED, THREE)
    # The property itself already reads, without a diagnostic; this does not change.
    assert prop["module"] is not None and not prop["diagnostics"], prop
    problems = []
    want = [{"code": "W107", "span": at(SHAPED, "offers", "rule ")}]
    if shaped["module"] is None or shaped["diagnostics"] != want:
        problems.append({"shaped": shaped["diagnostics"], "want": want})
    for name, read in (("filtered", filtered), ("three", three)):
        if read["module"] is None or read["diagnostics"]:
            problems.append({name: read["diagnostics"]})
    if problems:
        raise MissingPropertyHint(json.dumps(problems, indent=2))
