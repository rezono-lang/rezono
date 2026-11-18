import pytest

from offline_cases import PLAN_HASH, RUN, relation


def test_candidate_cannot_authorize_itself():
    # A single candidate repeats every value needed for a paid dispatch.
    candidate = "unconfirmed"
    claims = {"plan_hash": PLAN_HASH, "approval_hash": PLAN_HASH, "currency": "USD",
              "approval_currency": "USD", "decision": "approve", "cost_micros": 1,
              "cap_micros": 1, "event_us": 9, "expires_us": 10}
    facts = {"candidate": [(candidate,)]}
    facts.update({f"candidate__{field}": [(candidate, value)] for field, value in claims.items()})
    assert relation("dispatch", facts, "authorized") == set()


def evidence(candidate, changes=None):
    sources = {
        "plan": {"plan_hash": PLAN_HASH, "currency": "USD"},
        "quote": {"plan_hash": PLAN_HASH, "currency": "USD", "cost_micros": 1614000},
        "approval": {"plan_hash": PLAN_HASH, "currency": "USD", "decision": "approve",
                     "cap_micros": 1614000, "expires_us": 10},
        "observation": {"event_us": 9},
    }
    data = {"candidate": [(candidate,)]}
    for kind, fields in sources.items():
        source_id = f"{kind}-{candidate}"
        data[kind] = [(source_id,)]
        fields = {"candidate": candidate, **fields, **(changes or {}).get(kind, {})}
        for field, value in fields.items():
            if value is not None:
                data[f"{kind}__{field}"] = [(source_id, value)]
    return data


def test_dispatch_policy():
    variants = {
        "equal_cap": {},
        "below_cap": {"approval": {"cap_micros": 1620000}},
        "wrong_hash": {"approval": {"plan_hash": "b" * 64}},
        "declined": {"approval": {"decision": "decline"}},
        "expired": {"observation": {"event_us": 10}},
        "late": {"observation": {"event_us": 11}},
        "over_cap": {"approval": {"cap_micros": 1613999}},
        "currency": {"approval": {"currency": "EUR"}},
        "missing_cost": {"quote": {"cost_micros": None}},
        "no_expiry": {"approval": {"expires_us": None}},
        "different_quote": {"quote": {"plan_hash": "b" * 64}},
        "quote_currency": {"quote": {"currency": "EUR"}},
        "missing_decision": {"approval": {"decision": None}},
        "negative_cost": {"quote": {"cost_micros": -1}},
    }
    facts = {}
    for candidate, changes in variants.items():
        for name, rows in evidence(candidate, changes).items():
            facts.setdefault(name, []).extend(rows)
    assert relation("dispatch", facts, "authorized") == {("equal_cap",), ("below_cap",)}


@pytest.mark.parametrize("kind", ["plan", "quote", "approval", "observation"])
def test_each_source_must_exist_and_belong_to_the_attempt(kind):
    facts = evidence("dispatch")
    source_rows = facts.pop(kind)
    assert relation("dispatch", facts, "authorized") == set()
    facts[kind] = source_rows
    source_id, = source_rows[0]
    facts["candidate"].append(("other",))
    facts[f"{kind}__candidate"] = [(source_id, "other")]
    assert relation("dispatch", facts, "authorized") == set()


def test_conflicting_evidence_cannot_authorize():
    facts = evidence("dispatch")
    facts["approval__decision"].append(("approval-dispatch", "decline"))
    assert relation("dispatch", facts, "authorized") == set()
    facts = evidence("dispatch")
    second_approval = evidence("second", {"approval": {"candidate": "dispatch", "decision": "decline"}})
    for name, rows in second_approval.items():
        if name == "approval" or name.startswith("approval__"):
            facts[name].extend(rows)
    assert relation("dispatch", facts, "authorized") == set()


def test_authorization_witness_identifies_all_four_source_records():
    from rezono_compiler import batch, pack, rules

    program = rules.load(pack.read(RUN / "packs" / "dispatch").rules)
    connection = batch.connect(program, evidence("dispatch"))
    try:
        batch.compute(connection, program, witnesses=True)
        witness, = batch.witnesses(connection, program, ["authorized"])["authorized"]
        assert {"plan-dispatch", "quote-dispatch", "approval-dispatch", "observation-dispatch"} <= set(witness)
    finally:
        connection.close()
