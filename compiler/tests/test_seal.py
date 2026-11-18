"""The seal (docs/compiler.md#design-m3-the-seal) on the neutral fixture pack: the shape checks,
the rule check, the row hash, the close command, and refused and accepted input equal in SQL, in the
batch rows and in the definition written out."""

import datetime
import json
import shutil
from pathlib import Path

import duckdb
import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st
from rezono_canon import canonical_sha256

from support import FIXTURE, run_split, violations
from rezono_compiler import batch, emit, facts, pack, scenarios, seal
from rezono_compiler import rules as ir

DAY = datetime.date(2026, 10, 1)
OTHER = "0" * 64  # a hash no row has: the row was edited after the close
RULES = """
.decl counted(a: symbol, n: number)
counted(a, n) :- alpha__accepted(a), alpha__size(a, n).
.decl late(a: symbol, c: symbol)
late(a, c) :- alpha__refused(a, c).
"""


def sealed(d: Path, rules: str | None = RULES, note="period", close=True, cover=None) -> Path:
    """The fixture with Alpha sealed on `period`, PeriodClose and its cover kind ClosedAlpha."""
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    alpha = schema["classes"]["Alpha"]
    alpha["attributes"]["period"] = {"range": "date", "required": True}
    alpha["annotations"] = {"seal": note}
    if close:
        schema["classes"]["PeriodClose"] = {"attributes": {
            "id": {"identifier": True},
            "closed_until": {"range": "date", "required": True},
            "covers": {"range": "ClosedAlpha", "multivalued": True, "inlined_as_list": True}}}
        schema["classes"]["ClosedAlpha"] = {"attributes": cover or {
            "element": {"range": "Alpha", "required": True}, "sha256": {"required": True}}}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    if rules is not None:
        (d / "rules").mkdir(exist_ok=True)
        (d / "rules" / "r.dl").write_text(rules)
    return d


def copy(tmp: Path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp / "pack"))


@pytest.fixture
def fixture(tmp_path) -> Path:
    return sealed(copy(tmp_path))


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    model = pack.read(sealed(copy(tmp_path_factory.mktemp("seal"))))
    return model, emit.compile_pack(model)


def day(n: int) -> datetime.date:
    return DAY + datetime.timedelta(days=n)


def alphas(periods) -> list[dict]:
    return [{"id": f"a{i}", "title": "t", "size": i % 10, "period": day(p)} for i, p in enumerate(periods)]


def fact_rows(model, periods, closes):
    """closes: [(until, [(alpha index, the current hash or not)])]."""
    hashes = dict(facts.rows_of(model, {"alpha": alphas(periods)})["alpha__row_sha256"])
    return facts.rows_of(model, {"alpha": alphas(periods), "period_close": [
        {"id": f"c{j}", "closed_until": day(u),
         "covers": [{"element": f"a{i}", "sha256": hashes[f"a{i}"] if same else OTHER} for i, same in cover]}
        for j, (u, cover) in enumerate(closes)]})


def definition(periods, closes) -> set[tuple]:
    """Refused, written out: a close applies to a row when it closes the row's period or covers the row, and it
    refuses the row unless it covers the row with its current hash."""
    applies = {(i, j) for j, (u, cover) in enumerate(closes) for i, p in enumerate(periods)
               if p < u or any(c == i for c, _ in cover)}
    held = {(i, j) for j, (_, cover) in enumerate(closes) for i, same in cover if same}
    return {(f"a{i}", f"c{j}") for i, j in applies - held}


def sql_rows(files, rows) -> dict[str, set[tuple]]:
    db = duckdb.connect()
    db.execute(emit.DUCKDB_FUNCTIONS)
    db.execute(files["engine/tables.sql"])
    db.execute(emit.duckdb(files["engine/integrity.sql"]))
    for table, rs in rows.items():
        if rs:
            db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
    return {n: set(db.execute(f"SELECT * FROM {emit.q(n)}").fetchall()) for n in ("alpha__refused", "alpha__accepted")}


def test_the_row_hash_is_the_canonical_json_of_the_row(fixture):
    model = pack.read(fixture)
    rows = facts.rows_of(model, {"alpha": [{"id": "a1", "title": "t", "period": DAY}]})
    want = canonical_sha256({"alpha__period": ["2026-10-01"], "alpha__title": ["t"]})  # no size: left out
    assert rows["alpha__row_sha256"] == [("a1", want)]


