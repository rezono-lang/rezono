"""The LinkML extensions of M2 on domain-free fixtures: schema modules and pack imports, multivalued slots
as link kinds, and constraints (pattern, cardinality, constants, class rules) as violation views."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, compile_dir, row_text, text, violations
from rezono_compiler import facts, modules, pack, regex

SHARED = FIXTURE.parent / "shared"
SCHEMA = {"id": "https://rezono.example/x", "name": "x", "in_language": "nl", "imports": ["linkml:types"],
          "default_range": "string", "annotations": {"layer": "facts"}}


@pytest.fixture
def fixture(tmp_path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def edit(d: Path, change, name="minimal") -> None:
    path = d / "schema" / f"{name}.yaml"
    schema = yaml.safe_load(path.read_text())
    change(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False))


def module(d: Path, name: str, classes: dict, imports=()) -> None:
    body = dict(SCHEMA, id=f"https://rezono.example/{name}", name=name.replace("/", "_"),
                imports=["linkml:types", *imports], classes=classes)
    (d / "schema" / f"{name}.yaml").parent.mkdir(parents=True, exist_ok=True)
    (d / "schema" / f"{name}.yaml").write_text(yaml.safe_dump(body, sort_keys=False))


def refused(d: Path, message: str) -> None:
    with pytest.raises(pack.CompileError, match=message):
        pack.read(d)


def run(d: Path, tmp_path: Path, fact_text: str) -> dict:
    files = compile_dir(d, tmp_path / "out")
    (tmp_path / "facts.yaml").write_text(fact_text)
    return violations(files, facts.load(pack.read(d), tmp_path / "facts.yaml"))


def bundle(d: Path, tmp_path: Path) -> dict:
    return json.loads(compile_dir(d, tmp_path / "bundle")["bundle/schema-bundle.json"])


# ---- modules ----

def test_a_module_imports_another_by_relative_path(fixture, tmp_path):
    module(fixture, "parts/gear", {"Gear": {"attributes": {"id": {"identifier": True},
                                                          "alpha": {"range": "Alpha", "required": True}}}},
           imports=["../minimal"])
    b = bundle(fixture, tmp_path)
    assert [(s["module"], s["file"]) for s in b["schemas"]] == [("minimal", "schema/minimal.yaml"),
                                                                ("parts/gear", "schema/parts/gear.yaml")]
    assert {k["id"]: k["module"] for k in b["kinds"]}["gear"] == "parts/gear"
    assert run(fixture, tmp_path, "gear: [{id: g}]\n") == text({"gear__alpha__totality": {("g",)}})


def test_a_name_declared_by_two_modules_is_qualified_by_its_module(fixture, tmp_path):
    for name in ("one", "two"):
        module(fixture, name, {"Item": {"attributes": {"id": {"identifier": True}}}})
    kinds = {k["id"]: k["class"] for k in bundle(fixture, tmp_path)["kinds"]}
    assert kinds["one_item"] == kinds["two_item"] == "Item" and "item" not in kinds


def test_one_import_closure_cannot_hold_a_name_twice(fixture):
    module(fixture, "other", {"Alpha": {"attributes": {"id": {"identifier": True}}}})
    edit(fixture, lambda s: s["imports"].append("other"))
    refused(fixture, "'Alpha' is declared in modules minimal and other")


def test_a_parent_outside_the_import_closure_is_an_error_not_a_crash(fixture):
    module(fixture, "other", {"Gamma": {"is_a": "Alpha", "attributes": {"note": {}}}})
    refused(fixture, "class Gamma: parent Alpha is not in the import closure of other")


@pytest.mark.parametrize("imp, message", [("../outside", "outside schema/"), ("missing", "is not a module"),
                                           ("nobody:terms", "names no pack")])
def test_a_schema_imports_only_modules_of_its_pack_or_an_imported_pack(fixture, imp, message):
    edit(fixture, lambda s: s["imports"].append(imp))
    refused(fixture, message)


# ---- pack imports ----

def importing(tmp_path: Path, sha: str | None = None) -> Path:
    d = Path(shutil.copytree(FIXTURE, tmp_path / "packs" / "main"))
    shutil.copytree(SHARED, tmp_path / "packs" / "shared")
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    meta["imports"] = [{"name": "shared-terms", "path": "../shared", "sha256": sha or modules.pack_hash(SHARED)}]
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    edit(d, lambda s: (s["imports"].append("shared-terms:terms"),
                       s["classes"]["Beta"]["attributes"].update(party={"range": "Party"})))
    return d


def test_an_imported_pack_adds_its_modules_labels_and_signs(tmp_path):
    d = importing(tmp_path)
    b = bundle(d, tmp_path)
    assert b["imports"] == [{"name": "shared-terms", "version": "0.1.0", "sha256": modules.pack_hash(SHARED)}]
    assert {"module": "shared-terms:terms", "pack": "shared-terms", "file": "schema/terms.yaml",
            "name": "shared_terms", "id": "https://rezono.example/shared-terms"} in b["schemas"]
    assert {"element": "party.grade", "lang": "nl", "text": "klasse"} in b["labels"]
    assert {"kind": "party", "shape": "ellipse"} in b["channels"]["kinds"]
    got = run(d, tmp_path, "alpha: [{id: a, title: t}]\nparty: [{id: p, grade: odd}]\n"
                           "beta: [{id: b, alpha: a, party: q}]\n")
    assert got == text({"party__grade__value_range": {("p", "odd")}, "beta__party__reference": {("b", "q")}})


def test_an_import_is_pinned_on_the_hash_of_its_files(tmp_path):
    d = importing(tmp_path, sha="0" * 64)
    refused(d, "the files hash to [0-9a-f]{64}, not the pinned 0{64}")


def test_a_second_relief_binding_is_refused(tmp_path):
    """An import and the pack both bind a relief: refused, so neither silently replaces the other."""
    d = importing(tmp_path)
    shared = tmp_path / "packs" / "shared"
    with (shared / "channels.yaml").open("a") as f:
        f.write("relief: {region: party, member: beta.party}\n")
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    meta["imports"][0]["sha256"] = modules.pack_hash(shared)
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    pack.read(d)  # one relief, from the import, is fine
    with (d / "channels.yaml").open("a") as f:
        f.write("relief: {region: alpha, member: beta.alpha}\n")
    refused(d, "channels.yaml: a second relief binding; shared/channels.yaml binds one already")


def test_the_hash_covers_definitions_not_facts(tmp_path):
    d = Path(shutil.copytree(SHARED, tmp_path / "shared"))
    before = modules.pack_hash(d)
    (d / "facts").mkdir()
    (d / "facts" / "a.yaml").write_text("party: []\n")
    assert modules.pack_hash(d) == before
    (d / "labels" / "nl.yaml").write_text("party: iemand\n")
    assert modules.pack_hash(d) != before


def test_an_imported_name_that_clashes_is_qualified_and_its_labels_follow(tmp_path):
    d = importing(tmp_path)
    module(d, "local", {"Party": {"attributes": {"id": {"identifier": True}}}})
    b = bundle(d, tmp_path)
    kinds = {k["id"] for k in b["kinds"]}
    assert {"local_party", "shared_terms_terms_party"} <= kinds and "party" not in kinds
    assert {"element": "shared_terms_terms_party.grade", "lang": "nl", "text": "klasse"} in b["labels"]
    assert {"id": "beta.party", "target": "shared_terms_terms_party"}.items() <= \
        next(a for a in b["arrows"] if a["id"] == "beta.party").items()


# ---- multivalued slots ----

def test_a_multivalued_slot_is_a_link_kind_without_functionality(fixture, tmp_path):
    edit(fixture, lambda s: s["classes"]["Beta"]["attributes"]["state"].update(
        multivalued=True, minimum_cardinality=1, maximum_cardinality=2))
    files = compile_dir(fixture, tmp_path / "out")
    assert "beta__state__functionality" not in files["engine/integrity.sql"]
    params = json.loads(files["engine/parameters.json"])
    assert params["rezono__maximum_cardinality"] == [{"kind": "beta", "slot": "state", "v": 2}]
    assert "beta__state__maximum_cardinality" not in params  # no rule reads it
    got = run(fixture, tmp_path, "alpha: [{id: a, title: t}]\nbeta:\n  - {id: ok, alpha: a, state: [low, high]}\n"
                                 "  - {id: none, alpha: a}\n  - {id: same, alpha: a, state: [low, low]}\n")
    assert got == text({"beta__state__cardinality": {("none", 0)}})
    got = run(fixture, tmp_path, "alpha: [{id: a, title: t}]\nbeta: [{id: b, alpha: a, state: [low, high, odd]}]\n")
    assert got == text({"beta__state__cardinality": {("b", 3)}, "beta__state__value_range": {("b", "odd")}})


@pytest.mark.parametrize("facet, message", [
    ({"minimum_cardinality": 1}, "applies to multivalued slots only"),
    ({"multivalued": True, "minimum_cardinality": 3, "maximum_cardinality": 1}, "is above maximum_cardinality"),
    ({"multivalued": True, "maximum_cardinality": -1}, "at least 0"),
    ({"exact_cardinality": 1}, "applies to multivalued slots only"),
    ({"multivalued": True, "exact_cardinality": -1}, "at least 0"),
    ({"multivalued": True, "exact_cardinality": 2, "minimum_cardinality": 3},
     "exact_cardinality 2 is below minimum_cardinality 3"),
    ({"multivalued": True, "exact_cardinality": 2, "maximum_cardinality": 1},
     "exact_cardinality 2 is above maximum_cardinality 1"),
])
def test_cardinalities_are_validated(fixture, facet, message):
    edit(fixture, lambda s: s["classes"]["Beta"]["attributes"]["state"].update(facet))
    refused(fixture, message)


@pytest.mark.parametrize("beside", [{}, {"minimum_cardinality": 1}, {"maximum_cardinality": 3},
                                    {"minimum_cardinality": 2, "maximum_cardinality": 2}])
def test_an_exact_cardinality_holds_beside_limits_it_meets(fixture, beside):
    """Every cardinality given holds: an exact count within the minimum and maximum is that count; one
    outside them is refused above, never an override."""
    edit(fixture, lambda s: s["classes"]["Beta"]["attributes"]["state"].update(
        multivalued=True, exact_cardinality=2, **beside))
    slot = pack.read(fixture).kinds["beta"].slots["state"]
    assert (slot.minimum_cardinality, slot.maximum_cardinality) == (2, 2)


def test_embedded_list_elements_get_one_id_each(fixture, tmp_path):
    def change(s):
        s["classes"]["Part"] = {"attributes": {"note": {}}}
        s["classes"]["Alpha"]["attributes"]["parts"] = {"range": "Part", "multivalued": True, "inlined_as_list": True}
    edit(fixture, change)
    rows = facts.rows_of(pack.read(fixture), {"alpha": [{"id": "x/y", "title": "t", "parts": [{"note": "a"}, {"note": "b"}]}]})
    assert rows["alpha__parts"] == [("x/y", "x%2Fy/alpha.parts/1"), ("x/y", "x%2Fy/alpha.parts/2")]
    assert rows["part__note"] == [("x%2Fy/alpha.parts/1", "a"), ("x%2Fy/alpha.parts/2", "b")]


def test_the_dictionary_form_keys_elements_by_their_identifier(fixture):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"].update(
        betas={"range": "Beta", "multivalued": True, "inlined": True}))
    rows = facts.rows_of(pack.read(fixture), {"alpha": [{"id": "a", "title": "t", "betas": {
        "b1": {"alpha": "a"}, "b2": {"alpha": "a", "state": "low"}}}]})
    assert rows["alpha__betas"] == [("a", "b1"), ("a", "b2")]
    assert rows["beta__state"] == [("b2", "low")]


# ---- constraints ----

def test_patterns_of_a_slot_and_its_type_both_apply(fixture, tmp_path):
    def change(s):
        s["types"]["Code"] = {"typeof": "string", "pattern": "^[a-z]"}
        s["classes"]["Alpha"]["attributes"]["title"].update(range="Code", pattern=r"\d$")
    edit(fixture, change)
    b = bundle(fixture, tmp_path)
    assert next(a for a in b["attributes"] if a["id"] == "alpha.title")["patterns"] == ["[0-9]$", "^[a-z]"]
    got = run(fixture, tmp_path, "alpha: [{id: a, title: x1}, {id: b, title: x}, {id: c, title: '1'}]\n")
    assert got == text({"alpha__title__pattern": {("b", "x"), ("c", "1")}})


def test_an_identifier_may_carry_a_pattern(fixture, tmp_path):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["id"].update(pattern="^a-"))
    got = run(fixture, tmp_path, "alpha: [{id: a-1, title: t}, {id: b-1, title: t}]\n")
    assert got == text({"alpha__id__pattern": {("b-1", "b-1")}})


@pytest.mark.parametrize("pattern, message", [(r"\bx", r"'\\b' has no meaning"), ("(?i)x", "only '\\(\\?:' is allowed"),
                                               ("[[:alpha:]]", "nested classes"), ("x{3,2}", "counts down")])
def test_a_pattern_without_one_meaning_on_both_engines_is_refused(fixture, pattern, message):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["title"].update(pattern=pattern))
    refused(fixture, message)


@pytest.mark.parametrize("pattern, written", [
    ("x{1500}", "x{1000}x{500}"), ("^x{1200,2600}$", "^x{1000}x{200}x{0,1000}x{0,400}$"), ("x{1001,}", "x{1000}x{1}x*"),
    ("(?:ab{100}){20}", "(?:ab{100}){10}(?:ab{100}){10}"), ("(a|b{3}){400}", "(a|b{3}){333}(a|b{3}){67}"),
    ("[a-c]{2,3}", "[a-c]{2,3}")])
def test_a_repetition_above_what_re2_takes_is_split_with_the_same_language(pattern, written):
    """E10: RE2 (DuckDB) takes a count up to 1000, also as the product of nested counts; Rust (Feldera) has no
    such limit. The split pattern matches exactly what the pattern matches (Python's re as the reference)."""
    assert regex.portable(pattern) == written
    for n in [0, 1, 99, 100, 101, 999, 1000, 1001, 1199, 1200, 1201, 1499, 1500, 1501, 2599, 2600, 2601]:
        for s in ["x" * n, "a" * n, "ab" + "b" * n, ("a" + "b" * 100) * (n // 50), "bbb" * n]:
            assert bool(re.search(written, s)) == bool(re.search(pattern, s)), (pattern, n)


def test_a_long_repetition_runs_on_duckdb(fixture, tmp_path):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["title"].update(pattern="^x{1500}$"))
    long, short = "x" * 1500, "x" * 1499
    got = run(fixture, tmp_path, f"alpha: [{{id: a, title: {long}}}, {{id: b, title: {short}}}]\n")
    assert got == text({"alpha__title__pattern": {("b", short)}})


def test_a_currency_on_a_type_makes_its_integers_an_amount(fixture, tmp_path):
    """A type (or slot) annotation `currency` gives the bundle attribute its ISO 4217 code: the integers are
    whole minor units of that currency; the engine type stays integer."""
    def change(s):
        s["types"]["Cents"] = {"typeof": "integer", "annotations": {"currency": "EUR"}}
        s["classes"]["Alpha"]["attributes"]["size"].update(range="Cents")
    edit(fixture, change)
    a = next(a for a in bundle(fixture, tmp_path)["attributes"] if a["id"] == "alpha.size")
    assert (a["type"], a["schema_type"], a["currency"]) == ("integer", "Cents", "EUR")
    assert "currency" not in next(a for a in bundle(fixture, tmp_path)["attributes"] if a["id"] == "alpha.title")


@pytest.mark.parametrize("slot, currency, message", [("size", "eur", "is not an ISO 4217 code"),
                                                     ("title", "EUR", "a currency goes on whole numbers")])
def test_a_currency_is_checked(fixture, slot, currency, message):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"][slot].update(annotations={"currency": currency}))
    refused(fixture, message)


def test_a_pattern_on_a_number_is_refused(fixture):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["size"].update(pattern="^1"))
    refused(fixture, "a pattern applies to text only")


def test_constants_are_parameters_checked_as_a_value_range(fixture, tmp_path):
    def change(s):
        s["classes"]["Alpha"]["attributes"]["size"].update(equals_number=4)
        s["classes"]["Beta"]["attributes"]["state"].update(equals_string="low")
    edit(fixture, change)
    files = compile_dir(fixture, tmp_path / "out")
    params = json.loads(files["engine/parameters.json"])
    assert params["rezono__constant"] == [{"kind": "alpha", "slot": "size", "v": "4"},
                                        {"kind": "beta", "slot": "state", "v": "low"}]
    got = run(fixture, tmp_path, "alpha: [{id: a, title: t, size: 5}]\nbeta: [{id: b, alpha: a, state: high}]\n")
    assert got == text({"alpha__size__value_range": {("a", 5)}, "beta__state__value_range": {("b", "high")}})


@pytest.mark.parametrize("slot, facet, message", [
    ("title", {"equals_number": 1}, "equals_number applies to integers only"),
    ("size", {"equals_string": "x"}, "equals_string applies to text and enums only"),
    ("title", {"equals_expression": "{size} * 2"}, "'equals_expression' is not supported yet"),
])
def test_constants_must_fit_the_type(fixture, slot, facet, message):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"][slot].update(facet))
    refused(fixture, message)


def test_limits_of_a_type_and_the_types_it_derives_from_apply(fixture, tmp_path):
    def change(s):
        s["types"]["Count"].update(minimum_value=1, maximum_value=20)
        s["types"]["Small"] = {"typeof": "Count", "maximum_value": 7}
        s["classes"]["Alpha"]["attributes"]["size"].update(range="Small")
    edit(fixture, change)  # the slot says 0..9, Count 1..20, Small ..7: every limit holds, so 1..7
    assert pack.read(fixture).kinds["alpha"].slots["size"].minimum == 1
    assert pack.read(fixture).kinds["alpha"].slots["size"].maximum == 7


@pytest.mark.parametrize("facet, message", [
    ({"array": {"exact_number_dimensions": 2}}, "'array' is not supported yet"),
    ({"ifabsent": "string(x)"}, "'ifabsent' is not supported yet"),
])
def test_a_facet_outside_the_subset_is_refused_never_ignored(fixture, facet, message):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["title"].update(facet))
    refused(fixture, message)


