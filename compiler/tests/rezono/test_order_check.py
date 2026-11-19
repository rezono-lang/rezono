"""The acceptance pack `order-check` of decisions/language-expression-semantics.md §5.

The fixture in fixtures/order-check pins the real packs/std-order. Its native module is the source in
§5; its legacy rules are authored independently in Datalog. Expected rows, groups, role views and the
second epoch come from the §5 table. The legacy representation is published by the same helpers and
must show the same observations, so the expectations below are not read from either implementation.

Not yet covered here: the archived rank Value of `a` (`unknown not_measured`) and the question
`ask x: Stage where not (x.rank = 0)`. They need a pack-level source of archived Values, which the
ordinary pack format does not have; the planner adds them once that source exists.
"""

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from rezono_compiler import batch, explain, pack, rules
from rezono_publication import l0
from rezono_publisher import batch as publisher_batch
from rezono_publisher import publish, store
from expression_packs import ROOT, order_check_pack


TIME = "2026-01-01T00:00:00Z"
ROLES = {"checker": "complete", "complete": "may_read", "limited": "may_read"}
DERIVED = ("edge", "zero", "nonzero", "successors")


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def key(*fields: str) -> str:
    return json.dumps(list(fields), separators=(",", ":"))


def contributors(*keys: tuple[str, ...]) -> str:
    return digest(json.dumps([[key(*k)] for k in sorted(keys)], separators=(",", ":")).encode())


# The §5 table, written out per epoch and role. Rows are keys in column order.
FIRST = {
    "complete": {
        "edge": {("a", "b"), ("a", "c")},
        "zero": {("b",)},
        "nonzero": {("c",)},
        "successors": {("a", "2"), ("b", "0"), ("c", "0")},
    },
    "limited": {"edge": {("a", "c")}, "zero": set(), "nonzero": {("c",)}, "successors": set()},
}
SECOND = {
    "complete": FIRST["complete"] | {
        "edge": {("a", "c")}, "successors": {("a", "1"), ("b", "0"), ("c", "0")},
    },
    "limited": FIRST["limited"],
}
# The group of each successors conclusion: its fixed key, count and the distinct edge keys it counted.
GROUPS = {
    ("a", "2"): (key("a"), 2, contributors(("a", "b"), ("a", "c"))),
    ("a", "1"): (key("a"), 1, contributors(("a", "c"))),
    ("b", "0"): (key("b"), 0, contributors()),
    ("c", "0"): (key("c"), 0, contributors()),
}


class OrderCheckMismatch(AssertionError):
    """The ordinary path did not reproduce an observation of the acceptance table."""


def source_of(directory: Path) -> Path:
    native = directory / "rezono/order.rezono"
    return native if native.is_file() else directory / "rules/order.dl"


def build(directory: Path, number: int):
    source = source_of(directory)
    return publisher_batch.epoch(directory, epoch=number, knowledge_time=TIME,
                                 sources=[("rules", digest(source.read_bytes()))])


def second_world(directory: Path) -> Path:
    """The same pack with only the hidden edge a -> b removed."""
    changed = directory.parent.parent / "second" / directory.parent.name
    shutil.copytree(directory.parent, changed)
    facts = changed / directory.name / "facts/base.yaml"
    text = facts.read_text(encoding="utf-8")
    assert text.count("precedes: [b, c]") == 1
    facts.write_text(text.replace("precedes: [b, c]", "precedes: [c]"), encoding="utf-8", newline="\n")
    return changed / directory.name


def incremental(first, second):
    """Epoch two on the incremental rule path: apply the base-row changes to epoch one's database."""
    prog = rules.load(json.loads(second.rules))
    base = {name for name, relation in prog.relations.items() if relation.role == "base"}
    before = {name: set(first.rows.get(name, ())) for name in base}
    after = {name: set(second.rows.get(name, ())) for name in base}
    changed = {name for name in base if before[name] != after[name]}
    assert changed == {"ordered__precedes"}
    with batch.connect(prog, {name: sorted(rows) for name, rows in before.items()}) as con:
        batch.compute(con, prog)
        for relation in sorted(changed):
            for row in sorted(before[relation] - after[relation]):
                batch.apply(con, prog, relation, row, "delete")
            for row in sorted(after[relation] - before[relation]):
                batch.apply(con, prog, relation, row, "insert")
        batch.compute(con, prog, relations=prog.downstream(changed))
        derived = batch.read(con, prog)
        bindings = batch.witnesses(con, prog)
    evaluator = explain.Explainer(prog, {**{n: sorted(r) for n, r in after.items()}, **derived}, bindings)
    witnesses = [evaluator.instance(prog.rules[name], dict(zip(prog.rules[name].variables, values)))
                 for name, instances in bindings.items() for values in instances]
    return replace(second, rows=second.rows | {name: sorted(rows) for name, rows in derived.items()},
                   witnesses=witnesses)


