"""The subsidy pack's own tests: what the generic example tests (examples/test_*.py) cannot know.

- The evaluation date decides which partial rate counts: before 1 July 2026 an award at the partial
  rate is lower, to the cent as reference.py computes it.
- The supposition of the last scenario moves the awards the README names: who gains, who loses, who stays.
- Through the publisher: the policy adviser gets every award but nothing of the ledger; and a claim
  that differs from the quotes by one cent (the invariant costs_mismatch) stops the publication.
- std-time through views.yaml (T1): the policy adviser reads how each scheme parameter stands on the
  evaluation day, with a proof down to the parameter's own valid_until; a role without grants reads none of it.
- What other organisations state (W4 step 1): the credentials are what the credential in port observes, a
  changed byte is refused at input, and a claim is attested only with its statement, its issuer's authority and
  its status, each reached by the proof with its own source.
Needs the compiler with DuckDB and the publisher, and `cryptography` for the credential in port.
"""

import importlib.util
import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")
pytest.importorskip("rezono_publisher")

from calcsupport import run_both  # noqa: E402  (compiler/tests, on the path through examples/conftest.py)
from rezono_compiler import calc, calc_sql, pack, scenarios  # noqa: E402
from rezono_publisher import batch, publish, store  # noqa: E402

HERE = Path(__file__).parent
PACK = "subsidy"
PROFILE = HERE.parents[1] / "deploy" / "profiles" / "edge.yaml"
# The pack's own roles, and the roles of the profile that publishes it (`propose`, `viewer`).
ROLES = {"checker": "complete", "case_officer": "may_read", "policy_adviser": "may_read", "public": "may_read"} | yaml.safe_load(
    PROFILE.read_text(encoding="utf-8"))["access"]["roles"]
# What `public` reads, and what it does not: the kinds of a case (rules/access.dl).
# The justification kinds (std-decision) are read with the decision, by every role.
SCHEME = ("alternative", "article", "calendar", "cost_item", "decision", "exception", "principle", "purpose",
          "reference_date", "role", "scheme_parameter")
CASE = ("advice_report", "application", "closed_payment", "cost_line", "household", "income_statement", "ledger_payment",
        "period_close")
# What other organisations state (schema/credentials.yaml): about persons, so `public` reads none of it either.
CREDENTIALS = ("credential", "credential_claim", "identity_statement", "status_lookup", "trust_entry")
CASE += CREDENTIALS
PORT = HERE.parents[1] / "edge" / "plugins" / "credential-in" / "credential_in.py"
# A case of its own file: a household of two with one quote, an income statement and so an award.
PLANTED = """household:
  - {"id": "H900", "persons": 2}
application:
  - {"id": "A900", "household": "H900", "claimed_costs": 500000}
cost_line:
  - {"id": "L9000", "application": "A900", "item": "heat-pump", "amount": 500000}
income_statement:
  - {"id": "S900", "household": "H900", "income": 2500000}
"""
CLAIM = '{"id": "A001", "household": "H001", "claimed_costs": 1100000}'