@pytest.mark.parametrize("facet, message", [
    ({"array": {"exact_number_dimensions": 1}}, "'array' is not supported yet"),
    ({"ifabsent": "string(x)"}, "'ifabsent' is not supported yet"),
    ({"range": "Count"}, "cannot be multivalued or carry minimum or maximum"),
    ({"minimum_cardinality": 1}, "Alpha.id: an identifier names its element; it cannot carry minimum_cardinality"),
    ({"maximum_cardinality": 1}, "it cannot carry maximum_cardinality"),
    ({"exact_cardinality": 1}, "it cannot carry exact_cardinality"),
    ({"equals_string": "a"}, "it cannot carry equals_string"),
    ({"equals_number": 1}, "it cannot carry equals_number"),
    ({"annotations": {"currency": "EUR"}}, "it cannot carry annotation currency"),
    ({"slot_uri": "rdfs:label"}, "it cannot carry role name"),
])
def test_an_identifier_is_checked_like_any_slot(fixture, facet, message):
    def change(s):
        s["types"]["Count"].update(minimum_value=1)
        s["classes"]["Alpha"]["attributes"]["id"].update(facet)
    edit(fixture, change)
    refused(fixture, message)


@pytest.mark.parametrize("name", ["a__b", "Id", "is_a"])
def test_an_identifier_has_a_valid_slot_name(fixture, name):
    """The name of an identifier is held to the rule for every slot name."""
    def change(s):
        attributes = s["classes"]["Alpha"]["attributes"]
        s["classes"]["Alpha"]["attributes"] = {name if k == "id" else k: v for k, v in attributes.items()}
    edit(fixture, change)
    refused(fixture, f"Alpha.{name}: '{name}' is not a valid slot name")


