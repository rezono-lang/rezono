"""Value an offline quote from the captures effective on its UTC order day."""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing
from datetime import date, datetime, timezone
from fractions import Fraction
from functools import cache
from hashlib import sha256
import json
from pathlib import Path
from typing import TypedDict

from rezono_compiler import batch, facts, pack, rules, scenarios

from run.exact_quote import total_micros
from run.price_capture import hourly_micros

_ROOT = Path(__file__).resolve().parents[1]
_QUOTE_PACK = Path(__file__).resolve().parent / "packs" / "exact-quote"
_TIME_PACK = _ROOT / "packs" / "std-time"
_QUOTE_ID = "quote"
_OPERANDS = ("quantity", "billed_periods", "period_price_micros", "setup_price_micros")


class Edition(TypedDict):
    from_day: str
    body: bytes
    url: str
    sha256: str


@cache
def _quote_pack() -> tuple[pack.Pack, rules.Program, dict[str, list[tuple]], str, set[tuple[str, str]]]:
    model = pack.read(_QUOTE_PACK)
    program = rules.load(model.rules)
    states = scenarios.fact_states(model, _QUOTE_PACK, diagnostics=False)
    if not states:
        raise ValueError("exact-quote pack must provide fact states")
    pack_facts = states[0][3]
    quote_currencies = {currency for _, currency in pack_facts.get("quote_currency__currency", ())}
    if len(quote_currencies) != 1:
        raise ValueError("exact-quote pack must declare a single quote currency")
    (quote_currency,) = quote_currencies
    bases = dict(pack_facts.get("rate_pair__base", ()))
    targets = dict(pack_facts.get("rate_pair__target", ()))
    accepted_pairs = {(bases[rid], targets[rid]) for (rid,) in pack_facts.get("rate_pair", ())}
    return model, program, pack_facts, quote_currency, accepted_pairs


def pack_currencies() -> tuple[str, str, tuple[str, ...]]:
    """Return the quote currency, publication currency, and declared currencies from exact-quote."""
    _, _, pack_facts, quote_currency, accepted_pairs = _quote_pack()
    pub_currencies = {currency for _, currency in pack_facts.get("publication_currency__currency", ())}
    if len(pub_currencies) != 1:
        raise ValueError("exact-quote pack must declare a single publication currency")
    (publication_currency,) = pub_currencies
    all_currencies = tuple(sorted({
        quote_currency,
        publication_currency,
        *(currency for pair in accepted_pairs for currency in pair),
    }))
    return quote_currency, publication_currency, all_currencies


def _digits(value: int) -> Iterator[int]:
    while value >= 10:
        value, digit = divmod(value, 10)
        yield digit
    yield value


def _active_editions(day: date, histories: Mapping[str, list[Edition]]) -> dict[str, list[Edition]]:
    time_facts: dict[str, list[tuple[str, str | int]]] = {
        "interval__on_axis": [],
        "interval__start": [],
        "interval__end": [],
        "interval__unbounded": [],
        "reference_point__on_axis": [],
        "reference_point__position": [],
    }
    rows: dict[str, Edition] = {}
    for series, editions in histories.items():
        dated = [(date.fromisoformat(edition["from_day"]).toordinal(), edition) for edition in editions]
        starts = sorted({start for start, _ in dated})
        ends = dict(zip(starts, starts[1:]))
        time_facts["reference_point__on_axis"].append((series, series))
        time_facts["reference_point__position"].append((series, day.toordinal()))
        for number, (start, edition) in enumerate(dated):
            observation = f"{series}/{number}"
            rows[observation] = edition
            time_facts["interval__on_axis"].append((observation, series))
            time_facts["interval__start"].append((observation, start))
            if start in ends:
                time_facts["interval__end"].append((observation, ends[start]))
            else:
                time_facts["interval__unbounded"].append((observation, "end"))

    program = rules.load(pack.read(_TIME_PACK).rules)
    result: dict[str, list[Edition]] = {series: [] for series in histories}
    with closing(batch.connect(program, time_facts)) as connection:
        batch.compute(connection, program, relations={"holds_at", "begun_at"})
        for observation, reference in batch.read(connection, program, ["holds_at"])["holds_at"]:
            result[reference].append(rows[observation])
    return result


