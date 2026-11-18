"""The compiler on a minimal, domain-free fixture pack: determinism, refused input, and engine names."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from support import FIXTURE, REPO, compile_dir, text, violations
from rezono_compiler import emit, facts, pack


def tree(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture
def fixture(tmp_path) -> Path:
    return Path(shutil.copytree(FIXTURE, tmp_path / "pack"))


def edit_schema(d: Path, change) -> None:
    """Apply `change` to the schema as YAML data, so a test states exactly what differs."""
    path = d / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text())
    change(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False))


def refused(d: Path, message: str) -> None:
    with pytest.raises(pack.CompileError, match=message):
        pack.read(d)


def test_two_compiles_give_identical_bytes(tmp_path):
    compile_dir(FIXTURE, tmp_path / "a")
    compile_dir(FIXTURE, tmp_path / "b")
    assert tree(tmp_path / "a") == tree(tmp_path / "b")


def test_every_sql_writer_quotes_and_escapes_through_one_definition():
    """One `q` and one `literal`; the rule translator's own `q` left a `"` in a name unescaped."""
    from rezono_compiler import batch, calc_sql, checks, rules_split, rules_sql, seal, sqltext
    assert {m.q for m in (batch, calc_sql, checks, emit, rules_split, rules_sql, seal)} == {sqltext.q}
    assert {m.literal for m in (calc_sql, checks, emit, rules_sql)} == {sqltext.literal}
    assert sqltext.q('a"b') == '"a""b"' and sqltext.literal("it's") == "'it''s'"
    assert rules_sql.lit_sql("it's", "string") == "'it''s'"
    from rezono_compiler import calc, names, rules, views, writer
    assert {m.NAME for m in (pack, rules, views)} == {names.NAME}
    assert {m.ISO_DATE for m in (calc, rules, writer)} == {names.ISO_DATE}


@pytest.mark.parametrize("bad", ["float", "double", "decimal"])
def test_floating_point_is_refused(fixture, bad):
    edit_schema(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["size"].update(range=bad))
    refused(fixture, f"floating point type '{bad}'")


def test_a_type_derived_from_floating_point_is_refused(fixture):
    edit_schema(fixture, lambda s: s["types"]["Count"].update(typeof="double"))
    refused(fixture, "floating point type 'double'")


def test_a_missing_default_message_is_refused(fixture):
    (fixture / "messages" / "nl.mf2").write_text("@locale nl\n---\narrow.total = {{x}}\n")
    refused(fixture, "no message 'arrow.partial'")


def test_a_label_for_an_unknown_element_is_refused(fixture):
    with open(fixture / "labels" / "nl.yaml", "a") as f:
        f.write("no_such_kind: iets\n")
    refused(fixture, "unknown element 'no_such_kind'")


def second_language(d: Path) -> None:
    """Give the fixture an English catalogue with the keys and the variables of the Dutch one. English has no
    genders, so no message of it reads a `_gender` companion."""
    nl = yaml.safe_load((d / "labels" / "nl.yaml").read_text(encoding="utf-8"))
    (d / "labels" / "en.yaml").write_text("".join(f"{element}: {element}\n" for element in nl))
    body = (d / "messages" / "nl.mf2").read_text(encoding="utf-8").split("\n---\n")[1]
    (d / "messages" / "en.mf2").write_text("@locale en\n---\n" + "".join(
        f"{mid} = {{{{{' '.join('{$' + v + '}' for v in sorted(pack.variables(block)))}}}}}\n"
        for mid, block in pack.entries(body)))


@pytest.mark.parametrize("file, old, new, message", [
    ("labels/en.yaml", "beta.state: beta.state\n", "", "labels/en.yaml: no label for 'beta.state', which language 'nl' has"),
    ("labels/nl.yaml", "beta.state: stand\n", "", "labels/nl.yaml: no label for 'beta.state', which language 'en' has"),
    ("messages/en.mf2", "is_a = ", "is_b = ", "messages/en.mf2: no message 'is_a', which language 'nl' has"),
    ("messages/en.mf2", "is_a = ", "is_b = ", "messages/nl.mf2: no message 'is_b', which language 'en' has"),
    ("messages/en.mf2", "{$parent}", "{$kind}", "messages/en.mf2: 'is_a' names kind; in language 'nl' it names kind, parent"),
])
def test_a_pack_carries_a_language_whole(fixture, file, old, new, message):
    """A pack with two languages has the same labels and the same messages in both, and a message names
    the same variables in both; a `_gender` companion is not compared. A planted difference stops the compile
    and names the file, the key and the language that has it."""
    second_language(fixture)
    pack.read(fixture)
    text = (fixture / file).read_text(encoding="utf-8")
    assert old in text
    (fixture / file).write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(pack.CompileError) as refusal:
        pack.read(fixture)
    assert message in str(refusal.value).splitlines()


def test_redefining_an_inherited_slot_is_refused(fixture):
    """A subkind that makes an optional parent slot required would otherwise go unchecked."""
    def change(s):
        s["classes"]["Gamma"] = {"is_a": "Alpha", "attributes": {"size": {"range": "Count", "required": True}}}
    edit_schema(fixture, change)
    refused(fixture, "Gamma.size: redefines an inherited slot")


@pytest.mark.parametrize("extra, message", [
    ({"range": "integer", "minimum_value": 1}, "an identifier cannot be multivalued or carry minimum"),
    ({"multivalued": True}, "an identifier cannot be multivalued"),
    ({"range": "State"}, "an identifier must be text or a whole number"),
    ({"range": "date"}, "an identifier must be text or a whole number"),
])
def test_identifier_definitions_are_validated(fixture, extra, message):
    edit_schema(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["id"].update(extra))
    refused(fixture, message)


def test_more_than_one_identifier_is_refused(fixture):
    edit_schema(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["title"].update(identifier=True))
    refused(fixture, r"class Alpha: more than one identifier \(id, title\)")