def test_covered_late_edited_and_open_rows(fixture):
    model = pack.read(fixture)
    # Closed until day 31: a0 covered as it is, a1 never covered (late), a2 covered but edited since, a3 open.
    rows = fact_rows(model, [0, 5, 6, 31], [(31, [(0, True), (2, False)])])
    assert seal.rows(model, rows) == {"alpha__refused": [("a1", "c0"), ("a2", "c0")],
                                      "alpha__accepted": [("a0",), ("a3",)]}
    prog = ir.load(model.rules)
    con = batch.connect(prog, scenarios.rule_rows(model, prog, rows))
    batch.compute(con, prog)
    got = batch.read(con, prog)
    assert got["counted"] == {("a0", "0"), ("a3", "3")}
    assert got["late"] == {("a1", "c0"), ("a2", "c0")}


@given(periods=st.lists(st.integers(0, 9), max_size=6),
       closes=st.lists(st.tuples(st.integers(0, 9), st.lists(st.tuples(st.integers(0, 5), st.booleans()), max_size=4)),
                       max_size=3))
def test_sql_batch_and_definition_agree(compiled, periods, closes):
    model, files = compiled
    closes = [(u, [(i, same) for i, same in cover if i < len(periods)]) for u, cover in closes]
    rows = fact_rows(model, periods, closes)
    want = {n: set(rs) for n, rs in seal.rows(model, rows).items()}
    assert sql_rows(files, rows) == want
    late = definition(periods, closes)
    assert want["alpha__refused"] == late
    assert want["alpha__accepted"] == {(f"a{i}",) for i in range(len(periods))} - {(a,) for a, _ in late}


def both(compiled, rows) -> dict[str, set[tuple]]:
    """Refused and accepted in SQL, after holding them equal to the batch rows."""
    model, files = compiled
    got = sql_rows(files, rows)
    assert got == {n: set(rs) for n, rs in seal.rows(model, rows).items()}
    return got


def test_a_covered_row_moved_to_an_open_period_stays_refused(compiled):
    # Review P1: a0 was covered in October, then moved past the boundary and edited. No close closes its new
    # period, but the close that covers it holds another hash.
    rows = fact_rows(compiled[0], [40], [(31, [(0, False)])])
    assert both(compiled, rows) == {"alpha__refused": {("a0", "c0")}, "alpha__accepted": set()}


def test_a_later_close_does_not_lift_an_earlier_refusal(compiled):
    # Review P1: c1 covers the edited a0 (and the late a1) with their current hashes; c0 still refuses both.
    rows = fact_rows(compiled[0], [0, 0], [(31, [(0, False)]), (62, [(0, True), (1, True)])])
    assert both(compiled, rows) == {"alpha__refused": {("a0", "c0"), ("a1", "c0")}, "alpha__accepted": set()}


# Above the budget: counted and kept read the accepted rows in different parts, late the
# refused rows. kept needs small, which needs counted, so the three never fit in one part of 4 views.
SPLIT_RULES = RULES + """
.decl small(a: symbol)
small(a) :- counted(a, n), n < 3.
.decl kept(a: symbol)
kept(a) :- alpha__accepted(a), !small(a).
"""


@pytest.fixture(scope="module")
def split(tmp_path_factory):
    model = pack.read(sealed(copy(tmp_path_factory.mktemp("split")), rules=SPLIT_RULES))
    return model, emit.compile_pack(model, max_views=4)


def test_a_split_program_reads_the_seal_from_integrity(split):
    """integrity computes refused and accepted once and forwards them; no part reads them as facts."""
    model, files = split
    plan = json.loads(files["engine/pipelines.json"])
    integrity, parts = plan["pipelines"][0], plan["pipelines"][1:]
    assert integrity["name"] == "integrity" and len(parts) >= 2
    assert integrity["exports"] == ["alpha__accepted", "alpha__refused"]
    assert integrity["sql"] == ["engine/tables.sql", "engine/integrity.sql", "engine/integrity-export.sql"]
    assert '"export__out"' in files["engine/integrity-export.sql"] and '"epoch__in"' in files["engine/integrity-export.sql"]
    readers = sorted(p["name"] for p in parts if "alpha__accepted" in p["imports"])
    assert len(readers) == 2
    forward = {f["relation"]: f for f in plan["forward"]}
    assert forward["alpha__accepted"] == {"relation": "alpha__accepted", "producer": "integrity", "consumers": readers}
    assert forward["alpha__refused"]["producer"] == "integrity"
    for p in parts:
        assert not {"alpha__accepted", "alpha__refused"} & set(p["tables"])   # never sent as facts
        for r in {"alpha__accepted", "alpha__refused"} & set(p["imports"]):
            assert f'CREATE TABLE "{r}"' in files[p["sql"][0]]                  # an input table there
    assert json.loads(emit.compile_pack(model)["engine/pipelines.json"])["pipelines"][0]["name"] == "main"


