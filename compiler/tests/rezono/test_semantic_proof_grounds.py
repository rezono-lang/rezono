"""The converter must preserve checked grounds as well as published results."""

import json
import re
import shutil

from pyarrow import ipc
import pytest

from rezono_publisher import publish, store
from scripts import convert_pack
from support import FIXTURE
from test_native_rule_publication_parity import ROLES, SENTENCES, artifact, build, digest, write


FACTS = """alpha:
  - {id: winner, title: fixed}
  - {id: rival-left, title: left}
  - {id: rival-right, title: right}
  - {id: blocked-left, title: blocked-left}
  - {id: blocked-right, title: blocked-right}
"""
RULES = """.decl watch(cohort: symbol, candidate: symbol)
watch("left", item) :- alpha__title(item, "left").
watch("right", item) :- alpha__title(item, "right").

.decl candidate(cohort: symbol, item: symbol, amount: number, priority: number)
candidate("left", "winner", 7, 1) :- alpha("winner").
candidate("right", "winner", 7, 1) :- alpha("winner").
candidate(cohort, item, 7, 2) :- watch(cohort, item).
candidate("left", item, 8, 3) :- alpha__title(item, "blocked-left").
candidate("right", item, 8, 3) :- alpha__title(item, "blocked-right").

.decl excluded(cohort: symbol, item: symbol)
excluded("left", item) :- alpha__title(item, "blocked-left").
excluded("right", item) :- alpha__title(item, "blocked-right").

.decl compared(cohort: symbol, winner: symbol, rival: symbol)
compared(g, w, w) :- candidate(g, w, _, _), !excluded(g, w).
compared(g, w, r) :- candidate(g, w, amount, first), candidate(g, r, amount, second),
  first < second, !excluded(g, w), !excluded(g, r).

.decl selected(winner: symbol, inventory: number)
"""
SELECTION = """selected("winner", n) :-
  watch("left", item), alpha__title(item, "left"), !excluded("left", item),
  n = count : { candidate("left", _, _, _) },
  m = count : { compared("left", "winner", _) },
  x = count : { excluded("left", _) },
  covered = m + x, covered = n.
"""
MESSAGES = SENTENCES + """rule.watch = {{A candidate belongs to this group.}}
rule.candidate = {{This item entered the selection.}}
rule.excluded = {{This item was excluded.}}
rule.compared = {{The winner precedes this eligible candidate.}}
rule.selected = {{Every candidate is compared or excluded.}}
"""


def scenario(path, selection):
    directory = path / "minimal"
    shutil.copytree(FIXTURE / "schema", directory / "schema")
    shutil.copyfile(FIXTURE / "channels.yaml", directory / "channels.yaml")
    write(directory, "pack.yaml", 'name: minimal\nversion: "0"\ndefault_language: en\nimports: []\n')
    write(directory, "facts/base.yaml", FACTS)
    write(directory, "facts/base.sources.yaml",
          'default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
          'position: compiler/tests/rezono/test_semantic_proof_grounds.py#FACTS}\n')
    write(directory, "messages/en.mf2", MESSAGES)
    write(directory, "rules/access.dl", """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("viewer", "alpha", item) :- alpha(item).
""")
    source = "rules/eligibility.dl"
    write(directory, source, RULES + selection)
    return build(directory, source, 1)