RDFS = {"linkml": "https://w3id.org/linkml/", "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}


def named(s, kind="Alpha", slot="title", uri="rdfs:label"):
    s["prefixes"] = RDFS
    s["classes"][kind]["attributes"][slot]["slot_uri"] = uri


def keyed(s):
    """Beta identified by its arrow: a link kind."""
    s["classes"]["Beta"]["unique_keys"] = {"by_alpha": {"unique_key_slots": ["alpha"]}}


@pytest.mark.parametrize("uri", ["rdfs:label", "http://www.w3.org/2000/01/rdf-schema#label"])
def test_the_name_of_a_kind_and_the_arrows_that_name_a_link_kind_are_in_the_bundle(fixture, uri):
    """A kind's name is its slot with slot_uri rdfs:label; a kind identified by its arrows (a unique key of
    arrows only) is named by its ends' names (docs/compiler.md, Names)."""
    edit_schema(fixture, lambda s: (named(s, uri=uri), keyed(s)))
    kinds = {k["id"]: k for k in emit.bundle(pack.read(fixture), [])["kinds"]}
    assert kinds["alpha"]["name_attribute"] == "alpha.title" and "name_arrows" not in kinds["alpha"]
    assert kinds["beta"]["name_arrows"] == ["beta.alpha"] and "name_attribute" not in kinds["beta"]


@pytest.mark.parametrize("change", [lambda s: None, named, keyed])
def test_a_kind_is_named_by_its_ends_only_if_they_identify_it_and_one_has_a_name(fixture, change):
    """Without a unique key of arrows, an arrow to a named kind does not name an element: many share it."""
    edit_schema(fixture, change)
    kinds = {k["id"]: k for k in emit.bundle(pack.read(fixture), [])["kinds"]}
    assert "name_arrows" not in kinds["beta"] and "name_attribute" not in kinds["beta"]


def test_a_name_that_is_not_one_text_value_is_refused(fixture):
    edit_schema(fixture, lambda s: named(s, "Beta", "alpha"))
    refused(fixture, r"Beta.alpha: a name \(slot_uri rdfs:label\) is one text value")


def test_a_kind_with_two_names_is_refused(fixture):
    """A subkind inherits its parent's name; a second one would make the name ambiguous."""
    def change(s):
        named(s)
        s["classes"]["Gamma"] = {"is_a": "Alpha", "attributes": {"short": {"slot_uri": "rdfs:label"}}}
    edit_schema(fixture, change)
    refused(fixture, "Gamma: more than one name")


def test_a_subkind_cannot_declare_its_own_identifier(fixture):
    """A subkind shares the identity of its parent; a second identifier would go unchecked."""
    def change(s):
        s["classes"]["Gamma"] = {"is_a": "Alpha", "attributes": {"code": {"identifier": True}}}
    edit_schema(fixture, change)
    refused(fixture, "Gamma.code: a subkind inherits the identifier of alpha")


@pytest.mark.parametrize("change, message", [
    (lambda s: s["enums"].update({"Bad__State": {"permissible_values": {"x": {}}}}), "enum Bad__State: name"),
    (lambda s: s["classes"]["Alpha"].update(unique_keys={'t"x': {"unique_key_slots": ["title"]}}),
     "unique key 't\"x' is not a valid name"),
    (lambda s: s["classes"]["Beta"].update(annotations={"path_equations": [
        {"name": "a__b", "left": "alpha", "right": "alpha"}]}), "path equation 'a__b' is not a valid name"),
], ids=["enum", "unique-key", "path-equation"])
def test_names_that_become_engine_names_are_validated(fixture, change, message):
    edit_schema(fixture, change)
    refused(fixture, message)

def test_an_enum_defined_in_two_schema_files_is_qualified_by_its_module(fixture):
    """Two modules that do not import each other may use one name; each keeps its own (docs/compiler.md)."""
    (fixture / "schema" / "second.yaml").write_text(yaml.safe_dump({
        "id": "https://rezono.example/second", "name": "second", "in_language": "nl",
        "imports": ["linkml:types"], "default_range": "string", "annotations": {"layer": "facts"},
        "enums": {"State": {"permissible_values": {"low": {}}}}}))
    (fixture / "labels" / "nl.yaml").write_text("alpha: alfa\n")
    model = pack.read(fixture)
    assert model.enums == {"minimal_state": ["low", "high"], "second_state": ["low"]}
    assert model.kinds["beta"].slots["state"].enum == "minimal_state"


@pytest.mark.parametrize("bounds, message", [
    ({"minimum_value": 5, "maximum_value": 1}, "minimum 5 is above maximum 1"),
    ({"minimum_value": 2**63}, "within BIGINT"),
    ({"maximum_value": -(2**63) - 1}, "within BIGINT"),
])
def test_bounds_must_be_whole_numbers_within_bigint_and_ordered(fixture, bounds, message):
    edit_schema(fixture, lambda s: s["classes"]["Alpha"]["attributes"]["size"].update(bounds))
    refused(fixture, message)


def test_a_generated_name_that_clashes_is_refused(fixture):
    edit_schema(fixture, lambda s: s["classes"].update(ValidationResult={"attributes": {"id": {"identifier": True}}}))
    with pytest.raises(pack.CompileError, match="engine name 'validation_result' is generated twice"):
        compile_dir(fixture, fixture.parent / "out")


def test_a_reserved_word_is_a_valid_kind_name(fixture, tmp_path):
    """Names are quoted in every SQL statement, so a kind called `Order` works on the engine."""
    def change(s):
        s["classes"]["Order"] = {"attributes": {"id": {"identifier": True}, "alpha": {"range": "Alpha", "required": True}}}
    edit_schema(fixture, change)
    files = compile_dir(fixture, tmp_path / "out")
    (tmp_path / "facts.yaml").write_text("alpha: [{id: a, title: t}]\norder: [{id: o1}]\n")
    got = violations(files, facts.load(pack.read(fixture), tmp_path / "facts.yaml"))
    assert got == text({"order__alpha__totality": {("o1",)}})


def test_channels_follow_the_view_contract(fixture):
    (fixture / "channels.yaml").write_text("kinds:\n  - {kind: alpha, shape: rectangle}\n")
    refused(fixture, "needs a known kind and a shape")
    (fixture / "channels.yaml").write_text("statuses:\n  valid: {color: red}\n")
    refused(fixture, "unknown section 'statuses'")


ICON = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        b'stroke-width="1.65"><rect x="3" y="3" width="18" height="7" rx="2"/><path d="M7 6.5h.01"/></svg>')


def with_icon(fixture, svg, sources=None):
    """The fixture's alpha kind names icons/a.svg; sources.yaml lists it with its hash unless given."""
    (fixture / "icons").mkdir(exist_ok=True)
    (fixture / "icons" / "a.svg").write_bytes(svg)
    digest = hashlib.sha256(svg).hexdigest()
    (fixture / "icons" / "sources.yaml").write_text(sources if sources is not None else (
        f"- {{file: icons/a.svg, sha256: {digest}, source: 'example/icons@0123abc:a.svg', licence: CC0-1.0}}\n"))
    (fixture / "channels.yaml").write_text("kinds:\n  - {kind: alpha, shape: rect, icon: icons/a.svg}\n")


def test_an_icon_reaches_the_bundle_as_a_tree_of_safe_elements(fixture):
    """The kind sign names the icon by hash; the bundle carries it as elements, never SVG text."""
    with_icon(fixture, ICON)
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    digest = hashlib.sha256(ICON).hexdigest()
    assert bundle["channels"]["kinds"] == [{"kind": "alpha", "shape": "rect", "icon": digest}]
    [icon] = bundle["channels"]["icons"]
    assert icon["sha256"] == digest and icon["file"] == "icons/a.svg" and icon["licence"] == "CC0-1.0"
    assert icon["view_box"] == "0 0 24 24"
    assert [a["name"] for a in icon["attributes"]] == ["fill", "stroke", "stroke-width"]
    assert [c["tag"] for c in icon["children"]] == ["rect", "path"]
    assert "<" not in json.dumps(icon)


@pytest.mark.parametrize("svg, sources, message", [
    (ICON, "", "is not listed in icons/sources.yaml"),
    (ICON, "- {file: icons/a.svg, sha256: " + "f" * 64 + ", source: 'example/icons@0123abc:a.svg', licence: CC0-1.0}\n", "has sha256"),
    (ICON, "- {file: icons/a.svg, sha256: " + hashlib.sha256(ICON).hexdigest() + ", source: somewhere, licence: CC0-1.0}\n", "a pinned source and a licence"),
    (ICON.replace(b'stroke="currentColor"', b'stroke="#c00"'), None, "drawn in ink"),
    (ICON.replace(b'<path', b'<script>x</script><path'), None, "element <script>"),
    (ICON.replace(b'<path', b'<path onclick="x"'), None, "attribute onclick"),
    (ICON.replace(b'<path d', b'<path style="fill:red" d'), None, "attribute style"),
    (b'<!DOCTYPE svg [<!ENTITY a "a">]>' + ICON, None, "DOCTYPE or ENTITY"),
])
def test_an_icon_off_the_safe_list_or_without_source_blocks(fixture, svg, sources, message):
    with_icon(fixture, svg, sources)
    refused(fixture, message)

def test_an_image_binding_reaches_the_bundle_by_element_id(fixture):
    """A text slot becomes an image by the channel table's binding; its meaning is the pack's."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write("images:\n  - {kind: alpha, slot: alpha.title}\n")
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    assert bundle["channels"]["images"] == [{"kind": "alpha", "slot": "alpha.title"}]


@pytest.mark.parametrize("images, message", [
    ("  - {kind: beta, slot: beta.alpha}\n", "is not a single-valued text attribute"),
    ("  - {kind: alpha, slot: alpha.nothing}\n", "is not a slot of kind 'alpha'"),
    ("  - {kind: beta, slot: alpha.title}\n", "is not a slot of kind 'beta'"),
    ("  - {kind: alpha, slot: alpha.title, size: 3}\n", "needs exactly kind and slot"),
    ("  - {kind: alpha, slot: alpha.title}\n  - {kind: alpha, slot: alpha.title}\n", "a second image binding"),
])
def test_an_image_binding_names_one_text_slot_of_its_kind(fixture, images, message):
    with (fixture / "channels.yaml").open("a") as f:
        f.write("images:\n" + images)
    refused(fixture, message)

RELIEF = (
    "relief:\n"
    "  region: alpha\n"
    "  member: beta.alpha\n"
    "  label: alpha.title\n"
    "  height: {channel: elevation, slot: alpha.size, level: quantitative, meaning_message: m.size,\n"
    "           scale: {zero: 0, exponent_numerator: 1, exponent_denominator: 2, unit_message: m.unit}}\n")


def test_a_relief_binding_reaches_the_bundle(fixture):
    """A pack binds a relief from its own schema; the bundle carries it as written, by element id."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(RELIEF)
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    relief = bundle["channels"]["relief"]
    assert relief["region"] == "alpha" and relief["member"] == "beta.alpha" and relief["label"] == "alpha.title"
    assert relief["height"]["slot"] == "alpha.size" and relief["height"]["scale"]["exponent_denominator"] == 2