@settings(max_examples=min(settings().max_examples, 60))
@given(periods=st.lists(st.integers(0, 9), max_size=6),
       closes=st.lists(st.tuples(st.integers(0, 9), st.lists(st.tuples(st.integers(0, 5), st.booleans()), max_size=4)),
                       max_size=3))
def test_the_split_program_gives_what_one_pipeline_gives(split, periods, closes):
    """Pipeline by pipeline, the parts read the accepted rows integrity exports: the same relations as the
    unsplit program on the batch backend, and as the seal written out."""
    model, files = split
    closes = [(u, [(i, same) for i, same in cover if i < len(periods)]) for u, cover in closes]
    rows = fact_rows(model, periods, closes)
    got, forwarded = run_split(model, files, rows)
    prog = ir.load(model.rules)
    con = batch.connect(prog, scenarios.rule_rows(model, prog, rows))
    batch.compute(con, prog)
    assert got == batch.read(con, prog)
    late = definition(periods, closes)
    accepted = {f"a{i}" for i in range(len(periods))} - {a for a, _ in late}
    assert set(forwarded.get("alpha__refused", [])) == late
    assert set(forwarded.get("alpha__accepted", [])) == {(a,) for a in accepted}
    assert got["late"] == late
    assert got["kept"] == {(a,) for a in accepted if int(a[1:]) % 10 >= 3}   # size i % 10, small below 3


def test_a_subkind_is_part_of_the_row(tmp_path):
    # Review P1: a covered element that becomes a member of a subkind (no attributes of its own) is another row.
    d = sealed(copy(tmp_path), rules=None)
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["AlphaPlus"] = {"is_a": "Alpha"}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    model = pack.read(d)
    sub = next(k for k in model.kinds if k != "alpha" and model.root(k) == "alpha")
    assert sub in model.seals[0].tables
    h = dict(facts.rows_of(model, {"alpha": alphas([0])})["alpha__row_sha256"])["a0"]
    close = {"period_close": [{"id": "c0", "closed_until": day(31), "covers": [{"element": "a0", "sha256": h}]}]}
    assert seal.rows(model, facts.rows_of(model, {"alpha": alphas([0])} | close))["alpha__refused"] == []
    joined = facts.rows_of(model, {sub: alphas([0])} | close)
    assert joined["alpha__row_sha256"] != [("a0", h)]
    assert seal.rows(model, joined)["alpha__refused"] == [("a0", "c0")]


def test_a_calculation_cannot_take_a_sealed_kind_as_input(tmp_path):
    # Review P1: the inputs of a calculation would read refused rows; until it reads accepted input, refused.
    d = Path(shutil.copytree(FIXTURE.parent / "calc", tmp_path / "calc"))
    path = d / "schema" / "calc.yaml"
    schema = yaml.safe_load(path.read_text())
    entry = schema["classes"]["Entry"]
    entry["attributes"]["period"] = {"range": "date", "required": True}
    entry["annotations"] = {"seal": "period"}
    schema["classes"]["PeriodClose"] = {"attributes": {
        "id": {"identifier": True}, "closed_until": {"range": "date", "required": True},
        "covers": {"range": "ClosedEntry", "multivalued": True, "inlined_as_list": True}}}
    schema["classes"]["ClosedEntry"] = {"attributes": {
        "element": {"range": "Entry", "required": True}, "sha256": {"required": True}}}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    (d / "rules" / "entries.dl").write_text(
        ".decl ok_entry(e: symbol, i: symbol)\nok_entry(e, i) :- entry__accepted(e), entry__item(e, i).\n"
        ".decl entry_total(item: symbol, total: number)\nentry_total(i, t) :- item(i), t = count : { ok_entry(_, i) }.\n"
        ".decl has_entry(item: symbol)\nhas_entry(i) :- ok_entry(_, i).\n")
    refused(d, "inputs.kind 'entry' is a sealed kind")


