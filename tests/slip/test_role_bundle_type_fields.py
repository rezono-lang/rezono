"""Type and naming fields in the role's part of the bundle (decisions/viewer-slip.md, "The role's part of the bundle").

Extends a copy of `tests/fixtures/slip` with:
- money attributes in distinct currencies (`item.fee` in EUR, readable by both roles; `link.secret_fee` in JPY,
  readable by `reader` only);
- kind naming metadata (`item.label` as `name_attribute`, `hold.item` as `name_arrows`, `tag` with one visible arrow
  `tag.item` and one restricted arrow `tag.link`);
- a native derived relation with typed and money columns (`item_priced`, `link_priced`), named outcomes
  (`item_status`, `link_status`), and calculated relations (`calc__capped_amount`, `calc__link_fee_total`).

All expectations are derived by hand from those schema, rule and calc declarations.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from slip_support import PACK, ROOT, ask, node, publish_main


def _extend_pack(pack: Path) -> None:
    schema_path = pack / "schema" / "slip.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema["prefixes"] = {"rdfs": "http://www.w3.org/2000/01/rdf-schema#"}
    schema["types"] = {
        "EurCents": {"typeof": "integer", "annotations": {"currency": "EUR"}},
        "JpyUnits": {"typeof": "integer", "annotations": {"currency": "JPY"}},
    }
    schema["classes"]["Item"]["attributes"]["label"] = {"range": "string", "slot_uri": "rdfs:label"}
    schema["classes"]["Item"]["attributes"]["fee"] = {"range": "EurCents", "minimum_value": 0}
    schema["classes"]["Hold"]["unique_keys"] = {"by_item": {"unique_key_slots": ["item"]}}
    schema["classes"]["Link"]["attributes"]["secret_fee"] = {"range": "JpyUnits", "minimum_value": 0}
    schema["classes"]["Link"]["unique_keys"] = {"by_ends": {"unique_key_slots": ["tail", "head"]}}
    schema["classes"]["Tag"] = {
        "attributes": {
            "id": {"identifier": True},
            "item": {"range": "Item", "required": True},
            "link": {"range": "Link", "required": True},
        },
        "unique_keys": {"by_pair": {"unique_key_slots": ["item", "link"]}},
    }
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")

    access_path = pack / "rules" / "access.dl"
    access_path.write_text(
        access_path.read_text(encoding="utf-8")
        + '\nmay_read(r, "tag", t) :- role__capability(r, "read"), tag(t).\n'
        + 'may_read_full(r, "tag") :- role__capability(r, "read").\n',
        encoding="utf-8",
        newline="\n",
    )

    rezono_dir = pack / "rezono"
    rezono_dir.mkdir(exist_ok=True)
    source = rezono_dir / "fees.rezono"
    form = rezono_dir / "fees.json"
    source.write_text(
        "rezono 0\n"
        "pack slip\n"
        "rule item_priced(item: Item, fee: EurCents) when item in Item and item.fee = fee\n"
        "rule link_priced(link: Link, fee: JpyUnits) when link in Link and link.secret_fee = fee\n",
        encoding="utf-8",
        newline="\n",
    )
    compiled = subprocess.run(
        [node(), str(ROOT / "rezono" / "src" / "write-form.ts"), str(source), str(form)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert compiled.returncode == 0, compiled.stderr

    meta_path = pack / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["rezono"] = [{"module": "rezono/fees.rezono", "form": "rezono/fees.json", "layer": "conclusions"}]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8", newline="\n")

    flagged_path = pack / "rules" / "flagged.dl"
    flagged_path.write_text(
        flagged_path.read_text(encoding="utf-8")
        + "\n"
        + "// @outcome item\n"
        + ".decl item_status(item: symbol, state: symbol, reason: symbol)\n"
        + 'item_status(i, "known", "") :- item(i).\n',
        encoding="utf-8",
        newline="\n",
    )

    links_path = pack / "rules" / "links.dl"
    links_path.write_text(
        links_path.read_text(encoding="utf-8")
        + "\n"
        + "// @outcome link\n"
        + ".decl link_status(link: symbol, state: symbol, reason: symbol)\n"
        + 'link_status(l, "known", "") :- link(l).\n\n'
        + ".decl item_link_fee(item: symbol, fee: number)\n"
        + "item_link_fee(i, f) :- link__tail(l, i), link__secret_fee(l, f).\n",
        encoding="utf-8",
        newline="\n",
    )

    calc_path = pack / "calc" / "capped.yaml"
    calc_doc = yaml.safe_load(calc_path.read_text(encoding="utf-8"))
    calc_doc["rules"].append({
        "id": "link_fee_total@v1",
        "rule": "link_fee_total",
        "version": "v1",
        "output": "link_fee_total.value",
        "unit": "JPY",
        "valid_from": "2026-01-01",
        "valid_until": "2027-01-01",
        "known_from": "2026-01-01",
        "definitions": [{
            "name": "link_fee_base",
            "when": {"boolean": True},
            "value": {"fact": "item_link_fee.fee"},
        }],
    })
    calc_path.write_text(yaml.safe_dump(calc_doc, sort_keys=False), encoding="utf-8", newline="\n")

    facts_path = pack / "facts" / "rows.yaml"
    facts = yaml.safe_load(facts_path.read_text(encoding="utf-8"))
    facts["item"][0].update({"label": "Alpha", "fee": 1250})
    facts["item"][1].update({"label": "Beta", "fee": 400})
    facts["item"][2].update({"label": "Gamma"})
    facts["link"][0].update({"secret_fee": 900})
    facts["tag"] = [{"id": "tag-a", "item": "item-a", "link": "link-a"}]
    facts_path.write_text(yaml.safe_dump(facts, sort_keys=False), encoding="utf-8", newline="\n")


@pytest.fixture(scope="module")
def published_bundle_store(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict]:
    return publish_main(tmp_path_factory.mktemp("slip-bundle-types"), change=_extend_pack)


def _role_bundle(store: Path, role: str, manifest_id: str) -> dict:
    [answer] = ask(store, role, f"/{PACK}/bundle?m={manifest_id}")
    assert answer["status"] == 200, answer
    return answer["body"]


def _by_id(entries: list[dict]) -> dict[str, dict]:
    return {entry["id"]: entry for entry in entries}


def _columns_by_name(relation: dict) -> dict[str, dict]:
    return {column["name"]: column for column in relation["columns"]}


def test_role_bundle_exposes_money_attribute_and_kind_naming_fields(published_bundle_store):
    store, manifest = published_bundle_store
    reader = _role_bundle(store, "reader", manifest["id"])

    attributes = _by_id(reader["attributes"])
    assert attributes["item.fee"].get("currency") == "EUR"
    assert attributes["item.fee"].get("semantic") == {
        "case": "money",
        "base": "integer",
        "range": "EurCents",
        "currency": "EUR",
    }
    assert "currency" not in attributes["item.amount"]
    assert attributes["item.amount"].get("semantic") == {
        "case": "scalar",
        "base": "integer",
        "range": "integer",
    }

    arrows = _by_id(reader["arrows"])
    assert arrows["hold.item"].get("semantic") == {
        "case": "ref",
        "base": "string",
        "range": "item",
        "target": "item",
    }

    kinds = _by_id(reader["kinds"])
    assert kinds["item"].get("name_attribute") == "item.label"
    assert "name_arrows" not in kinds["item"]
    assert kinds["hold"].get("name_arrows") == ["hold.item"]
    assert "name_attribute" not in kinds["hold"]
    assert kinds["tag"].get("name_arrows") == ["tag.item", "tag.link"]
    assert "name_attribute" not in kinds["group"]
    assert "name_arrows" not in kinds["group"]


def test_role_bundle_exposes_calc_outcome_and_column_type_fields(published_bundle_store):
    store, manifest = published_bundle_store
    reader = _role_bundle(store, "reader", manifest["id"])
    relations = _by_id(reader["relations"])

    calc = relations["calc__capped_amount"]
    assert calc.get("calc") == "capped_amount"
    assert calc.get("semantic") == {
        "case": "derived",
        "base": "number",
        "unit": "count",
        "derived": "capped_amount",
    }
    assert "outcome" not in calc

    priced = relations["item_priced"]
    assert "calc" not in priced
    assert "outcome" not in priced
    priced_cols = _columns_by_name(priced)
    assert "currency" not in priced_cols["item"]
    assert priced_cols["item"].get("semantic") == {
        "case": "ref",
        "base": "string",
        "range": "item",
        "target": "item",
    }
    assert priced_cols["fee"].get("currency") == "EUR"
    assert priced_cols["fee"].get("semantic") == {
        "case": "money",
        "base": "integer",
        "range": "slip.EurCents",
        "currency": "EUR",
    }

    status = relations["item_status"]
    assert status.get("outcome") == "item"
    assert "calc" not in status

    flagged = relations["flagged"]
    assert "calc" not in flagged
    assert "outcome" not in flagged


def test_role_bundle_hides_unreadable_type_fields_without_leak(published_bundle_store):
    store, manifest = published_bundle_store
    reader = _role_bundle(store, "reader", manifest["id"])
    summary = _role_bundle(store, "summary", manifest["id"])

    # `reader` reads `link` and `role`, so it receives their naming, money, outcome and calc type fields.
    reader_kinds = _by_id(reader["kinds"])
    assert reader_kinds["link"].get("name_arrows") == ["link.tail", "link.head"]
    assert reader_kinds["role"].get("name_attribute") == "role.title"
    reader_attrs = _by_id(reader["attributes"])
    assert reader_attrs["link.secret_fee"].get("currency") == "JPY"
    assert reader_attrs["link.secret_fee"].get("semantic") == {
        "case": "money",
        "base": "integer",
        "range": "JpyUnits",
        "currency": "JPY",
    }
    reader_rels = _by_id(reader["relations"])
    assert _columns_by_name(reader_rels["link_priced"])["fee"].get("currency") == "JPY"
    assert reader_rels["link_status"].get("outcome") == "link"
    assert reader_rels["calc__link_fee_total"].get("calc") == "link_fee_total"
    assert reader_rels["calc__link_fee_total"].get("semantic") == {
        "case": "derived",
        "base": "number",
        "unit": "JPY",
        "derived": "link_fee_total",
    }

    # `summary` reads neither `link` nor `role`: omitted elements and their fields look absent, with zero leak.
    summary_kinds = _by_id(summary["kinds"])
    assert "link" not in summary_kinds
    assert "role" not in summary_kinds
    assert summary_kinds["tag"].get("name_arrows") == ["tag.item"]

    summary_attrs = _by_id(summary["attributes"])
    assert not ({"link.secret_fee", "role.title", "role.capability"} & set(summary_attrs))

    summary_arrows = _by_id(summary["arrows"])
    assert not ({"link.tail", "link.head", "tag.link"} & set(summary_arrows))

    summary_rels = _by_id(summary["relations"])
    assert not ({"link_priced", "link_status", "item_link_fee", "calc__link_fee_total", "linked"} & set(summary_rels))

    serialized = json.dumps(summary)
    for forbidden in ("JPY", "JpyUnits", "secret_fee", "link_priced", "link_status", "link_fee_total", "tag.link",
                      "role.title"):
        assert forbidden not in serialized, f"summary role bundle leaked {forbidden!r}"