def test_a_relief_without_height_counts_members(fixture):
    """`height` is optional: then an island's height is its number of members (std-view's count scale)."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write("relief: {region: alpha, member: beta.alpha}\n")
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    assert bundle["channels"]["relief"] == {"region": "alpha", "member": "beta.alpha"}


@pytest.mark.parametrize("change, message", [
    (("region: alpha", "region: gamma"), "region 'gamma' is not a kind"),
    (("member: beta.alpha", "member: beta.state"), "is not a single-valued arrow to alpha"),
    (("label: alpha.title", "label: alpha.size"), "is not a text attribute of alpha"),
    (("slot: alpha.size", "slot: alpha.title"), "is not an integer attribute of alpha"),
    (("channel: elevation", "channel: size"), "height is an elevation binding"),
    (("exponent_numerator: 1", "exponent_numerator: 0"), "whole numbers"),
    (("  region: alpha\n", ""), "needs region and member"),
])
def test_a_wrong_relief_binding_is_refused(fixture, change, message):
    """Correctness blocks: a binding that names no such kind or slot, or breaks the grammar, stops the compile."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(RELIEF.replace(*change))
    refused(fixture, message)


FLOW = (
    "flows:\n"
    "  - id: chain\n"
    "    title_message: m.chain\n"
    "    nodes:\n"
    "      - {kind: alpha, label: alpha.title}\n"
    "      - {kind: beta, lane: {channel: lane, slot: beta.state, level: nominal, meaning_message: m.state}}\n"
    "    edges:\n"
    "      - {arrow: beta.alpha}\n"
    "    direction: down\n")


def test_a_flow_binding_reaches_the_bundle(fixture):
    """A pack binds a Flow from its own schema; the bundle carries it by element id, in id order."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(FLOW)
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    [flow] = bundle["channels"]["flows"]
    assert flow["id"] == "chain" and flow["direction"] == "down" and flow["edges"] == [{"arrow": "beta.alpha"}]
    assert flow["nodes"][0] == {"kind": "alpha", "label": "alpha.title"} and flow["nodes"][1]["lane"]["slot"] == "beta.state"


@pytest.mark.parametrize("change, message", [
    (("kind: alpha, label", "kind: gamma, label"), "node 'gamma' is not a kind"),
    (("label: alpha.title", "label: alpha.size"), "is not a text attribute of alpha"),
    (("slot: beta.state", "slot: beta.alpha"), None),
    (("slot: beta.state", "slot: alpha.size"), "is not a slot of beta"),
    (("level: nominal", "level: quantitative"), "lane of beta is a lane binding"),
    (("{arrow: beta.alpha}", "{arrow: beta.state}"), "is not an arrow between node kinds"),
    (("{arrow: beta.alpha}", "{relation: near, from: a, to: b, from_kinds: [beta], to_kinds: [alpha]}"), "is not a derived relation"),
    (("{arrow: beta.alpha}", "{via: beta}"), "edge is an arrow"),
    (("direction: down", "direction: up"), "a direction is down or right"),
    (("  - id: chain", "  - id: Chain"), "an id is lower case"),
])
def test_a_wrong_flow_binding_is_refused(fixture, change, message):
    """Correctness blocks: a Flow that names no such kind, slot, arrow or relation stops the compile. A lane on a
    single-valued arrow is as good as one on an enum."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(FLOW.replace(*change))
    if message is None:
        pack.read(fixture)
    else:
        refused(fixture, message)


HOME = "home:\n  hero: {flow: chain}\n"
# A relation with one rule and one with two, over the fixture's tables.
HOME_RULES = (
    ".decl sized(a: symbol, n: number)\n"
    "sized(a, n) :- alpha(a), n = count : { beta__alpha(_, a) }.\n"
    ".decl near(a: symbol)\n"
    "near(a) :- alpha(a).\n"
    "near(a) :- beta__alpha(_, a).\n")


def with_home(d: Path, home: str, message: str | None = "rule.sized = {$a} has {$n}.\n") -> Path:
    """The fixture with a Flow, rules, the sentence of `sized` (or none) and a home."""
    (d / "rules").mkdir()
    (d / "rules" / "core.dl").write_text(HOME_RULES)
    with (d / "messages" / "nl.mf2").open("a") as f:
        f.write(message or "")
    with (d / "channels.yaml").open("a") as f:
        f.write(FLOW + home)
    return d


def test_a_home_reaches_the_bundle(fixture):
    """A pack names the hero of its home, and the relations whose rows are its claim; the bundle carries both."""
    bundle = json.loads(emit.compile_pack(pack.read(with_home(fixture, HOME + "  claim: [sized]\n")))["bundle/schema-bundle.json"])
    assert bundle["channels"]["home"] == {"hero": {"flow": "chain"}, "claim": ["sized"]}


def test_a_pack_without_a_home_has_none_in_its_bundle(fixture):
    """The declaration is optional: without it the bundle is as before."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(FLOW)
    assert "home" not in json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])["channels"]


@pytest.mark.parametrize("home, message", [
    ("home:\n  hero: {flow: other}\n", "hero is one Flow of the pack"),
    ("home:\n  hero: {flow: chain, matrix: grid}\n", "hero is one Flow of the pack"),
    ("home:\n  hero: {flow: [chain]}\n", "hero is one Flow of the pack"),
    ("home: {}\n", "a home declares a hero, a claim or both"),
    (HOME + "  cards: []\n", "a home declares a hero, a claim or both"),
    (HOME + "  claim: sized\n", "claim is a list of derived relations"),
    (HOME + "  claim: [sized, sized]\n", "claim is a list of derived relations"),
    (HOME + "  claim: [alpha]\n", "claim 'alpha' is not a derived relation with exactly one rule"),
    (HOME + "  claim: [near]\n", "claim 'near' is not a derived relation with exactly one rule"),
])
def test_a_wrong_home_is_refused(fixture, home, message):
    """Correctness blocks: a hero that is no sheet of the pack, or a claim whose rows read as no one sentence."""
    refused(with_home(fixture, home), message)


def test_a_home_may_be_a_claim_alone(fixture):
    """`hero` and `claim` are each optional: a pack may declare a claim for its home without a picture."""
    bundle = json.loads(emit.compile_pack(pack.read(with_home(fixture, "home:\n  claim: [sized]\n")))["bundle/schema-bundle.json"])
    assert bundle["channels"]["home"] == {"claim": ["sized"]}


def test_a_claim_needs_the_sentence_of_its_rule(fixture):
    """A claim is the sentence of a row: without the rule's message in the default language there is none."""
    refused(with_home(fixture, HOME + "  claim: [sized]\n", message=None), "no message 'rule.sized'")


HOUSE_STYLE = (
    "house_style:\n  palettes:\n"
    "    - theme: print\n      tokens:\n        - {role: proof, value: \"#000000\"}\n"
    "    - theme: light\n      tokens:\n        - {role: proof, value: \"#1F4F7A\"}\n        - {role: paper, value: \"#f1eee6\"}\n")


def with_house_style(d: Path, text: str) -> Path:
    with (d / "channels.yaml").open("a") as f:
        f.write(text)
    return d


