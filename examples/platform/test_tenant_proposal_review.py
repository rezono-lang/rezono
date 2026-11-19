import subprocess
import sys
from pathlib import Path

import pytest
from tenant_proposal_case import load, proposal, query, write


def test_real_proposal_requires_both_teams_and_authorized_decision(tmp_path):
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    target = "elm-1/managed-database"
    def decision():
        return query(teams, catalog, "relation", "tenant_connection_review")
    def reed(rows):
        return [row[4:] for row in rows if row[:4] == ["reed", "reed-1", target, 5432]]
    rows = decision()
    assert ["elm", "elm-1", "partner", 443, "review", "profile"] in rows
    assert reed(rows) == [["denied", "isolation"]]
    model["zoneMatrix"].append(["sandbox", "stable", 5432])
    approval = {"reviewer": "operator", "sourceDelivery": "reed-1", "target": target, "port": 5432}
    model["decisionsByReviewer"] = [approval]
    model["reviewGrants"] = [["operator", "approve-connection"]]
    write(catalog, model)
    assert reed(decision()) == [["denied", "isolation"]]
    elm = teams / "elm/ledger/request.json"
    request = load(elm)
    request["connections"].append({"peer": "reed", "targetZone": "sandbox",
                                   "target": "reed-1/guest-cluster", "port": 5432})
    write(elm, request)
    assert reed(decision()) == [["standard", "matrix"]]
    approval["port"] = 5433
    write(catalog, model)
    assert reed(decision()) == [["denied", "isolation"]]
    approval["port"] = 5432
    model["reviewGrants"] = [["someone-else", "approve-connection"]]
    write(catalog, model)
    assert reed(decision()) == [["denied", "isolation"]]


@pytest.mark.parametrize("target, zone", [
    ("elm-1", "stable"),
    ("elm-1/no-such-component", "stable"),
    ("elm-9/managed-database", "stable"),
    ("elm/managed-database", "stable"),
    ("elm-1/no-such-component", "shared"),
    ("unlisted-database", "stable"),
])
def test_target_without_established_owner_is_never_within_one_tenant(tmp_path, target, zone):
    # Reed's development delivery may reach the stable zone on 5432 by matrix, and even holds an
    # authorized approval for this target; only an owner resolved from a delivered component could
    # make the connection tenant-internal, so none of these targets may pass as a standard connection.
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    model["zoneMatrix"] += [["sandbox", "stable", 5432], ["sandbox", "shared", 5432]]
    model["decisionsByReviewer"] = [{"reviewer": "operator", "sourceDelivery": "reed-1",
                                     "target": target, "port": 5432}]
    model["reviewGrants"] = [["operator", "approve-connection"]]
    write(catalog, model)
    path = next(teams.glob("reed/*/request.json"))
    request = load(path)
    request["connections"] = [{"targetZone": zone, "target": target, "port": 5432}]
    write(path, request)
    rows = query(teams, catalog, "relation", "tenant_connection_review")
    assert [row[4:] for row in rows if row[:4] == ["reed", "reed-1", target, 5432]] == [
        ["denied", "unresolved-owner"]]


def test_ambiguous_tenant_key_resolves_no_owner(tmp_path):
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    model["teams"]["elm-twin"] = {"key": "elm"}
    write(catalog, model)
    entry = Path(__file__).resolve().parent / "request_preview.py"
    result = subprocess.run([sys.executable, str(entry), "--pack", str(entry.parent), "--teams", str(teams),
                             "--catalog", str(catalog), "relation", "tenant_connection_review"],
                            capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert result.stdout == ""
