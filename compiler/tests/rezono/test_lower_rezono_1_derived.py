"""`derived` written in `rezono 1` lowers to `rezono.rules/2`: single-key derived properties in `extend` as
functional relations `<k>_<d>` over their kind, module-level multi-key declarations as `Bool` sets or as functional
relations over their `over` domain, `.one()` and `.one(expr)`, method-form `.where(...)` and `.count(pred)`,
a relation read as its tuple set, and `means` with `@` on a derivation
(decisions/language-rezono-1.md sections 2, 4 and 8 step 4; decisions/language-rezono-1-refinements.md sections 1,
3.1 and 3.3; decisions/language-readable-rules.md section 2).

The module, the fact rows and every expected row below are written by hand from those decisions:
- a slot path gives `known` with the slot's value, `unknown no_value` for a missing required slot and
  `not_applicable no_value` for a missing optional one (language-rezono-1.md section 2);
- `S.one()` and `S.one(expr)` give `known` for one distinct value, `invalid multiple_values` for more than one, and
  `no_match` for none: `unknown` when the declared type is `T`, `not_applicable` when it is `T?`; a row whose
  membership is undecided makes the result undecided (refinements section 3.3, strict in row membership);
- `S.count(pred)` counts the rows where `pred` is true, gives `known 0` for none, and is undecided when `pred` is
  undecided for a row, here `unknown no_value` from a missing required slot (refinements section 3.1);
- a `Bool` derivation stays a plain set without state columns, and every functional derivation has exactly one row
  per key of its closed domain (language-rezono-1.md sections 2 and 4);
- a functional derivation over an open domain is refused with `functional_open_domain` (section 2 and 5.4);
- `means` lowers to the message of the clause in the default language and `@` to the `source` of the bundle's rule
  entry, so the witness of a conclusion reaches its article (language-readable-rules.md section 2).
DuckDB runs the compiled pack; Soufflé, where installed, runs the same rule IR as the independent oracle."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from linkml_runtime.linkml_model.meta import SchemaDefinition
from linkml_runtime.loaders import yaml_loader
import pytest

import souffle
from expression_packs import ROOT, register
from rezono_compiler import batch, emit, pack, rules, rules_sql, scenarios
from support import FIXTURE

MODULE = """\
rezono 1
pack minimal

kind Area
kind Item
  area: Area
  parent: Item?
kind Link
  src: Item
  dst: Item
kind Choice
  owner: Item
  area: Area
  target: Item

extend s: Item
  derived home: Area = s.area
  derived up: Item? = s.parent
  derived chooses: Int = Choice.count(owner = s)
  derived out_links: Int = Link.count(src = s)

extend l: Link
  derived goal: Item = l.dst

extend g: Area
  derived askers: Int = asks.count(r = g)

derived asks(a: Item, r: Area): Bool = a.area = r

derived chosen(a: Item, r: Area): Item?
  over asks(a, r)
  = Choice.where(owner = a and area = r).one(target)
  means "{$a} chose a target in {$r}." @ policy#art-3

derived peer(a: Item, r: Area): Item
  over asks(a, r)
  = Item.where(area = r and it != a).one()
"""
SENTENCE = "{$a} chose a target in {$r}."
SOURCE = "policy#art-3"

FACTS = """\
area:
  - {id: north}
  - {id: south}
  - {id: east}
  - {id: west}
item:
  - {id: ann, area: north, parent: bob}
  - {id: bob, area: north}
  - {id: cid, area: south}
  - {id: dan, area: east}
  - {id: eve, area: east}
link:
  - {id: l1, src: ann, dst: bob}
  - {id: l2, src: bob, dst: cid}
  - {id: l3, src: ann}
  - {id: l4, dst: bob}
choice:
  - {id: c1, owner: ann, area: north, target: bob}
  - {id: c2, owner: cid, area: south, target: ann}
  - {id: c3, owner: cid, area: south, target: bob}
  - {id: c4, owner: bob, area: south, target: cid}
  - {id: c5, owner: dan, target: ann}
