import pytest

from case_support import engine, exact, reference


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Depends on the individual cluster relation tasks. Bind and reconcile the full cluster projection in examples/platform/rules/cluster_projection.dl. Read decisions/platform-derivation-acceptance.md.")
def test_complete_cluster_projection():
    expected = {k: rows for k, rows in reference().items() if k.startswith("cluster_")}
    actual = {k for k in engine()[1].derived if k.startswith("cluster_")}
    assert actual == expected.keys(), (sorted(expected.keys() - actual), sorted(actual - expected.keys()))
    for relation in sorted(expected):
        exact(relation, expected[relation])
