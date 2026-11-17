"""Standard pack std-decision (RV-C03): its rules and axioms against independent oracles.

Three evaluations must agree as sets: an exact Python reference written from the definitions, the DuckDB
batch backend on the compiled IR, and Soufflé on rules/decision.dl as written (when present, as in CI). The
must-fail cases show that each axiom and each schema rule fires. The worked example is read from the pack's
README, so the README cannot drift from the rules. No domain: the decisions are plain letters.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings, strategies as st

from support import FIXTURE, REPO, violations
from rezono_compiler import emit, facts, modules, pack
from rezono_compiler import rules as ir

STD = REPO / "packs" / "std-decision"
BASE = ("decision", "decision__state", "decision__supersedes", "decision__decider", "decision__valid_from_day",
        "decision__valid_until_day", "reference_date__day", "ground__decision", "ground__rests_on")
pytest.importorskip("duckdb")


def reference(data):
    """The definitions of rules/decision.dl, relation by relation, on sets of rows."""
    kind, state, supersedes, decider, start, end, days, resting, rested = (set(map(tuple, data.get(k, ()))) for k in BASE)
    grounds = {(a, b) for g, a in resting for h, b in rested if g == h}
    ground_chain = set(grounds)
    while True:
        more = {(a, c) for a, b in grounds for x, c in ground_chain if b == x} - ground_chain
        if not more:
            break
        ground_chain |= more
    replaces = set(supersedes)
    while True:
        more = {(a, c) for a, b in replaces for x, c in supersedes if b == x} - replaces
        if not more:
            break
        replaces |= more
    proposed = {d for d, s in state if s == "proposed"}
    took_effect = {(d, r) for r, n in days for d, f in start if f <= n and d not in proposed and (d,) in kind}
    ended = {(d, r) for r, n in days for d, u in end if u <= n}
    replaced = {(d, s, r) for s, d in supersedes for x, r in took_effect if x == s}
    was_replaced = {(d, r) for d, _, r in replaced}
    in_force_on = took_effect - ended - was_replaced
    has_start = {(d,) for d, _ in start}
    has_successor = {(d,) for s, d in supersedes if (s,) in has_start and s not in proposed}
    has_decider = {(d,) for d, _ in decider}
    return {
        "replaces": replaces,
        "supersession_cycle": {(a,) for a, b in replaces if a == b},
        "window_inverted": {(d,) for d, f in start for x, u in end if d == x and u <= f},
        "took_effect": took_effect,
        "ended": ended,
        "replaced": replaced,
        "was_replaced": was_replaced,
        "in_force_on": in_force_on,
        "has_start": has_start,
        "has_successor": has_successor,
        "superseded_in_force": {(d, r) for d, r in in_force_on if (d, "superseded") in state and (d,) not in has_successor},
        "has_decider": has_decider,
        "in_force_without_decider": {(d, r) for d, r in in_force_on if (d,) not in has_decider},
        "in_force_without_start": {(d,) for d, s in state if s == "in_force" and (d,) not in has_start},
        "withdrawn_without_start": {(d,) for d, s in state if s == "withdrawn" and (d,) not in has_start},
        "proposal": {(d,) for d in proposed},
        "ground_chain": ground_chain,
        "ground_cycle": {(a,) for a, b in ground_chain if a == b},
    }


def program():
    return ir.load(pack.read(STD).rules)


def batch_eval(prog, data):
    from rezono_compiler import batch
    con = batch.connect(prog, {k: sorted(data.get(k, ())) for k in BASE})
    batch.compute(con, prog)
    return batch.read(con, prog)


def as_text(result):
    return {name: {tuple(str(v) for v in row) for row in rows} for name, rows in result.items()}


def evaluate(data, tmp_path):
    """Every engine at hand, each compared with the reference."""
    prog = program()
    want = as_text(reference(data))
    assert as_text(batch_eval(prog, data)) == want
    if shutil.which("souffle"):
        import souffle
        source = souffle.source(prog, [p.read_text("utf-8") for p in sorted((STD / "rules").glob("*.dl"))])
        rows = {k: sorted(data.get(k, ())) for k in BASE}
        assert souffle.run(prog, rows, tmp_path, program_text=source) == want
    return want


def records(*decisions, days=(("then", 20250101), ("now", 20261110)), grounds=()):
    """Base rows from short records (id, state, first day, last day, supersedes, deciders); None leaves a slot out.
    A ground is a pair: a decision and the decision it rests on."""
    data = {k: set() for k in BASE}
    for d, state, start, end, supersedes, deciders in decisions:
        data["decision"].add((d,))
        data["decision__state"].add((d, state))
        if start is not None:
            data["decision__valid_from_day"].add((d, start))
        if end is not None:
            data["decision__valid_until_day"].add((d, end))
        data["decision__supersedes"] |= {(d, old) for old in supersedes}
        data["decision__decider"] |= {(d, who) for who in deciders}
    data["reference_date__day"] = set(days)
    data["ground__decision"] = {(f"{a}-on-{b}", a) for a, b in grounds}
    data["ground__rests_on"] = {(f"{a}-on-{b}", b) for a, b in grounds}
    return data


def test_the_pack_compiles_on_its_own_and_carries_roles_and_questions():
    model = pack.read(STD)
    assert not model.meta.get("theory") and not (STD / "facts").exists()
    layer = {"purpose", "principle", "alternative", "exception"}  # the justification layer (EX9)
    assert set(model.kinds) == {"decision", "ground", "subject", "reference_date"} | layer
    bundle = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])
    roles = {k["id"]: k.get("slot_roles") for k in bundle["kinds"]}["decision"]
    assert roles == {"name": "decision.title", "known_from": "decision.decided_on",
                     "valid_from": "decision.valid_from", "valid_until": "decision.valid_until"}
    prog = program()
    derived = {r.name: r for r in prog.relations.values() if r.role == "derived"}
    assert sorted(derived) == sorted(reference({}))
    # No rule reads the justification layer: it is shown beside the proof and changes no conclusion.
    unread = layer | {"decision__warrant", "decision__owner", "decision__review_on"}
    source = "".join(p.read_text("utf-8") for p in sorted((STD / "rules").glob("*.dl")))
    assert not [n for n in sorted(unread) if re.search(rf"\b{n}(__\w+)?\(", source)]
    assert sorted(n for n, r in derived.items() if r.invariant) == [
        "ground_cycle", "superseded_in_force", "supersession_cycle", "window_inverted"]
    assert [n for n, r in derived.items() if r.absence] == ["in_force_without_decider"]
    assert [q["term"] for q in model.questions] == ["decided", "replaced"]


def readme_example():
    block = re.search(r"## Worked example.*?```yaml\n(.*?)```", (STD / "README.md").read_text("utf-8"), re.S)
    return block.group(1)


def test_the_worked_example_of_the_readme(tmp_path):
    """The README's facts load through the real fact loader, pass every schema check, and give the rows the
    README states."""
    model = pack.read(STD)
    (tmp_path / "example.yaml").write_text(readme_example(), encoding="utf-8")
    rows = facts.load(model, tmp_path / "example.yaml")
    assert violations(emit.compile_pack(model), rows) == {}
    got = evaluate({k: rows.get(k, []) for k in BASE}, tmp_path)
    assert got["in_force_on"] == {
        ("hours-2024", "2025-01-01"),
        ("hours-2025", "2026-08-01"), ("summer-2026", "2026-08-01"),
        ("hours-2025", "2026-11-10")}
    assert got["replaced"] == {("hours-2024", "hours-2025", "2026-08-01"), ("hours-2024", "hours-2025", "2026-11-10")}
    assert got["in_force_without_decider"] == {("summer-2026", "2026-08-01")}
    assert got["ended"] == {("summer-2026", "2026-11-10")}
    assert not got["superseded_in_force"] and not got["supersession_cycle"] and not got["window_inverted"]
    assert not got["in_force_without_start"]
    # A date and its day number say the same day (the stopgap of schema/decision.yaml).
    for slot in ("valid_from", "valid_until"):
        days = dict(rows.get(f"decision__{slot}_day", []))
        assert {d: int(str(v).replace("-", "")) for d, v in rows.get(f"decision__{slot}", [])} == days


def test_a_superseded_decision_is_in_force_until_its_successor_takes_effect(tmp_path):
    got = evaluate(records(("a", "superseded", 20240301, None, [], ["p"]),
                           ("b", "in_force", 20250701, None, ["a"], ["p"])), tmp_path)
    assert got["in_force_on"] == {("a", "then"), ("b", "now")}      # history: a on 1-1-2025, b on 10-11-2026
    assert got["replaced"] == {("a", "b", "now")} and not got["superseded_in_force"]


def test_a_proposed_decision_is_never_in_force_and_replaces_nothing(tmp_path):
    got = evaluate(records(("a", "in_force", 20240301, None, [], ["p"]),
                           ("b", "proposed", 20250701, None, ["a"], ["p"])), tmp_path)
    assert got["in_force_on"] == {("a", "then"), ("a", "now")} and not got["replaced"]
    assert got["replaces"] == {("b", "a")}                          # the chain is there, whatever the state


def test_a_successor_that_is_not_yet_in_force_leaves_its_predecessor_in_force(tmp_path):
    """Both records say in force and the successor starts later: no contradiction on any reference date."""
    got = evaluate(records(("a", "in_force", 20240301, None, [], ["p"]),
                           ("b", "in_force", 20270101, None, ["a"], ["p"]),
                           days=(("now", 20261110), ("later", 20270601))), tmp_path)
    assert got["in_force_on"] == {("a", "now"), ("b", "later")} and not got["superseded_in_force"]


def test_a_replaced_decision_does_not_come_back_when_its_successor_ends(tmp_path):
    got = evaluate(records(("a", "superseded", 20240301, None, [], ["p"]),
                           ("b", "withdrawn", 20240901, 20250601, ["a"], ["p"])), tmp_path)
    assert got["in_force_on"] == {("b", "then")} and got["ended"] == {("b", "now")}


def test_the_last_day_is_exclusive_and_the_first_inclusive(tmp_path):
    got = evaluate(records(("a", "in_force", 20250101, 20261110, [], ["p"])), tmp_path)
    assert got["in_force_on"] == {("a", "then")}                    # starts on 'then', ended on 'now'


def test_must_fail_a_superseded_record_without_a_successor_that_was_taken(tmp_path):
    lone = records(("a", "superseded", 20240301, None, [], ["p"]))
    assert evaluate(lone, tmp_path)["superseded_in_force"] == {("a", "then"), ("a", "now")}
    proposed = records(("a", "superseded", 20240301, None, [], ["p"]), ("b", "proposed", 20250701, None, ["a"], []))
    assert evaluate(proposed, tmp_path)["superseded_in_force"] == {("a", "then"), ("a", "now")}
    undated = records(("a", "superseded", 20240301, None, [], ["p"]), ("b", "in_force", None, None, ["a"], ["p"]))
    got = evaluate(undated, tmp_path)
    assert got["superseded_in_force"] == {("a", "then"), ("a", "now")} and got["in_force_without_start"] == {("b",)}


def test_must_fail_a_cycle_of_superseded_decisions(tmp_path):
    got = evaluate(records(("a", "in_force", 20240301, None, ["c"], ["p"]), ("b", "superseded", 20230101, None, ["a"], ["p"]),
                           ("c", "superseded", 20220101, None, ["b"], ["p"]), ("d", "superseded", 20210101, None, [], ["p"]),
                           ("e", "in_force", 20260101, None, ["d"], ["p"])), tmp_path)
    assert got["supersession_cycle"] == {("a",), ("b",), ("c",)}    # e and d form a chain, not a cycle
    assert evaluate(records(("a", "in_force", 20240301, None, ["a"], ["p"])), tmp_path)["supersession_cycle"] == {("a",)}


def test_must_fail_a_cycle_of_grounds(tmp_path):
    """RV-A31: the grounds have no cycle, whatever the state of the decisions; a chain is no cycle."""
    two = records(("a", "in_force", 20240301, None, [], ["p"]), ("b", "proposed", None, None, [], []),
                  ("c", "in_force", 20240301, None, [], ["p"]), ("d", "in_force", 20240301, None, [], ["p"]),
                  grounds=[("a", "b"), ("b", "a"), ("c", "a"), ("d", "c")])
    got = evaluate(two, tmp_path)
    assert got["ground_cycle"] == {("a",), ("b",)}                  # c and d rest on the cycle, and are not in it
    assert {("d", "c"), ("d", "a"), ("d", "b"), ("c", "b")} <= got["ground_chain"]
    alone = records(("a", "in_force", 20240301, None, [], ["p"]), grounds=[("a", "a")])
    assert evaluate(alone, tmp_path)["ground_cycle"] == {("a",)}
    chain = records(("a", "in_force", 20240301, None, [], ["p"]), ("b", "in_force", 20240301, None, [], ["p"]),
                    ("c", "in_force", 20240301, None, [], ["p"]), grounds=[("a", "b"), ("b", "c"), ("a", "c")])
    got = evaluate(chain, tmp_path)
    assert got["ground_chain"] == {("a", "b"), ("b", "c"), ("a", "c")} and not got["ground_cycle"]


def test_a_withdrawn_record_without_a_first_day_is_a_finding_and_one_with_days_is_read_by_its_days(tmp_path):
    """RV-A31: time comes from the days. A withdrawn record that names its days is in force until its last day;
    one that names none is in force on no reference date, and the finding says so. A proposal is neither."""
    got = evaluate(records(("a", "withdrawn", None, None, [], ["p"]),
                           ("b", "withdrawn", 20240301, 20270101, [], ["p"]),
                           ("c", "withdrawn", 20240301, 20250601, [], ["p"]),
                           ("d", "proposed", None, None, [], [])), tmp_path)
    assert got["withdrawn_without_start"] == {("a",)} and got["proposal"] == {("d",)}
    assert got["in_force_on"] == {("b", "then"), ("b", "now"), ("c", "then")} and got["ended"] == {("c", "now")}
    invariants = [r.name for r in program().relations.values() if r.invariant]
    assert all(not got[name] for name in invariants)                # a finding: it does not block


def test_must_fail_a_window_that_ends_before_it_starts(tmp_path):
    got = evaluate(records(("a", "in_force", 20250101, 20250101, [], ["p"]), ("b", "in_force", 20250101, 20240101, [], ["p"]),
                           ("c", "in_force", 20250101, 20250102, [], ["p"])), tmp_path)
    assert got["window_inverted"] == {("a",), ("b",)}


def test_findings_do_not_block_and_name_what_the_record_lacks(tmp_path):
    got = evaluate(records(("a", "in_force", 20240301, None, [], []), ("b", "in_force", None, None, [], ["p"]),
                           ("c", "proposed", None, None, [], [])), tmp_path)
    assert got["in_force_without_decider"] == {("a", "then"), ("a", "now")}     # c is not in force: no finding
    assert got["in_force_without_start"] == {("b",)}
    invariants = [r.name for r in program().relations.values() if r.invariant]
    assert all(not got[name] for name in invariants)


def test_must_fail_the_schema_rules(tmp_path):
    """LinkML rules of Decision: a validity date and its day number come together, and a decision that applied
    and was withdrawn names its last day. A withdrawn proposal names no day at all and passes."""
    model = pack.read(STD)
    (tmp_path / "facts.yaml").write_text(
        "decision:\n"
        "  - {id: a, title: t, state: in_force, valid_from: '2025-01-01'}\n"
        "  - {id: b, title: t, state: in_force, valid_from_day: 20250101}\n"
        "  - {id: c, title: t, state: in_force, valid_from: '2025-01-01', valid_from_day: 20250101, valid_until: '2026-01-01'}\n"
        "  - {id: d, title: t, state: in_force, valid_from: '2025-01-01', valid_from_day: 20250101, valid_until_day: 20260101}\n"
        "  - {id: e, title: t, state: withdrawn, valid_from: '2025-01-01', valid_from_day: 20250101}\n"
        "  - {id: f, title: t, state: withdrawn}\n"
        "  - {id: g, title: t, state: withdrawn, valid_from: '2025-01-01', valid_from_day: 20250101,"
        " valid_until: '2025-06-01', valid_until_day: 20250601}\n", encoding="utf-8")
    got = violations(emit.compile_pack(model), facts.load(model, tmp_path / "facts.yaml"))
    assert {check: {subject for subject, _ in rows} for check, rows in got.items()} == {
        "decision__rule_1__rule": {"a"}, "decision__rule_2__rule": {"b"}, "decision__rule_3__rule": {"c"},
        "decision__rule_4__rule": {"d"}, "decision__rule_5__rule": {"e"}}


def test_a_ground_is_a_link_between_two_decisions_and_a_reassessment_an_arrow(tmp_path):
    """S27: Ground is a relation kind named by its ends, the decision and the one it rests on, and a second row
    for the same pair breaks its key. What a decision looked at again is an arrow on it, and open: no
    record of a reassessment leaves unknown whether there was one. The pack follows the grounds and holds them to
    one axiom (ground_cycle); no rule of the pack reads a reassessment (README, "What a decision rests on")."""
    model = pack.read(STD)
    compiled = emit.compile_pack(model)
    assert model.kinds["decision"].slots["reassesses"].world == "open"
    assert model.kinds["ground"].world == "closed" and model.kinds["ground"].slots["rests_on"].world == "closed"
    ground = {k["id"]: k for k in json.loads(compiled["bundle/schema-bundle.json"])["kinds"]}["ground"]
    assert ground["relationship"] is True and ground["ends"] == ["ground.decision", "ground.rests_on"]
    assert "name_attribute" not in ground and ground["name_arrows"] == ground["ends"]  # its ends name it
    (tmp_path / "facts.yaml").write_text(
        "decision:\n"
        "  - {id: a, title: first, state: in_force}\n"
        "  - {id: b, title: second, state: in_force}\n"
        "  - {id: c, title: looked again, state: in_force, reassesses: [a, b]}\n"
        "ground:\n"
        "  - {id: b-a, decision: b, rests_on: a}\n"
        "  - {id: c-a, decision: c, rests_on: a}\n"
        "  - {id: c-a-again, decision: c, rests_on: a}\n", encoding="utf-8")
    rows = facts.load(model, tmp_path / "facts.yaml")
    assert sorted(rows["decision__reassesses"]) == [("c", "a"), ("c", "b")]
    assert sorted(rows["ground__rests_on"]) == [("b-a", "a"), ("c-a", "a"), ("c-a-again", "a")]
    got = violations(compiled, rows)
    assert list(got) == ["ground__ground_pair__unique"] and {s for s, _ in got["ground__ground_pair__unique"]} == {
        "c-a", "c-a-again"}


def test_a_consumer_imports_the_pack_and_rests_a_conclusion_on_a_decision_in_force(tmp_path):
    """S28: the import brings kinds, rules and questions; a consumer's rule reads in_force_on like its own."""
    consumer = Path(shutil.copytree(FIXTURE, tmp_path / "consumer"))
    meta = yaml.safe_load((consumer / "pack.yaml").read_text())
    meta["imports"] = [{"name": "std-decision", "path": str(STD), "sha256": modules.pack_hash(STD)}]
    (consumer / "pack.yaml").write_text(yaml.safe_dump(meta))
    (consumer / "rules").mkdir(exist_ok=True)
    (consumer / "rules" / "core.dl").write_text(
        ".decl settled(x: symbol, d: symbol, r: symbol)\nsettled(x, d, r) :- alpha(x), in_force_on(d, r).\n")
    model = pack.read(consumer)
    assert {"decision", "subject", "reference_date"} <= set(model.kinds)
    prog = ir.load(model.rules)
    assert prog.rules["in_force_on"].module == "import_std_decision_decision"
    assert [b.atom.relation for b in prog.rules["settled"].body] == ["alpha", "in_force_on"]
    assert {"decided", "replaced"} <= {q["term"] for q in model.questions}