def test_a_calculation_cannot_take_its_parameters_from_a_sealed_kind(tmp_path):
    # Audit 07-11: a refused row of the parameter kind would set a parameter; refused like the inputs.
    d = Path(shutil.copytree(FIXTURE.parent / "calc", tmp_path / "calc"))
    path = d / "schema" / "calc.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["Setting"]["attributes"]["period"] = {"range": "date", "required": True}
    schema["classes"]["Setting"]["annotations"] = {"seal": "period"}
    schema["classes"]["PeriodClose"] = {"attributes": {
        "id": {"identifier": True}, "closed_until": {"range": "date", "required": True},
        "covers": {"range": "ClosedSetting", "multivalued": True, "inlined_as_list": True}}}
    schema["classes"]["ClosedSetting"] = {"attributes": {
        "element": {"range": "Setting", "required": True}, "sha256": {"required": True}}}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    refused(d, "parameters: kind 'setting' is a sealed kind")


def test_the_close_command_covers_what_is_accepted(fixture):
    model = pack.read(fixture)
    rows = fact_rows(model, [0, 5, 31], [(3, [(0, True)])])  # c0 closes a0; a1 is open, a2 too
    delta = seal.close(model, rows, "c1", day(31), "facts/closes.yaml")
    hashes = dict(rows["alpha__row_sha256"])
    assert delta["changes"] == [{"op": "insert", "file": "facts/closes.yaml", "kind": "period_close", "key": "c1",
                                 "values": {"closed_until": "2026-11-01", "covers": [
                                     {"element": "a0", "sha256": hashes["a0"]}, {"element": "a1", "sha256": hashes["a1"]}]}}]
    late = fact_rows(model, [0, 0], [(3, [])])  # rows of a closed period that c0 does not cover: refused, never covered
    assert [c["element"] for c in seal.close(model, late, "c1", day(31), "facts/x.yaml")["changes"][0]["values"]["covers"]] == []


def test_a_covered_row_that_is_gone_is_a_violation(fixture):
    model = pack.read(fixture)
    rows = fact_rows(model, [0], [(31, [(0, True)])])
    rows = {t: [r for r in rs if r[0] != "a0"] if t.startswith("alpha") else rs for t, rs in rows.items()}
    assert "closed_alpha__element__reference" in violations(emit.compile_pack(model), rows)


def test_the_relations_are_base_relations_of_the_rules(fixture):
    model = pack.read(fixture)
    rels = {r["name"]: r for r in model.rules["relations"]}
    assert rels["alpha__accepted"]["role"] == "base"
    assert [c["name"] for c in rels["alpha__refused"]["key"] + rels["alpha__refused"].get("values", [])] == ["id", "period_close"]
    files = emit.compile_pack(model)
    assert 'CREATE MATERIALIZED VIEW "alpha__refused"' in files["engine/integrity.sql"]
    assert 'CREATE TABLE "alpha__row_sha256"' in files["engine/tables.sql"]


def test_a_pack_without_rules_carries_its_seal_in_the_rule_ir(tmp_path):
    # Review P1: without rules the publisher fell back to an empty rule IR, and the checker saw no seal.
    files = emit.compile_pack(pack.read(sealed(copy(tmp_path), rules=None)))
    doc = json.loads(files["ir/rules.json"])
    assert doc["rules"] == [] and [s["kind"] for s in doc["seals"]] == ["alpha"]
    assert "engine/rules.sql" not in files


def refused(d: Path, message: str) -> None:
    with pytest.raises(pack.CompileError, match=message):
        pack.read(d)


@pytest.mark.parametrize("rules, where", [
    (".decl s(a: symbol, n: number)\ns(a, n) :- alpha__size(a, n).\n", "reads alpha__size"),
    (".decl s(a: symbol)\ns(a) :- alpha(a).\n", "reads alpha of"),
    (".decl s(b: symbol, n: number)\ns(b, n) :- beta(b), n = count : { alpha(_) }.\n", "reads alpha of"),
    (".decl s(a: symbol)\ns(a) :- alpha__accepted(a), beta__alpha(b, a), !alpha__size(b, 1).\n", "reads alpha__size"),
])
def test_a_rule_that_reads_a_sealed_kind_without_accepted_is_refused(tmp_path, rules, where):
    refused(sealed(copy(tmp_path), rules=rules), f"{where}.*without alpha__accepted")


ACCESS_RULE = '.decl may_read(role: symbol, kind: symbol, element: symbol)\nmay_read("guest", "alpha", x) :- alpha(x).\n'