"""
FACT_SOURCE = ('default: {kind: git, name: rezono-lang/rezono, revision: "0000000", '
               'position: compiler/tests/rezono/test_lower_rezono_1_derived.py#FACTS}\n')

# Single-key derived properties: relation `<k>_<d>`, its kind as domain, and the value type of the declaration.
PROPERTIES = {
    "item_home": ("item", "string"),
    "item_up": ("item", "string"),
    "item_chooses": ("item", "integer"),
    "item_out_links": ("item", "integer"),
    "link_goal": ("link", "string"),
    "area_askers": ("area", "integer"),
}
# Module-level functional derivations: their `over` domain and value type.
MULTI_KEY = {"chosen": ("asks", "string"), "peer": ("asks", "string")}

# (key..., state, reason) per row; the value of a known row follows in KNOWN.
EXPECTED = {
    # s.area: every item has its required area.
    "item_home": {("ann", "known", ""), ("bob", "known", ""), ("cid", "known", ""), ("dan", "known", ""),
                  ("eve", "known", "")},
    # s.parent is optional: absent -> not_applicable no_value.
    "item_up": {("ann", "known", ""), ("bob", "not_applicable", "no_value"), ("cid", "not_applicable", "no_value"),
                ("dan", "not_applicable", "no_value"), ("eve", "not_applicable", "no_value")},
    # Choice.count(owner = s): every choice has its owner; no choice -> known 0.
    "item_chooses": {("ann", "known", ""), ("bob", "known", ""), ("cid", "known", ""), ("dan", "known", ""),
                     ("eve", "known", "")},
    # Link.count(src = s): l4 has no src, so `src = s` is unknown for every s and every count is undecided.
    "item_out_links": {("ann", "unknown", "no_value"), ("bob", "unknown", "no_value"), ("cid", "unknown", "no_value"),
                       ("dan", "unknown", "no_value"), ("eve", "unknown", "no_value")},
    # l.dst is required: l3 has none -> unknown no_value.
    "link_goal": {("l1", "known", ""), ("l2", "known", ""), ("l3", "unknown", "no_value"), ("l4", "known", "")},
    # asks.count(r = g): the tuples of asks per area; west has none -> known 0.
    "area_askers": {("north", "known", ""), ("south", "known", ""), ("east", "known", ""), ("west", "known", "")},
    # Choice.where(owner = a and area = r).one(target) over asks, declared Item?:
    # one choice -> known; none -> not_applicable no_match; two targets -> invalid multiple_values;
    # c5 has owner dan and no area, so its membership for (dan, east) is unknown -> unknown no_value.
    # c4 (bob, south) lies outside the domain asks and gives no row.
    "chosen": {("ann", "north", "known", ""), ("bob", "north", "not_applicable", "no_match"),
               ("cid", "south", "invalid", "multiple_values"), ("dan", "east", "unknown", "no_value"),
               ("eve", "east", "not_applicable", "no_match")},
    # Item.where(area = r and it != a).one() over asks, declared Item: nobody else in south -> unknown no_match.
    "peer": {("ann", "north", "known", ""), ("bob", "north", "known", ""), ("cid", "south", "unknown", "no_match"),
             ("dan", "east", "known", ""), ("eve", "east", "known", "")},
}
KNOWN = {
    "item_home": {("ann",): "north", ("bob",): "north", ("cid",): "south", ("dan",): "east", ("eve",): "east"},
    "item_up": {("ann",): "bob"},
    "item_chooses": {("ann",): "1", ("bob",): "1", ("cid",): "2", ("dan",): "1", ("eve",): "0"},
    "link_goal": {("l1",): "bob", ("l2",): "cid", ("l4",): "bob"},
    "area_askers": {("north",): "2", ("south",): "1", ("east",): "2", ("west",): "0"},
    "chosen": {("ann", "north"): "bob"},
    "peer": {("ann", "north"): "bob", ("bob", "north"): "ann", ("dan", "east"): "eve", ("eve", "east"): "dan"},
}
ASKS = {("ann", "north"), ("bob", "north"), ("cid", "south"), ("dan", "east"), ("eve", "east")}

# A functional derivation over an open kind, and one over a Bool relation that reads an open kind.
OPEN_PROPERTY = """\
rezono 1
pack minimal

kind Area
kind Item world open
  area: Area

extend s: Item
  derived home: Area = s.area
"""
OPEN_OVER = """\
rezono 1
pack minimal

kind Area
kind Item world open
  area: Area

derived pair(a: Item, r: Area): Bool = a.area = r

derived pick(a: Item, r: Area): Item?
  over pair(a, r)
  = Item.where(area = r).one()
"""


class MissingRezono1DerivedLowering(AssertionError):
    """`derived` in rezono 1 did not lower to rezono.rules/2 as decisions/language-rezono-1.md gives it."""


def _validate(schema_name: str, instance: dict, target_class: str) -> list[str]:
    definition = yaml_loader.load(str(ROOT / "contracts" / schema_name), target_class=SchemaDefinition)
    validator = Validator(definition, validation_plugins=[JsonschemaValidationPlugin(closed=True)])
    return [item.message for item in validator.validate(instance, target_class).results]


def _write_pack(directory: Path, source: str, facts: str | None = None) -> Path:
    directory = Path(shutil.copytree(FIXTURE, directory))
    folder = directory / "rezono"
    folder.mkdir()
    module, form = folder / "derived.rezono", folder / "derived.json"
    module.write_text(source, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [os.environ.get("REZONO_NODE", "node"), str(ROOT / "rezono/src/write-form.ts"), str(module), str(form)],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(form.read_bytes())["format"] == "rezono.module/5"
    if facts is not None:
        (directory / "facts").mkdir(exist_ok=True)
        (directory / "facts/case.yaml").write_text(facts, encoding="utf-8", newline="\n")
        (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    register(directory, {"module": "rezono/derived.rezono", "form": "rezono/derived.json", "layer": "facts"})
    return directory


def _refusal(directory: Path) -> str | None:
    """The compiler's refusal of a pack as text, or None when it compiles."""
    try:
        emit.compile_pack(pack.read(directory))
    except pack.CompileError as error:
        return " ".join([str(error), *(f"{d.code} {d.message}" for d in getattr(error, "diagnostics", ()))])
    return None