def reference():
    """The pack's reference.py under a name of its own: other packs have a reference.py too."""
    spec = importlib.util.spec_from_file_location("subsidy_reference", HERE / "reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy(tmp: Path) -> Path:
    """A copy of the pack at the same depth, next to packs/ and the scheme it imports, so the imports resolve."""
    root = HERE.parents[1]
    d = tmp / "examples" / "subsidy"
    shutil.copytree(HERE, d, ignore=shutil.ignore_patterns("expected", "__pycache__", "test_*.py"))
    shutil.copytree(HERE.parent / "subsidy-scheme", d.parent / "subsidy-scheme")
    try:
        (tmp / "packs").symlink_to(root / "packs", target_is_directory=True)
    except OSError:  # no symbolic links without rights (Windows): a copy pins the same bytes
        shutil.copytree(root / "packs", tmp / "packs")
    return d


def published(pack_dir: Path, root: Path):
    e = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-11-10T00:00:00Z", sources=[("rules", "test")])
    s = store.FileStore(root)
    return s, publish.publish(e, s, ROLES)


def rows(s, role: str, rel: str) -> list[tuple]:
    return [tuple(r["key"]) for r in json.loads(s.get(publish.role_objects(s, PACK, "m-1", role)[f"relations/{rel}.json"]))]


# --- The calculation -------------------------------------------------------------------------------

def test_the_evaluation_date_decides_the_partial_rate():
    """The partial rate has two rows (facts/scheme.yaml): 20% until 1 July 2026, 24% from then on. The
    evaluation date is a fact row, so asking for another date needs no compilation."""
    ref = reference()
    model = pack.read(HERE)
    prog = calc.build(model, model.calc)
    _, facts = scenarios.states(model, HERE)[0]
    t = next(ref.states())[1]

    def awards(valid_at: str):
        as_of = {table: [tuple({**r, "valid_at": valid_at if isinstance(r["valid_at"], str) else date.fromisoformat(valid_at)}.values())
                         for r in rs] for table, rs in calc_sql.rows(prog).items()}
        got, exact = run_both(model, prog, model.calc, facts | as_of)
        assert got == exact
        mine = ref.calc(t, on=valid_at)["award"]
        assert {a: (v[1] if v[0] == "known" else v[0]) for a, v in got["award"].items()} == mine
        return mine

    spring, autumn = awards("2026-03-01"), awards("2026-11-10")
    assert (spring["A001"], autumn["A001"]) == ("227000", "269400")  # 20% and 24% of 10,600 euros, plus the allowance
    assert spring["A002"] == autumn["A002"] == "166000"                # the full rate did not change
    assert spring["A003"] == autumn["A003"] == "unknown"               # and unknown stays unknown, on any date


def test_the_supposed_threshold_has_gainers_and_losers():
    """The last scenario against the state before it, over the whole population (expected/calc, which the
    generic test holds equal to the engine): the README's numbers."""
    states = sorted(p.name for p in (HERE / "expected" / "calc").glob("*.json"))
    assert states[-1] == "4-family-threshold.json"
    before, after = (json.loads((HERE / "expected" / "calc" / state).read_text(encoding="utf-8"))["award"] for state in states[-2:])
    known = [a for a in before if before[a] != "unknown"]
    assert [a for a in before if (before[a] == "unknown") != (after[a] == "unknown")] == []
    change = {a: int(after[a]) - int(before[a]) for a in known}
    gain, lose = [d for d in change.values() if d > 0], [d for d in change.values() if d < 0]
    assert (len(gain), sum(gain)) == (23, 2780081)
    assert (len(lose), sum(lose)) == (14, -1760996)
    assert (len(known) - len(gain) - len(lose), len(before) - len(known)) == (187, 16)


def test_a_supposed_amount_is_reported_as_not_decided():
    """Every parameter of the scheme stands on a decision in force (std-decision's in_force_on). The
    supposition of the last scenario is a decision that is only proposed, so its two rows are the finding
    (expected/rules, which the generic test holds equal to the engine)."""
    states = sorted((HERE / "expected" / "rules").glob("*.json"))
    before, after = (json.loads(state.read_text(encoding="utf-8")) for state in states[-2:])
    assert before["undecided_parameter"] == [] and len(before["decided_parameter"]) == 8
    assert ["par-06", "2026-047", "2026-11-10"] in before["decided_parameter"]
    assert after["undecided_parameter"] == [["par-01", "2026-11-10"], ["par-02", "2026-11-10"]]
    assert len(after["decided_parameter"]) == 6


# --- Access and the invariant, through the publisher -----------------------------------------------

def test_the_policy_adviser_gets_every_award_but_nothing_of_the_ledger(tmp_path):
    s, m = published(HERE, tmp_path)
    assert {"name": "costs_mismatch", "status": "green", "violations": 0} in m["checks"]
    # Both roles read everything an award rests on, so both get every award as the checker has it.
    for rel in ("application", "income_statement", "assessment", "repeat_application", "decided_parameter", "calc__award"):
        for role in ("case_officer", "policy_adviser"):
            assert rows(s, role, rel) == rows(s, "checker", rel), (role, rel)
    assert ("A001", "269400", "known", "") in rows(s, "policy_adviser", "calc__award")
    # The ledger is the case officer's: the payments, what they add up to, and the drift against the award.
    for rel in ("ledger_payment", "ledger_payment__accepted", "ledger_paid", "calc__payment_difference"):
        assert rows(s, "case_officer", rel) == rows(s, "checker", rel) != [], rel
        assert rows(s, "policy_adviser", rel) == [], rel
    assert ("A007", "-15000", "known", "") in rows(s, "case_officer", "calc__payment_difference")


def witnesses(s, role: str) -> dict:
    """The role's published witnesses by the row they conclude: (relation, canonical key) -> witness."""
    found = {}

    def walk(x):
        if isinstance(x, dict):
            if "conclusion" in x and "rule_id" in x:
                found[(x["conclusion"]["relation"], json.dumps(x["conclusion"]["key"]))] = x
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(json.loads(s.get(publish.role_objects(s, PACK, "m-1", role)["witnesses.json"])))
    return found


def test_a_role_reads_how_each_parameter_stands_on_the_evaluation_day_down_to_its_own_date(tmp_path):
    """std-time's rules run over the scheme's own facts (views.yaml): what the reference computes from the
    dates themselves, and a proof that ends at the parameter's own valid_until. A role that the pack grants
    nothing (it names no such role) reads no judgement, no day count and no proof of it."""
    e = batch.epoch(HERE, epoch=1, knowledge_time="2026-11-10T00:00:00Z", sources=[("rules", "test")])
    s = store.FileStore(tmp_path)
    publish.publish(e, s, ROLES | {"outsider": "may_read"})
    expected = json.loads((HERE / "expected" / "rules" / "0-applications.json").read_text(encoding="utf-8"))
    for rel in ("judgement", "holds_at"):
        assert set(rows(s, "policy_adviser", rel)) == {tuple(r) for r in expected[rel]} != set(), rel
    assert ("par-05", "2026-11-10", "negative", "ended") in rows(s, "policy_adviser", "judgement")
    proofs = witnesses(s, "policy_adviser")
    todo = [w for (rel, key), w in proofs.items() if rel == "judgement" and "par-05" in key]
    reached = set()
    while todo:
        w = todo.pop()
        for premise in w.get("premises", []):
            ref = (premise["row"]["relation"], json.dumps(premise["row"]["key"]))
            if ref not in reached:
                reached.add(ref)
                if ref in proofs:
                    todo.append(proofs[ref])
    assert ("scheme_parameter__valid_until", json.dumps(["par-05", "2026-07-01"])) in reached \
        or any(rel == "scheme_parameter__valid_until" and "par-05" in key for rel, key in reached), reached
    for rel in ("judgement", "holds_at", "std_time_interval_end", "scheme_parameter__valid_until"):
        assert rows(s, "outsider", rel) == [], rel
    assert not any("par-05" in key for _, key in witnesses(s, "outsider"))


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


def own(s, m, role: str) -> dict[str, bytes]:
    """Everything the publication holds for one role: its objects, and the manifest's lines that name it."""
    out = {name: s.get(name) for name in s.list(f"{PACK}/{m['id']}/{role}/")}
    # Its snapshots, witnesses and sources are keyed by their bytes: found through the manifest.
    out |= {name: s.get(key) for name, key in publish.role_objects(s, PACK, m["id"], role).items()}
    for part in ("snapshots", "witnesses", "fact_sources"):
        out[part] = json.dumps([x for x in m[part] if x["role"] == role], sort_keys=True).encode()
    return out


def test_the_public_reads_the_scheme_and_no_case(tmp_path):
    """`public` is a role like any other (Y1.2): it reads the scheme, and so it sees that every amount and
    rate stands on a council decision in force, with the proof. It reads no case, so it has no award, no
    assessment and no count over them: not zero rows of a relation it half reads, no relation at all."""
    s, m = published(HERE, tmp_path)
    relations = sorted(name.rsplit("/", 1)[1][:-len(".json")] for name in publish.role_objects(s, PACK, "m-1", "checker")
                       if name.startswith("relations/"))
    got = [rel for rel in relations if rows(s, "public", rel)]
    # What it reads, it reads whole, and it is told so: every snapshot it has rows of is `full`.
    full = {x["relation"] for x in m["snapshots"] if x["role"] == "public" and x["full"]}
    for rel in got:
        if rel != "may_read":
            assert rows(s, "public", rel) == rows(s, "checker", rel) and rel in full, rel
    assert set(SCHEME) <= set(got) and not set(CASE) & set(got)
    # The conclusions the scheme alone gives: which decision is in force, and which parameter stands on one.
    assert {"decided_parameter", "in_force_on", "took_effect"} <= set(got)
    assert ("par-06", "2026-047", "2026-11-10") in rows(s, "public", "decided_parameter")
    proved = {w["conclusion"]["relation"] for w in json.loads(s.get(publish.role_objects(s, PACK, "m-1", "public")["witnesses.json"]))["witnesses"]}
    assert "decided_parameter" in proved
    # Nothing that rests on a case: no award, no assessment, no eligible costs, no finding, no payment.
    for rel in ("assessment", "eligible_costs", "application_count", "repeat_application", "ledger_paid", "calc__award",
                "calc__payment_difference"):
        assert rows(s, "public", rel) == [] != rows(s, "checker", rel), rel
    # Its read rights name the scheme's kinds only, for itself and for the roles it reads about.
    assert {r[1] for r in rows(s, "public", "may_read")} == set(SCHEME)
    # And no case is named anywhere in what it gets: not in a row, a proof or a source.
    ids = {r[0] for kind in CASE for r in rows(s, "checker", kind)}
    assert len(ids) > 1000 and "A001" in ids
    for name, data in own(s, m, "public").items():
        text = data.decode("utf-8")
        assert not [i for i in sorted(ids) if f'"{i}"' in text or f'\\"{i}\\"' in text], name


def test_a_case_changes_nothing_the_public_gets(tmp_path):
    """Two worlds that differ in one case (a household, its application, a quote line and an income
    statement, in a fact file of its own). The policy adviser gets the case and its award; what `public`
    gets is the same bytes in both worlds: objects, proofs, sources and its lines of the manifest."""
    d = copy(tmp_path / "pack")
    without = published(d, tmp_path / "without")
    (d / "facts" / "planted.yaml").write_text(PLANTED, encoding="utf-8", newline="\n")
    with_ = published(d, tmp_path / "with")
    assert ("A900",) not in rows(without[0], "policy_adviser", "application")
    assert ("A900",) in rows(with_[0], "policy_adviser", "application")
    assert [r for r in rows(with_[0], "policy_adviser", "calc__award") if r[0] == "A900" and r[2] == "known"]
    assert own(*with_, "policy_adviser") != own(*without, "policy_adviser")
    assert own(*with_, "public") == own(*without, "public") != {}
    # The definition did not change either, and that is the one hash of the pack a role is given.
    assert with_[1]["definition_sha256"] == without[1]["definition_sha256"]
    assert with_[1]["pack_sha256"] != without[1]["pack_sha256"]


# --- What other organisations state (W4 step 1, K19) -----------------------------------------------

def credential_port():
    """The credential in port (edge/plugins/credential-in), under a name of its own."""
    spec = importlib.util.spec_from_file_location("credential_in", PORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_credentials_are_what_the_in_port_observes():
    """facts/credentials.yaml and its sources companion are exactly what the port writes from the fixture: the
    signatures, the disclosures and the pins verify, and the same inputs give the same bytes."""
    port = credential_port()
    rows, sources = port.observe(HERE / "credentials" / "inputs.yaml", HERE)
    assert (HERE / "facts" / "credentials.yaml").read_text(encoding="utf-8") == port.facts_text(rows, "credentials/inputs.yaml")
    assert ((HERE / "facts" / "credentials.sources.yaml").read_text(encoding="utf-8")
            == port.sources_text(sources, "facts/credentials.yaml"))
    # Synthetic: every issuer is invented and says so, every person is `p-` and eight opaque characters.
    stated = rows["credential"] + rows["trust_entry"] + rows["identity_statement"]
    assert {r["issuer"] for r in stated} <= {"https://advisor-register.invented.example",
                                             "https://training-institute.invented.example", "https://person-register.invented.example"}
    assert all("invented" in r["title"] and "synthetic" in r["title"] for r in stated)
    assert {r["subject"] for r in rows["credential"]} == {"p-4k7q2m9x", "p-8d3n6r1w"}
    nodes = {r[f"{side}_node"] for r in rows["identity_statement"] for side in ("first", "second")}
    assert nodes == {"https://municipality.invented.example", "https://advisor-register.invented.example"}


@pytest.mark.parametrize("where", ["credential", "disclosure", "trust list"])
def test_a_changed_credential_is_refused_at_input(tmp_path, where):
    port = credential_port()
    d = tmp_path / "credentials"
    shutil.copytree(HERE / "credentials", d)
    path = d / ("trust-list.json" if where == "trust list" else "presentations/advisor-register-p-4k7q2m9x.sd-jwt")
    text = path.read_text(encoding="utf-8")
    at = {"credential": lambda: text.index(".") + 30, "disclosure": lambda: text.index("~") + 10,
          "trust list": lambda: text.index("qualification")}[where]()
    path.write_text(text[:at] + ("x" if text[at] != "x" else "y") + text[at + 1:], encoding="utf-8", newline="\n")
    with pytest.raises(port.Refused):
        port.observe(d / "inputs.yaml", tmp_path)


def proof_leaves(s, role: str, relation: str, key: list) -> set[tuple[str, str]]:
    """The rows a published proof of one conclusion rests on, down to its base rows."""
    witnesses = {(w["conclusion"]["relation"], w["conclusion"]["key"]): w
                 for w in json.loads(s.get(publish.role_objects(s, PACK, "m-1", role)["witnesses.json"]))["witnesses"]}
    todo, seen, leaves = [(relation, json.dumps(key, separators=(",", ":")))], set(), set()
    while todo:
        node = todo.pop()
        if node in seen:
            continue
        seen.add(node)
        if node in witnesses:
            todo += [(p["row"]["relation"], p["row"]["key"]) for p in witnesses[node]["premises"]]
        else:
            leaves.add(node)
    return leaves


def test_a_claim_is_attested_only_with_its_statement_its_authority_and_its_status(tmp_path):
    """Of three credentials one claim holds: disclosed, its issuer on the trust list for that attribute on the day
    of issuance, its status valid. Its proof reaches all three grounds, each with its own source. The others are
    unknown with their reason: not disclosed, an issuer without authority for the attribute, a revoked status."""
    s, m = published(HERE, tmp_path)
    attested = [(ADVISOR_REGISTER, "p-4k7q2m9x", "qualification", "energy_advisor")]
    for role in ("case_officer", "policy_adviser", "propose", "viewer"):
        assert rows(s, role, "attested") == attested == rows(s, "checker", "attested"), role
    unknown = {r[2] for r in rows(s, "viewer", "claim_assessment") if r[1] == "unknown"}
    assert unknown == {"not_disclosed", "issuer_not_authorised", "status_not_valid"}
    assert {r[0] for r in rows(s, "viewer", "claim_assessment") if r[1] == "known"} == {f"{REGISTERED}/qualification"}
    leaves = proof_leaves(s, "viewer", "attested", list(attested[0]))
    relations = {r for r, _ in leaves}
    assert {"credential_claim__value", "trust_entry__attribute", "trust_entry__valid_from_day", "status_lookup__status"} <= relations
    published_sources = json.loads(s.get(publish.role_objects(s, PACK, "m-1", "viewer")["sources.json"]))
    entries = published_sources if isinstance(published_sources, list) else published_sources["entries"]
    cited = {src["position"].split("#")[0].split(";")[0] for e in entries
             if (e["row"]["relation"], e["row"]["key"]) in leaves for src in e["sources"]}
    assert {"credentials/presentations/advisor-register-p-4k7q2m9x.sd-jwt", "credentials/trust-list.json",
            "credentials/status/advisor-register-1.jwt"} <= cited
    # `public` reads none of it: no claim, no outcome over a claim, nothing attested, no identity.
    for rel in CREDENTIALS + IDENTITY + ("claim_assessment", "attested"):
        assert rows(s, "public", rel) == [], rel


# --- Identity across nodes (W4 step 2, K20) --------------------------------------------------------

ADVISOR_REGISTER = "https://advisor-register.invented.example"
MUNICIPALITY = "https://municipality.invented.example"
# The fixture's credentials (facts/credentials.yaml): the register's qualification of its p-4k7q2m9x, the training
# institute's of its own p-4k7q2m9x (an identifier that only looks like the register's), and the register's revoked
# one of its p-8d3n6r1w. The person register's statement names the first; the training institute's the third.
REGISTERED, LOOKALIKE, REVOKED = "c-dd7a1848cd75", "c-6033735e29f1", "c-51d13f3f3a79"
STATEMENT = "s-48f2102858ac"
IDENTITY = ("same_subject", "subject_identification", "attested_here")
HERE_PERSON = ("p-7w3j5n2e", "qualification", "energy_advisor")


def edited(tmp: Path, change) -> Path:
    """A copy of the pack whose credential facts and their sources companion `change` rewrote line by line."""
    d = copy(tmp / "pack")
    for name in ("credentials.yaml", "credentials.sources.yaml"):
        path = d / "facts" / name
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        path.write_text("".join(x for x in (change(line) for line in lines) if x is not None), encoding="utf-8", newline="\n")
    return d


def test_two_identifiers_are_one_person_only_by_an_authoritative_statement(tmp_path):
    """The person register, which the trust list lets name identifiers of both nodes (an entry per node), says the
    municipality's p-7w3j5n2e is the advisor register's p-4k7q2m9x: that credential's subject is known here, and the
    municipality relies on its qualification for its own p-7w3j5n2e. The training institute's p-4k7q2m9x looks the
    same and joins nothing; a statement of an issuer without that authority joins nothing either. The proof of what is
    relied on shows the statement, both trust entries and the municipality's own lookup of the statement (Y4.15)."""
    s, m = published(HERE, tmp_path)
    for role in ("case_officer", "policy_adviser", "propose", "viewer"):
        assert rows(s, role, "attested_here") == [HERE_PERSON] == rows(s, "checker", "attested_here"), role
    assert rows(s, "viewer", "same_subject") == [
        (ADVISOR_REGISTER, "p-4k7q2m9x", MUNICIPALITY, "p-7w3j5n2e"), (MUNICIPALITY, "p-7w3j5n2e", ADVISOR_REGISTER, "p-4k7q2m9x")]
    assert set(rows(s, "viewer", "subject_identification")) == {
        (REGISTERED, "known", ""), (LOOKALIKE, "unknown", "no_identity_statement"),
        (REVOKED, "unknown", "statement_issuer_not_authorised")}
    leaves = proof_leaves(s, "viewer", "attested_here", list(HERE_PERSON))
    relations = {r for r, _ in leaves}
    assert {"identity_statement__first_identifier", "identity_statement__second_identifier", "identity_statement__issuer",
            "trust_entry__attribute", "status_lookup__statement", "status_lookup__status", "credential_claim__value",
            "trust_entry__node", "status_lookup__looked_up_on_day"} <= relations
    scope = {k for r, k in leaves if r == "trust_entry__node"}
    assert any('"te-3a"' in k for k in scope) and any('"te-3b"' in k for k in scope), scope
    published_sources = json.loads(s.get(publish.role_objects(s, PACK, "m-1", "viewer")["sources.json"]))
    entries = published_sources if isinstance(published_sources, list) else published_sources["entries"]
    cited = {src["position"].split("#")[0].split(";")[0] for e in entries
             if (e["row"]["relation"], e["row"]["key"]) in leaves for src in e["sources"]}
    assert {"credentials/statements/person-register-p-7w3j5n2e.sd-jwt", "credentials/status/person-register-1.jwt",
            "credentials/presentations/advisor-register-p-4k7q2m9x.sd-jwt", "credentials/trust-list.json"} <= cited


@pytest.mark.parametrize("world, reason", [
    ("without the statement", "no_identity_statement"),
    ("the statement revoked", "statement_status_not_valid"),
    ("its issuer without that authority", "statement_issuer_not_authorised"),
    ("a node outside its issuer's entries", "statement_issuer_not_authorised"),
    ("an entry without a node", "statement_issuer_not_authorised"),
    ("a window that ended before the first lookup", "statement_issuance_not_established"),
])
def test_without_a_statement_that_holds_the_join_is_unknown(tmp_path, world, reason):
    """Worlds that differ from the fixture in the person register's statement or its two trust entries alone. The
    claim stays attested at the advisor register; here its subject is unknown with the reason, and the municipality
    relies on nothing for p-7w3j5n2e. An entry names the node whose identifiers its issuer may name, and one without
    a node names none (Y4.15). A window that holds the issuer's day (2026-06-01) but ended before the municipality
    first looked the statement up (2026-11-10) establishes no issuance: the issuer's date alone proves no time."""
    def entry(line: str, ids: tuple[str, ...]) -> bool:
        return line.lstrip().startswith('- {"id"') and any(f'"id": "{i}"' in line for i in ids)

    change = {
        "without the statement": lambda line: None if STATEMENT in line else line,
        "the statement revoked": lambda line: (line.replace('"status": "valid"', '"status": "revoked"')
                                               if f'"statement": "{STATEMENT}"' in line else line),
        "its issuer without that authority": lambda line: (line.replace('"same_subject"', '"course_completed"')
                                                           if entry(line, ("te-3a", "te-3b")) else line),
        "a node outside its issuer's entries": lambda line: (
            line.replace(f'"node": "{ADVISOR_REGISTER}"', '"node": "https://training-institute.invented.example"')
            if entry(line, ("te-3b",)) else line),
        "an entry without a node": lambda line: (line.replace(f'"node": "{ADVISOR_REGISTER}", ', "")
                                                 if entry(line, ("te-3b",)) else line),
        "a window that ended before the first lookup": lambda line: (
            line.replace('"valid_until": "2028-01-01", "valid_until_day": 20280101',
                         '"valid_until": "2026-11-01", "valid_until_day": 20261101')
            if entry(line, ("te-3a", "te-3b")) else line),
    }[world]
    d = edited(tmp_path, change)
    assert ((d / "facts" / "credentials.yaml").read_text(encoding="utf-8")
            != (HERE / "facts" / "credentials.yaml").read_text(encoding="utf-8")), "the world changed nothing"
    s, m = published(d, tmp_path / "store")
    assert rows(s, "viewer", "attested") == [(ADVISOR_REGISTER, "p-4k7q2m9x", "qualification", "energy_advisor")]
    assert (REGISTERED, "unknown", reason) in rows(s, "viewer", "subject_identification")
    assert not [r for r in rows(s, "viewer", "subject_identification") if r[1] == "known"]
    assert rows(s, "viewer", "attested_here") == [] == rows(s, "viewer", "same_subject")


def test_a_claim_that_differs_from_the_quotes_stops_the_publication(tmp_path):
    d = copy(tmp_path / "pack")
    facts = d / "facts" / "applications.yaml"
    text = facts.read_text(encoding="utf-8")
    assert CLAIM in text
    facts.write_text(text.replace(CLAIM, CLAIM.replace("1100000", "1100001")), encoding="utf-8")
    with pytest.raises(publish.Blocked, match="costs_mismatch"):
        published(d, tmp_path / "red")
    assert not (tmp_path / "red" / PACK / "manifests").exists()
    # Repaired, the pack publishes again, and the checker has every application.
    facts.write_text(text, encoding="utf-8")
    s, m = published(d, tmp_path / "green")
    assert {"name": "costs_mismatch", "status": "green", "violations": 0} in m["checks"]
    assert ("A001",) in rows(s, "checker", "application")