def _unique_rate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ValueError(f"duplicate rate capture field {key!r}")
        document[key] = value
    return document


def _rate_documents(
    rates: Iterable[Edition],
    accepted_pairs: set[tuple[str, str]],
) -> tuple[list[Edition], dict[str, dict[str, object]]]:
    editions: list[Edition] = []
    documents: dict[str, dict[str, object]] = {}
    for edition in rates:
        digest = edition["sha256"]
        raw = edition["body"]
        if sha256(raw).hexdigest() != digest:
            raise ValueError("rate capture bytes do not match the SHA-256 digest")
        document = json.loads(raw, object_pairs_hook=_unique_rate_object)
        if not isinstance(document, dict) or any(
            not isinstance(document.get(field), str) for field in ("base", "quote")
        ):
            raise ValueError("rate capture requires a currency pair")
        if (document["base"], document["quote"]) in accepted_pairs:
            editions.append(edition)
            documents[digest] = document
    return editions, documents


def _provide_quote_carries(connection, program: rules.Program, columns: Iterable[tuple[str, str, str]]) -> None:
    amounts: dict[str, dict[int, int]] = defaultdict(dict)
    for ref, position, coefficient in columns:
        amounts[ref][int(position)] = int(coefficient)
    for ref, coefficients in sorted(amounts.items()):
        carry = 0
        position = 0
        last = max(coefficients)
        while True:
            source = f"{ref}/carry/{position}"
            for relation, row in (
                ("quote_carry", (source,)),
                ("quote_carry__amount", (source, ref)),
                ("quote_carry__position", (source, position)),
                ("quote_carry__value", (source, carry)),
            ):
                batch.apply(connection, program, relation, row, "insert")
            if position > last and carry == 0:
                break
            carry = (coefficients.get(position, 0) + carry) // 10
            position += 1


def _provide_effective_carries(
    connection,
    program: rules.Program,
    columns: Iterable[tuple[str, str, str, str, str]],
) -> None:
    amounts: dict[tuple[str, str, str], dict[int, int]] = defaultdict(dict)
    for quote_ref, currency, part, position, coefficient in columns:
        amounts[(quote_ref, currency, part)][int(position)] = int(coefficient)
    for (quote_ref, currency, part), coefficients in sorted(amounts.items()):
        carry = 0
        position = 0
        last = max(coefficients)
        while True:
            source = f"{quote_ref}/{currency}/{part}/carry/{position}"
            for relation, row in (
                ("effective_carry", (source,)),
                ("effective_carry__quote", (source, quote_ref)),
                ("effective_carry__currency", (source, currency)),
                ("effective_carry__part", (source, part)),
                ("effective_carry__position", (source, position)),
                ("effective_carry__value", (source, carry)),
            ):
                batch.apply(connection, program, relation, row, "insert")
            if position > last and carry == 0:
                break
            carry = (coefficients.get(position, 0) + carry) // 10
            position += 1


