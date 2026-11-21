from query_fixture import check_relation, evidence


def test_support_unknown():
    rows, _ = evidence()
    # The scenario selects these releases. None has a vendor support statement.
    releases = {
        ("cp", "kube-control-1.32.13"),
        ("db-git", "postgresql-16"),
        ("db-idp", "postgresql-17"),
        ("idp", "keycloak-26"),
        ("reg", "distribution-3.0.0"),
    }
    assert set(map(tuple, rows["runs"])) == releases
    check_relation("support_unknown", {(service, release, "unknown") for service, release in releases})
