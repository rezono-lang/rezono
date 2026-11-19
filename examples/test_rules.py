"""Every example pack with rules/, per fact state (facts/, then each scenario): the derived relations
equal the pack's own independent reference and Soufflé, incremental recompute equals batch, every
derived row has a proof that the independent checker accepts, and the explained output (snapshots and
proofs for the viewer) is byte-equal to expected/explained. Nothing here knows a pack."""

import importlib
import json
import re
import runpy
import shutil
from functools import lru_cache
from pathlib import Path

import pytest

import souffle
from golden import differences
from rezono_compiler import batch, emit, explain, rules_sql
from rezono_compiler.__main__ import explained
from rules_support import RULED, name, states

pytestmark = pytest.mark.skipif(not RULED, reason="no example pack with rules")


@pytest.fixture(autouse=True)
def each_snapshot_parsed_once(monkeypatch):
    """`check` reads every snapshot of the manifest again for each proof, and a test here checks one proof
    per derived row: quadratic in the size of a pack. A state's snapshots are the same bytes for every
    proof, so within one test each is parsed once. The checker itself is unchanged, and so is what it checks."""
    module = importlib.import_module("rezono_checker.check")
    monkeypatch.setattr(module, "read_rows", lru_cache(maxsize=None)(module.read_rows))