def _state_rows(rows: set[tuple], keys: int) -> tuple[set[tuple], dict[tuple, str]]:
    """(key..., state, reason) of every row, and the value of every known row, from (key..., state, reason, value)."""
    states = {row[:keys + 2] for row in rows}
    known = {row[:keys]: row[keys + 2] for row in rows if row[keys] == "known"}
    return states, known


def test_lower_rezono_1_derived(tmp_path):
    # Counter-case: a rezono 1 pack whose module declares kinds and no derivation compiles to no rule program.
    plain = _write_pack(tmp_path / "plain", MODULE.split("\nextend s: Item")[0] + "\n")
    assert "ir/rules.json" not in emit.compile_pack(pack.read(plain))

    directory = _write_pack(tmp_path / "derived", MODULE, FACTS)
    try:
        model = pack.read(directory)
        files = emit.compile_pack(model)
    except pack.CompileError as error:
        raise MissingRezono1DerivedLowering(str(error)) from error
    if "ir/rules.json" not in files:
        raise MissingRezono1DerivedLowering(f"no ir/rules.json among {sorted(files)}")
    document = json.loads(files["ir/rules.json"])
    bundle = json.loads(files["bundle/schema-bundle.json"])
    problems: list = []

    # 1. The rule IR: rezono.rules/2, valid against contracts/rules.yaml, loadable with every witness.
    if document.get("format") != "rezono.rules/2":
        problems.append({"format": document.get("format")})
    if errors := _validate("rules.yaml", document, "RuleProgram"):
        problems.append({"contracts/rules.yaml": errors[:5]})
    if errors := _validate("bundle.yaml", bundle, "Bundle"):
        problems.append({"contracts/bundle.yaml": errors[:5]})
    relations = {relation["name"]: relation for relation in document.get("relations", [])}
    try:
        prog = rules.load(document)
    except rules.IRError as error:
        raise MissingRezono1DerivedLowering(f"rules.load: {error}\n{json.dumps(problems, indent=1)}") from error

    # 2. Naming, role, closed domain and value of every derivation.
    for name, (domain, value_type) in {**PROPERTIES, **MULTI_KEY}.items():
        relation = relations.get(name)
        keys = 1 if name in PROPERTIES else 2
        if relation is None:
            problems.append({"missing relation": name, "relations": sorted(relations)})
            continue
        found = {member: relation.get(member) for member in ("role", "domain", "value", "world")}
        if (relation.get("role") != "functional" or relation.get("domain") != domain
                or relation.get("value") != {"name": "value", "type": value_type}
                or relation.get("world", "closed") != "closed" or len(relation.get("key", [])) != keys
                or relation.get("conflict_policy") not in ("publish", "block")):
            problems.append({name: found | {"key": relation.get("key"), "conflict": relation.get("conflict_policy")}})
    for name in MULTI_KEY:   # data multiplicity from .one() publishes by default (section 2)
        if relations.get(name, {}).get("conflict_policy") != "publish":
            problems.append({name: {"conflict_policy": relations.get(name, {}).get("conflict_policy")}})
    for bare in ("home", "up", "chooses", "out_links", "goal", "askers"):
        if bare in relations:
            problems.append({"a property under its bare name": bare})
    asks = relations.get("asks", {})
    if (asks.get("role") != "derived" or len(asks.get("key", [])) != 2
            or any(member in asks for member in ("domain", "value", "conflict_policy"))):
        problems.append({"asks is a plain Bool set": asks})

    # 3. DuckDB: co-located (key..., state, reason, value) views, one row per domain key, and the states of the
    #    decisions. A Bool derivation is a plain set of its keys.
    rows = dict(scenarios.states(model, directory))["0-case"]
    con, _, _ = batch.run(model, prog, rows)
    derived = batch.read(con, prog)
    for name, expected in EXPECTED.items():
        keys = 1 if name in PROPERTIES else 2
        if name not in prog.relations:
            continue
        columns = [column[0] for column in con.execute(f'SELECT * FROM "{name}" LIMIT 0').description]
        if len(columns) != keys + 3 or columns[keys:] != ["state", "reason", "value"]:
            problems.append({name: {"columns": columns}})
            continue
        if any(cell is None for row in con.execute(f'SELECT * FROM "{name}"').fetchall() for cell in row):
            problems.append({name: "a NULL cell in a NOT NULL functional view"})
        states, known = _state_rows(derived.get(name, set()), keys)
        if states != expected:
            problems.append({name: {"missing": sorted(expected - states), "unexpected": sorted(states - expected)}})
        if known != KNOWN.get(name, {}):
            problems.append({name: {"known values": sorted(known.items()), "expected": sorted(KNOWN[name].items())}})
    if "asks" in prog.relations:
        asks_columns = [column[0] for column in con.execute('SELECT * FROM "asks" LIMIT 0').description]
        if len(asks_columns) != 2 or derived.get("asks") != ASKS:
            problems.append({"asks": {"columns": asks_columns, "rows": sorted(derived.get("asks", ()))}})

    # 4. Soufflé, the independent oracle, gives the same rows for every derived and functional relation.
    if shutil.which("souffle"):
        oracle = souffle.run(prog, scenarios.rule_rows(model, prog, rows), tmp_path)
        for name in sorted(set(oracle) | set(derived)):
            if oracle.get(name) != derived.get(name):
                problems.append({"souffle": name, "oracle": sorted(oracle.get(name, ())),
                                 "duckdb": sorted(derived.get(name, ()))})

    # 5. Feldera: one co-located materialized view per functional derivation, never inside a recursive view.
    feldera_sql = rules_sql.feldera(prog, witnesses="none")
    for name in sorted({**PROPERTIES, **MULTI_KEY}):
        if (len(re.findall(rf'CREATE MATERIALIZED VIEW\s+"?{name}\b', feldera_sql)) != 1
                or re.search(rf'DECLARE RECURSIVE VIEW\s+"?{name}\b', feldera_sql)):
            problems.append({"feldera view": name})

    # 6. `means` and `@`: every rule of `chosen` carries the sentence as its message in the default language and the
    #    source in its bundle entry; the witness of the known row (ann, north) -> bob is one of those rules.
    [messages] = [entry["resource"].splitlines() for entry in bundle.get("messages", []) if entry["lang"] == "nl"]
    chosen_rules = {entry["id"]: entry for entry in bundle.get("rules", []) if entry.get("relation") == "chosen"}
    if not chosen_rules:
        problems.append({"no bundle rule for chosen": sorted(entry.get("relation") for entry in bundle.get("rules", []))})
    for rid, entry in chosen_rules.items():
        variables = {variable["name"] for variable in entry.get("variables", [])}
        if (entry.get("source") != SOURCE or f"{entry['message']} = {{{{{SENTENCE}}}}}" not in messages
                or not {"?a", "?r"} <= variables):
            problems.append({"means and source": entry, "messages": [m for m in messages if m.startswith("rule.")]})
    if any("source" in entry for entry in bundle.get("rules", []) if entry.get("relation") != "chosen"):
        problems.append({"a source on a rule without @": [e["id"] for e in bundle["rules"] if "source" in e]})
    witnessed = set()
    for rid, thetas in batch.witnesses(con, prog).items():
        rule = prog.rules[rid]
        for theta in thetas:
            binding = dict(zip(rule.variables, theta))
            head = tuple(binding.get(term, term) for term in rule.head.terms)
            if rule.head.relation == "chosen" and head == ("ann", "north", "bob"):
                witnessed.add(rid)
    if not witnessed or not witnessed <= set(chosen_rules):
        problems.append({"witness of chosen(ann, north) = bob": sorted(witnessed), "rules": sorted(chosen_rules)})

    # 7. An open domain is refused with functional_open_domain, for a property and for an `over` relation.
    for label, source in (("property", OPEN_PROPERTY), ("over", OPEN_OVER)):
        refusal = _refusal(_write_pack(tmp_path / f"open-{label}", source))
        if refusal is None or "functional_open_domain" not in refusal:
            problems.append({f"open {label}": refusal})

    if problems:
        raise MissingRezono1DerivedLowering(json.dumps(problems, indent=1, default=str))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M3: decisions/language-rezono-1.md: sections 2, 5.8, and 8; compiler/rezono_compiler/emit.py "
        "must emit role=='functional' relations into bundle/schema-bundle.json with co-located "
        "(key..., state, reason, value) columns and populate kind/property on <k>_<d> derived properties."
    ),
)
def test_rezono_1_derived_bundle_includes_functional_relations(tmp_path):
    source = MODULE + "\nextend s: Item\n  derived self_parent: Bool = s.parent = s\n"
    directory = _write_pack(tmp_path / "bundle-functional", source, FACTS)
    files = emit.compile_pack(pack.read(directory))
    bundle = json.loads(files["bundle/schema-bundle.json"])
    assert _validate("bundle.yaml", bundle, "Bundle") == []

    by_id = {rel["id"]: rel for rel in bundle.get("relations", [])}

    # Every single-key functional derived property <k>_<d> appears with kind, property, and co-located columns.
    for name, (domain, value_type) in PROPERTIES.items():
        assert name in by_id, f"functional property {name!r} missing from bundle relations: {sorted(by_id)}"
        rel = by_id[name]
        prop = name[len(domain) + 1:]
        assert rel.get("kind") == domain, (name, rel)
        assert rel.get("property") == prop, (name, rel)
        assert rel.get("world", "closed") == "closed", (name, rel)
        cols = rel["columns"]
        assert len(cols) == 4, (name, cols)
        assert [(c["name"], c["type"]) for c in cols[1:]] == [
            ("state", "string"), ("reason", "string"), ("value", value_type),
        ], (name, cols)

    # Multi-key functional derivations appear with co-located columns and no kind/property.
    for name, (_, value_type) in MULTI_KEY.items():
        assert name in by_id, f"functional relation {name!r} missing from bundle relations: {sorted(by_id)}"
        rel = by_id[name]
        assert "kind" not in rel and "property" not in rel, (name, rel)
        assert rel.get("world", "closed") == "closed", (name, rel)
        cols = rel["columns"]
        assert len(cols) == 5, (name, cols)
        assert [(c["name"], c["type"]) for c in cols[2:]] == [
            ("state", "string"), ("reason", "string"), ("value", value_type),
        ], (name, cols)

    # Single-key Bool derived property carries kind/property and plain key column; module-level Bool asks omits them.
    assert "item_self_parent" in by_id, sorted(by_id)
    assert by_id["item_self_parent"].get("kind") == "item"
    assert by_id["item_self_parent"].get("property") == "self_parent"
    assert len(by_id["item_self_parent"]["columns"]) == 1

    assert "asks" in by_id
    assert "kind" not in by_id["asks"] and "property" not in by_id["asks"]
    assert len(by_id["asks"]["columns"]) == 2