DECISIONS = st.sampled_from("abcde")
DAY = st.sampled_from([20240101, 20250101, 20250701, 20260101, 20270101])


@settings(max_examples=60, deadline=None)
@given(kind=st.sets(DECISIONS), state=st.dictionaries(DECISIONS, st.sampled_from(["proposed", "in_force", "superseded", "withdrawn"])),
       start=st.dictionaries(DECISIONS, DAY), end=st.dictionaries(DECISIONS, DAY),
       supersedes=st.sets(st.tuples(DECISIONS, DECISIONS), max_size=8),
       decider=st.sets(st.tuples(DECISIONS, st.sampled_from("pq")), max_size=5),
       days=st.dictionaries(st.sampled_from(["r1", "r2", "r3"]), DAY, min_size=1),
       grounds=st.sets(st.tuples(DECISIONS, DECISIONS), max_size=8))
def test_rules_and_axioms_agree_with_the_reference_on_any_registration(kind, state, start, end, supersedes, decider, days,
                                                                      grounds, tmp_path_factory):
    """Property (Hypothesis): on any registration every engine equals the reference. A decision in force is
    never replaced, ended or proposed; and once a successor has taken effect it stays in effect on every
    later reference date, so its predecessor never returns."""
    data = {"decision": {(d,) for d in kind}, "decision__state": set(state.items()), "decision__valid_from_day": set(start.items()),
            "decision__valid_until_day": set(end.items()), "decision__supersedes": supersedes,
            "decision__decider": decider, "reference_date__day": set(days.items()),
            "ground__decision": {(f"{a}-on-{b}", a) for a, b in grounds},
            "ground__rests_on": {(f"{a}-on-{b}", b) for a, b in grounds}}
    got = evaluate(data, tmp_path_factory.mktemp("decision"))
    assert got["ground_cycle"] == {(a,) for a, b in got["ground_chain"] if a == b}
    assert not got["in_force_on"] & got["was_replaced"] and not got["in_force_on"] & got["ended"]
    assert all(state.get(d) != "proposed" for d, _ in got["in_force_on"])
    for d, s, r in got["replaced"]:
        assert all((d, s, later) in got["replaced"] for later, n in days.items() if n >= days[r])
        assert all((d, later) not in got["in_force_on"] for later, n in days.items() if n >= days[r])