def test_an_unknown_annotation_on_an_identifier_warns(fixture):
    """An annotation the compiler does not read warns on an identifier as on any slot."""
    before = pack.read(fixture).warnings
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["id"].update(annotations={"colour": "red"}))
    assert [w for w in pack.read(fixture).warnings if w not in before] == ["Alpha.id: unknown annotation 'colour'"]


def test_linkml_any_is_an_open_value_also_without_the_prefix():
    from rezono_compiler.pack import open_value

    class View:  # a schema that declares no linkml prefix: expanding gives the CURIE back unchanged
        def get_class(self, name):
            return type("C", (), {"class_uri": "linkml:Any"})()

        def expand_curie(self, uri):
            return uri

    assert open_value(View(), "Anything")


def test_an_open_structure_is_refused(fixture):
    edit(fixture, lambda s: s["classes"]["Alpha"].update(extra_slots={"allowed": True}))
    refused(fixture, "extra_slots \\(an open structure\\) is not supported yet")


def test_extra_slots_not_allowed_is_the_closed_default(fixture):
    edit(fixture, lambda s: s["classes"]["Alpha"].update(extra_slots={"allowed": False}))
    pack.read(fixture)


def test_an_open_value_is_refused(fixture):
    def change(s):
        s["classes"]["Anything"] = {"class_uri": "linkml:Any"}
        s["classes"]["Alpha"]["attributes"]["extra"] = {"range": "Anything", "inlined": True}
    edit(fixture, change)
    refused(fixture, "range Anything is linkml:Any, an open value")


