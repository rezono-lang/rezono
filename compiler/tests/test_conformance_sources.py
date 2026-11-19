"""Inventory the specification records and check their migration into cases."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import TypedDict

import jsonschema
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/conformance"
TABLES = {
    "value": "docs/semantics/value-cases.yaml",
    "witness": "docs/semantics/witness-alternatives-cases.yaml",
}
PUBLICATION = ("X03", "Y01", "Y02", "Y03", "Y04")
PINS = "decisions/publication-case-pins.md"


class Entry(TypedDict):
    id: str
    source: str


class MissingConformanceCases(AssertionError):
    """A source record still needs a case file or an explicit deferral."""


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads((CORPUS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def inventory() -> list[Entry]:
    index = load_yaml(CORPUS / "sources.yaml")
    validator("sources.schema.json").validate(index)
    return index["sources"]


def source_records() -> dict[str, tuple[str, str]]:
    rows = []
    for family, path in TABLES.items():
        for record in load_yaml(ROOT / path)["cases"]:
            key = record["id"]
            rows.append((f"{family}-{key}", f"{path}#{key}", record.get("status", "settled")))
    for family, folder, keys in (
        ("publication", "docs/publication/cases", PUBLICATION),
        ("language", "docs/rezono/cases", ("E53",)),
    ):
        for key in keys:
            path = f"{folder}/{key}.yaml"
            record = load_yaml(ROOT / path)
            assert record["id"] == key
            rows.append((f"{family}-{key.lower()}", f"{path}#{key}", record["status"]))
    pins = re.findall(r"^\| ([A-Z][0-9]{2}) \|", (ROOT / PINS).read_text(encoding="utf-8"), re.M)
    assert pins, "publication pin decision has no case table"
    rows.extend((f"publication-{key.lower()}", f"{PINS}#{key}", "settled") for key in pins)
    assert len(rows) == len({key for key, _, _ in rows}), "duplicate specification record ID"
    return {key: (anchor, status) for key, anchor, status in rows}


def test_inventory_matches_the_specification_records():
    entries = inventory()
    actual = Counter((entry["id"], entry["source"]) for entry in entries)
    expected = Counter((key, anchor) for key, (anchor, _) in source_records().items())
    assert actual == expected, f"missing: {list(expected - actual)}\nextra: {list(actual - expected)}"


def check_decision(path: Path, source: str, *headings: str) -> str:
    text = path.read_text(encoding="utf-8")
    assert f"`{source}`" in text, f"{path.name} must cite {source}"
    for heading in headings:
        section = re.search(rf"^## {heading}[ \t]*$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if section:
            assert section.group(1).strip(), f"{path.name} needs a {heading} explanation"
            return heading
    raise AssertionError(f"{path.name} needs a {' or '.join(headings)} explanation")


def test_every_inventory_source_has_a_case_or_decision():
    records = source_records()
    schema = validator("case.schema.json")
    missing = []
    for entry in inventory():
        key, source = entry["id"], entry["source"]
        case_path = CORPUS / f"{key}.yaml"
        decision = ROOT / "decisions" / f"conformance-{key}.md"
        needs_adoption = records[key][1] in {"open", "gap"}
        if case_path.is_file():
            case = load_yaml(case_path)
            schema.validate(case)
            assert (case["id"], case["source"]) == (key, source), case_path.name
            if needs_adoption:
                check_decision(decision, source, "Adopted behavior")
        elif decision.is_file():
            headings = ("Deferral", "Adopted behavior") if needs_adoption else ("Deferral",)
            if check_decision(decision, source, *headings) == "Adopted behavior":
                missing.append(key)
        else:
            missing.append(key)
    if missing:
        raise MissingConformanceCases(f"{len(missing)} sources still need a case or decision: {', '.join(missing)}")