def _write_json_form_pack(directory: Path, decls: list[dict], facts: str | None = None) -> Path:
    from rezono_compiler import rezono_module

    directory = Path(shutil.copytree(FIXTURE, directory))
    folder = directory / "rezono"
    folder.mkdir()
    module = {"rezono": "1", "pack": "minimal", "use": [], "decls": decls}
    spans = [{"at": at, "line": "1", "start": "0", "end": "1"} for at in rezono_module.place_pointers(module)]
    form = {"format": "rezono.module/5", "module": module, "spans": spans}
    (folder / "derived.rezono").write_text("rezono 1\npack minimal\n", encoding="utf-8", newline="\n")
    (folder / "derived.json").write_text(json.dumps(form, sort_keys=True), encoding="utf-8", newline="\n")
    if facts is not None:
        (directory / "facts").mkdir(exist_ok=True)
        (directory / "facts/case.yaml").write_text(facts, encoding="utf-8", newline="\n")
        (directory / "facts/case.sources.yaml").write_text(FACT_SOURCE, encoding="utf-8", newline="\n")
    register(directory, {"module": "rezono/derived.rezono", "form": "rezono/derived.json", "layer": "facts"})
    return directory


def test_rezono_1_derived_rejects_yes_no_booleans_and_integer_scalar(tmp_path):
    # Counter-cases: true/false and Int compile cleanly.
    ok_source = """\
rezono 1
pack minimal

kind Item
  flag: Bool

extend s: Item
  derived yes_flag: Bool = s.flag = true
  derived no_flag: Bool = s.flag = false
  derived total_items: Int = Item.count()
"""
    assert _refusal(_write_pack(tmp_path / "ok", ok_source)) is None

    # Integer (instead of Int) must be refused as a rezono 1 scalar type, and yes/no must be refused for Bool.
    problems: list[str] = []
    bad_integer = """\
rezono 1
pack minimal

kind Item
  flag: Bool

extend s: Item
  derived total_items: Integer = Item.count()
"""
    if _refusal(_write_pack(tmp_path / "bad-integer", bad_integer)) is None:
        problems.append("rezono_derived accepted scalar type 'Integer' instead of refusing it in favour of 'Int'")

    for token in ("yes", "no"):
        decls = [
            {"kind": "Item", "world": "closed", "slots": [{"slot": "flag", "type": "Bool"}], "derived": []},
            {
                "extend": "Item",
                "binder": "s",
                "derived": [{
                    "derived": f"bad_{token}",
                    "type": "Bool",
                    "value": {"cmp": ["=", {"path": ["s", "flag"]}, {"lit": token}]},
                }],
            },
        ]
        if _refusal(_write_json_form_pack(tmp_path / f"bad-bool-{token}", decls)) is None:
            problems.append(f"rezono_derived accepted {token!r} as a Bool literal instead of requiring true/false")

    assert not problems, "\n".join(problems)