def test_a_read_rule_sees_refused_rows_but_nothing_counts_them(tmp_path):
    # A read rule (std-access) gives the sealed kind whole: a refused row stays visible to who may read it.
    pack.read(sealed(copy(tmp_path / "a"), rules=ACCESS_RULE))
    # Any other rule that reads the access relation would count refused rows: refused.
    counting = ACCESS_RULE + '.decl s(b: symbol, n: number)\ns(b, n) :- beta(b), n = count : { may_read(_, "alpha", _) }.\n'
    refused(sealed(copy(tmp_path / "b"), rules=counting), "reads may_read, which holds refused rows")
    # A right is no read: a late or edited row may not grant one, so may_propose reads accepted rows (review).
    right = '.decl may_propose(role: symbol, kind: symbol, element: symbol)\nmay_propose("guest", "alpha", x) :- alpha(x).\n'
    refused(sealed(copy(tmp_path / "c"), rules=right), "reads alpha of the sealed kind alpha without alpha__accepted")


@pytest.mark.parametrize("change, message", [
    ({"note": "title"}, "names the period: one required, single date slot"),
    ({"note": "nope"}, "names the period"),
    ({"close": False}, "a seal needs the kind PeriodClose"),
    ({"cover": {"element": {"range": "Alpha", "required": True}}}, "a cover has exactly the required arrow element"),
    ({"cover": {"element": {"range": "Beta", "required": True}, "sha256": {"required": True}}},
     "a cover has exactly the required arrow element to Alpha"),
])
def test_a_wrong_seal_is_refused(tmp_path, change, message):
    refused(sealed(copy(tmp_path), rules=None, **change), message)


def test_a_generated_name_that_clashes_is_refused(fixture):
    path = fixture / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["Alpha"]["attributes"]["accepted"] = {"range": "integer"}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    (fixture / "rules" / "r.dl").unlink()
    with pytest.raises(pack.CompileError, match="alpha__accepted"):
        emit.compile_pack(pack.read(fixture))


# Parts (`sealed_with`, docs/compiler.md#parts): Beta is part of Alpha through its arrow `alpha`, Gamma part of
# Beta through `beta`. Their rows belong to the row of the Alpha they reach, and they count only when it does.
PART_RULES = RULES + """
.decl staged(b: symbol, s: symbol)
staged(b, s) :- beta__accepted(b), beta__state(b, s).
.decl noted(g: symbol, n: symbol)
noted(g, n) :- gamma__accepted(g), gamma__note(g, n).
"""


def with_parts(d: Path, rules: str | None = PART_RULES, beta: str | None = "alpha", gamma="beta") -> Path:
    sealed(d, rules=rules)
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    if beta is not None:
        schema["classes"]["Beta"]["annotations"] = {"sealed_with": beta}
    schema["classes"]["Gamma"] = {"annotations": {"sealed_with": gamma}, "attributes": {
        "id": {"identifier": True}, "beta": {"range": "Beta", "required": True}, "note": {}}}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    return d


@pytest.fixture(scope="module")
def parted(tmp_path_factory):
    model = pack.read(with_parts(copy(tmp_path_factory.mktemp("parts"))))
    return model, emit.compile_pack(model)


def records(periods, betas, gammas) -> dict:
    """betas: [(alpha index, state)]; gammas: [(beta index, note)]."""
    return {"alpha": alphas(periods),
            "beta": [{"id": f"b{j}", "alpha": f"a{i}", "state": s} for j, (i, s) in enumerate(betas)],
            "gamma": [{"id": f"g{k}", "beta": f"b{j}", "note": n} for k, (j, n) in enumerate(gammas)]}


def closed(model, now: dict, then: dict, until: int, covered) -> dict:
    """The rows of `now` with one close until day `until`, covering the alphas `covered` with their hash in
    the facts `then` (the state when the close was made)."""
    hashes = dict(facts.rows_of(model, then)["alpha__row_sha256"])
    return facts.rows_of(model, now | {"period_close": [{"id": "c0", "closed_until": day(until), "covers": [
        {"element": f"a{i}", "sha256": hashes[f"a{i}"]} for i in covered]}]})


def check_seal(model, rows) -> list:
    """What the independent checker finds, from the rows as snapshots give them (all text)."""
    from rezono_checker.check import _check_seal
    from rezono_checker.rules import load_seals

    [doc] = load_seals({"seals": json.loads(emit.compile_pack(model)["ir/rules.json"])["seals"]})
    findings = []
    _check_seal(doc, lambda rel, _: {n: (tuple(seal.text(v) for v in r), None) for n, r in enumerate(rows.get(rel, []))},
                findings)
    return [(f["reason"], f["relation"]) for f in findings]


