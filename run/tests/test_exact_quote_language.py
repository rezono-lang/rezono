"""The exact-quote pack's quote module is written in Rezono and means what its LinkML and Datalog form meant.

See decisions/run-exact-quote-language.md and decisions/code-does-not-decide.md.
`run/fixtures/exact-quote-linkml/` keeps the replaced schema and rules byte for byte. The comparison
follows the whole-pack test of `scripts/convert_pack.py` scoped to `rezono/quote.rezono` and its
legacy conclusions, so the pack can carry additional Rezono modules and derived relations (such as
`effective_amount` and rate/currency facts) while keeping the quote module equivalent to the oracle.
"""

import hashlib
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from rezono_compiler import batch, pack, rules_dl
from rezono_publisher import batch as publisher_batch

from run import exact_quote
from scripts import convert_pack

RUN = Path(__file__).resolve().parents[1]
PACK = RUN / "packs" / "exact-quote"
ORACLE = RUN / "fixtures" / "exact-quote-linkml"
QUOTE_MODULE = "rezono/quote.rezono"
ROLES = {"checker": "complete"}
TIME = "2026-01-01T00:00:00Z"
CARRY = ("quote_carry", "quote_carry__amount", "quote_carry__position", "quote_carry__value")

# Two machines at 164,000 millionths for two periods and one at 479,000 (1,614,000 in total),
# repeated identical lines, a setup charge, an empty quote, and a line with no price digits.
QUOTES = {
    "priced": [(2, 2, 164000, 0), (1, 2, 479000, 0)],
    "repeated": [(2, 3, 1, 7), (2, 3, 1, 7)],
    "empty": [],
    "unpriced": [(0, 0, 0, 0)],
}


def _oracle_scope() -> tuple[set[str], set[str], set[str]]:
    """The kinds, arrows and labelable elements defined by the retained legacy oracle."""
    schema = yaml.safe_load((ORACLE / "schema" / "quote.yaml").read_text(encoding="utf-8"))
    classes = schema.get("classes") or {}
    kinds = {pack.snake(name) for name in classes}
    slots = set()
    arrows = set()
    for cls, body in classes.items():
        kind = pack.snake(cls)
        for slot, spec in (body.get("attributes") or {}).items():
            if isinstance(spec, dict) and spec.get("identifier"):
                continue
            element = f"{kind}.{slot}"
            slots.add(element)
            if isinstance(spec, dict) and spec.get("range") in classes:
                arrows.add(element)
    enum_elements = set()
    for enum, body in (schema.get("enums") or {}).items():
        name = pack.snake(enum)
        enum_elements.add(name)
        for value in body.get("permissible_values") or {}:
            enum_elements.add(f"{name}.{value}")
    rule_items = rules_dl.parse_file((ORACLE / "rules" / "amount.dl").read_text(encoding="utf-8"), "rules/amount.dl")
    derived_rels = {item[1] for item in rule_items if item[0] == "decl"}
    return kinds, arrows | derived_rels, kinds | slots | enum_elements | derived_rels