def rule(**parts):
    return {k: {"slot_conditions": v} for k, v in parts.items()}


def test_a_class_rule_is_a_violation_view(fixture, tmp_path):
    edit(fixture, lambda s: s["classes"]["Beta"].update(rules=[
        rule(preconditions={"state": {"equals_string": "high"}}, postconditions={"alpha": {"required": True}},
             elseconditions={"alpha": {"value_presence": "ABSENT"}})]))
    got = run(fixture, tmp_path, "alpha: [{id: a, title: t}]\nbeta:\n  - {id: ok1, alpha: a, state: high}\n"
                                 "  - {id: ok2, state: low}\n  - {id: bad1, state: high}\n"
                                 "  - {id: bad2, alpha: a, state: low}\n  - {id: bad3, alpha: a}\n")
    assert got["beta__rule_1__rule"] == {row_text(r) for r in {("bad1",), ("bad2",), ("bad3",)}}


def test_a_rule_value_condition_needs_a_value_and_every_value_to_meet_it(fixture, tmp_path):
    def change(s):
        s["classes"]["Alpha"]["attributes"]["size"].update(multivalued=True)
        s["classes"]["Alpha"]["rules"] = [rule(postconditions={"size": {"minimum_value": 2, "maximum_value": 4}})]
    edit(fixture, change)
    got = run(fixture, tmp_path, "alpha: [{id: a, title: t, size: [2, 4]}, {id: b, title: t, size: [3, 5]},\n"
                                 "        {id: c, title: t}]\n")
    assert got == text({"alpha__rule_1__rule": {("b",), ("c",)}})


