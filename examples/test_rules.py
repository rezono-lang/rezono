"""Every example pack with rules/, per fact state (facts/, then each scenario): the derived relations
equal the pack's own reference (expected/rules) and Soufflé, incremental recompute equals batch, every
derived row has a proof that the independent checker accepts, and the explained output (snapshots and
proofs for the viewer) is byte-equal to expected/explained. Nothing here knows a pack."""

import importlib
import json
import re
import shutil
from functools import lru_cache
from pathlib import Path

import pytest

import souffle
from golden import differences
from rede_compiler import batch, emit, explain, rules_sql
from rede_compiler.__main__ import explained
from rules_support import RULED, name, states

pytestmark = pytest.mark.skipif(not RULED, reason="no example pack with rules")


@pytest.fixture(autouse=True)
def each_snapshot_parsed_once(monkeypatch):
    """`check` reads every snapshot of the manifest again for each proof, and a test here checks one proof
    per derived row: quadratic in the size of a pack. A state's snapshots are the same bytes for every
    proof, so within one test each is parsed once. The checker itself is unchanged, and so is what it checks."""
    module = importlib.import_module("rede_checker.check")
    monkeypatch.setattr(module, "read_rows", lru_cache(maxsize=None)(module.read_rows))


def tree(d: Path) -> dict[str, bytes]:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def reference(example, labels) -> dict[str, dict[str, set]]:
    """{state: {relation: rows}} as the pack's reference gives them. One reference writes
    expected/rules/<state>.json. A pack with a reference per module (reference/<module>.py) has
    expected/rules/<module>/<state>.json instead: each module names its own relations, in every fact state, and
    a relation several modules add to (the read rules) is the union of what they name."""
    root = example / "expected" / "rules"
    parts = [root] if list(root.glob("*.json")) else sorted(d for d in root.iterdir() if d.is_dir())
    out: dict[str, dict[str, set]] = {label: {} for label in labels}
    for part in parts:
        files = sorted(part.glob("*.json"))
        assert [f.stem for f in files] == labels, f"{part.relative_to(example)}: one file per fact state"
        for f in files:
            for relation, rows in json.loads(f.read_text()).items():
                out[f.stem].setdefault(relation, set()).update(tuple(str(x) for x in r) for r in rows)
    return out


@pytest.mark.xfail(strict=True, reason="generated expected/rules goldens are not stored in git")
@pytest.mark.parametrize("example", RULED, ids=name)
def test_same_as_the_pack_reference(example):
    """expected/rules, written by the pack's own reference, names the outcomes it checks, and the refused and
    accepted input of a seal (decision E3), which the reference computes itself."""
    _, _, run = states(example)
    wanted = reference(example, [s.label for s in run])
    for s in run:
        want = wanted[s.label]
        have = s.derived | s.seal
        assert sorted(set(s.seal) - set(want)) == [], f"{s.label}: the reference skips the seal"
        for relation, rows in sorted(want.items()):
            assert relation in have, f"{s.label}: {relation} is not derived"
            assert have[relation] == rows, f"{s.label}: {relation}"


@pytest.mark.xfail(strict=True, reason="generated expected/rules goldens are not stored in git")
@pytest.mark.parametrize("example", RULED, ids=name)
def test_every_named_outcome_is_checked_by_the_reference_and_holds(example):
    """Decision W7: the pack's reference computes every named outcome itself (state and reason), and in
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
    closure (decision S28)."""
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
    from rede_checker.check import check, check_epoch
    from rede_checker.rules import derived_relations, load_rules

    model, prog, run = states(example)
    rules = load_rules(model.rules)
    for s in run:
        manifest, read = s.manifest()
        if s.calc_witnesses:  # only the epoch check recomputes a calculation witness (W12): all proofs at once
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
    from rede_checker.check import check
    from rede_checker.rules import load_rules

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


@pytest.mark.xfail(strict=True, reason="generated expected/explained goldens are not stored in git")
@pytest.mark.parametrize("example", RULED, ids=name)
def test_explained_output_is_the_golden(example, tmp_path):
    """What goes to the viewer: per state one proof per derived relation, with complete snapshots.
    A new or changed golden comes from CI (artifact compiled-examples), never from a local machine."""
    model, _, _ = states(example)
    got = explained(model, example)
    want = tree(example / "expected" / "explained") if (example / "expected" / "explained").is_dir() else {}
    diff = differences({k: v.encode() for k, v in got.items()}, want)
    assert not diff, diff
    for path, text in got.items():
        if path.endswith("proofs.json"):
            for proof in json.loads(text):
                for rel in explain.relations_of(proof):
                    assert f"{path.rsplit('/', 1)[0]}/snapshots/{rel}.json" in got
