"""The witnesses of a real pack's rules on Feldera, beside the batch run (DuckDB).

The two engines, batch and incremental, must agree on conclusions and on witnesses (docs/vision.md, "Proof").
examples/test_feldera_rules.py compares the conclusions of every example pack at each fact state. Witnesses are
compared only for generated programs (compiler/tests/test_rules_properties.py) and for one rule of the platform
pack (examples/test_platform_incremental_proof.py); decisions/feldera-calculation-parity.md compares the
calculation witnesses. This test compares the rule witnesses of the subsidy pack: at each of its fact states, every
witness relation the compiled pipelines materialize on Feldera holds the same bindings as the witness query of the
same rule on the batch run (rezono_compiler.batch.witnesses), as canonical text.

A relation with `explain on_demand` has no witness relation on Feldera: its witnesses are the explain query over the
final relations, which examples/test_feldera_rules.py compares. With equal witnesses and equal relations, the
checker's verdict on the batch proofs (examples/test_rules.py::test_every_proof_is_valid_and_acyclic) holds for
the proofs Feldera's witnesses give.

Offline the test checks that the comparison can run: every witness relation the plan materializes is a
CREATE MATERIALIZED VIEW in the pipeline part that computes its rule's head, and the live oracle runs this test.
With FELDERA_URL set it replays the fact states as examples/test_feldera_rules.py does, part by part with the
exported rows relayed, and compares the witnesses after each state."""

import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

import feldera
from feldera_file_input import FileInputs
from rezono_compiler import feldera_names, rules_sql
from rezono_compiler import rules as ir
from rezono_compiler.seal import text
from rules_support import name, states
from test_feldera_rules import changes, export_rows, fact_updates

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
TEST = "examples/test_rule_witness_engine_parity.py::test_feldera_rule_witnesses_match_batch"
# A real pack with rules, a calculation the rules read, and fact states (scenarios/).
WITNESSED = [ROOT / "subsidy"]


class MissingRuleWitnessParity(LookupError):
    """A witness relation the plan materializes is not readable on Feldera, or the live oracle does not run this
    comparison."""


def readable(sql: str) -> set[str]:
    return set(re.findall(r'(?m)^CREATE MATERIALIZED VIEW ("(?:""|[^"])*")', sql))


def witnessed_rules(prog, parts) -> dict[str, list]:
    """Per pipeline part, the rules whose head it computes and whose witnesses the plan materializes."""
    return {part["name"]: [r for rel in part["views"] if rel in prog.relations for r in prog.rules_for(rel)
                           if rules_sql.wants_witness(prog, r, "materialize")]
            for part in parts}


def routed(example: Path) -> list[str]:
    """What the live oracle lacks to run this test for the pack: the selector, a shard, and not ORIGINAL."""
    ci = str(REPO / "compiler" / "ci")
    if ci not in sys.path:
        sys.path.insert(0, ci)
    import feldera_shards

    node = f"{TEST}[{name(example)}]"
    runner = (REPO / "compiler" / "ci" / "run_feldera_oracle.sh").read_text(encoding="utf-8")
    gaps = []
    if not re.search(rf"(?m)^\s*{re.escape(TEST)}\s*$", runner):
        gaps.append(f"compiler/ci/run_feldera_oracle.sh does not select {TEST}")
    if not any(node in cases for cases in feldera_shards.SHARDS.values()):
        gaps.append(f"compiler/ci/feldera_shards.py routes {node} in no shard")
    if node in feldera_shards.ORIGINAL:
        gaps.append(f"compiler/ci/feldera_shards.py counts {node} in ORIGINAL")
    return gaps


def held(pipeline, rule) -> set[tuple]:
    """The bindings Feldera holds in a rule's witness relation, as batch.witnesses gives them: canonical text in
    the order of rule.variables, and the empty tuple for the empty substitution."""
    columns = [c.lower() for c in rules_sql.witness_columns(rule)]
    rows = [{k.lower(): v for k, v in row.items()} for row in feldera.read_relation(pipeline, rule.witness_relation)]
    return {tuple(text(row[c]) for c in columns) if rule.variables else () for row in rows}


@pytest.fixture
def oracle_input_dir():
    shared = os.environ.get("FELDERA_ORACLE_INPUT_DIR")
    if shared is None:
        yield None
        return
    with tempfile.TemporaryDirectory(dir=shared) as directory:
        path = Path(directory)
        path.chmod(0o755)
        yield path


