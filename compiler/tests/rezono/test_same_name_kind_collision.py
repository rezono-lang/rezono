"""Two independent source packs declaring a kind with the same name (`Partner`) must never silently merge
(decisions/healthcare-allowance-three-sources.md, docs/formal.md § Design: theories, views and colimits).

An unqualified reference to `Partner` must fail with a diagnostic naming both candidate sources; qualified
references (`use ... as ...`, `civil.Partner` and `tax.Partner`) must compile to two distinct kinds with
distinct arrows and attributes while sharing the pinned `Persoon` kind.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler import modules, native_rule_signatures, pack, rezono_module
from support import FIXTURE, compile_dir


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
    shutil.copytree(FIXTURE / "messages", directory / "messages")
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: Preserve import-alias qualification when "
           "lowering Rezono slots and allow a module with distinct `use <pack> as <alias>` prefixes to import "
           "two packs that each declare a kind with the same name (`Partner`) without merging or refusing "
           "qualified references (`civil.Partner`, `tax.Partner`).",
)
def test_same_name_kinds_across_two_sources_stay_disjoint_with_qualified_imports(tmp_path: Path):
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/healthcare-allowance-three-sources.md: An unqualified reference to `Partner` when "
           "two imported sources each declare `Partner` must produce a diagnostic naming both candidate sources "
           "(both in schema lowering and in native rule signatures), while qualified references (`civil.Partner`, "
           "`tax.Partner`) resolve cleanly to distinct engine kinds.",
)
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