@pytest.mark.parametrize("r, message", [
    (rule(postconditions={"nothing": {"required": True}}), "not a slot of alpha"),
    (rule(postconditions={"title": {"range": "Count"}}), "uses range"),
    (rule(postconditions={"size": {"equals_string": "x"}}), "apply to text and enums only"),
    (rule(preconditions={"title": {"required": True}}), "has no postconditions"),
    ({"postconditions": {"any_of": [{"slot_conditions": {"title": {"required": True}}}]}},
     "only slot_conditions are supported"),
])
def test_rules_outside_the_subset_are_refused(fixture, r, message):
    edit(fixture, lambda s: s["classes"]["Alpha"].update(rules=[r]))
    refused(fixture, message)


def test_a_deactivated_rule_makes_no_view(fixture, tmp_path):
    edit(fixture, lambda s: s["classes"]["Alpha"].update(rules=[
        dict(rule(postconditions={"size": {"required": True}}), deactivated=True)]))
    assert "rule" not in compile_dir(fixture, tmp_path / "out")["engine/integrity.sql"]


# ---- review of PR 2 ----

def test_a_pattern_on_an_enum_slot_is_checked(fixture, tmp_path):
    edit(fixture, lambda s: s["classes"]["Beta"]["attributes"]["state"].update(pattern="^low$"))
    got = run(fixture, tmp_path, "alpha: [{id: a, title: t}]\nbeta: [{id: b1, alpha: a, state: low}, "
                                 "{id: b2, alpha: a, state: high}]\n")
    assert got == text({"beta__state__pattern": {("b2", "high")}})