def checked_output(epoch, path):
    bucket = store.FileStore(path)
    manifest = publish.publish(epoch, bucket, ROLES, forms=True)
    assert {check["status"] for check in manifest["checks"]} == {"green"}
    assert next(check for check in manifest["checks"] if check["name"] == "rezono:proofs")["violations"] == 0
    snapshots = {
        (entry["role"], entry["relation"]): artifact(bucket, entry)
        for entry in manifest["snapshots"]
    }
    assert {role for role, _ in snapshots} == set(ROLES)

    prefix = f"minimal/{manifest['id']}/viewer/publication/"
    index = json.loads(bucket.get(prefix + "index.json"))
    assert index["role"] == "viewer"
    files = {entry["name"]: entry for entry in index["objects"]}
    visible_rows = [
        {key: value for key, value in row.items() if key not in ("$src", "$why")}
        for row in artifact(bucket, files["rows.json"])["$rows"]
    ]
    assert [row for row in visible_rows if row["$kind"] == "Selected"] == [
        {"$id": '["winner","3"]', "$kind": "Selected", "inventory": "3", "winner": "winner"}
    ]
    columns = {}
    for name, entry in files.items():
        if name.startswith("table.") and name.endswith(".arrow") and not name.startswith("table._"):
            data = bucket.get(prefix + name)
            assert digest(data) == entry["sha256"]
            columns[name] = ipc.open_file(data).schema.names
    assert columns["table.Selected.arrow"] == ["$id", "inventory", "winner"]
    [bundle] = [entry for entry in manifest["compiled"] if entry["file"] == "bundle/schema-bundle.json"]
    messages = artifact(bucket, bundle)["messages"]
    en_resources = [entry["resource"] for entry in messages if entry["lang"] == "en"]
    assert en_resources
    pack_lines = MESSAGES.split("\n---\n", 1)[1].splitlines()
    en_lines = [line for res in en_resources for line in res.split("\n---\n", 1)[-1].splitlines()]
    assert all(line in en_lines for line in pack_lines)
    return snapshots, visible_rows, columns, messages


def ground_key(*fields):
    return json.dumps(fields, separators=(",", ":"))


def selected_grounds(epoch, cohort):
    [proof] = [w for w in epoch.witnesses if w["conclusion"]["relation"] == "selected"]
    assert proof["conclusion"]["key"] == ground_key("winner", "3")
    rival, blocked = f"rival-{cohort}", f"blocked-{cohort}"
    signed_reads = {
        (premise["polarity"], premise["row"]["relation"], premise["row"]["key"])
        for premise in proof["premises"]
    }
    assert signed_reads == {
        ("positive", "watch", ground_key(cohort, rival)),
        ("positive", "alpha__title", ground_key(rival, cohort)),
        ("negative", "excluded", ground_key(cohort, rival)),
    }

    # The equal-score rival loses by priority, and the higher-score candidate is excluded.
    # Check every member named by the checked count certificate, including intermediate rows.
    groups = {
        "candidate": ((cohort,), [
            (cohort, "winner", "7", "1"), (cohort, rival, "7", "2"), (cohort, blocked, "8", "3"),
        ]),
        "compared": ((cohort, "winner"), [(cohort, "winner", "winner"), (cohort, "winner", rival)]),
        "excluded": ((cohort,), [(cohort, blocked)]),
    }
    certificates = {entry["relation"]: entry for entry in proof["aggregates"]}
    assert set(certificates) == set(groups)
    grounds = set(signed_reads)
    for relation, (key, members) in groups.items():
        assert sorted(row for row in epoch.rows[relation] if row[:len(key)] == key) == sorted(members)
        certificate = certificates[relation]
        assert certificate["group_key"] == ground_key(*key)
        assert certificate["count"] == len(members)
        assert certificate["result"] == f"known:{len(members)}"
        member_keys = sorted(ground_key(*row) for row in members)
        assert certificate["contributors_sha256"] == digest(ground_key(*[[row] for row in member_keys]).encode())
        grounds.update(("positive", relation, row) for row in member_keys)
    return grounds


def test_full_pack_comparison_preserves_grounds(tmp_path):
    baseline = scenario(tmp_path / "baseline", SELECTION)
    trial = scenario(tmp_path / "trial", SELECTION.replace('"left"', '"right"'))
    renamed_variables = {"item": "rival", "n": "total", "m": "eligible", "x": "disqualified"}
    renamed = scenario(
        tmp_path / "renamed",
        "\n" + re.sub(r"\b(?:item|n|m|x)\b", lambda hit: renamed_variables[hit[0]], SELECTION),
    )

    expected = checked_output(baseline, tmp_path / "baseline-store")
    assert checked_output(trial, tmp_path / "trial-store") == expected
    assert checked_output(renamed, tmp_path / "renamed-store") == expected
    assert baseline.rows == trial.rows == renamed.rows
    assert baseline.definition_sha256 != renamed.definition_sha256
    before = selected_grounds(baseline, "left")
    assert before == selected_grounds(renamed, "left")
    assert before.isdisjoint(selected_grounds(trial, "right"))

    convert_pack.compare_publications(baseline, renamed, ROLES)
    with pytest.raises(convert_pack.ConversionError, match="changed the grounds"):
        convert_pack.compare_publications(baseline, trial, ROLES)