@pytest.mark.xfail(strict=True, raises=MissingRuleWitnessParity, reason=(
    "M3: docs/vision.md \"Proof\"; the batch and incremental engines must agree on conclusions and on witnesses. "
    "Feldera's witnesses are compared with the batch run only for generated programs "
    "(compiler/tests/test_rules_properties.py) and one platform rule (examples/test_platform_incremental_proof.py); "
    "examples/test_feldera_rules.py compares conclusions only, and decisions/feldera-calculation-parity.md compares "
    "calculation witnesses. Missing: the live route; select this test in compiler/ci/run_feldera_oracle.sh, add its "
    "case to one shard in compiler/ci/feldera_shards.py (the subsidy shard already downloads the pack's dependencies; "
    "keep the shard within its 60-minute limit) and leave it out of ORIGINAL there; scripts/feldera_admission.py "
    "stays unchanged. The route changes the live collection that examples/test_live_feldera_shards.py and "
    "examples/test_feldera_incident.py pin, so a planner adds the case there first. Lift this mark. A difference on "
    "the live run is a defect in the witness SQL (compiler/rezono_compiler/rules_sql.py), not in this comparison. "
    "Verify the exact implementation revision on hosted Feldera before queue admission."))
@pytest.mark.parametrize("example", WITNESSED, ids=name)
def test_feldera_rule_witnesses_match_batch(example, committed_packs, oracle_input_dir):
    files = committed_packs.compiled(example)
    prog = ir.load(committed_packs.model(example).rules)
    plan = json.loads(files["engine/pipelines.json"])
    parts = plan["pipelines"]
    witnessed = witnessed_rules(prog, parts)
    gaps = [] if any(witnessed.values()) else ["the plan materializes no witness relation"]
    for part in parts:
        sql = "\n".join(files[path] for path in part["sql"])
        unreadable = sorted(r.witness_relation for r in witnessed[part["name"]]
                            if feldera_names.quoted(r.witness_relation) not in readable(sql))
        if unreadable:
            gaps.append(f"part {part['name']} does not materialize {unreadable}")
    gaps += routed(example)
    if gaps:
        raise MissingRuleWitnessParity(f"{name(example)}: " + "; ".join(gaps))
    if not feldera.URL:
        return

    model, prog, run = states(example)
    witnessed = witnessed_rules(prog, parts)
    inputs = list(fact_updates(model, files, example))
    # Replay all states of one producer before its consumers, as examples/test_feldera_rules.py does: only
    # Feldera's own exports cross a part boundary.
    forwarded = [{} for _ in inputs]
    for index, part in enumerate(parts):
        pipeline = f"rezono-witnesses-{example.name}-{part['name']}"
        sql = "\n".join(files[path] for path in part["sql"])
        if part["exports"]:
            sql += f'\nCREATE MATERIALIZED VIEW "oracle_export_snapshot" AS SELECT * FROM "{plan["export_view"]}";'
        feeds = None
        if oracle_input_dir is not None:
            tables = {t for t in part["tables"] if any(delta.get(t) for _, delta in inputs)}
            tables.update(t for t in part["imports"] if any(relay[t] for relay in forwarded))
            feeds = FileInputs(oracle_input_dir / str(index), tables)
            sql = feeds.connect(sql)
        feldera.deploy(pipeline, sql, profile="unoptimized", workers=2)
        try:
            previous = {}
            for (label, facts_delta), state, relay in zip(inputs, run, forwarded, strict=True):
                assert label == state.label
                delta = {t: facts_delta[t] for t in part["tables"] if t in facts_delta}
                delta.update({t: relay[t] for t in part["imports"]})
                if feeds is None:
                    feldera.processed(pipeline, feldera.push(pipeline, delta))
                else:
                    feeds.send(pipeline, delta)
                with feldera.comparing():
                    for rule in witnessed[part["name"]]:
                        assert held(pipeline, rule) == set(state.explainer.witnesses[rule.id]), (label, rule.id)
                if part["exports"]:
                    current = export_rows(pipeline, prog, part["exports"])
                    for rel, rows in current.items():
                        key = [c.name for c in prog.relations[rel].key]
                        relay[rel] = [{op: dict(zip(key, row, strict=True))}
                                      for op, changed in changes(previous.get(rel, []), rows) for row in changed]
                    previous = current
        finally:
            feldera.stop(pipeline)