def _run_derived_case(tmp_path: Path, name: str, source: str, facts: str) -> tuple[dict, dict, set[tuple]]:
    directory = _write_pack(tmp_path / name, source, facts)
    model = pack.read(directory)
    files = emit.compile_pack(model)
    assert "ir/calc.json" not in files, f"{name}: rezono 1 derivation fell back to rezono.calc/1 (ir/calc.json)"
    assert "ir/rules.json" in files, f"{name}: missing ir/rules.json among {sorted(files)}"
    doc = json.loads(files["ir/rules.json"])
    assert doc.get("format") == "rezono.rules/2", f"{name}: expected rezono.rules/2, got {doc.get('format')!r}"
    assert _validate("rules.yaml", doc, "RuleProgram") == []
    prog = rules.load(doc)
    rows = dict(scenarios.states(model, directory))["0-case"]
    con, _, _ = batch.run(model, prog, rows)
    return files, doc, batch.read(con, prog)


def test_rezono_1_derived_retires_calc_fallback(tmp_path):
    item_facts = """\
item:
  - {id: a1, score: 4}
  - {id: a2, score: 15}
  - {id: a3}
"""

    # 1. `unit` on a rezono 1 derived value lowers to rezono.rules/2 (no ir/calc.json).
    unit_src = """\
rezono 1
pack minimal

kind Item
  score: Int

extend Item
  derived doubled: Int = score * 2
    unit points
"""
    _, doc, derived = _run_derived_case(tmp_path, "unit-case", unit_src, item_facts)
    rels = {r["name"]: r for r in doc["relations"]}
    assert rels["item_doubled"]["role"] == "functional"
    assert rels["item_doubled"]["domain"] == "item"
    states, known = _state_rows(derived["item_doubled"], 1)
    assert states == {("a1", "known", ""), ("a2", "known", ""), ("a3", "unknown", "no_value")}
    assert known == {("a1",): "8", ("a2",): "30"}

    # 2. Module with `as of` still lowers its rezono 1 derivations to rezono.rules/2.
    as_of_src = """\
rezono 1
pack minimal
as of 2026-11-10 known 2026-11-10

kind Area
kind Item
  area: Area

extend Item
  derived home: Area = area
"""
    as_of_facts = "area:\n  - {id: north}\nitem:\n  - {id: ann, area: north}\n"
    _, doc, derived = _run_derived_case(tmp_path, "as-of-case", as_of_src, as_of_facts)
    rels = {r["name"]: r for r in doc["relations"]}
    assert rels["item_home"]["role"] == "functional"
    assert rels["item_home"]["domain"] == "item"
    states, known = _state_rows(derived["item_home"], 1)
    assert states == {("ann", "known", "")}
    assert known == {("ann",): "north"}

    # 3. `versions` on a rezono 1 derived value lowers to rezono.rules/2.
    versions_src = """\
rezono 1
pack minimal
as of 2026-11-10 known 2026-11-10

kind Item
  score: Int

extend Item
  derived rate: Int
    version 1, valid 2025-01-01..<2026-01-01, known 2024-12-01 = 10
    version 2, valid 2026-01-01..<2027-01-01, known 2025-12-01 = 20
"""
    _, doc, derived = _run_derived_case(tmp_path, "versions-case", versions_src, item_facts)
    rels = {r["name"]: r for r in doc["relations"]}
    assert rels["item_rate"]["role"] == "functional"
    assert rels["item_rate"]["domain"] == "item"
    states, known = _state_rows(derived["item_rate"], 1)
    assert states == {("a1", "known", ""), ("a2", "known", ""), ("a3", "known", "")}
    assert known == {("a1",): "20", ("a2",): "20", ("a3",): "20"}

    # 4. `unless` on a rezono 1 derived value lowers to rezono.rules/2.
    unless_src = """\
rezono 1
pack minimal

kind Item
  score: Int

extend Item
  derived capped: Int = score
    unless score > 10 then 10
"""
    _, doc, derived = _run_derived_case(tmp_path, "unless-case", unless_src, item_facts)
    rels = {r["name"]: r for r in doc["relations"]}
    assert rels["item_capped"]["role"] == "functional"
    assert rels["item_capped"]["domain"] == "item"
    states, known = _state_rows(derived["item_capped"], 1)
    assert states == {("a1", "known", ""), ("a2", "known", ""), ("a3", "unknown", "no_value")}
    assert known == {("a1",): "4", ("a2",): "10"}

    # 5. `table first` on a rezono 1 derived value lowers to a single functional relation in rezono.rules/2
    #    rather than legacy rezono.rules/1 multi-relation desugaring (`item_tier_value`).
    table_src = """\
rezono 1
pack minimal

enum Tier
  low
  high

kind Item
  score: Int

extend Item
  derived tier: Tier
    table first
      | score | -> tier |
      | 10..  | high    |
      | -     | low     |
"""
    _, doc, derived = _run_derived_case(tmp_path, "table-case", table_src, item_facts)
    rels = {r["name"]: r for r in doc["relations"]}
    assert rels["item_tier"]["role"] == "functional"
    assert rels["item_tier"]["domain"] == "item"
    assert "item_tier_value" not in rels
    states, known = _state_rows(derived["item_tier"], 1)
    assert states == {("a1", "known", ""), ("a2", "known", ""), ("a3", "unknown", "no_value")}
    assert known == {("a1",): "low", ("a2",): "high"}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M3: decisions/language-rezono-1.md: sections 2 and 5.4; compiler/rezono_compiler/rezono_derived.py "
        "must refuse functional derivations whose `.one(...)` or `.count(...)` reads an open-world derived "
        "Bool relation or projects an open-world slot (`slot.world == 'open'`) with R004."
    ),
)
def test_rezono_1_functional_derivation_refuses_open_world_collection_and_slot(tmp_path):
    # Counter-case: the exact same `.one(col)`, `.count(...)` and `.one(slot)` derivations over a closed
    # derived Bool relation and a closed slot compile cleanly.
    closed_ok = [
        {"kind": "Area", "world": "closed", "slots": [], "derived": []},
        {"kind": "ClosedItem", "world": "closed", "slots": [{"slot": "area", "type": "Area"}], "derived": []},
        {"kind": "Choice", "world": "closed", "slots": [
            {"slot": "owner", "type": "ClosedItem"},
            {"slot": "target", "type": "Area"},
        ], "derived": []},
        {
            "derived": "closed_pair",
            "params": [{"name": "a", "type": "ClosedItem"}, {"name": "r", "type": "Area"}],
            "type": "Bool",
            "value": {"cmp": ["=", {"path": ["a", "area"]}, {"path": ["r"]}]},
        },
        {
            "extend": "Area",
            "binder": "g",
            "derived": [
                {
                    "derived": "picked",
                    "type": "ClosedItem",
                    "card": "?",
                    "value": {"agg": [
                        "one",
                        {"filter": [{"path": ["closed_pair"]}, {"cmp": ["=", {"path": ["r"]}, {"path": ["g"]}]}]},
                        {"path": ["a"]},
                    ]},
                },
                {
                    "derived": "total",
                    "type": "Int",
                    "value": {"agg": [
                        "count",
                        {"path": ["closed_pair"]},
                        {"cmp": ["=", {"path": ["r"]}, {"path": ["g"]}]},
                    ]},
                },
            ],
        },
        {
            "extend": "ClosedItem",
            "binder": "s",
            "derived": [{
                "derived": "chosen_area",
                "type": "Area",
                "card": "?",
                "value": {"agg": [
                    "one",
                    {"filter": [{"kind": "Choice"}, {"cmp": ["=", {"path": ["owner"]}, {"path": ["s"]}]}]},
                    {"path": ["target"]},
                ]},
            }],
        },
    ]
    assert _refusal(_write_json_form_pack(tmp_path / "closed-ok", closed_ok)) is None

    problems: list[str] = []

    # 1. `.one(col)` over an open-world derived Bool relation must be refused with R004.
    open_one_rel = [
        {"kind": "Area", "world": "closed", "slots": [], "derived": []},
        {"kind": "OpenItem", "world": "open", "slots": [{"slot": "area", "type": "Area"}], "derived": []},
        {
            "derived": "open_pair",
            "params": [{"name": "a", "type": "OpenItem"}, {"name": "r", "type": "Area"}],
            "type": "Bool",
            "value": {"cmp": ["=", {"path": ["a", "area"]}, {"path": ["r"]}]},
        },
        {
            "extend": "Area",
            "binder": "g",
            "derived": [{
                "derived": "picked",
                "type": "OpenItem",
                "card": "?",
                "value": {"agg": [
                    "one",
                    {"filter": [{"path": ["open_pair"]}, {"cmp": ["=", {"path": ["r"]}, {"path": ["g"]}]}]},
                    {"path": ["a"]},
                ]},
            }],
        },
    ]
    refusal = _refusal(_write_json_form_pack(tmp_path / "open-one-rel", open_one_rel))
    if refusal is None or "R004" not in refusal:
        problems.append(f".one(col) over open derived Bool relation expected R004, got: {refusal!r}")

    # 2. `.count(...)` over an open-world derived Bool relation must be refused with R004.
    open_count_rel = [
        {"kind": "Area", "world": "closed", "slots": [], "derived": []},
        {"kind": "OpenItem", "world": "open", "slots": [{"slot": "area", "type": "Area"}], "derived": []},
        {
            "derived": "open_pair",
            "params": [{"name": "a", "type": "OpenItem"}, {"name": "r", "type": "Area"}],
            "type": "Bool",
            "value": {"cmp": ["=", {"path": ["a", "area"]}, {"path": ["r"]}]},
        },
        {
            "extend": "Area",
            "binder": "g",
            "derived": [{
                "derived": "total",
                "type": "Int",
                "value": {"agg": [
                    "count",
                    {"path": ["open_pair"]},
                    {"cmp": ["=", {"path": ["r"]}, {"path": ["g"]}]},
                ]},
            }],
        },
    ]
    refusal = _refusal(_write_json_form_pack(tmp_path / "open-count-rel", open_count_rel))
    if refusal is None or "R004" not in refusal:
        problems.append(f".count(...) over open derived Bool relation expected R004, got: {refusal!r}")

    # 3. `.one(open_slot)` projecting an open-world slot on a closed kind must be refused with R004.
    open_one_slot = [
        {"kind": "Area", "world": "closed", "slots": [], "derived": []},
        {"kind": "Item", "world": "closed", "slots": [], "derived": []},
        {"kind": "Choice", "world": "closed", "slots": [
            {"slot": "owner", "type": "Item"},
            {"slot": "target", "type": "Area", "world": "open"},
        ], "derived": []},
        {
            "extend": "Item",
            "binder": "s",
            "derived": [{
                "derived": "picked",
                "type": "Area",
                "card": "?",
                "value": {"agg": [
                    "one",
                    {"filter": [{"kind": "Choice"}, {"cmp": ["=", {"path": ["owner"]}, {"path": ["s"]}]}]},
                    {"path": ["target"]},
                ]},
            }],
        },
    ]
    refusal = _refusal(_write_json_form_pack(tmp_path / "open-one-slot", open_one_slot))
    if refusal is None or "R004" not in refusal:
        problems.append(f".one(open_slot) with slot.world == 'open' expected R004, got: {refusal!r}")

    assert not problems, "\n".join(problems)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M3: decisions/language-rezono-1.md: section 2; compiler/rezono_compiler/rezono_derived.py "
        "must allow implicit `it` slot paths inside Bool derived predicates declared in `kind` "
        "(e.g. `size > 10` and slot-path equality comparisons without `it.`) while refusing unknown "
        "identifiers with R001."
    ),
)
def test_rezono_1_kind_bool_derived_allows_implicit_it_paths(tmp_path):
    case_facts = """\
area:
  - {id: north}
  - {id: south}
item:
  - {id: small, size: 5, area: north, backup: south}
  - {id: large, size: 15, area: north, backup: north, parent: large}
  - {id: edge, size: 10, area: south, backup: north, parent: small}
"""
    slots = [
        {"slot": "size", "type": "Int"},
        {"slot": "area", "type": "Area"},
        {"slot": "backup", "type": "Area"},
        {"slot": "parent", "type": "Item", "card": "?"},
    ]

    def _run_json_case(name: str, item_derived: list[dict]) -> tuple[dict, dict]:
        decls = [
            {"kind": "Area", "world": "closed", "slots": [], "derived": []},
            {"kind": "Item", "world": "closed", "slots": slots, "derived": item_derived},
        ]
        directory = _write_json_form_pack(tmp_path / name, decls, case_facts)
        model = pack.read(directory)
        files = emit.compile_pack(model)
        assert "ir/rules.json" in files, f"{name}: missing ir/rules.json among {sorted(files)}"
        doc = json.loads(files["ir/rules.json"])
        assert doc.get("format") == "rezono.rules/2", f"{name}: expected rezono.rules/2, got {doc.get('format')!r}"
        assert _validate("rules.yaml", doc, "RuleProgram") == []
        prog = rules.load(doc)
        rows = dict(scenarios.states(model, directory))["0-case"]
        con, _, _ = batch.run(model, prog, rows)
        try:
            return doc, batch.read(con, prog)
        finally:
            con.close()

    # Counter-case: explicit `it.` paths in `kind Item` already compile to rezono.rules/2 and evaluate on DuckDB.
    explicit_derived = [
        {"derived": "home", "type": "Area", "value": {"path": ["area"]}},
        {"derived": "big", "type": "Bool", "value": {"cmp": [">", {"path": ["it", "size"]}, {"lit": "10"}]}},
        {"derived": "same_area", "type": "Bool", "value": {"cmp": ["=", {"path": ["it", "area"]}, {"path": ["it", "backup"]}]}},
        {"derived": "self_parent", "type": "Bool", "value": {"cmp": ["=", {"path": ["it", "parent"]}, {"path": ["it"]}]}},
    ]
    _, explicit_rows = _run_json_case("explicit-it", explicit_derived)
    assert explicit_rows["item_big"] == {("large",)}
    assert explicit_rows["item_same_area"] == {("large",)}
    assert explicit_rows["item_self_parent"] == {("large",)}

    # Implicit `it`: omitting `it.` on slot paths in `kind Item` Bool derivations must compile to rezono.rules/2
    # and yield the exact same derived rows on DuckDB.
    implicit_derived = [
        {"derived": "home", "type": "Area", "value": {"path": ["area"]}},
        {"derived": "big", "type": "Bool", "value": {"cmp": [">", {"path": ["size"]}, {"lit": "10"}]}},
        {"derived": "same_area", "type": "Bool", "value": {"cmp": ["=", {"path": ["area"]}, {"path": ["backup"]}]}},
        {"derived": "self_parent", "type": "Bool", "value": {"cmp": ["=", {"path": ["parent"]}, {"path": ["it"]}]}},
    ]
    _, implicit_rows = _run_json_case("implicit-it", implicit_derived)
    assert implicit_rows["item_big"] == {("large",)}
    assert implicit_rows["item_same_area"] == {("large",)}
    assert implicit_rows["item_self_parent"] == {("large",)}

    # Counter-case: an unknown identifier in a `kind Item` Bool derivation must still be refused with R001.
    unknown_decls = [
        {
            "kind": "Item",
            "world": "closed",
            "slots": [{"slot": "size", "type": "Int"}],
            "derived": [{
                "derived": "bad",
                "type": "Bool",
                "value": {"cmp": [">", {"path": ["nonexistent"]}, {"lit": "10"}]},
            }],
        },
    ]
    refusal = _refusal(_write_json_form_pack(tmp_path / "unknown-id", unknown_decls))
    assert refusal is not None and "R001" in refusal, f"unknown identifier expected R001, got: {refusal!r}"
