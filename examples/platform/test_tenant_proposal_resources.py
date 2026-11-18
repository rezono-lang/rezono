"""Admission against landed capacity and the full ordered candidate."""
import pytest

from tenant_oracle import calculate, load_requests
from tenant_proposal_case import ROOT, load, proposal, write

REVISION = "de" * 20
BASE = [["guest-host", "cores", 6, 9], ["guest-host", "memoryGiB", 12, 18],
        ["storage-pool", "storageGiB", 70, 100]]
DEFICITS = [["guest-host", "cores", 1], ["guest-host", "memoryGiB", 2],
            ["storage-pool", "storageGiB", 10]]
RELATIONS = {"tenant_resource_capacity": "capacity", "tenant_resource_shortage": "shortages"}


def candidate(tmp_path, additions=("draft", "next"), *, room=False, merged=False, recorded=True):
    teams, catalog = proposal(tmp_path)
    model = load(catalog)
    model["profiles"]["development"]["unlisted"] = "review"
    model["landedDeliveries"] = [
        {"request": "elm/ledger", "revision": REVISION, "cores": 6, "memoryGiB": 12, "storageGiB": 70}
    ]
    if not recorded:
        model["landedDeliveries"] = []
    if merged:
        model["landedDeliveries"].append(
            {"request": "reed/draft", "revision": "bc" * 20, "cores": 2, "memoryGiB": 4, "storageGiB": 20})
    if room:
        model["capacity"] = {"guest-host": {"cores": 10, "memoryGiB": 20}, "storage-pool": {"storageGiB": 110}}
    write(catalog, model)
    ledger = teams / "elm/ledger/request.json"
    request = load(ledger)
    external = request["connections"]
    write(ledger, dict(request, connections=[]))
    studio = teams / "reed/studio/request.json"
    request = load(studio)
    write(studio, dict(request, connections=request["connections"] + external))
    small = load(ROOT / "tenant-scenarios/third-request.json")
    del small["team"], small["service"]
    write(teams / "elm/wait/request.json", dict(small, connections=external, submittedAt="2026-01-02T12:00:00Z"))
    for service in additions:
        date = "2026-01-03" if service == "draft" else "2026-01-04"
        write(teams / "reed" / service / "request.json", dict(small, submittedAt=date + "T00:00:00Z"))
    return teams, catalog


def expected(teams, catalog):
    return calculate(load(catalog), load_requests(teams))


def test_landed_capacity_and_combined_candidate(tmp_path):
    for service in ("draft", "next"):
        alone = expected(*candidate(tmp_path / service, (service,)))
        assert alone["capacity"] == BASE and alone["shortages"] == []
        assert ["reed", "reed-2", "standard"] in alone["proposal"]
    unmerged = expected(*candidate(tmp_path / "unmerged", recorded=False))
    assert [r[2] for r in unmerged["capacity"]] == [0, 0, 0] and unmerged["shortages"] == DEFICITS
    together = expected(*candidate(tmp_path / "together"))
    assert together["capacity"] == BASE and together["shortages"] == DEFICITS
    assert together["proposal"] == [["elm", "elm-1", "standard"], ["elm", "elm-2", "review"],
                                    ["reed", "reed-1", "denied"], ["reed", "reed-2", "standard"],
                                    ["reed", "reed-3", "denied"]]
    assert {r[4] for r in together["connections"] if r[1] == "reed-1"} == {"denied", "review"}
    enough = expected(*candidate(tmp_path / "enough", room=True))
    assert enough["shortages"] == [] and ["reed", "reed-3", "standard"] in enough["proposal"]
    assert [row[2] for row in enough["capacity"]] == [6, 12, 70]
    landed = expected(*candidate(tmp_path / "landed", merged=True))
    assert [r[2] for r in landed["capacity"]] == [8, 16, 90]
    assert landed["shortages"] == DEFICITS


class MissingCapacityRules(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=MissingCapacityRules, reason="Depends on test_trusted_tenant_proposal_inputs. Derive landed tenant_resource_capacity and ordered candidate tenant_resource_shortage with witnesses in examples/platform/rules and calc. Read decisions/platform-tenant-proposal-relations.md.")
def test_real_proposal_capacity_and_three_resource_shortages(tmp_path):
    from proof_cases.case_support import verified
    from request_preview import preview_inputs
    from rezono_compiler import calc, pack, rules
    from rules_support import State

    model = pack.read(ROOT)
    program = rules.load(model.rules)
    missing = RELATIONS.keys() - set(program.derived())
    if missing:
        raise MissingCapacityRules(f"Missing production rules: {sorted(missing)}")
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    cases = [("alone-draft", ("draft",), False, False, True), ("alone-next", ("next",), False, False, True),
             ("joint", ("draft", "next"), False, False, True), ("room", ("draft", "next"), True, False, True),
             ("landed", ("draft", "next"), False, True, True), ("unmerged", ("draft", "next"), False, False, False)]
    for label, additions, room, merged, recorded in cases:
        teams, catalog = candidate(tmp_path / label, additions, room=room, merged=merged, recorded=recorded)
        reference = expected(teams, catalog)
        data = preview_inputs(model, ROOT, teams, catalog)
        state = State(model, program, label, data, calculation)
        for relation, key in RELATIONS.items():
            rows = {tuple(map(str, row)) for row in reference[key]}
            assert state.derived[relation] == rows
            for row in rows:
                leaves = verified(relation, row, state=(model, state))
                if recorded:
                    assert ("tenant_landed_delivery__revision", ("elm/ledger", REVISION)) in leaves
                if relation == "tenant_resource_shortage":
                    for request in ("reed/draft", "reed/next"):
                        assert any(value == request or value.startswith(request + "/")
                                   for _, leaf in leaves for value in leaf), (request, leaves)