def test_a_house_style_reaches_the_bundle_in_a_fixed_order(fixture):
    """A pack gives its own values for colour roles of std-view; the bundle carries them, the themes in the
    contract's order and the roles by name, whatever order the pack wrote them in."""
    bundle = json.loads(emit.compile_pack(pack.read(with_house_style(fixture, HOUSE_STYLE)))["bundle/schema-bundle.json"])
    assert bundle["channels"]["house_style"] == {"palettes": [
        {"theme": "light", "tokens": [{"role": "paper", "value": "#f1eee6"}, {"role": "proof", "value": "#1F4F7A"}]},
        {"theme": "print", "tokens": [{"role": "proof", "value": "#000000"}]}]}


def test_a_pack_without_a_house_style_has_none_in_its_bundle(fixture):
    assert "house_style" not in json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])["channels"]


@pytest.mark.parametrize("text, message", [
    ("house_style: {}\n", "a house style is a list of palettes"),
    ("house_style:\n  palettes: []\n", "a house style is a list of palettes"),
    ("house_style:\n  palettes: [{theme: light, tokens: [{role: ink, value: '#000000'}]}]\n  fonts: []\n", "a house style is a list of palettes"),
    ("house_style:\n  palettes: [{theme: forced_colors, tokens: [{role: paper, value: '#ffffff'}]}]\n", "its theme one of light, dark, print"),
    ("house_style:\n  palettes:\n    - {theme: light, tokens: [{role: ink, value: '#000000'}]}\n"
     "    - {theme: light, tokens: [{role: paper, value: '#ffffff'}]}\n", "each theme once"),
    ("house_style:\n  palettes: [{theme: light, tokens: []}]\n", "a token is {role, value}"),
    ("house_style:\n  palettes: [{theme: light, tokens: [{role: status.valid, value: '#2d6a30'}]}]\n", "its role one the contract lets a house style set"),
    ("house_style:\n  palettes: [{theme: light, tokens: [{role: sheet, value: '#ffffff'}]}]\n", "its role one the contract lets a house style set"),
    ("house_style:\n  palettes: [{theme: light, tokens: [{role: ink, value: '#000000'}, {role: ink, value: '#111111'}]}]\n", "each role once"),
    ("house_style:\n  palettes: [{theme: light, tokens: [{role: paper, value: Canvas}]}]\n", "the value of 'paper' is not a hex colour"),
    ("house_style:\n  palettes: [{theme: light, tokens: [{role: paper, value: '#fff'}]}]\n", "the value of 'paper' is not a hex colour"),
    ("house_style:\n  palettes: [{theme: dark, tokens: [{role: paper, value: '#10161D'}, {role: ink, value: '#10161d'}]}]\n",
     "dark: 'ink' has the value of the paper"),
])
def test_a_wrong_house_style_is_refused(fixture, text, message):
    """Correctness blocks: a theme or a role a house style may not set, a value that is no colour, a role twice,
    and ink that cannot be seen on its paper. Which themes and roles may be set is the contract's."""
    refused(with_house_style(fixture, text), message)


ORDERED = FLOW.replace("slot: beta.state, level: nominal", "slot: beta.alpha, level: ordered")


def test_a_flow_without_a_lane_order_is_refused(fixture):
    """A lane bound as ordered says that the place of a lane means something, so its order is declared:
    there is no alphabetical fallback. The target kind of the lane's arrow has no order here."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(ORDERED)
    refused(fixture, "flow chain: lane 'beta.alpha' of beta is bound as ordered, but alpha has no order: "
                     "give it a whole-number slot with slot_uri schema:position, or bind the lane at level nominal")


@pytest.mark.parametrize("slot, change", [
    ("size", lambda a: a["size"].update(slot_uri="schema:position")),  # the order role (S26)
    ("lane_order", lambda a: a.update(lane_order={"range": "integer"})),  # until every pack carries the role
])
def test_an_ordered_lane_has_the_order_of_its_target_kind(fixture, slot, change):
    """The order of an ordered lane on an arrow is the target kind's: its slot with the order role, or, until every
    pack carries the role, its own whole-number attribute `lane_order`."""
    edit_schema(fixture, lambda s: change(s["classes"]["Alpha"]["attributes"]))
    with (fixture / "channels.yaml").open("a") as f:
        f.write(ORDERED)
    model = pack.read(fixture)
    assert pack.order_slot(model, "alpha").element == f"alpha.{slot}"
    [flow] = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])["channels"]["flows"]
    assert flow["nodes"][1]["lane"] == {"channel": "lane", "slot": "beta.alpha", "level": "ordered", "meaning_message": "m.state"}


@pytest.mark.parametrize("change", [
    lambda a: a.update(lane_order={"range": "string"}),  # not a whole number
    lambda a: a.update(lane_order={"range": "integer", "multivalued": True}),  # more than one place
])
def test_an_attribute_that_cannot_order_is_no_lane_order(fixture, change):
    edit_schema(fixture, lambda s: change(s["classes"]["Alpha"]["attributes"]))
    with (fixture / "channels.yaml").open("a") as f:
        f.write(ORDERED)
    refused(fixture, "is bound as ordered, but alpha has no order")


@pytest.mark.parametrize("level", ["ordered", "nominal"])
def test_enum_lanes_preserve_the_schema_order_and_bound_level(fixture, level):
    with (fixture / "channels.yaml").open("a") as f:
        f.write(FLOW.replace("level: nominal", f"level: {level}"))
    model = pack.read(fixture)
    assert not [w for w in model.warnings if "bound as ordered" in w]
    bundle = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])
    enum = next(e for e in bundle["enums"] if e["id"] == "state")
    assert enum["values"] == ["state.low", "state.high"]
    [flow] = bundle["channels"]["flows"]
    assert flow["nodes"][1]["lane"] == {"channel": "lane", "slot": "beta.state", "level": level, "meaning_message": "m.state"}


MATRIX = (
    "matrices:\n"
    "  - id: grid\n"
    "    title_message: m.grid\n"
    "    rows: {kind: beta}\n"
    "    columns: {kind: alpha}\n"
    "    cells: {arrow: beta.alpha}\n")


def test_a_matrix_binding_reaches_the_bundle(fixture):
    """A pack binds a Matrix from its own schema: rows and columns are kinds, cells an edge source between them."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(MATRIX)
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    assert bundle["channels"]["matrices"] == [{"id": "grid", "title_message": "m.grid", "rows": {"kind": "beta"},
                                               "columns": {"kind": "alpha"}, "cells": {"arrow": "beta.alpha"}}]


@pytest.mark.parametrize("change, message", [
    (("rows: {kind: beta}", "rows: {kind: gamma}"), "rows is a kind"),
    (("columns: {kind: alpha}", "columns: {kind: alpha, lane: x}"), "lane of columns is a lane binding"),
    (("columns: {kind: alpha}", "columns: {kind: alpha, group: x}"), "columns is a kind, with an optional lane"),
    (("rows: {kind: beta}", "rows: {kind: beta, lane: {channel: lane, slot: beta.state, level: ordered, meaning_message: m.state}}"), "rows is a kind"),
    # A Board's lane is an enum attribute of the column kind: alpha has none, and its title is text.
    (("columns: {kind: alpha}", "columns: {kind: alpha, lane: {channel: lane, slot: beta.state, level: ordered, meaning_message: m.state}}"), "is not a slot of alpha"),
    (("columns: {kind: alpha}", "columns: {kind: alpha, lane: {channel: lane, slot: alpha.title, level: nominal, meaning_message: m.state}}"), "is not a single-valued enum attribute of alpha"),
    # The direction counts: the arrow runs from beta to alpha, so beta's are the rows.
    (("rows: {kind: beta}\n    columns: {kind: alpha}", "rows: {kind: alpha}\n    columns: {kind: beta}"), "is not an arrow between node kinds"),
    (("{arrow: beta.alpha}", "{arrow: beta.alpha, quantity: {}}"), "cells have no quantity"),
    (("{arrow: beta.alpha}", "{relation: near, from: a, to: b, from_kinds: [beta], to_kinds: [alpha]}"), "is not a derived relation"),
    (("  - id: grid", "  - id: Grid"), "an id is lower case"),
    (("    title_message: m.grid\n", ""), "a matrix needs id, title_message, rows, columns and cells"),
])
def test_a_wrong_matrix_binding_is_refused(fixture, change, message):
    """Correctness blocks: a Matrix that names no such kind or edge source, or reads it the wrong way round, stops
    the compile."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(MATRIX.replace(*change))
    refused(fixture, message)


def test_a_matrix_with_a_lane_on_its_columns_is_a_board(fixture):
    """A Board (docs/gui.md): the column axis has a lane on a single-valued enum attribute of its kind, and the
    binding reaches the bundle with the lane's slot under the pack's names."""
    edit_schema(fixture, lambda s: s["classes"]["Alpha"]["attributes"].update(state={"range": "State"}))
    lane = "lane: {channel: lane, slot: alpha.state, level: ordered, meaning_message: m.state}"
    with (fixture / "channels.yaml").open("a") as f:
        f.write(MATRIX.replace("columns: {kind: alpha}", f"columns: {{kind: alpha, {lane}}}"))
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    assert bundle["channels"]["matrices"][0]["columns"] == {
        "kind": "alpha", "lane": {"channel": "lane", "slot": "alpha.state", "level": "ordered", "meaning_message": "m.state"}}


def test_a_second_matrix_with_the_same_id_is_refused(fixture):
    with (fixture / "channels.yaml").open("a") as f:
        f.write(MATRIX + MATRIX.split("\n", 1)[1])
    refused(fixture, "a second matrix 'grid'")


REPORT = (
    "reports:\n"
    "  - id: sheet\n"
    "    title_message: r.sheet\n"
    "    parts:\n"
    "      - cards: {kind: beta, fields: [beta.alpha, beta.state]}\n")


def test_a_report_binding_reaches_the_bundle(fixture):
    """A pack binds a Report of cards: a kind and fields of its page template, kept in the order given."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(REPORT)
    bundle = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])
    assert bundle["channels"]["reports"] == [{"id": "sheet", "title_message": "r.sheet", "parts": [
        {"cards": {"kind": "beta", "fields": ["beta.alpha", "beta.state"]}}]}]
    assert set(bundle["channels"]["reports"][0]["parts"][0]["cards"]["fields"]) <= set(
        next(p for p in bundle["pages"] if p["kind"] == "beta")["fields"])