def _derive_effective_amounts(
    total: int,
    base: str,
    target: str,
    numerator: int,
    denominator: int,
) -> dict[str, list[int]]:
    model, program, pack_facts, _, _ = _quote_pack()
    quote_digits = []
    line_values = (1, 0, 0, total)
    for operand, value in zip(_OPERANDS, line_values):
        for position, digit in enumerate(_digits(value)):
            quote_digits.append({
                "id": f"line/0/{operand}/{position}",
                "line": "line/0",
                "operand": operand,
                "position": position,
                "value": digit,
            })

    rate_digits = []
    for operand, value in (("numerator", numerator), ("denominator", denominator)):
        for position, digit in enumerate(_digits(value)):
            rate_digits.append({
                "id": f"rate/{operand}/{position}",
                "rate": "rate",
                "operand": operand,
                "position": position,
                "value": digit,
            })

    runtime_rows = facts.rows_of(model, {
        "recorded_quote": [{"id": _QUOTE_ID}],
        "recorded_line": [{"id": "line/0", "quote": _QUOTE_ID}],
        "quote_digit": quote_digits,
        "rate_capture": [{"id": "rate", "quote": _QUOTE_ID, "base": base, "target": target}],
        "rate_digit": rate_digits,
    })
    merged = {
        table: [*pack_facts.get(table, ()), *runtime_rows.get(table, ())]
        for table in pack_facts.keys() | runtime_rows.keys()
    }
    inputs = scenarios.rule_rows(model, program, merged)

    after_quote_carry = program.downstream({"quote_carry__amount", "quote_carry__position", "quote_carry__value"})
    after_effective_carry = program.downstream({
        "effective_carry__quote",
        "effective_carry__currency",
        "effective_carry__part",
        "effective_carry__position",
        "effective_carry__value",
    })
    all_derived = set(program.derived())

    with closing(batch.connect(program, inputs, threads=1)) as connection:
        batch.compute(connection, program, relations=all_derived - after_quote_carry)
        _provide_quote_carries(connection, program, batch.read(connection, program, ["amount_column"])["amount_column"])
        batch.compute(connection, program, relations=after_quote_carry - after_effective_carry)
        _provide_effective_carries(
            connection, program, batch.read(connection, program, ["effective_column"])["effective_column"]
        )
        batch.compute(connection, program, relations=after_effective_carry)
        derived = batch.read(connection, program, ["effective_amount", "effective_digit"])

    amounts: dict[str, list[int]] = {}
    for row_quote, currency, num_text, den_text in derived["effective_amount"]:
        if row_quote == _QUOTE_ID:
            value = Fraction(int(num_text), int(den_text))
            amounts[currency.lower()] = [value.numerator, value.denominator]

    digits_by_currency: dict[str, dict[str, list[tuple[int, int]]]] = defaultdict(lambda: defaultdict(list))
    for row_quote, currency, part, position, digit in derived["effective_digit"]:
        if row_quote == _QUOTE_ID:
            digits_by_currency[currency][part].append((int(position), int(digit)))
    for currency, parts in digits_by_currency.items():
        if currency.lower() not in amounts and "numerator" in parts and "denominator" in parts:
            num = int("".join(str(digit) for _, digit in sorted(parts["numerator"], reverse=True)))
            den = int("".join(str(digit) for _, digit in sorted(parts["denominator"], reverse=True)))
            value = Fraction(num, den)
            amounts[currency.lower()] = [value.numerator, value.denominator]

    if {base.lower(), target.lower()} - set(amounts):
        raise ValueError("the pack did not derive complete effective amounts")
    return amounts


def quote_at(
    instant: str, lines: Iterable[Mapping[str, object]], prices: Iterable[Edition], rates: Iterable[Edition]
) -> dict[str, list[int] | list[str] | str]:
    """Return the exact quote and converted amounts, or the price and exchange findings."""
    order_time = datetime.fromisoformat(instant)
    if order_time.utcoffset() is None:
        raise ValueError("an order instant requires a time zone")
    day = order_time.astimezone(timezone.utc).date()
    _, _, _, quote_currency, accepted_pairs = _quote_pack()
    fx_editions, documents = _rate_documents(rates, accepted_pairs)
    active = _active_editions(day, {"price": list(prices), "fx": fx_editions})
    problems = [
        f"{'ambiguous' if editions else 'missing'}_{series}"
        for series, editions in active.items()
        if len(editions) != 1
    ]
    if problems:
        return {"problems": problems}

    price, = active["price"]
    fx, = active["fx"]
    hourly = hourly_micros(price["body"], price["sha256"])
    priced_lines = []
    for line in lines:
        if not isinstance(line, Mapping):
            raise ValueError("each quote line must be a mapping")
        sku = line.get("sku")
        if not isinstance(sku, str) or not sku.strip():
            raise ValueError("each quote line requires a SKU")
        if sku not in hourly:
            return {"problems": ["missing_price"]}
        priced_lines.append(dict(line, period_price_micros=hourly[sku]))

    rate = documents[fx["sha256"]]
    numerator, denominator = rate.get("n"), rate.get("d")
    if type(numerator) is not int or type(denominator) is not int or numerator <= 0 or denominator <= 0:
        raise ValueError("rate capture must provide a positive integer ratio")
    total = total_micros(priced_lines, quote_currency)
    amounts = _derive_effective_amounts(total, str(rate["base"]), str(rate["quote"]), numerator, denominator)
    return {
        **amounts,
        "price_source": price["sha256"],
        "fx_source": fx["sha256"],
        "problems": [],
    }