def test_a_pattern_on_an_arrow_is_refused(fixture):
    edit(fixture, lambda s: s["classes"]["Beta"]["attributes"]["alpha"].update(pattern="^a"))
    refused(fixture, "a pattern applies to text and enums, not to an arrow")


def test_a_path_equation_cannot_step_over_a_multivalued_arrow(fixture):
    """One end per path is what the view compares; over a multivalued arrow it would compare every pair."""
    def change(s):
        s["classes"]["Beta"]["attributes"].update(targets={"range": "Alpha", "multivalued": True})
        s["classes"]["Beta"]["annotations"] = {"path_equations": [{"name": "same", "left": "targets", "right": "alpha"}]}
    edit(fixture, change)
    refused(fixture, "'targets' is a multivalued arrow, which a path equation cannot follow yet")


@pytest.mark.parametrize("pattern", ["a++", "a*+", "a?+", "a{2}+", r"\d++"])
def test_a_possessive_quantifier_is_refused(fixture, pattern):
    edit(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["title"].update(pattern=pattern))
    refused(fixture, "a possessive quantifier")


@pytest.mark.parametrize("pattern, text, match", [
    (r"^k-[0-9a-f]{24}$", "k-" + "a" * 24, True), (r"^P(?:\d+D)?$", "P12D", True), (r"[\d-]x{2,3}", "-xx", True),
    (r"^(?:\/(?:[^~]|~[01])*)*$", "/a~0", True), (r"a{", "a{", True), (r"^\w+$", "é", False), (r"\s", " ", False),
    (r"a+?b", "aab", True), (r"^[]a]$", "]", True), (r"^\x{e9}$", "é", True)])
def test_an_accepted_pattern_means_the_same_in_python_and_duckdb(pattern, text, match):
    """Both engines search; shorthand classes are ASCII (Feldera's Rust regex follows the written-out form)."""
    import re
    import duckdb
    from rezono_compiler import emit
    from rezono_compiler.regex import portable
    p = portable(pattern)
    db = duckdb.connect()
    db.execute(emit.DUCKDB_FUNCTIONS)
    assert db.execute("SELECT RLIKE(?, ?)", [text, p]).fetchone()[0] is match
    assert (re.search(p, text) is not None) is match


def test_labels_of_a_pack_follow_renames_of_the_packs_it_imports(tmp_path):
    """main imports feature, feature imports shared-terms. feature labels shared-terms' Party; main also has a
    Party, so that kind is qualified, and feature's label must follow it and win over shared-terms' own."""
    packs = tmp_path / "packs"
    shutil.copytree(SHARED, packs / "shared")
    feature = packs / "feature"
    (feature / "schema").mkdir(parents=True)
    (feature / "labels").mkdir()
    (feature / "pack.yaml").write_text(yaml.safe_dump({"name": "feature", "version": "0.1.0", "default_language": "nl",
        "imports": [{"name": "shared-terms", "path": "../shared", "sha256": modules.pack_hash(SHARED)}]}))
    module(feature, "uses", {"Use": {"attributes": {"id": {"identifier": True}, "party": {"range": "Party"}}}},
           imports=["shared-terms:terms"])
    (feature / "labels" / "nl.yaml").write_text("party: deelnemer\nuse: gebruik\n")
    main = Path(shutil.copytree(FIXTURE, packs / "main"))
    meta = yaml.safe_load((main / "pack.yaml").read_text())
    meta["imports"] = [{"name": "feature", "path": "../feature", "sha256": modules.pack_hash(feature)}]
    (main / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    module(main, "local", {"Party": {"attributes": {"id": {"identifier": True}}}})
    b = bundle(main, tmp_path)
    assert [i["name"] for i in b["imports"]] == ["feature", "shared-terms"]
    labels = {(x["element"], x["text"]) for x in b["labels"]}
    assert ("shared_terms_terms_party", "deelnemer") in labels
    assert ("shared_terms_terms_party.grade", "klasse") in labels and ("use", "gebruik") in labels
    assert not any(e == "party" for e, _ in labels)


# ---- module interfaces (F04) ----

def interface(d: Path, *entries) -> None:
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    meta["modules"] = list(entries)
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))