def sql_rows_of(files, rows, names) -> dict[str, set[tuple]]:
    db = duckdb.connect()
    db.execute(emit.DUCKDB_FUNCTIONS)
    db.execute(files["engine/tables.sql"])
    db.execute(emit.duckdb(files["engine/integrity.sql"]))
    for table, rs in rows.items():
        if rs:
            db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
    return {n: set(db.execute(f"SELECT * FROM {emit.q(n)}").fetchall()) for n in names}


def test_the_parts_belong_to_the_row(parted):
    model, _ = parted
    rows = facts.rows_of(model, records([0], [(0, "low")], [(0, "n")]))
    want = canonical_sha256({"alpha__period": ["2026-10-01"], "alpha__size": ["0"], "alpha__title": ["t"],
                             "beta__alpha": [["b0", "a0"]], "beta__state": [["b0", "low"]],
                             "gamma__beta": [["g0", "b0"]], "gamma__note": [["g0", "n"]]})
    assert rows["alpha__row_sha256"] == [("a0", want)]
    assert [p.kind for p in model.seals[0].parts] == ["beta", "gamma"]  # an owner before its parts


def test_an_edited_added_or_moved_part_refuses_its_element(parted):
    model, files = parted
    then = records([0, 0, 0, 40], [(0, "low"), (1, "low"), (2, "low"), (3, "low")], [(0, "n"), (3, "n")])
    # a0: a part of a part edited, and b2 moved in from a2; a1: a part added (b4); a3: open, its parts count.
    now = records([0, 0, 0, 40], [(0, "low"), (1, "low"), (0, "low"), (3, "low"), (1, "high")], [(0, "m"), (3, "n")])
    rows = closed(model, now, then, 31, [0, 1, 2])
    got = seal.rows(model, rows)
    assert got["alpha__refused"] == [("a0", "c0"), ("a1", "c0"), ("a2", "c0")]
    assert got["alpha__accepted"] == [("a3",)]
    assert got["beta__accepted"] == [("b3",)] and got["gamma__accepted"] == [("g1",)]
    assert sql_rows_of(files, rows, got) == {n: set(rs) for n, rs in got.items()}
    prog = ir.load(model.rules)
    con = batch.connect(prog, scenarios.rule_rows(model, prog, rows))
    batch.compute(con, prog)
    out = batch.read(con, prog)
    assert out["staged"] == {("b3", "low")} and out["noted"] == {("g1", "n")}
    assert check_seal(model, rows | got) == []
    # Unchanged since the close, everything counts.
    rows = closed(model, then, then, 31, [0, 1, 2])
    assert seal.rows(model, rows)["alpha__refused"] == []


@settings(max_examples=min(settings().max_examples, 60))
@given(periods=st.lists(st.integers(0, 9), min_size=1, max_size=4),
       betas=st.lists(st.tuples(st.integers(0, 3), st.sampled_from(["low", "high"])), max_size=5),
       gammas=st.lists(st.tuples(st.integers(0, 4), st.sampled_from(["n", "m"])), max_size=4),
       edits=st.lists(st.tuples(st.integers(0, 4), st.sampled_from(["low", "high"])), max_size=2),
       until=st.integers(0, 10), covered=st.lists(st.integers(0, 3), max_size=4))
def test_parts_sql_batch_and_checker_agree(parted, periods, betas, gammas, edits, until, covered):
    model, files = parted
    betas = [(i % len(periods), s) for i, s in betas]
    gammas = [(j, n) for j, n in gammas if j < len(betas)]
    then = records(periods, betas, gammas)
    now_betas = list(betas)
    for j, s in edits:
        if j < len(now_betas):
            now_betas[j] = (now_betas[j][0], s)
    rows = closed(model, records(periods, now_betas, gammas), then, until, sorted({i for i in covered if i < len(periods)}))
    got = seal.rows(model, rows)
    assert sql_rows_of(files, rows, got) == {n: set(rs) for n, rs in got.items()}
    assert check_seal(model, rows | got) == []
    accepted = {a for (a,) in got["alpha__accepted"]}
    assert {b for (b,) in got["beta__accepted"]} == {f"b{j}" for j, (i, _) in enumerate(now_betas) if f"a{i}" in accepted}