def artifact(bucket, entry):
    data = bucket.get(entry["uri"].split("/", 3)[3])
    assert data is not None and digest(data) == entry["sha256"]
    return json.loads(data)


def observe(bucket, manifest, expected):
    """Check one publication against the table; return the limited role's published digests."""
    assert {entry["status"] for entry in manifest["checks"]} == {"green"}
    for role in ("complete", "limited"):
        refs = {entry["relation"]: entry for entry in manifest["snapshots"] if entry["role"] == role}
        rows = {name: {tuple(row["key"]) for row in artifact(bucket, refs[name])} for name in DERIVED}
        if rows != expected[role]:
            raise OrderCheckMismatch(f"{role}: got {rows!r}, expected {expected[role]!r}")
        [witness_set] = [entry for entry in manifest["witnesses"] if entry["role"] == role]
        witnesses = artifact(bucket, witness_set)
        assert witnesses["hidden"] == []
        groups = {tuple(json.loads(w["conclusion"]["key"])): w["aggregates"] for w in witnesses["witnesses"]
                  if w["conclusion"]["relation"] == "successors"}
        assert set(groups) == expected[role]["successors"]
        for conclusion, aggregates in groups.items():
            [group] = aggregates
            fixed, count, members = GROUPS[conclusion]
            assert (group["relation"], group["group_key"], group["count"], group["contributors_sha256"],
                    group["result"]) == ("edge", fixed, count, members, f"known:{count}"), (conclusion, group)
    limited = {entry["relation"]: entry["sha256"] for entry in manifest["snapshots"] if entry["role"] == "limited"}
    [witness_set] = [entry for entry in manifest["witnesses"] if entry["role"] == "limited"]
    return limited, witness_set["sha256"]


def typed_successors(bucket, manifest):
    """Read the complete role's successors through the publication reader; select n > 1; mutate n."""
    prefix = f"order-check/{manifest['id']}/complete/publication/"
    index = json.loads(bucket.get(prefix + "index.json"))
    objects = {entry["name"]: entry for entry in index["objects"]}
    schema, document = artifact(bucket, objects["schema.json"]), artifact(bucket, objects["rows.json"])
    slots = schema["kinds"]["Successors"]["slots"]
    if (slots["x"].get("ref"), slots["n"].get("type")) != ("Stage", "Integer"):
        raise OrderCheckMismatch(f"successors is published as {slots!r}, not a Stage reference and an integer")
    read = l0.read_collection(schema, document)
    above = sorted(row["x"]["$ref"] if isinstance(row["x"], dict) else row["x"]
                   for row in read if row["$kind"] == "Successors" and int(row["n"]) > 1)
    assert above == ["a"]
    for altered_key in (False, True):
        rows = []
        for row in document["$rows"]:
            if row["$kind"] == "Successors" and row["$id"] == key("a", "2"):
                row = row | {"n": "zero"} | ({"$id": key("a", "zero")} if altered_key else {})
            rows.append(row)
        with pytest.raises(l0.L0Error):
            l0.read_collection(schema, document | {"$rows": rows})


def publish_both_epochs(tmp_path, directory):
    bucket = store.FileStore(tmp_path / f"{directory.parent.name}-batch")
    first = build(directory, 1)
    m1 = publish.publish(first, bucket, ROLES, forms=True)
    second = build(second_world(directory), 2)
    m2 = publish.publish(second, bucket, ROLES, reuse=m1, forms=True)
    delta_bucket = store.FileStore(tmp_path / f"{directory.parent.name}-incremental")
    base = publish.publish(first, delta_bucket, ROLES, forms=True)
    m2_delta = publish.publish(incremental(first, second), delta_bucket, ROLES, reuse=base, forms=True)
    assert m2_delta == m2
    return bucket, m1, m2