def parts(d: Path) -> None:
    """A second module that uses Alpha of `minimal` twice: as a parent and as a range."""
    module(d, "parts", {"Gear": {"attributes": {"id": {"identifier": True},
                                                "alpha": {"range": "Alpha", "required": True}}},
                        "Wheel": {"is_a": "Alpha", "attributes": {"spokes": {"range": "integer"}}}},
           imports=["minimal"])


def test_a_module_without_an_interface_keeps_everything_public(fixture):
    parts(fixture)
    pack.read(fixture)
    interface(fixture, {"module": "minimal", "public": [{"name": "Alpha"}]})
    assert "wheel" in pack.read(fixture).kinds


def test_using_a_kind_outside_another_modules_interface_is_a_compile_error(fixture):
    parts(fixture)
    interface(fixture, {"module": "minimal", "public": [{"name": "Beta"}]})
    with pytest.raises(pack.CompileError) as error:
        pack.read(fixture)
    found = [line for line in str(error.value).splitlines() if "not in that module's public interface" in line]
    assert found == ["schema/parts.yaml: uses 'Alpha' of module minimal, which is not in that module's public "
                     "interface (pack.yaml, modules)"]  # once, though Gear and Wheel both use it


def test_the_module_itself_uses_its_private_kinds(fixture):
    interface(fixture, {"module": "minimal", "public": []})
    assert pack.read(fixture).kinds  # Beta's arrow to Alpha stays inside minimal


def hidden_grade(d: Path) -> None:
    """minimal publishes only Alpha, whose own slot grade has a private enum HiddenGrade; parts only writes
    `Wheel is_a Alpha` (and Gear's arrow to Alpha), never HiddenGrade."""
    edit(d, lambda s: (s["classes"]["Alpha"]["attributes"].update(grade={"range": "HiddenGrade"}),
                       s.setdefault("enums", {}).update(HiddenGrade={"permissible_values": {"low": {}, "high": {}}})))
    parts(d)
    interface(d, {"module": "minimal", "public": [{"name": "Alpha"}]})


def test_an_inherited_slot_is_held_to_the_interface_of_the_module_that_declares_it(fixture):
    hidden_grade(fixture)
    assert "wheel" in pack.read(fixture).kinds  # Wheel inherits grade; only minimal names HiddenGrade


def test_naming_a_private_enum_of_another_module_stays_refused(fixture):
    hidden_grade(fixture)
    edit(fixture, lambda s: s["classes"]["Gear"]["attributes"].update(grade={"range": "HiddenGrade"}), name="parts")
    refused(fixture, "uses 'HiddenGrade' of module minimal, which is not in that module's public interface")


def test_a_deprecated_element_warns_with_its_date_and_never_reads_a_clock(fixture):
    parts(fixture)
    interface(fixture, {"module": "minimal", "public": [{"name": "Alpha", "deprecated": "2001-01-01"},
                                                        {"name": "Beta", "deprecated": "2999-12-31"}]})
    warned = [w for w in pack.read(fixture).warnings if "deprecated" in w]
    assert warned == ["schema/parts.yaml: uses 'Alpha' of module minimal, deprecated from 2001-01-01"]


@pytest.mark.parametrize("entries, message", [
    ([{"module": "nowhere", "public": []}], "'nowhere' is not a module"),
    ([{"module": "minimal", "public": [{"name": "Missing"}]}], "lists 'Missing' as public, but declares no class"),
    ([{"module": "minimal", "public": [{"name": "Alpha", "deprecated": "31-12-2026"}]}], "not a date YYYY-MM-DD"),
    ([{"module": "minimal", "public": []}, {"module": "minimal", "public": []}], "declared twice"),
    ([{"module": "minimal", "public": [{"name": "Alpha", "until": "2026-12-31"}]}], "may have 'deprecated'"),
    ([{"module": "minimal"}], "needs 'module' and a list 'public', a 'namespace', or both"),
])
def test_an_interface_names_only_what_its_module_declares(fixture, entries, message):
    interface(fixture, *entries)
    refused(fixture, message)


def test_an_imported_packs_interface_holds_for_the_pack_that_imports_it(tmp_path):
    shared = Path(shutil.copytree(SHARED, tmp_path / "packs" / "shared"))
    interface(shared, {"module": "terms", "public": [{"name": "Grade"}]})
    d = Path(shutil.copytree(FIXTURE, tmp_path / "packs" / "main"))
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    meta["imports"] = [{"name": "shared-terms", "path": "../shared", "sha256": modules.pack_hash(shared)}]
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    edit(d, lambda s: (s["imports"].append("shared-terms:terms"),
                       s["classes"]["Beta"]["attributes"].update(party={"range": "Party"})))
    refused(d, "uses 'Party' of module shared-terms:terms, which is not in that module's public interface")
    edit(d, lambda s: s["classes"]["Beta"]["attributes"].update(party={"range": "Grade"}))
    assert "beta" in pack.read(d).kinds


