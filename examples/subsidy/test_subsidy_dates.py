"""The subsidy example reads its dates, not copies of them as day numbers (decisions/standard-packs-everywhere.md,
section 1).

The dates that stay are the ones the credentials schema already records beside their numbers: the validity of
a trust entry, the day a credential or an identity statement was issued, and the day a status was looked up.
"""

from pathlib import Path

import pytest
import yaml

SUBSIDY = Path(__file__).resolve().parent
DATES = {
    "TrustEntry": ("valid_from", "valid_until"),
    "Credential": ("issued_on",),
    "IdentityStatement": ("issued_on",),
    "StatusLookup": ("looked_up_on",),
}
READ = {"trust_entry__valid_from", "trust_entry__valid_until", "credential__issued_on",
        "identity_statement__issued_on", "status_lookup__looked_up_on"}


def classes():
    found = {}
    for path in sorted((SUBSIDY / "schema").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, body in (doc.get("classes") or {}).items():
            found[name] = (path.name, (body or {}).get("attributes") or {})
    return found


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M3: decisions/standard-packs-everywhere.md, section 1.4, step 4, after "
    "compiler/tests/test_std_decision_dates.py::test_std_decision_rules_read_dates. Remove the *_day slots "
    "from examples/subsidy/schema/credentials.yaml and the numbers from its facts, make rules/credentials.dl "
    "read the dates through @days, and let views.yaml read the evaluation day's `date` with reading: days."))
def test_subsidy_schema_has_no_day_numbers():
    found = classes()
    numbers = sorted(f"{where}: {kind}.{slot}" for kind, (where, slots) in found.items()
                     for slot in slots if slot.endswith("_day"))
    assert not numbers, f"The subsidy schema still copies dates as day numbers: {numbers}"

    for kind, slots in DATES.items():
        assert kind in found, f"The subsidy schema lost the kind {kind}"
        attributes = found[kind][1]
        for slot in slots:
            assert (attributes.get(slot) or {}).get("range") == "date", f"{kind}.{slot} must stay a date slot"

    views = yaml.safe_load((SUBSIDY / "views.yaml").read_text(encoding="utf-8")) or {}
    readings = sorted(f"{view.get('theory')}: {mapped.get('of')}.{mapped.get('name')}"
                      for view in views.get("views") or ()
                      for mapped in view.get("attributes") or () if mapped.get("reading") == "yyyymmdd")
    assert not readings, f"A view still reads a whole number as a YYYYMMDD day: {readings}"

    from rezono_compiler import pack, rules

    used = set(rules.load(pack.read(SUBSIDY).rules).base_used())
    assert READ <= used, f"The subsidy rules must read the recorded dates, missing: {sorted(READ - used)}"