@pytest.mark.xfail(
    strict=True,
    raises=OrderCheckMismatch,
    reason="extra: Make the native order-check pack publish the §5 observations on the ordinary path. Read "
           "decisions/language-expression-semantics.md §5. Waits for test_expression_python_branch_bindings, "
           "test_expression_python_scalar_negation and test_order_check_ordinary_filtered_count for lowering.",
)
def test_order_check_publication(tmp_path):
    # The independently authored legacy representation shows the same rows, groups and role views.
    legacy = order_check_pack(tmp_path, "legacy")
    bucket, m1, m2 = publish_both_epochs(tmp_path, legacy)
    legacy_views = (observe(bucket, m1, FIRST), observe(bucket, m2, SECOND))

    native = order_check_pack(tmp_path, "native")
    try:
        bucket, m1, m2 = publish_both_epochs(tmp_path, native)
    except pack.CompileError as error:
        raise OrderCheckMismatch(str(error)) from error
    first_view, second_view = observe(bucket, m1, FIRST), observe(bucket, m2, SECOND)
    # Removing the hidden edge changes nothing the limited role can read, in either representation.
    assert first_view == second_view and legacy_views[0] == legacy_views[1]
    typed_successors(bucket, m1)


@pytest.mark.xfail(
    strict=True,
    raises=OrderCheckMismatch,
    reason="M3: Lower successors(x, n) when x in Stage and n = (edge(_, _) where it.pred = x).count() through "
           "compiler/rezono_compiler/native_rule_lowering.py into native_rule_groups: one count aggregate over "
           "edge with terms [?x, _], as the legacy rule. Read decisions/language-expression-semantics.md §1 "
           "and §5. Waits for test_expression_python_filtered_count and test_expression_python_path_bindings.",
)
def test_order_check_ordinary_filtered_count(tmp_path):
    def counted(directory):
        program = json.loads(pack_files(directory)["ir/rules.json"])
        [rule] = [rule for rule in program["rules"] if rule["head"]["relation"] == "successors"]
        body = [(item["polarity"], item["relation"], item["terms"]) for item in rule["body"]]
        groups = [(item["relation"], item["terms"], item["function"], item["as"]) for item in rule["aggregates"]]
        return rule["head"]["terms"], body, groups, rule.get("conditions", [])

    expected = (["?x", "?n"], [("positive", "stage", ["?x"])], [("edge", ["?x", "_"], "count", "?n")], [])
    assert counted(order_check_pack(tmp_path, "legacy")) == expected
    try:
        native = counted(order_check_pack(tmp_path, "native"))
    except pack.CompileError as error:
        raise OrderCheckMismatch(str(error)) from error
    if native != expected:
        raise OrderCheckMismatch(f"got {native!r}, expected {expected!r}")


def pack_files(directory):
    from rezono_compiler import emit

    return emit.compile_pack(pack.read(directory))


def column_of(path: Path, line: int, text: str) -> int:
    return path.read_text(encoding="utf-8").splitlines()[line - 1].index(text) + 1


def test_order_check_rejects_partial_negation(tmp_path):
    directory = order_check_pack(tmp_path, "rejected")
    source = directory / "rezono/order.rezono"
    schema = ROOT / "packs/std-order/schema/order.yaml"
    [rank_line] = [number for number, line in enumerate(schema.read_text(encoding="utf-8").splitlines(), 1)
                   if line == "      rank:"]
    expected_related = [
        {"file": "rezono/order.rezono", "line": "6", "column": str(column_of(source, 6, "x.rank = 0"))},
        {"file": "std-order:schema/order.yaml", "line": str(rank_line), "column": "7"},
    ]
    with pytest.raises(pack.CompileError) as refused:
        pack_files(directory)
    found = [(item.code, item.where, item.span, item.doc().get("related", []))
             for item in refused.value.diagnostics]
    want = ("R047", "rezono/order.rezono#/decls/2/when/and/1",
            ("rezono/order.rezono", 7, column_of(source, 7, "not zero(x)")))
    matches = [entry for entry in found if entry[:3] == want]
    if not matches or not all(place in matches[0][3] for place in expected_related):
        raise OrderCheckMismatch(f"got {found!r}, expected {want!r} with related {expected_related!r}")
    # The accepted revision is a separate invocation and is not refused for R047.
    accepted = order_check_pack(tmp_path, "native")
    try:
        pack_files(accepted)
    except pack.CompileError as error:
        assert all(item.code != "R047" for item in error.diagnostics)