@pytest.mark.parametrize("change, message", [
    (("kind: beta,", "kind: gamma,"), "'gamma' is not a kind"),
    (("beta.alpha, beta.state", "beta.alpha, alpha.state"), "alpha.state is not"),
    (("beta.alpha, beta.state", "beta.state, beta.state"), "none twice"),
    (("beta.alpha, beta.state", ""), "fields are one or more slots"),
    (("- cards: {kind: beta,", "- matrix: {kind: beta,"), "a matrix needs only a sheet binding id"),
    (("    parts:\n      - cards: {kind: beta, fields: [beta.alpha, beta.state]}\n", "    parts: []\n"), "parts is a list of one or more"),
    (("  - id: sheet", "  - id: Sheet"), "an id is lower case"),
    (("    title_message: r.sheet\n", ""), "a report needs id, title_message and parts"),
])
def test_a_wrong_report_binding_is_refused(fixture, change, message):
    """Correctness blocks: cards of no such kind, or showing a field that is not on the kind's page, stop the compile."""
    with (fixture / "channels.yaml").open("a") as f:
        f.write(REPORT.replace(*change))
    refused(fixture, message)


def test_a_second_report_with_the_same_id_is_refused(fixture):
    with (fixture / "channels.yaml").open("a") as f:
        f.write(REPORT + REPORT.split("\n", 1)[1])
    refused(fixture, "a second report 'sheet'")


def add_kinds(fixture: Path, link_key: bool = True) -> None:
    """Gamma, a kind Beta points to; Delta, a kind between Alpha and Beta, a link kind when its key holds both."""
    def change(schema):
        schema["classes"]["Beta"]["attributes"]["gamma"] = {"range": "Gamma"}
        schema["classes"]["Gamma"] = {"attributes": {"id": {"identifier": True}}}
        schema["classes"]["Delta"] = {"attributes": {"id": {"identifier": True}, "a": {"range": "Alpha", "required": True},
                                                     "b": {"range": "Beta", "required": True}}}
        if link_key:
            schema["classes"]["Delta"]["unique_keys"] = {"delta_pair": {"unique_key_slots": ["a", "b"]}}
    edit_schema(fixture, change)


def test_a_group_and_a_link_kind_reach_the_bundle(fixture):
    """A node's group is a single-valued arrow of it to a kind that is no node kind; `via` is a link kind whose key
    holds both its arrows."""
    add_kinds(fixture)
    with (fixture / "channels.yaml").open("a") as f:
        f.write(FLOW.replace("level: nominal, meaning_message: m.state}}", "level: nominal, meaning_message: m.state}, group: beta.gamma}")
                .replace("{arrow: beta.alpha}", "{via: delta, from: delta.a, to: delta.b}"))
    [flow] = json.loads(emit.compile_pack(pack.read(fixture))["bundle/schema-bundle.json"])["channels"]["flows"]
    assert flow["nodes"][1]["group"] == "beta.gamma" and flow["edges"] == [{"via": "delta", "from": "delta.a", "to": "delta.b"}]


@pytest.mark.parametrize("change, link_key, message", [
    (("meaning_message: m.state}}", "meaning_message: m.state}, group: beta.state}"), True, "is not a single-valued arrow of beta"),
    (("meaning_message: m.state}}", "meaning_message: m.state}, group: beta.alpha}"), True, "points to a node kind"),
    (("{arrow: beta.alpha}", "{via: delta, from: delta.a, to: delta.b}"), False, "needs a link kind whose key holds from and to"),
    (("{arrow: beta.alpha}", "{via: delta, from: delta.a, to: delta.a}"), True, "needs a link kind whose key holds from and to"),
])
def test_a_wrong_group_or_link_kind_is_refused(fixture, change, link_key, message):
    add_kinds(fixture, link_key)
    with (fixture / "channels.yaml").open("a") as f:
        f.write(FLOW.replace(*change))
    refused(fixture, message)


def test_two_flows_with_one_id_are_refused(fixture):
    with (fixture / "channels.yaml").open("a") as f:
        f.write(FLOW + FLOW[len("flows:\n"):])
    refused(fixture, "a second flow 'chain'")


def test_embedded_ids_are_injective(fixture, tmp_path):
    """Two parents with the same id in different kinds, and ids with '/', never give the same child id."""
    def change(s):
        s["classes"]["Part"] = {"attributes": {"note": {}}}
        for name in ("One", "Two"):
            s["classes"][name] = {"attributes": {"id": {"identifier": True},
                                                 "part": {"range": "Part", "inlined": True}}}
    edit_schema(fixture, change)
    (fixture / "facts.yaml").write_text(
        "one: [{id: x, part: {note: a}}, {id: 'x/one.part', part: {note: b}}]\n"
        "two: [{id: x, part: {note: c}}]\n")
    rows = facts.load(pack.read(fixture), fixture / "facts.yaml")
    ids = [r[0] for r in rows["part"]]
    assert len(ids) == len(set(ids)) == 3
    assert "x/one.part" in ids and "x/two.part" in ids and "x%2Fone.part/one.part" in ids


def test_check_reads_the_pack_and_every_fact_file(fixture, capsys):
    """`check` is the quick test for a pack author: no compile, but the schema, labels, messages and facts."""
    from rezono_compiler.__main__ import main
    (fixture / "facts").mkdir()
    (fixture / "facts" / "good.yaml").write_text("alpha: [{id: a, title: t}]\n")
    assert main(["check", str(fixture)]) == 0
    assert "good.yaml 2 rows" in capsys.readouterr().out
    (fixture / "facts" / "bad.yaml").write_text("alpha: [{id: a, title: t, size: many}]\n")
    assert main(["check", str(fixture)]) == 1
    assert "facts/bad.yaml" in capsys.readouterr().err


@pytest.mark.parametrize("text, ok", [("'2026-01-02'", True), ("2026-01-02", True), ("'2026-1-2'", False),
                                      ("'2026-02-30'", False), ("2026-01-02T10:00:00", False)],
                         ids=["iso-text", "yaml-date", "short", "no-such-day", "timestamp"])
