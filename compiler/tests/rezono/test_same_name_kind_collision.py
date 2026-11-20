"""Two independent source packs declaring a kind with the same name (`Partner`) must never silently merge
(decisions/healthcare-allowance-three-sources.md, docs/formal.md § Design: theories, views and colimits).

An unqualified reference to `Partner` must fail with a diagnostic naming both candidate sources; qualified
references (`use ... as ...`, `civil.Partner` and `tax.Partner`) must compile to two distinct kinds with
distinct arrows and attributes while sharing the pinned `Persoon` kind.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rezono_compiler import modules, native_rule_signatures, pack, rezono_module
from support import compile_dir


def _spans(body: dict) -> list[dict]:
    def fixture_line(pointer: str) -> int:
        group, index, *rest = pointer[1:].split("/")
        if group == "use":
            return 3 + int(index)
        base = 10 * (1 + int(index))
        if rest[:1] == ["slots"]:
            return base + 1 + int(rest[1])
        return base

    return [
        {"at": pointer, "line": str(fixture_line(pointer)), "start": "0", "end": "1"}
        for pointer in rezono_module.place_pointers(body)
    ]


def _write_pack(
    directory: Path,
    pack_name: str,
    module_name: str,
    decls: list[dict],
    *,
    imports: list[tuple[str, Path]] = (),
    uses: list[dict] = (),
    labels: str = "",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "channels.yaml").write_text("{}\n", encoding="utf-8", newline="\n")
    (directory / "messages").mkdir()
    (directory / "messages" / "en.mf2").write_text(
        "@locale en\n---\n" + "".join(f"{key} = {{{{{key}}}}}\n" for key in pack.MESSAGES),
        encoding="utf-8",
        newline="\n",
    )
    (directory / "labels").mkdir()
    (directory / "labels" / "en.yaml").write_text(labels, encoding="utf-8", newline="\n")
    (directory / "rezono").mkdir()

    body = {"rezono": "0", "pack": pack_name, "use": list(uses), "decls": decls}
    form = {"format": "rezono.module/1", "module": body, "spans": _spans(body)}
    (directory / "rezono" / f"{module_name}.json").write_bytes(
        json.dumps(form, sort_keys=True).encode("utf-8")
    )
    (directory / "rezono" / f"{module_name}.rezono").write_text(
        f"rezono 0\npack {pack_name}\n", encoding="utf-8", newline="\n"
    )

    meta = {
        "name": pack_name,
        "version": "0.1.0",
        "default_language": "en",
        "imports": [
            {"name": name, "path": f"../{path.name}", "sha256": modules.pack_hash(path)}
            for name, path in imports
        ],
        "rezono": [
            {
                "module": f"rezono/{module_name}.rezono",
                "form": f"rezono/{module_name}.json",
                "layer": "facts",
            }
        ],
    }
    (directory / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))
    return directory


def _build_sources(base: Path) -> tuple[Path, Path, Path]:
    """Create a shared `person` pack (`Persoon`) and two independent source packs (`civil`, `tax`)
    that each declare their own `Partner` kind."""
    person = _write_pack(
        base / "person",
        "person",
        "person",
        [{"kind": "Persoon", "world": "closed", "slots": [], "derived": []}],
        labels="persoon: person\n",
    )
    civil = _write_pack(
        base / "civil",
        "civil",
        "civil",
        [
            {
                "kind": "Partner",
                "world": "closed",
                "slots": [
                    {"slot": "persoon_a", "type": "Persoon"},
                    {"slot": "persoon_b", "type": "Persoon"},
                    {"slot": "echtscheidingsverzoek", "type": "Bool"},
                ],
                "derived": [],
            }
        ],
        imports=[("person", person)],
        uses=[{"use": "person"}],
        labels=(
            "partner: civil partner\n"
            "partner.persoon_a: person a\n"
            "partner.persoon_b: person b\n"
            "partner.echtscheidingsverzoek: divorce petition\n"
        ),
    )
    tax = _write_pack(
        base / "tax",
        "tax",
        "tax",
        [
            {
                "kind": "Partner",
                "world": "closed",
                "slots": [
                    {"slot": "persoon_a", "type": "Persoon"},
                    {"slot": "persoon_b", "type": "Persoon"},
                    {"slot": "grond", "type": "Text"},
                ],
                "derived": [],
            }
        ],
        imports=[("person", person)],
        uses=[{"use": "person"}],
        labels=(
            "partner: fiscal partner\n"
            "partner.persoon_a: person a\n"
            "partner.persoon_b: person b\n"
            "partner.grond: fiscal basis\n"
        ),
    )
    return person, civil, tax


def _native_form(pack_name: str, decls: list[dict], uses: list[dict]) -> dict:
    body = {"rezono": "0", "pack": pack_name, "use": uses, "decls": decls}
    places = []

    def walk(value: object, at: str):
        if isinstance(value, dict):
            yield at
            for key, child in sorted(value.items()):
                yield from walk(child, f"{at}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from walk(child, f"{at}/{index}")

    for section in ("decls", "use"):
        for index, node in enumerate(body[section]):
            line = index + (3 if section == "use" else 3 + len(uses))
            for pointer in walk(node, f"/{section}/{index}"):
                start = str(100 * line)
                places.append({"at": pointer, "line": str(line), "start": start, "end": start})
    return {"format": "rezono.module/3", "module": body, "spans": places}


def test_qualified_cross_pack_same_name_kinds_stay_disjoint(tmp_path: Path):
    base = tmp_path / "qualified"
    person, civil, tax = _build_sources(base)
    allowance = _write_pack(
        base / "allowance",
        "allowance",
        "allowance",
        [
            {
                "kind": "Review",
                "world": "closed",
                "slots": [
                    {"slot": "applicant", "type": "Persoon"},
                    {"slot": "civil_partner", "type": "civil.Partner"},
                    {"slot": "fiscal_partner", "type": "tax.Partner"},
                ],
                "derived": [],
            }
        ],
        imports=[("person", person), ("civil", civil), ("tax", tax)],
        uses=[
            {"use": "person"},
            {"use": "civil", "as": "civil"},
            {"use": "tax", "as": "tax"},
        ],
        labels=(
            "review: review\n"
            "review.applicant: applicant\n"
            "review.civil_partner: civil partner\n"
            "review.fiscal_partner: fiscal partner\n"
        ),
    )

    try:
        compiled = compile_dir(allowance, tmp_path / "qualified-out")
    except pack.CompileError as error:
        raise AssertionError(
            f"qualified imports of two Partner kinds failed to compile: {error}"
        ) from error

    bundle = json.loads(compiled["bundle/schema-bundle.json"])
    kinds_by_module = {kind["module"]: kind for kind in bundle["kinds"]}
    assert "civil:civil" in kinds_by_module, kinds_by_module
    assert "tax:tax" in kinds_by_module, kinds_by_module
    civil_partner_id = kinds_by_module["civil:civil"]["id"]
    tax_partner_id = kinds_by_module["tax:tax"]["id"]
    assert civil_partner_id != tax_partner_id, (
        "two Partner kinds from independent sources silently merged into one kind"
    )

    # Shared Persoon is unified once through the pinned person pack.
    person_kinds = [kind for kind in bundle["kinds"] if kind["module"] == "person:person"]
    assert len(person_kinds) == 1, person_kinds

    # Each Partner kind keeps only its own source's attributes.
    attrs_by_kind: dict[str, set[str]] = {}
    for attr in bundle["attributes"]:
        owner, _, slot = attr["id"].partition(".")
        attrs_by_kind.setdefault(owner, set()).add(slot)
    assert "echtscheidingsverzoek" in attrs_by_kind.get(civil_partner_id, set())
    assert "grond" not in attrs_by_kind.get(civil_partner_id, set())
    assert "grond" in attrs_by_kind.get(tax_partner_id, set())
    assert "echtscheidingsverzoek" not in attrs_by_kind.get(tax_partner_id, set())

    # Qualified arrows on Review resolve to the two distinct Partner kinds.
    arrows = {arrow["id"]: arrow["target"] for arrow in bundle["arrows"]}
    assert arrows["review.civil_partner"] == civil_partner_id
    assert arrows["review.fiscal_partner"] == tax_partner_id


def test_unqualified_same_name_kind_reports_both_candidates(tmp_path: Path):
    # 1. Schema slot level: unaliased `use civil` and `use tax` with bare `Partner` must fail naming both.
    schema_base = tmp_path / "unqualified-schema"
    person, civil, tax = _build_sources(schema_base)
    ambiguous = _write_pack(
        schema_base / "allowance",
        "allowance",
        "allowance",
        [
            {
                "kind": "Review",
                "world": "closed",
                "slots": [{"slot": "partner", "type": "Partner"}],
                "derived": [],
            }
        ],
        imports=[("person", person), ("civil", civil), ("tax", tax)],
        uses=[{"use": "person"}, {"use": "civil"}, {"use": "tax"}],
        labels="review: review\nreview.partner: partner\n",
    )

    with pytest.raises(pack.CompileError) as schema_err:
        pack.read(ambiguous)
    schema_msg = str(schema_err.value)
    assert "civil:civil" in schema_msg and "tax:tax" in schema_msg, schema_msg
    assert "of this pack" not in schema_msg, (
        f"cross-pack ambiguity should not falsely claim the candidates are 'of this pack': {schema_msg}"
    )

    # 2. Native rule signature level: bare `Partner` must refuse with R046 naming BOTH candidates,
    # while `civil.Partner` and `tax.Partner` must link to distinct engine kinds.
    rule_base = tmp_path / "unqualified-rules"
    r_person, r_civil, r_tax = _build_sources(rule_base)
    consumer = rule_base / "allowance"
    consumer.mkdir()
    (consumer / "pack.yaml").write_bytes(
        yaml.safe_dump(
            {
                "name": "allowance",
                "version": "0.1.0",
                "default_language": "en",
                "imports": [
                    {"name": "person", "path": "../person", "sha256": modules.pack_hash(r_person)},
                    {"name": "civil", "path": "../civil", "sha256": modules.pack_hash(r_civil)},
                    {"name": "tax", "path": "../tax", "sha256": modules.pack_hash(r_tax)},
                ],
            },
            sort_keys=False,
        ).encode("utf-8")
    )

    bad_decls = [
        {
            "rule": "seen_partner",
            "columns": [{"name": "p", "type": "Partner"}],
            "when": {"in": [{"path": ["p"]}, {"kind": "Partner"}]},
        }
    ]
    bad_forms = {
        ("allowance", "rezono/rules.rezono"): _native_form(
            "allowance", bad_decls, [{"use": "civil"}, {"use": "tax"}]
        )
    }
    with pytest.raises(pack.CompileError) as rule_err:
        native_rule_signatures.link(consumer, bad_forms)
    r046 = [d for d in rule_err.value.diagnostics if d.code == "R046"]
    assert r046, rule_err.value.diagnostics
    rule_msg = " ".join(d.message for d in r046)
    assert "civil" in rule_msg and "tax" in rule_msg, (
        f"R046 diagnostic for ambiguous Partner must name both candidates (civil and tax), got: {rule_msg}"
    )

    good_decls = [
        {
            "rule": "both_partners",
            "columns": [
                {"name": "cp", "type": "civil.Partner"},
                {"name": "fp", "type": "tax.Partner"},
            ],
            "when": {
                "and": [
                    {"in": [{"path": ["cp"]}, {"kind": "civil.Partner"}]},
                    {"in": [{"path": ["fp"]}, {"kind": "tax.Partner"}]},
                ]
            },
        }
    ]
    good_forms = {
        ("allowance", "rezono/rules.rezono"): _native_form(
            "allowance",
            good_decls,
            [{"use": "civil", "as": "civil"}, {"use": "tax", "as": "tax"}],
        )
    }
    try:
        linked = native_rule_signatures.link(consumer, good_forms)
    except pack.CompileError as error:
        raise AssertionError(
            f"qualified civil.Partner and tax.Partner in native rules failed to link: {error}"
        ) from error
    cols = linked.signatures["both_partners"].key
    assert cols[0][1] != cols[1][1], f"qualified Partner columns merged to the same kind: {cols}"


def _write_v2_pack(
    directory: Path,
    pack_name: str,
    module_name: str,
    decls: list[dict],
    *,
    imports: list[tuple[str, Path]] = (),
    uses: list[dict] = (),
    labels: str = "",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "channels.yaml").write_text("{}\n", encoding="utf-8", newline="\n")
    (directory / "messages").mkdir()
    (directory / "messages" / "en.mf2").write_text(
        "@locale en\n---\n" + "".join(f"{key} = {{{{{key}}}}}\n" for key in pack.MESSAGES),
        encoding="utf-8",
        newline="\n",
    )
    (directory / "labels").mkdir()
    (directory / "labels" / "en.yaml").write_text(labels, encoding="utf-8", newline="\n")
    (directory / "rezono").mkdir()

    body = {"rezono": "0", "pack": pack_name, "use": list(uses), "decls": decls}
    form = {"format": "rezono.module/2", "module": body, "spans": _spans(body)}
    (directory / "rezono" / f"{module_name}.json").write_bytes(
        json.dumps(form, sort_keys=True).encode("utf-8")
    )
    (directory / "rezono" / f"{module_name}.rezono").write_text(
        f"rezono 0\npack {pack_name}\n", encoding="utf-8", newline="\n"
    )

    meta = {
        "name": pack_name,
        "version": "0.1.0",
        "default_language": "en",
        "imports": [
            {"name": name, "path": f"../{path.name}", "sha256": modules.pack_hash(path)}
            for name, path in imports
        ],
        "rezono": [
            {
                "module": f"rezono/{module_name}.rezono",
                "form": f"rezono/{module_name}.json",
                "layer": "facts",
            }
        ],
    }
    (directory / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))
    return directory


def _build_inheritance_sources(
    base: Path,
    *,
    civil_relationship: bool = False,
    tax_relationship: bool = False,
) -> tuple[Path, Path, Path]:
    """Create `person` (`Persoon`) plus `civil` (`Partner` with `civil_id: Int` and `soort: Text`)
    and `tax` (`Partner` with `tax_id: Text` and `grond: Text`), with optional `relationship: true`."""
    person = _write_v2_pack(
        base / "person",
        "person",
        "person",
        [{"kind": "Persoon", "world": "closed", "slots": [], "derived": []}],
        labels="persoon: person\n",
    )

    civil_decl: dict = {
        "kind": "Partner",
        "world": "closed",
        "slots": [
            {"slot": "civil_id", "type": "Int", "identifier": True},
            {"slot": "persoon_a", "type": "Persoon"},
            {"slot": "persoon_b", "type": "Persoon"},
            {"slot": "soort", "type": "Text"},
        ],
        "derived": [],
    }
    civil_labels = (
        "partner: civil partner\n"
        "partner.persoon_a: person a\n"
        "partner.persoon_b: person b\n"
        "partner.soort: civil kind\n"
    )
    if civil_relationship:
        civil_decl["relationship"] = True
        civil_decl["keys"] = [{"unique": "civil_pair", "slots": ["persoon_a", "persoon_b"]}]
        civil_labels += "partner.civil_pair: civil pair\n"

    civil = _write_v2_pack(
        base / "civil",
        "civil",
        "civil",
        [civil_decl],
        imports=[("person", person)],
        uses=[{"use": "person"}],
        labels=civil_labels,
    )

    tax_decl: dict = {
        "kind": "Partner",
        "world": "closed",
        "slots": [
            {"slot": "tax_id", "type": "Text", "identifier": True},
            {"slot": "persoon_a", "type": "Persoon"},
            {"slot": "persoon_b", "type": "Persoon"},
            {"slot": "grond", "type": "Text"},
        ],
        "derived": [],
    }
    tax_labels = (
        "partner: fiscal partner\n"
        "partner.persoon_a: person a\n"
        "partner.persoon_b: person b\n"
        "partner.grond: fiscal basis\n"
    )
    if tax_relationship:
        tax_decl["relationship"] = True
        tax_decl["keys"] = [{"unique": "tax_pair", "slots": ["persoon_a", "persoon_b"]}]
        tax_labels += "partner.tax_pair: tax pair\n"

    tax = _write_v2_pack(
        base / "tax",
        "tax",
        "tax",
        [tax_decl],
        imports=[("person", person)],
        uses=[{"use": "person"}],
        labels=tax_labels,
    )
    return person, civil, tax


def test_qualified_parent_allows_other_same_name_kind_slot_and_inherits_identifier(tmp_path: Path):
    """`CivilSub` (`parent: civil.Partner`) can declare `grond: Text` (which exists only on `tax.Partner`),
    inherits `civil_id` (not `tax_id`) across single and multi-hop inheritance, and uses `civil_id`'s
    integer storage in native rule signatures."""
    base = tmp_path / "own-slot-ok"
    person, civil, tax = _build_inheritance_sources(base)
    allowance = _write_v2_pack(
        base / "allowance",
        "allowance",
        "allowance",
        [
            {
                "kind": "CivilSub",
                "parent": "civil.Partner",
                "slots": [{"slot": "grond", "type": "Text"}],
                "derived": [],
            },
            {
                "kind": "CivilLeaf",
                "parent": "CivilSub",
                "slots": [{"slot": "note", "type": "Text"}],
                "derived": [],
            },
            {
                "kind": "Partner",
                "parent": "civil.Partner",
                "slots": [{"slot": "local_tag", "type": "Text"}],
                "derived": [],
            },
            {
                "kind": "Review",
                "world": "closed",
                "slots": [
                    {"slot": "civil_sub", "type": "CivilSub"},
                    {"slot": "tax_partner", "type": "tax.Partner"},
                ],
                "derived": [],
            },
        ],
        imports=[("person", person), ("civil", civil), ("tax", tax)],
        uses=[
            {"use": "civil", "as": "civil"},
            {"use": "tax", "as": "tax"},
        ],
        labels=(
            "civil_sub: civil sub\n"
            "civil_sub.grond: own basis\n"
            "civil_leaf: civil leaf\n"
            "civil_leaf.note: note\n"
            "allowance_partner: local partner\n"
            "allowance_partner.local_tag: local tag\n"
            "review: review\n"
            "review.civil_sub: civil sub\n"
            "review.tax_partner: tax partner\n"
        ),
    )

    loaded = pack.read(allowance)
    assert loaded.kinds["civil_sub"].parent == "civil_civil_partner"
    assert loaded.kinds["civil_sub"].identifier == "civil_id"
    assert loaded.kinds[loaded.root("civil_sub")].id_type == "BIGINT"
    assert "grond" in loaded.kinds["civil_sub"].slots
    assert loaded.slot("civil_sub", "soort") is not None
    assert loaded.slot("civil_sub", "soort").kind == "civil_civil_partner"
    assert loaded.kinds["civil_leaf"].parent == "civil_sub"
    assert loaded.kinds["civil_leaf"].identifier == "civil_id"
    assert loaded.kinds["allowance_partner"].parent == "civil_civil_partner"
    assert loaded.kinds["allowance_partner"].identifier == "civil_id"

    # Native rule signatures must also resolve CivilSub's inherited identifier storage from civil.Partner (Int),
    # not from tax.Partner (Text).
    forms = {
        ("allowance", "rezono/rules.rezono"): _native_form(
            "allowance",
            [
                {
                    "rule": "civil_sub_rule",
                    "columns": [{"name": "s", "type": "CivilSub"}],
                    "when": {"in": [{"path": ["s"]}, {"kind": "CivilSub"}]},
                }
            ],
            [{"use": "civil", "as": "civil"}, {"use": "tax", "as": "tax"}],
        )
    }
    linked = native_rule_signatures.link(allowance, forms)
    assert linked.signatures["civil_sub_rule"].key == (("s", "civil_sub", "integer"),)


def test_qualified_parent_rejects_redefining_true_parent_slot(tmp_path: Path):
    """`CivilSub` (`parent: civil.Partner`) declaring `soort: Int` (inherited as `Text` from `civil.Partner`)
    must be rejected even when `tax.Partner` (which has no `soort`) is imported later in the same module."""
    base = tmp_path / "redefine-rejected"
    person, civil, tax = _build_inheritance_sources(base)
    allowance = _write_v2_pack(
        base / "allowance",
        "allowance",
        "allowance",
        [
            {
                "kind": "CivilSub",
                "parent": "civil.Partner",
                "slots": [{"slot": "soort", "type": "Int"}],
                "derived": [],
            },
            {
                "kind": "Review",
                "world": "closed",
                "slots": [{"slot": "tax_partner", "type": "tax.Partner"}],
                "derived": [],
            },
        ],
        imports=[("person", person), ("civil", civil), ("tax", tax)],
        uses=[
            {"use": "civil", "as": "civil"},
            {"use": "tax", "as": "tax"},
        ],
        labels=(
            "civil_sub: civil sub\n"
            "civil_sub.soort: conflicting kind\n"
            "review: review\n"
            "review.tax_partner: tax partner\n"
        ),
    )

    with pytest.raises(pack.CompileError) as err:
        pack.read(allowance)
    assert "CivilSub.soort: redefines an inherited slot, which is not supported" in str(err.value)


def test_qualified_parent_relationship_flag_follows_resolved_parent(tmp_path: Path):
    """`relationship: true` on `tax.Partner` must NOT leak onto `CivilSub` (`parent: civil.Partner`),
    while `relationship: true` on `civil.Partner` MUST propagate to `CivilSub` and NOT leak onto `TaxSub`."""
    # Case A: tax.Partner is a relationship, civil.Partner is not.
    base_a = tmp_path / "rel-tax-only"
    person_a, civil_a, tax_a = _build_inheritance_sources(
        base_a, civil_relationship=False, tax_relationship=True
    )
    app_a = _write_v2_pack(
        base_a / "allowance",
        "allowance",
        "allowance",
        [
            {
                "kind": "CivilSub",
                "parent": "civil.Partner",
                "slots": [{"slot": "extra", "type": "Text"}],
                "derived": [],
            },
            {
                "kind": "TaxSub",
                "parent": "tax.Partner",
                "slots": [{"slot": "tax_extra", "type": "Text"}],
                "derived": [],
            },
        ],
        imports=[("person", person_a), ("civil", civil_a), ("tax", tax_a)],
        uses=[
            {"use": "civil", "as": "civil"},
            {"use": "tax", "as": "tax"},
        ],
        labels=(
            "civil_sub: civil sub\n"
            "civil_sub.extra: extra\n"
            "tax_sub: tax sub\n"
            "tax_sub.tax_extra: tax extra\n"
        ),
    )
    pack_a = pack.read(app_a)
    assert pack_a.kinds["civil_sub"].relationship is False
    assert pack_a.kinds["tax_sub"].relationship is True

    # Case B: civil.Partner is a relationship, tax.Partner is not.
    base_b = tmp_path / "rel-civil-only"
    person_b, civil_b, tax_b = _build_inheritance_sources(
        base_b, civil_relationship=True, tax_relationship=False
    )
    app_b = _write_v2_pack(
        base_b / "allowance",
        "allowance",
        "allowance",
        [
            {
                "kind": "CivilSub",
                "parent": "civil.Partner",
                "slots": [{"slot": "extra", "type": "Text"}],
                "derived": [],
            },
            {
                "kind": "TaxSub",
                "parent": "tax.Partner",
                "slots": [{"slot": "tax_extra", "type": "Text"}],
                "derived": [],
            },
        ],
        imports=[("person", person_b), ("civil", civil_b), ("tax", tax_b)],
        uses=[
            {"use": "civil", "as": "civil"},
            {"use": "tax", "as": "tax"},
        ],
        labels=(
            "civil_sub: civil sub\n"
            "civil_sub.extra: extra\n"
            "tax_sub: tax sub\n"
            "tax_sub.tax_extra: tax extra\n"
        ),
    )
    pack_b = pack.read(app_b)
    assert pack_b.kinds["civil_sub"].relationship is True
    assert pack_b.kinds["tax_sub"].relationship is False