# ---- pack.yaml `iri:` (docs/ring2/iris.md section 4) ----

NS = "https://w3id.org/example-publisher/"


def declare(d: Path, block=None, *entries) -> None:
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    if block is not None:
        meta["iri"] = block
    if entries:
        meta["modules"] = list(entries)
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))


def test_a_pack_without_the_block_writes_no_iri(fixture, tmp_path):
    b = bundle(fixture, tmp_path)
    assert "base" not in b["pack"] and "reasons" not in b and not [k for k in b["kinds"] if "iri" in k]


def test_a_kind_takes_its_entry_else_its_module_s_namespace_else_the_base(fixture, tmp_path):
    parts(fixture)
    declare(fixture, {"base": f"{NS}minimal/", "namespaces": [{"iri": f"{NS}lab/", "kinds": ["Wheel"]}]},
            {"module": "parts", "namespace": f"{NS}parts/"})
    b = bundle(fixture, tmp_path)
    assert b["pack"]["base"] == f"{NS}minimal/"
    assert {k["class"]: k["iri"] for k in b["kinds"]} == {"Alpha": f"{NS}minimal/Alpha", "Beta": f"{NS}minimal/Beta",
                                                         "Gear": f"{NS}parts/Gear", "Wheel": f"{NS}lab/Wheel"}
    assert "reasons" not in b  # the fixture has no named outcome


@pytest.mark.parametrize("block, entries, message", [
    ({"base": "http://w3id.org/example-publisher/minimal/"}, [], "an IRI here is https"),
    ({"base": f"{NS}minimal"}, [], "a namespace ends in '/'"),
    ({"base": f"{NS}min imal/"}, [], "is not a whole IRI"),
    ({"base": f"{NS}minimal/", "namespaces": [{"iri": f"{NS}lab", "kinds": ["Alpha"]}]}, [], "ends in '/'"),
    ({"base": f"{NS}minimal/", "namespaces": [{"iri": f"{NS}a/", "kinds": ["Alpha"]},
                                              {"iri": f"{NS}b/", "kinds": ["Alpha"]}]}, [],
     "'Alpha' is named in two namespaces"),
    ({"base": f"{NS}minimal/", "namespaces": [{"iri": f"{NS}a/", "kinds": ["Gamma"]}]}, [],
     "'Gamma' is not a kind the pack declares"),
    ({"base": f"{NS}minimal/", "namespaces": [{"iri": f"{NS}a/", "reasons": ["not_measured"]}]}, [],
     "'not_measured' is not a reason code of the pack"),
    ({"namespaces": []}, [], "needs 'base'"),
    (None, [{"module": "minimal", "namespace": f"{NS}a/"}], "a module namespace needs the block 'iri'"),
    ({"base": f"{NS}minimal/"}, [{"module": "nowhere", "namespace": f"{NS}a/"}], "'nowhere' is not a module"),
    ({"base": f"{NS}minimal/"}, [{"module": "minimal", "namespace": f"{NS}a"}], "ends in '/'"),
])
def test_the_block_is_refused_with_its_reason(fixture, block, entries, message):
    declare(fixture, block, *entries)
    refused(fixture, message)


def imports_shared(tmp_path: Path, shared_block=None, main_block=None) -> Path:
    shared = Path(shutil.copytree(SHARED, tmp_path / "packs" / "shared"))
    declare(shared, shared_block)
    d = Path(shutil.copytree(FIXTURE, tmp_path / "packs" / "main"))
    meta = yaml.safe_load((d / "pack.yaml").read_text())
    meta["imports"] = [{"name": "shared-terms", "path": "../shared", "sha256": modules.pack_hash(shared)}]
    (d / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False))
    declare(d, main_block)
    edit(d, lambda s: (s["imports"].append("shared-terms:terms"),
                       s["classes"]["Beta"]["attributes"].update(party={"range": "Party"})))
    return d


def test_an_import_and_its_consumer_never_share_a_base(tmp_path):
    d = imports_shared(tmp_path, {"base": f"{NS}one/"}, {"base": f"{NS}one/"})
    refused(d, "is also the base of")


def test_a_kind_keeps_the_namespace_of_the_pack_that_declares_it(tmp_path):
    d = imports_shared(tmp_path, {"base": f"{NS}terms/"}, {"base": f"{NS}main/"})
    kinds = {k["class"]: k["iri"] for k in bundle(d, tmp_path)["kinds"]}
    assert kinds["Party"] == f"{NS}terms/Party" and kinds["Alpha"] == f"{NS}main/Alpha"