def test_a_date_is_a_yaml_date_or_iso_text(fixture, tmp_path, text, ok):
    """JSON has no dates, so a fact file written as JSON gives a date as ISO text; both load the same."""
    edit_schema(fixture, lambda s: s["classes"]["Alpha"]["attributes"].update(since={"range": "date"}))
    (tmp_path / "facts.yaml").write_text(f"alpha: [{{id: a, title: t, since: {text}}}]\n")
    model = pack.read(fixture)
    if ok:
        import datetime
        assert ("a", datetime.date(2026, 1, 2)) in facts.load(model, tmp_path / "facts.yaml")["alpha__since"]
    else:
        with pytest.raises(facts.LoadError, match="is not a DATE"):
            facts.load(model, tmp_path / "facts.yaml")


def report_with_waterfall(fixture, part):
    edit_schema(fixture, lambda s: s["classes"]["Beta"]["attributes"].update(
        total={"range": "integer", "annotations": {"currency": "EUR"}}))
    with (fixture / "channels.yaml").open("a") as f:
        f.write(REPORT + "      - " + part + "\n")


def test_a_report_waterfall_preserves_typed_slot_without_instance_ids(fixture):
    report_with_waterfall(fixture, "waterfall: {slot: beta.total}")
    first = emit.compile_pack(pack.read(fixture))
    assert first == emit.compile_pack(pack.read(fixture))
    report = json.loads(first["bundle/schema-bundle.json"])["channels"]["reports"][0]
    assert report["parts"] == [
        {"cards": {"kind": "beta", "fields": ["beta.alpha", "beta.state"]}},
        {"waterfall": {"slot": "beta.total"}}]


@pytest.mark.parametrize("part,message", [
    ("waterfall: {slot: beta.state}", "is not an amount attribute"),
    ("waterfall: {slot: gamma.total}", "is not an amount attribute"),
    ("waterfall: {slot: beta.total, element: b1}", "no instance ids or selector"),
    ("waterfall: {}", "no instance ids or selector"),
    ("waterfall: {slot: beta.total, query: all}", "no instance ids or selector"),
    ("{cards: {kind: beta, fields: [beta.state]}, waterfall: {slot: beta.total}}", "is cards"),
])
def test_a_wrong_report_waterfall_is_refused(fixture, part, message):
    report_with_waterfall(fixture, part)
    refused(fixture, message)


# A comparison: `alike` ends in a verdict per alpha; `echo` writes a variable where a verdict would stand.
COMPARISON_RULES = (
    ".decl alike(a: symbol, verdict: symbol)\n"
    "alike(a, \"same\") :- alpha(a), beta__alpha(_, a).\n"
    "alike(a, \"other\") :- alpha(a).\n"
    ".decl echo(a: symbol, verdict: symbol)\n"
    "echo(a, a) :- alpha(a).\n")


def report_with_comparison(d: Path, part: str) -> Path:
    (d / "rules").mkdir()
    (d / "rules" / "core.dl").write_text(COMPARISON_RULES)
    with (d / "channels.yaml").open("a") as f:
        f.write(REPORT + "      - " + part + "\n")
    return d


def test_a_report_comparison_reaches_the_bundle(fixture):
    report_with_comparison(fixture, "comparison: {relation: alike, verdict: verdict, equal: [same], different: [other]}")
    first = emit.compile_pack(pack.read(fixture))
    assert first == emit.compile_pack(pack.read(fixture))
    report = json.loads(first["bundle/schema-bundle.json"])["channels"]["reports"][0]
    assert report["parts"][1] == {"comparison": {"relation": "alike", "verdict": "verdict", "equal": ["same"], "different": ["other"]}}


@pytest.mark.parametrize("part,message", [
    # Unknown is explicit: a verdict a rule can give and no class names stops the pack.
    ("comparison: {relation: alike, verdict: verdict, equal: [same]}", "gives the verdict 'other', which no class names"),
    ("comparison: {relation: echo, verdict: verdict, equal: [x]}", "gives its verdict from a variable"),
    ("comparison: {relation: alike, verdict: verdict, equal: [same], different: [same, other]}", "exactly one class"),
    ("comparison: {relation: alike, verdict: a, equal: [same], different: [other]}", "rule alike_1 gives its verdict from a variable"),
    ("comparison: {relation: alike, verdict: state, equal: [same], different: [other]}", "is not a column of alike"),
    ("comparison: {relation: beta, verdict: state, equal: [x]}", "is not a derived relation"),
    ("comparison: {relation: alike, equal: [same]}", "needs relation and verdict"),
    ("comparison: {relation: alike, verdict: verdict, equal: same, different: [other]}", "a class is a list"),
])
def test_a_wrong_report_comparison_is_refused(fixture, part, message):
    report_with_comparison(fixture, part)
    refused(fixture, message)


def test_report_reuses_a_declared_matrix_binding(fixture):
    with (fixture / "channels.yaml").open("a") as file:
        file.write(REPORT + "      - matrix: {sheet: grid}\n" + MATRIX)
    first = emit.compile_pack(pack.read(fixture))
    assert first == emit.compile_pack(pack.read(fixture))
    result = json.loads(first["bundle/schema-bundle.json"])["channels"]
    assert result["reports"][0]["parts"][1] == {"matrix": {"sheet": "grid"}}
    assert result["matrices"][0]["id"] == "grid"


@pytest.mark.parametrize("part,message", [
    ("matrix: {sheet: missing}", "is not a Matrix binding"),
    ("matrix: {sheet: grid, role: audit}", "needs only a sheet binding id"),
    ("matrix: {sheet: grid, manifest: other}", "needs only a sheet binding id"),
    ("matrix: {sheet: grid, element: fixed}", "needs only a sheet binding id"),
    ("matrix: {sheet: 'file:///private'}", "needs only a sheet binding id"),
    ("matrix: {}", "needs only a sheet binding id"),
    ("{matrix: {sheet: grid}, cards: {kind: beta, fields: [beta.state]}}", "is cards"),
])
def test_report_matrix_refuses_selectors_and_unknown_sheet(fixture, part, message):
    with (fixture / "channels.yaml").open("a") as file:
        file.write(REPORT + "      - " + part + "\n" + MATRIX)
    refused(fixture, message)


# A Timeline and a Nest on the fixture: alpha gets dates and a state, beta is a part of its alpha.
TIMELINE = (
    "timelines:\n"
    "  - id: validity\n"
    "    title_message: t.validity\n"
    "    rows: alpha\n"
    "    label: alpha.title\n"
    "    start: alpha.valid_from\n"
    "    end: alpha.valid_until\n"
    "    extension: alpha.extended_until\n"
    "    main_message: t.valid\n"
    "    extension_message: t.extended\n"
    "    judgement: {channel: tone, slot: alpha.state, level: ordered, meaning_message: t.state}\n"
    "    marks:\n"
    "      - {slot: alpha.decided_on}\n")
TIMELINE_MESSAGES = ("t.validity", "t.valid", "t.extended", "t.state")
NEST = (
    "nests:\n"
    "  - id: parts\n"
    "    title_message: n.parts\n"
    "    part_message: n.part\n"
    "    levels:\n"
    "      - {kind: alpha, label: alpha.title, flow: row, order_message: n.order}\n"
    "      - {kind: beta, part_of: beta.alpha}\n"
    "    perspectives:\n"
    "      - {id: plain, label_message: n.plain}\n"
    "      - id: rated\n"
    "        label_message: n.rated\n"
    "        relation: rating\n"
    "        part: b\n"
    "        origin: a\n"
    "        state: {channel: tone, slot: s, level: ordered, meaning_message: n.state}\n")
NEST_MESSAGES = ("n.parts", "n.part", "n.order", "n.plain", "n.rated", "n.state")
RATING = ".decl rating(a: symbol, b: symbol, s: symbol)\nrating(a, b, s) :- beta__alpha(b, a), beta__state(b, s).\n"


def sheets(d: Path, table: str, messages=(), lang: str = "nl") -> Path:
    """The fixture with dates and a state on alpha and a relation over beta, `table` added to its channel table and
    a message per id in `lang`."""
    edit_schema(d, lambda s: s["classes"]["Alpha"]["attributes"].update(
        {x: {"range": "date"} for x in ("valid_from", "valid_until", "extended_until", "decided_on")}
        | {"state": {"range": "State"}, "days": {"range": "date", "multivalued": True}}))
    (d / "rules").mkdir(exist_ok=True)
    (d / "rules" / "core.dl").write_text(RATING)
    with (d / "channels.yaml").open("a") as f:
        f.write(table)
    with (d / "messages" / f"{lang}.mf2").open("a", encoding="utf-8") as f:
        f.writelines(f"{m} = {{{{{m}}}}}\n" for m in messages)
    return d


