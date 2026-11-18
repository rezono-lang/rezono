"""Verify the public edge profile against every role relation the publisher emits."""
import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

from rezono_publisher import publish

from subsidy_publication_support import HERE, PACK, PROFILE, published, rows


def test_the_profile_that_publishes_the_pack_names_no_role_the_pack_does_not(tmp_path):
    """Profile `edge` publishes this pack (publish.packs). A role of the profile that the pack's facts do
    not name would read nothing; so each is named, and reads exactly what one of the pack's own roles reads:
    `viewer` as the policy adviser, `propose` as the case officer, the sealed ledger included."""
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    assert "examples/subsidy" in profile["publish"]["packs"]
    filtered = sorted(r for r, mode in profile["access"]["roles"].items() if mode == "may_read")
    assert filtered == ["propose", "viewer"]
    s, m = published(HERE, tmp_path)
    assert set(filtered) <= {r[0] for r in rows(s, "checker", "role")}
    as_role = {"propose": "case_officer", "viewer": "policy_adviser"}
    relations = sorted({name.rsplit("/", 1)[1][:-len(".json")] for name in publish.role_objects(s, PACK, "m-1", "checker")
                        if name.startswith("relations/")}
                       - {"may_read"})
    assert "calc__payment_difference" in relations and "ledger_payment__refused" in relations
    for role in filtered:
        for rel in relations:
            assert rows(s, role, rel) == rows(s, as_role[role], rel), (role, rel)
        # What a role may read is said per role: the same elements, under its own name.
        assert ({r[1:] for r in rows(s, role, "may_read")}
                == {r[1:] for r in rows(s, as_role[role], "may_read")} != set())
    assert rows(s, "viewer", "ledger_payment") == [] != rows(s, "propose", "ledger_payment")
