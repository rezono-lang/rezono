"""The exact-quote pack is written in Rezono and means what its LinkML and Datalog form meant.

See decisions/run-exact-quote-language.md. `run/fixtures/exact-quote-linkml/` keeps the replaced
schema and rules byte for byte. The comparison follows the whole-pack test of `scripts/convert_pack.py`:
the typed schema and presentation, and for recorded quotes the facts, the conclusions, the union of
checked grounds per conclusion and what each role sees.
"""

import hashlib
import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from rezono_compiler import batch, pack
from rezono_publisher import batch as publisher_batch

from run import exact_quote
from scripts import convert_pack

RUN = Path(__file__).resolve().parents[1]
PACK = RUN / "packs" / "exact-quote"
ORACLE = RUN / "fixtures" / "exact-quote-linkml"
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


def legacy(directory: Path) -> Path:
    """The pack as it was: the retained schema and rules beside the unchanged presentation files."""
    target = directory / "exact-quote"
    shutil.copytree(PACK, target, ignore=shutil.ignore_patterns("rezono"))
    meta = yaml.safe_load((PACK / "pack.yaml").read_text(encoding="utf-8"))
    meta.pop("rezono")
    (target / "pack.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    shutil.copytree(ORACLE, target, dirs_exist_ok=True)
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
    assert [entry["module"] for entry in meta.get("rezono", ())] == ["rezono/quote.rezono"]
    assert not (PACK / "schema").exists() and not (PACK / "rules").exists()


def test_exact_quote_pack_keeps_its_schema_and_presentation(tmp_path):
    convert_pack.compare(pack.read(legacy(tmp_path)), pack.read(PACK))


@pytest.mark.parametrize("name", sorted(QUOTES))
def test_exact_quote_pack_keeps_its_conclusions(tmp_path, name):
    lines = QUOTES[name]
    assert derived(PACK, lines) == derived(legacy(tmp_path), lines)


@pytest.mark.parametrize("name", ["priced", "repeated"])
def test_exact_quote_pack_keeps_its_publication(tmp_path, name):
    rows = facts(QUOTES[name])
    baseline = epoch(legacy(tmp_path / "source"), tmp_path / "legacy" / "exact-quote", rows)
    trial = epoch(PACK, tmp_path / "rezono" / "exact-quote", rows)
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