def test_a_timeline_and_a_nest_reach_the_bundle(fixture):
    """A pack binds a Timeline and a Nest from its own schema and rules; the bundle carries them under the pack's
    names, in the contract's shape, and two compiles give the same bytes."""
    model = pack.read(sheets(fixture, TIMELINE + NEST, TIMELINE_MESSAGES + NEST_MESSAGES))
    first = emit.compile_pack(model)
    assert first == emit.compile_pack(pack.read(fixture))
    channels = json.loads(first["bundle/schema-bundle.json"])["channels"]
    assert channels["timelines"] == [{
        "id": "validity", "title_message": "t.validity", "rows": "alpha", "label": "alpha.title",
        "start": "alpha.valid_from", "end": "alpha.valid_until", "extension": "alpha.extended_until",
        "main_message": "t.valid", "extension_message": "t.extended",
        "judgement": {"channel": "tone", "slot": "alpha.state", "level": "ordered", "meaning_message": "t.state"},
        "marks": [{"slot": "alpha.decided_on"}]}]
    assert channels["nests"] == [{
        "id": "parts", "title_message": "n.parts", "part_message": "n.part",
        "levels": [{"kind": "alpha", "label": "alpha.title", "flow": "row", "order_message": "n.order"},
                   {"kind": "beta", "part_of": "beta.alpha"}],
        "perspectives": [{"id": "plain", "label_message": "n.plain"},
                         {"id": "rated", "label_message": "n.rated", "relation": "rating", "part": "b", "origin": "a",
                          "state": {"channel": "tone", "slot": "s", "level": "ordered", "meaning_message": "n.state"}}]}]


def test_a_timeline_needs_only_its_row_kind_two_dates_and_their_names(fixture):
    least = "".join(line + "\n" for line in TIMELINE.splitlines() if line.split(":")[0].strip() in (
        "timelines", "- id", "title_message", "rows", "start", "end", "main_message"))
    model = pack.read(sheets(fixture, least, ("t.validity", "t.valid")))
    assert model.channels["timelines"] == [{"id": "validity", "title_message": "t.validity", "rows": "alpha",
                                            "start": "alpha.valid_from", "end": "alpha.valid_until", "main_message": "t.valid"}]


@pytest.mark.parametrize("change, message", [
    (("rows: alpha", "rows: gamma"), "timeline validity: rows 'gamma' is not a kind"),
    (("start: alpha.valid_from", "start: alpha.days"), "timeline validity: start 'alpha.days' is not a single-valued date attribute of alpha"),
    (("end: alpha.valid_until", "end: alpha.title"), "timeline validity: end 'alpha.title' is not a single-valued date attribute of alpha"),
    (("extension: alpha.extended_until", "extension: beta.alpha"), "timeline validity: extension 'beta.alpha' is not a slot of alpha"),
    (("{slot: alpha.decided_on}", "{slot: alpha.size}"), "timeline validity: mark 'alpha.size' is not a single-valued date attribute of alpha"),
    (("{slot: alpha.decided_on}", "{slot: alpha.valid_from}"), "timeline validity: mark 'alpha.valid_from' is bound twice"),
    (("end: alpha.valid_until", "end: alpha.valid_from"), "timeline validity: end 'alpha.valid_from' is bound twice"),
    (("label: alpha.title", "label: alpha.size"), "timeline validity: label 'alpha.size' is not a text attribute of alpha"),
    (("    extension_message: t.extended\n", ""), "timeline validity: .*an extension has an extension_message"),
    (("    extension: alpha.extended_until\n", ""), "timeline validity: .*only an extension has one"),
    (("channel: tone", "channel: lane"), "timeline validity: judgement is a tone binding"),
    (("level: ordered", "level: nominal"), "timeline validity: judgement is a tone binding"),
    (("slot: alpha.state, level", "slot: alpha.days, level"), "timeline validity: judgement 'alpha.days' is not a single-valued attribute of alpha"),
    (("      - {slot: alpha.decided_on}\n", "      - {slot: alpha.decided_on, sign: x}\n"), "timeline validity: marks is a list, each a slot"),
    (("  - id: validity", "  - id: Validity"), "timeline Validity: an id is lower case"),
    (("    main_message: t.valid\n", ""), "a timeline needs id, title_message, rows, start, end and main_message"),
    (("    rows: alpha\n", "    rows: alpha\n    as_of: alpha.valid_from\n"), "a timeline needs id, title_message, rows, start, end and main_message"),
])
def test_a_wrong_timeline_binding_is_refused(fixture, change, message):
    """Correctness blocks: a Timeline on a kind that is not there, on an attribute that is no single date of that
    kind, or without the name of its extension stops the compile, with the section and the id in the message."""
    assert change[0] in TIMELINE
    sheets(fixture, TIMELINE.replace(*change), TIMELINE_MESSAGES)
    refused(fixture, f"channels.yaml: {message}")


def test_a_second_timeline_or_nest_with_the_same_id_is_refused(fixture):
    sheets(fixture, TIMELINE + TIMELINE.split("\n", 1)[1], TIMELINE_MESSAGES)
    refused(fixture, "channels.yaml: a second timeline 'validity'")
    (fixture / "channels.yaml").write_text((fixture / "channels.yaml").read_text().split("timelines:")[0] + NEST + NEST.split("\n", 1)[1])
    refused(fixture, "channels.yaml: a second nest 'parts'")


@pytest.mark.parametrize("table, given, missing, form", [
    (TIMELINE, TIMELINE_MESSAGES, "t.extended", "timeline 'validity'"),
    (TIMELINE, TIMELINE_MESSAGES, "t.state", "timeline 'validity'"),
    (NEST, NEST_MESSAGES, "n.order", "nest 'parts'"),
    (NEST, NEST_MESSAGES, "n.state", "nest 'parts'"),
])
def test_a_sheet_message_is_needed_in_every_language(fixture, table, given, missing, form):
    """A Timeline and a Nest are read in every language the pack carries: a name of theirs that one language lacks
    stops the compile, also where that language is not the default."""
    sheets(fixture, table, given)
    pack.read(fixture)
    (fixture / "messages" / "en.mf2").write_text("@locale en\n---\n" + "".join(f"{m} = {{{{{m}}}}}\n" for m in given if m != missing))
    refused(fixture, f"messages/en.mf2: no message '{missing}' for {form}")
    (fixture / "messages" / "en.mf2").unlink()
    text = (fixture / "messages" / "nl.mf2").read_text(encoding="utf-8")
    (fixture / "messages" / "nl.mf2").write_text(text.replace(f"{missing} = {{{{{missing}}}}}\n", ""), encoding="utf-8")
    refused(fixture, f"messages/nl.mf2: no message '{missing}' for {form}")