def test_a_forged_part_acceptance_is_found(parted):
    model, _ = parted
    rows = closed(model, records([0], [(0, "high")], []), records([0], [(0, "low")], []), 31, [0])  # b0 edited
    got = seal.rows(model, rows)
    assert got["beta__accepted"] == []
    assert check_seal(model, rows | got | {"beta__accepted": [("b0",)]}) == [("seal_mismatch", "beta__accepted")]


@pytest.mark.parametrize("rules, where", [
    (".decl s(b: symbol, x: symbol)\ns(b, x) :- beta__state(b, x).\n", "reads beta__state of the part beta without beta__accepted"),
    (".decl s(g: symbol)\ns(g) :- beta__accepted(b), gamma__beta(g, b).\n", "reads gamma__beta of the part gamma without gamma__accepted"),
])
def test_a_rule_that_reads_a_part_without_accepted_is_refused(tmp_path, rules, where):
    refused(with_parts(copy(tmp_path), rules=rules), where)


@pytest.mark.parametrize("change, message", [
    ({"beta": "state"}, "sealed_with names the element it is part of: one required, single arrow"),
    ({"beta": "nope"}, "sealed_with names the element it is part of"),
    ({"beta": None}, "sealed_with points to beta, which is neither the sealed kind alpha nor a part"),
])
def test_a_wrong_part_is_refused(tmp_path, change, message):
    refused(with_parts(copy(tmp_path), rules=None, **change), message)


def test_a_part_without_a_seal_is_refused(tmp_path):
    d = copy(tmp_path)
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["Beta"]["annotations"] = {"sealed_with": "alpha"}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    refused(d, "sealed_with, but the pack seals no kind")


def test_a_part_on_a_subkind_is_refused(tmp_path):
    # A subkind shares the tables of its root kind, so the root kind is the part; the subkind cannot be one alone.
    d = with_parts(copy(tmp_path), rules=None)
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["BetaPlus"] = {"is_a": "Beta", "annotations": {"sealed_with": "alpha"}}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    refused(d, "class BetaPlus: sealed_with goes on the root kind, not on a subkind of beta")


def test_the_parts_are_in_the_rule_ir_and_the_engine(parted):
    model, files = parted
    [doc] = json.loads(files["ir/rules.json"])["seals"]
    assert [(p["kind"], p["arrow"], p["owner"], p["accepted"]) for p in doc["parts"]] == [
        ("beta", "beta__alpha", "alpha", "beta__accepted"), ("gamma", "gamma__beta", "beta", "gamma__accepted")]
    assert 'CREATE MATERIALIZED VIEW "gamma__accepted"' in files["engine/integrity.sql"]
    rels = {r["name"]: r for r in model.rules["relations"]}
    assert rels["beta__accepted"]["role"] == "base"


def test_a_cycle_of_parts_or_two_wholes_is_refused(tmp_path):
    # A cycle: Beta part of Gamma, Gamma part of Beta; neither reaches the sealed Alpha.
    d = with_parts(copy(tmp_path / "cycle"), rules=None, beta="gamma")
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["Beta"]["attributes"]["gamma"] = {"range": "Gamma", "required": True}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    refused(d, "sealed_with points to gamma, which is neither the sealed kind alpha nor a part of it: a cycle")
    # Two wholes: one annotation names one arrow; a list of two is refused.
    d = with_parts(copy(tmp_path / "two"), rules=None)
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["Gamma"]["annotations"] = {"sealed_with": ["beta", "beta"]}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    refused(d, "class Gamma: sealed_with names the element it is part of: one required, single arrow")


# Above the budget with parts: integrity forwards every part's accepted relation too.
SPLIT_PART_RULES = PART_RULES + """
.decl small(a: symbol)
small(a) :- counted(a, n), n < 3.
.decl kept(b: symbol)
kept(b) :- beta__accepted(b), beta__alpha(b, a), !small(a).
"""


@pytest.fixture(scope="module")
def split_parts(tmp_path_factory):
    model = pack.read(with_parts(copy(tmp_path_factory.mktemp("split-parts")), rules=SPLIT_PART_RULES))
    return model, emit.compile_pack(model, max_views=4)


def test_a_split_program_forwards_the_parts(split_parts):
    model, files = split_parts
    plan = json.loads(files["engine/pipelines.json"])
    assert plan["pipelines"][0]["name"] == "integrity" and len(plan["pipelines"]) >= 3
    assert {"alpha__accepted", "beta__accepted", "gamma__accepted"} <= set(plan["pipelines"][0]["exports"])
    for p in plan["pipelines"][1:]:
        assert not {"beta__accepted", "gamma__accepted"} & set(p["tables"])  # never sent as facts