def _copy_presentation(target: Path) -> None:
    """Copy the pack's presentation files, scoped to the elements of the legacy quote oracle."""
    target.mkdir(parents=True, exist_ok=True)
    kinds, arrows, elements = _oracle_scope()
    labels_dir = PACK / "labels"
    if labels_dir.is_dir():
        dest = target / "labels"
        dest.mkdir(parents=True, exist_ok=True)
        for path in sorted(labels_dir.glob("*.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            scoped = {key: value for key, value in data.items() if key in elements}
            (dest / path.name).write_text(yaml.safe_dump(scoped, sort_keys=False), encoding="utf-8")
    messages_dir = PACK / "messages"
    if messages_dir.is_dir():
        shutil.copytree(messages_dir, target / "messages")
    channels_path = PACK / "channels.yaml"
    if channels_path.is_file():
        data = yaml.safe_load(channels_path.read_text(encoding="utf-8")) or {}
        scoped = dict(data)
        if isinstance(scoped.get("kinds"), list):
            scoped["kinds"] = [entry for entry in scoped["kinds"]
                               if isinstance(entry, dict) and entry.get("kind") in kinds]
        if isinstance(scoped.get("arrows"), list):
            scoped["arrows"] = [entry for entry in scoped["arrows"]
                                if isinstance(entry, dict) and entry.get("arrow") in arrows]
        if isinstance(scoped.get("images"), list):
            scoped["images"] = [entry for entry in scoped["images"]
                                if isinstance(entry, dict) and entry.get("kind") in kinds]
        (target / "channels.yaml").write_text(yaml.safe_dump(scoped, sort_keys=False), encoding="utf-8")


def legacy(directory: Path) -> Path:
    """The pack as it was: the retained schema and rules beside the scoped presentation files."""
    target = directory / "exact-quote"
    _copy_presentation(target)
    meta = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))
    meta.pop("rezono", None)
    meta["imports"] = []
    (target / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    shutil.copytree(ORACLE, target, dirs_exist_ok=True)
    return target


def quote_only(directory: Path) -> Path:
    """The Rezono quote module alone beside the scoped presentation files."""
    target = directory / "exact-quote"
    _copy_presentation(target)
    meta = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))
    entries = [entry for entry in meta.get("rezono", ()) if entry.get("module") == QUOTE_MODULE]
    assert len(entries) == 1, f"{QUOTE_MODULE} must be declared once in pack.yaml"
    entry = entries[0]
    for key in ("module", "form"):
        rel = Path(entry[key])
        destination = target / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACK / rel, destination)
    meta["imports"] = []
    meta["rezono"] = [entry]
    (target / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return target


@contextmanager
def evaluated(directory: Path, lines):
    """Run the production quote evaluation against one form of the pack."""
    read = pack.read
    original = exact_quote.pack
    exact_quote.pack = type("Reader", (), {"read": staticmethod(lambda _: read(directory))})
    try:
        with exact_quote._valued_quote([exact_quote._Line(*line) for line in lines]) as valued:
            yield valued
    finally:
        exact_quote.pack = original


def derived(directory: Path, lines) -> dict:
    with evaluated(directory, lines) as (_, program, connection):
        return batch.read(connection, program, sorted(program.derived()))


def facts(lines) -> dict:
    """Facts for a publication: the recorded digits and the carries the quote evaluation proposes."""
    def ref(value):
        return str(value).replace("/", "-")

    recorded = exact_quote._facts([exact_quote._Line(*line) for line in lines])
    with evaluated(PACK, lines) as (_, program, connection):
        carries = batch.read(connection, program, list(CARRY))
    one = {name: {row[0]: row[1] for row in recorded.get(name, ())}
           for name in ("recorded_line__quote", "quote_digit__line", "quote_digit__operand",
                        "quote_digit__position", "quote_digit__value")}
    carry = {name: {row[0]: row[1] for row in carries[name]} for name in CARRY[1:]}
    return {
        "recorded_quote": [{"id": exact_quote.QUOTE}],
        "recorded_line": [{"id": ref(line), "quote": one["recorded_line__quote"][line]}
                          for (line,) in recorded.get("recorded_line", ())],
        "quote_digit": [{"id": ref(digit), "line": ref(one["quote_digit__line"][digit]),
                         "operand": one["quote_digit__operand"][digit],
                         "position": one["quote_digit__position"][digit],
                         "value": one["quote_digit__value"][digit]}
                        for (digit,) in recorded.get("quote_digit", ())],
        "quote_carry": [{"id": ref(source), "amount": ref(carry["quote_carry__amount"][source]),
                         "position": int(carry["quote_carry__position"][source]),
                         "value": int(carry["quote_carry__value"][source])}
                        for (source,) in sorted(carries["quote_carry"])],
    }


def epoch(directory: Path, target: Path, rows: dict):
    shutil.copytree(directory, target)
    (target / "facts").mkdir()
    (target / "facts" / "quote.yaml").write_text(yaml.safe_dump(rows, sort_keys=False), encoding="utf-8")
    authored = sorted(path for path in target.rglob("*") if path.suffix in {".dl", ".rezono"})
    position = hashlib.sha256(b"".join(path.read_bytes() for path in authored)).hexdigest()
    return publisher_batch.epoch(target, epoch=1, knowledge_time=TIME, sources=[("rules", position)])


def test_exact_quote_pack_is_written_in_rezono():
    meta = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))
    assert QUOTE_MODULE in [entry["module"] for entry in meta.get("rezono", ())]
    assert not (PACK / "schema").exists() and not (PACK / "rules").exists()


def test_exact_quote_pack_keeps_its_schema_and_presentation(tmp_path):
    convert_pack.compare(pack.read(legacy(tmp_path / "legacy")), pack.read(quote_only(tmp_path / "rezono")))


@pytest.mark.parametrize("name", sorted(QUOTES))
def test_exact_quote_pack_keeps_its_conclusions(tmp_path, name):
    lines = QUOTES[name]
    pack_derived = derived(PACK, lines)
    legacy_derived = derived(legacy(tmp_path), lines)
    assert legacy_derived.keys() <= pack_derived.keys()
    for relation, rows in legacy_derived.items():
        assert pack_derived[relation] == rows


@pytest.mark.parametrize("name", ["priced", "repeated"])
def test_exact_quote_pack_keeps_its_publication(tmp_path, name):
    rows = facts(QUOTES[name])
    baseline = epoch(legacy(tmp_path / "legacy-source"), tmp_path / "legacy" / "exact-quote", rows)
    trial = epoch(quote_only(tmp_path / "rezono-source"), tmp_path / "rezono" / "exact-quote", rows)
    convert_pack.compare_publications(baseline, trial, ROLES)


def test_exact_quote_publication_comparison_sees_a_changed_conclusion(tmp_path):
    """A rule that ignores the digit 9 of 479,000 must not pass the comparison."""
    rows = facts(QUOTES["priced"])
    baseline = epoch(legacy(tmp_path / "source"), tmp_path / "legacy" / "exact-quote", rows)
    changed = legacy(tmp_path / "changed")
    rules = changed / "rules" / "amount.dl"
    text = rules.read_text(encoding="utf-8")
    assert text.count("n >= 0, n <= 9.") == 1
    rules.write_text(text.replace("n >= 0, n <= 9.", "n >= 0, n <= 8."), encoding="utf-8")
    trial = epoch(changed, tmp_path / "trial" / "exact-quote", rows)
    with pytest.raises(convert_pack.ConversionError):
        convert_pack.compare_publications(baseline, trial, ROLES)


def test_exact_quote_total_is_unchanged():
    assert exact_quote.total_micros(
        [dict(quantity=q, billed_periods=b, period_price_micros=p, setup_price_micros=s, currency="USD")
         for q, b, p, s in QUOTES["priced"]], "USD") == 1_614_000