@pytest.mark.parametrize("change, message", [
    (("      - {kind: beta, part_of: beta.alpha}\n", ""), "nest parts: levels is a list of two levels at least"),
    (("kind: beta, part_of", "kind: gamma, part_of"), "nest parts: level 'gamma' is not a kind, or is there twice"),
    (("kind: beta, part_of", "kind: alpha, part_of"), "nest parts: level 'alpha' is not a kind, or is there twice"),
    (("{kind: beta, part_of: beta.alpha}", "{kind: beta}"), "nest parts: level beta: every level but the first has part_of"),
    (("kind: alpha, label", "kind: alpha, part_of: beta.alpha, label"), "nest parts: level alpha: every level but the first has part_of"),
    (("part_of: beta.alpha", "part_of: beta.state"), "nest parts: part_of 'beta.state' is not a single-valued arrow of beta to alpha"),
    (("part_of: beta.alpha", "part_of: alpha.title"), "nest parts: part_of 'alpha.title' is not a slot of beta"),
    (("flow: row, ", ""), "nest parts: level alpha: every level but the last has a flow"),
    (("flow: row", "flow: grid"), "nest parts: level alpha: every level but the last has a flow"),
    (("part_of: beta.alpha}", "part_of: beta.alpha, flow: column}"), "nest parts: level beta: every level but the last has a flow"),
    (("label: alpha.title", "label: alpha.size"), "nest parts: label 'alpha.size' is not a text attribute of alpha"),
    (("id: rated", "id: plain"), "nest parts: a perspective has an id"),
    (("        relation: rating\n", ""), "nest parts: a perspective has an id"),
    (("        part: b\n", ""), "nest parts: a perspective has an id"),
    (("relation: rating", "relation: ranking"), "nest parts: perspective rated: 'ranking' is not a derived relation"),
    (("part: b", "part: c"), "nest parts: perspective rated: part and origin are different text columns of rating"),
    (("origin: a", "origin: b"), "nest parts: perspective rated: part and origin are different text columns of rating"),
    (("slot: s, level", "slot: b, level"), "nest parts: perspective rated: state 'b' is not another column of rating"),
    (("slot: s, level: ordered", "slot: s, level: nominal"), "nest parts: state of perspective rated is a tone binding"),
    (("    part_message: n.part\n", ""), "a nest needs id, title_message, part_message and levels"),
    (("  - id: parts", "  - id: Parts"), "nest Parts: an id is lower case"),
])
def test_a_wrong_nest_binding_is_refused(fixture, change, message):
    """Correctness blocks: a Nest with one level, with a level that is no part of the level before it, or with a
    perspective that does not name its part and state stops the compile, with the section and the id in the
    message."""
    assert change[0] in NEST
    sheets(fixture, NEST.replace(*change), NEST_MESSAGES)
    refused(fixture, f"channels.yaml: {message}")


def test_a_part_of_arrow_to_many_is_no_tree(fixture):
    edit_schema(fixture, lambda s: s["classes"]["Beta"]["attributes"]["alpha"].update(multivalued=True))
    sheets(fixture, NEST, NEST_MESSAGES)
    refused(fixture, "nest parts: part_of 'beta.alpha' is not a single-valued arrow of beta to alpha")


def test_an_installed_compiler_reads_the_contracts_it_carries(tmp_path):
    """A non-editable install of the compiler, built from a copy of compiler/ and contracts/ and run from a
    directory outside any checkout, carries the runtime contracts byte for byte as package data, reads them from there,
    and compiles a pack given by path to the same bytes as the compiler of this checkout."""
    import os
    import subprocess
    import sys

    from rezono_compiler.native_literals import LITERALS_SCHEMA

    repo, src = pack.CONTRACTS.parent, tmp_path / "src"
    contracts = [*pack.CONTRACTS.glob("*.yaml"), pack.CONTRACTS / LITERALS_SCHEMA]
    (src / "contracts").mkdir(parents=True)
    for p in contracts:
        shutil.copy(p, src / "contracts" / p.name)
    shutil.copytree(repo / "compiler" / "rezono_compiler", src / "compiler" / "rezono_compiler",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "setup.py"):
        shutil.copy(repo / "compiler" / name, src / "compiler" / name)
    site, work = (tmp_path / "site").resolve(), (tmp_path / "work").resolve()
    work.mkdir()
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "--no-build-isolation", "--no-index",
                    "--target", str(site), str(src / "compiler")], cwd=work, check=True)
    shipped = site / "rezono_compiler" / "contracts"
    assert tree(shipped) == {p.name: p.read_bytes() for p in contracts}
    # The installed copy first; the dependencies from this interpreter's path, without the checkout's compiler.
    own = Path(pack.__file__).resolve().parents[1]
    path = [str(site)] + [p for p in sys.path if p and Path(p).resolve() != own]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(path)}
    probe = "from rezono_compiler import pack; print(pack.__file__); print(pack.contract_dir())"
    where = subprocess.run([sys.executable, "-c", probe], cwd=work, env=env, capture_output=True, text=True, check=True)
    assert [Path(line).resolve() for line in where.stdout.splitlines()] == [site / "rezono_compiler" / "pack.py", shipped]
    subprocess.run([sys.executable, "-m", "rezono_compiler", "compile", str(FIXTURE), str(work / "out")], cwd=work, env=env,
                   check=True)
    expected, out = tmp_path / "expected", tree(work / "out")
    compile_dir(FIXTURE, expected)  # the CLI writes generated/sources.json beside these
    assert {name: out.get(name) for name in tree(expected)} == tree(expected)


def test_missing_contracts_are_an_error_that_names_where_it_looked(tmp_path, monkeypatch):
    monkeypatch.setattr(pack, "CONTRACTS", tmp_path / "contracts")
    with pytest.raises(pack.CompileError, match="the compiler's contracts are missing"):
        pack.contract_dir()


def test_the_golden_form_keeps_the_bundle_in_full():
    """A compiled file above the bound is in the golden by its hash, except a file named in FULL
    (the schema bundle), which other tools read back from the golden."""
    import golden

    big = "x" * (golden.LARGE + 1)
    form = golden.golden({"bundle/schema-bundle.json": big, "batch/big.sql": big, "small.txt": "s"})
    assert "bundle/schema-bundle.json" in golden.FULL
    assert form["bundle/schema-bundle.json"] == big.encode("utf-8")
    assert form["small.txt"] == b"s"
    assert "batch/big.sql" not in form
    assert json.loads(form[golden.MANIFEST]) == [{
        "path": "batch/big.sql", "sha256": hashlib.sha256(big.encode("utf-8")).hexdigest(), "bytes": str(len(big))}]
    # Nothing hashed, no manifest.
    assert golden.MANIFEST not in golden.golden({"bundle/schema-bundle.json": big, "small.txt": "s"})


def test_a_failed_golden_explains_itself_in_a_few_lines():
    """golden.differences names each file missing, extra or changed, and a changed file's first differing line. Its
    report stays a few lines on a large tree, where pytest's own explanation of a failed `==` (a whole-tree ndiff)
    kept the nightly `examples` shard busy for two hours on 15-11-2026."""
    import golden

    want = {"a.sql": b"one\ntwo\nthree\n", "b.json": b"{}\n", "gone.txt": b"x"}
    got = {"a.sql": b"one\n2\nthree\n", "b.json": b"{}\n", "new.txt": b"y"}
    assert golden.differences(want, dict(want)) == ""
    assert golden.differences(got, want).splitlines() == [
        "missing: gone.txt", "extra: new.txt", "changed: a.sql, 3 lines expected and 3 got, first at line 2:",
        "  - b'two'", "  - b'three'", "  + b'2'", "  + b'three'"]
    # A shorter file differs where it ends.
    assert "first at line 3:" in golden.differences({"a.sql": b"one\ntwo\n"}, {"a.sql": b"one\ntwo\nthree\n"})
    # A tree the size of the largest example's golden, every line shifted by one: still one line per file and six of context.
    lines = b"".join(b'      "line": "%d",\n' % i for i in range(200_000))
    assert len(golden.differences({"big.json": b"\n" + lines}, {"big.json": lines}).splitlines()) == 7


def test_no_committed_manifest_hashes_an_always_full_file(monkeypatch):
    """A committed large-files.json never lists a file of FULL: such a file is read back from the golden, so a
    regeneration under an older golden.py must not leave it as a hash. Reads the goldens only."""
    import golden

    examples = REPO / "examples"
    recorded = Path(__file__).resolve().parent / "fixtures" / "recorded-output" / golden.MANIFEST
    manifests = [recorded, *sorted(examples.glob(f"**/expected/compiled/{golden.MANIFEST}"))]
    hashed = [f"{m.relative_to(REPO).as_posix()}: {e['path']}" for m in manifests
              for e in json.loads(m.read_text(encoding="utf-8")) if e["path"] in golden.FULL]
    assert not hashed, hashed

    bundle = '{"kinds":["Item"]}\n'
    monkeypatch.setattr(golden, "LARGE", 8)
    assert golden.golden({"bundle/schema-bundle.json": bundle, "engine/tables.sql": "SELECT 1;\n"}) == {
        "bundle/schema-bundle.json": bundle.encode("utf-8"),
        golden.MANIFEST: recorded.read_text(encoding="utf-8").encode("utf-8"),
    }
