"""Independent checker verification of sweep variant status_readers (decisions/central-read-access.md, section 2)."""

from __future__ import annotations

import pytest

from rezono_checker import access


class MissingStatusReaderCheck(AssertionError):
    """The checker does not yet expose or enforce check_variant_status_readers."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingStatusReaderCheck,
    reason=(
        "extra: decisions/central-read-access.md: Add check_variant_status_readers(variant, role_full, "
        "all_relations, complete_roles=frozenset()) to checker/rezono_checker/access.py and call it from "
        "edge/publisher/rezono_publisher/sweep.py with checker-derived full sets before writing a variant "
        "manifest or diagnosis. Refuse any status_reader not in readers or missing any relation of all_relations."
    ),
)
def test_checker_refuses_incomplete_variant_status_reader():
    check = getattr(access, "check_variant_status_readers", None)
    if check is None:
        raise MissingStatusReaderCheck("rezono_checker.access.check_variant_status_readers is missing")

    all_relations = frozenset({"item", "item__label", "secret"})
    role_full = {
        "whole": frozenset({"item", "item__label", "secret"}),
        "partial": frozenset({"item", "item__label"}),
    }

    # Counter-case: a complete role and a filtered role covering every relation are both accepted.
    valid = {
        "sweep": "rate",
        "index": 1,
        "value": "10",
        "readers": ["checker", "whole", "partial"],
        "status_readers": ["checker", "whole"],
    }
    assert check(valid, role_full, all_relations, complete_roles=frozenset({"checker"})) == []

    # A filtered role missing even one relation from all_relations must be refused.
    incomplete = dict(valid, status_readers=["checker", "partial"])
    findings = check(incomplete, role_full, all_relations, complete_roles=frozenset({"checker"}))
    assert findings and all(f.get("severity") == "error" for f in findings), findings
    assert any(f.get("reason") == "status_reader_incomplete" for f in findings), findings

    # An unknown filtered role (no checker-derived full set) must also be refused.
    unknown = dict(valid, readers=["checker", "ghost"], status_readers=["checker", "ghost"])
    unknown_findings = check(unknown, role_full, all_relations, complete_roles=frozenset({"checker"}))
    assert any(f.get("reason") == "status_reader_incomplete" for f in unknown_findings), unknown_findings

    # A role listed in status_readers but omitted from readers must be refused.
    not_reader = dict(valid, readers=["checker"], status_readers=["checker", "whole"])
    not_reader_findings = check(not_reader, role_full, all_relations, complete_roles=frozenset({"checker"}))
    assert any(f.get("reason") == "status_reader_not_reader" for f in not_reader_findings), not_reader_findings