def tree(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def relation_rows(document):
    assert document, "the reference must name the relations it checks"
    return {relation: {tuple(map(str, row)) for row in rows} for relation, rows in document.items()}


def reference(example, labels) -> dict[str, dict[str, set]]:
    """Read the pack's independently authored rows for exactly the requested fact states."""
    root = example / "expected" / "rules"
    if not root.is_dir() and (example / "reference.py").is_file():
        source = runpy.run_path(str(example / "reference.py"))
        # The reference applies each scenario to the previous state in place. Read its rows before advancing.
        result = {}
        for label, facts in source["states"]():
            assert label not in result, label
            result[label] = relation_rows(source["rules"](facts))
        assert list(result) == labels, "one independent reference per fact state"
        return result
    if not root.is_dir() and (example / "oracle-rows.json").is_file():
        assert len(labels) == 1 and labels[0].startswith("0-"), "one reference snapshot covers only initial facts"
        rows = json.loads((example / "oracle-rows.json").read_text(encoding="utf-8"))
        return {labels[0]: relation_rows(rows)}
    # A modular reference contributes its own relations in every state. Read rules may span modules.
    parts = [root] if list(root.glob("*.json")) else sorted(d for d in root.iterdir() if d.is_dir())
    assert parts, f"{root}: no independent rule references"
    out: dict[str, dict[str, set]] = {label: {} for label in labels}
    for part in parts:
        files = sorted(part.glob("*.json"))
        assert [f.stem for f in files] == labels, f"{part.relative_to(example)}: one file per fact state"
        for f in files:
            for relation, rows in json.loads(f.read_text(encoding="utf-8")).items():
                out[f.stem].setdefault(relation, set()).update(tuple(str(x) for x in r) for r in rows)
    assert all(out.values()), f"{root}: a fact state has no reference relations"
    return out


class MissingPlatformRelations(AssertionError):
    """The outstanding cluster projections from the independent platform reference."""


PLATFORM = Path(__file__).resolve().parent / "platform"
PENDING_PLATFORM = {
    "cluster_endpoint_host", "cluster_endpoint_network", "cluster_endpoint_zone", "cluster_firewall_rule",
    "cluster_fleet_member", "cluster_flow", "cluster_in_zone_policy", "cluster_machine_stack",
    "cluster_network_stack", "cluster_service_placement", "cluster_worker_host", "cluster_worker_interface",
}


@pytest.mark.parametrize("example, pending", [
    *(pytest.param(p, set(), id=name(p)) for p in RULED if p != PLATFORM),
    pytest.param(PLATFORM, PENDING_PLATFORM, id="platform", marks=pytest.mark.xfail(
        strict=True, raises=MissingPlatformRelations,
        reason="Waits for the platform cluster projection tasks in examples/platform/proof_cases. "
               "Read decisions/platform-derivation-acceptance.md. Every implemented relation must already agree.")),
])
def test_same_as_the_pack_reference(example, pending):
    """Compare every named row and both sides of every seal, including expected empty relations."""
    _, _, run = states(example)
    wanted = reference(example, [s.label for s in run])
    missing = set()
    for s in run:
        want = wanted[s.label]
        have = s.derived | s.seal
        assert pending <= want.keys(), f"{s.label}: the reference omits a pending relation"
        assert sorted(set(s.seal) - set(want)) == [], f"{s.label}: the reference skips the seal"
        for relation, rows in sorted(want.items()):
            if relation not in have and relation in pending:
                missing.add(relation)
                continue
            assert relation in have, f"{s.label}: {relation} is not derived"
            assert have[relation] == rows, f"{s.label}: {relation}"
    if missing:
        raise MissingPlatformRelations(sorted(missing))


@pytest.mark.parametrize("example", RULED, ids=name)
def test_every_named_outcome_is_checked_by_the_reference_and_holds(example):
    """The pack's reference computes every named outcome itself (state and reason), and in
    every fact state each element of the kind has exactly one state (the views <outcome>__total and
    <outcome>__state are empty)."""
    _, prog, run = states(example)
    outcomes = sorted(n for n, r in prog.relations.items() if r.outcome)
    for label, want in reference(example, [s.label for s in run]).items():
        assert sorted(set(outcomes) - set(want)) == [], f"{label}: the reference skips an outcome"
    for s in run:
        con = batch.connect(prog, s.base)
        batch.compute(con, prog)
        for o in outcomes:
            for view, _ in rules_sql.outcome_checks(prog, o):
                assert con.execute(f"SELECT COUNT(*) FROM {emit.q(view)}").fetchone()[0] == 0, (s.label, view)


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
@pytest.mark.parametrize("example", RULED, ids=name)
def test_same_as_souffle(example, tmp_path):
    _, prog, run = states(example)
    for s in run:
        assert souffle.run(prog, s.base, tmp_path) == s.derived, s.label


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
@pytest.mark.parametrize("example", RULED, ids=name)
def test_the_pack_source_as_written_on_souffle(example, tmp_path):
    """Soufflé runs rules/*.dl as written (not the IR the parser made of them), with the tables bound: the
    pack's own files and those of every pack it imports, since the program is the union over the import
    closure."""
    _, prog, run = states(example)
    text = souffle.pack_source(prog, example)
    for s in run:
        assert souffle.run(prog, s.base, tmp_path, program_text=text) == s.derived, s.label


@pytest.mark.parametrize("example", RULED, ids=name)
def test_the_pack_source_declares_every_relation_once(example):
    """Without Soufflé: the program Soufflé gets declares every relation of the compiled program, once. A
    rule file of an imported pack that is left out, or a relation declared again, shows here."""
    _, prog, _ = states(example)
    declared = re.findall(r"^\s*\.decl\s+([a-z0-9_]+)", souffle.pack_source(prog, example), flags=re.M)
    assert sorted(declared) == sorted(prog.relations)


@pytest.mark.parametrize("example", RULED, ids=name)
def test_incremental_equals_batch(example):
    """From each state to the next: apply only the changed rows and recompute only what they reach."""
    _, prog, run = states(example)
    con = batch.connect(prog, run[0].base)
    batch.compute(con, prog)
    for before, after in zip(run, run[1:]):
        changed = set()
        for rel in prog.base_used() + prog.calc_inputs():  # a selection is an input of the rules like a table
            old, new = set(before.base.get(rel, [])), set(after.base.get(rel, []))
            for row in sorted(old - new, key=repr):
                batch.apply(con, prog, rel, row, "delete")
            for row in sorted(new - old, key=repr):
                batch.apply(con, prog, rel, row, "insert")
            if old != new:
                changed.add(rel)
        batch.compute(con, prog, relations=prog.downstream(changed))
        assert batch.read(con, prog) == after.derived, after.label


@pytest.mark.parametrize("example", RULED, ids=name)
def test_every_proof_is_valid_and_acyclic(example):
    from rezono_checker.check import check, check_epoch
    from rezono_checker.rules import derived_relations, load_rules

    model, prog, run = states(example)
    rules = load_rules(model.rules)
    for s in run:
        manifest, read = s.manifest()
        if s.calc_witnesses:  # only the epoch check recomputes a calculation witness: all proofs at once
            report = check_epoch(s.explainer.chosen(), manifest, rules, read, derived=derived_relations(model.rules, rules),
                                 calc_witnesses=s.calc_witnesses, calc_ir=s.calc_ir)
            assert report["valid"] and not report["findings"], (s.label, report["findings"][:5])
        for rel in sorted(s.derived):
            for key in sorted(s.derived[rel]):
                proof = s.proof(rel, key)
                if "calc_witnesses" in proof:
                    continue  # its calculation premise: checked in the epoch above
                report = check(proof, manifest, rules, read)
                assert report["valid"], (s.label, rel, key, report["findings"][:5])
                assert not report["findings"], (s.label, rel, key, report["findings"][:5])


@pytest.mark.parametrize("example", RULED, ids=name)
def test_a_changed_proof_is_refused(example):
    """The checker is not a rubber stamp: a proof whose conclusion or binding is changed is refused."""
    from rezono_checker.check import check
    from rezono_checker.rules import load_rules

    model, prog, run = states(example)
    rules = load_rules(model.rules)
    s = run[-1]
    manifest, read = s.manifest()
    for rel in sorted(s.derived):
        if not s.derived[rel]:
            continue
        proof = s.explainer.proof(rel, min(s.derived[rel]), s.label)
        root = next(w for w in proof["witnesses"] if w["conclusion"] == proof["root"])
        if root.get("bindings"):
            root["bindings"][0]["value"] += "x"
            assert not check(proof, manifest, rules, read)["valid"], rel


class MissingExplainedReference(FileNotFoundError):
    """The pack has no independent byte reference for the explained output."""


@pytest.mark.xfail(strict=True, raises=MissingExplainedReference, reason=(
    "later: a byte reference for explained output is recorded per example only after its proofs were checked "
    "by hand against the pack's worked reference; engine output is never its own golden. Not a worker task. "
    "Read decisions/example-explained-output.md."))
@pytest.mark.parametrize("example", RULED, ids=name)
def test_explained_output_is_the_golden(example, tmp_path):
    """Check all emitted proof and snapshot bytes against the pack's independent reference."""
    model, _, run = states(example)
    got = explained(model, example)
    assert {path for path in got if path.endswith("/proofs.json")} == {f"{s.label}/proofs.json" for s in run}
    for state in run:
        proofs = json.loads(got[f"{state.label}/proofs.json"])
        assert [(p["root"]["relation"], tuple(json.loads(p["root"]["key"]))) for p in proofs] == [
            (rel, min(rows)) for rel, rows in sorted(state.derived.items()) if rows
        ], state.label
        for proof in proofs:
            for rel in explain.relations_of(proof):
                assert f"{state.label}/snapshots/{rel}.json" in got
    root = example / "expected" / "explained"
    if not root.is_dir():
        raise MissingExplainedReference(f"{name(example)}: missing expected/explained")
    diff = differences({k: v.encode() for k, v in got.items()}, tree(root))
    assert not diff, diff