@settings(max_examples=min(settings().max_examples, 40))
@given(periods=st.lists(st.integers(0, 9), min_size=1, max_size=4),
       betas=st.lists(st.tuples(st.integers(0, 3), st.sampled_from(["low", "high"])), max_size=5),
       gammas=st.lists(st.tuples(st.integers(0, 4), st.sampled_from(["n", "m"])), max_size=4),
       edits=st.lists(st.tuples(st.integers(0, 4), st.sampled_from(["low", "high"])), max_size=2),
       until=st.integers(0, 10), covered=st.lists(st.integers(0, 3), max_size=4))
def test_the_split_program_with_parts_gives_what_one_pipeline_gives(split_parts, periods, betas, gammas, edits, until,
                                                                    covered):
    model, files = split_parts
    betas = [(i % len(periods), s) for i, s in betas]
    gammas = [(j, n) for j, n in gammas if j < len(betas)]
    now_betas = list(betas)
    for j, s in edits:
        if j < len(now_betas):
            now_betas[j] = (now_betas[j][0], s)
    rows = closed(model, records(periods, now_betas, gammas), records(periods, betas, gammas), until,
                  sorted({i for i in covered if i < len(periods)}))
    got, forwarded = run_split(model, files, rows)
    prog = ir.load(model.rules)
    con = batch.connect(prog, scenarios.rule_rows(model, prog, rows))
    batch.compute(con, prog)
    assert got == batch.read(con, prog)
    want = seal.rows(model, rows)
    for rel, rs in forwarded.items():
        assert set(rs) == set(want[rel]), rel


def calc_with_a_part(tmp: Path, part: str, inputs: str | None = None) -> Path:
    """The calc fixture with a sealed kind Batch and `part` (a class of the fixture) sealed with it."""
    d = Path(shutil.copytree(FIXTURE.parent / "calc", tmp / "calc"))
    path = d / "schema" / "calc.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["classes"]["Batch"] = {"annotations": {"seal": "period"}, "attributes": {
        "id": {"identifier": True}, "period": {"range": "date", "required": True}}}
    schema["classes"][part]["attributes"]["batch"] = {"range": "Batch", "required": True}
    schema["classes"][part]["annotations"] = {"sealed_with": "batch"}
    schema["classes"]["PeriodClose"] = {"attributes": {
        "id": {"identifier": True}, "closed_until": {"range": "date", "required": True},
        "covers": {"range": "ClosedBatch", "multivalued": True, "inlined_as_list": True}}}
    schema["classes"]["ClosedBatch"] = {"attributes": {
        "element": {"range": "Batch", "required": True}, "sha256": {"required": True}}}
    if inputs:
        schema["classes"]["SubEntry"] = {"is_a": "Entry"}
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    if inputs:
        for f in (d / "calc").glob("*.yaml"):
            f.write_text(f.read_text().replace("inputs: {kind: entry,", f"inputs: {{kind: {inputs},"))
    # The fixture's rules, reading accepted rows of the part as the rule check demands.
    rules = {"Item": ".decl entry_total(item: symbol, total: number)\n"
                     "entry_total(i, t) :- item__accepted(i), t = count : { entry__item(_, i) }.\n"
                     ".decl has_entry(item: symbol)\nhas_entry(i) :- entry__item(_, i).\n",
             "Entry": ".decl ok_entry(e: symbol, i: symbol)\nok_entry(e, i) :- entry__accepted(e), entry__item(e, i).\n"
                      ".decl entry_total(item: symbol, total: number)\n"
                      "entry_total(i, t) :- item(i), t = count : { ok_entry(_, i) }.\n"
                      ".decl has_entry(item: symbol)\nhas_entry(i) :- ok_entry(_, i).\n"}
    if part in rules:
        (d / "rules" / "entries.dl").write_text(rules[part])
    return d


@pytest.mark.parametrize("part, inputs, message", [
    ("Item", None, "subject 'item' is a sealed kind or a part of one"),
    ("Entry", "sub_entry", "inputs.kind 'sub_entry' is a sealed kind or a part of one"),  # a subkind of a part
    ("Setting", None, "parameters: kind 'setting' is a sealed kind or a part of one"),
])
def test_a_calculation_cannot_read_a_part_of_a_sealed_kind(tmp_path, part, inputs, message):
    # A part counts only when its element is accepted, so the calculation refusal covers it.
    refused(calc_with_a_part(tmp_path, part, inputs), message)
