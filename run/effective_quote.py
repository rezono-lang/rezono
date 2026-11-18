"""Value an offline quote from the captures effective on its UTC order day."""

from collections.abc import Iterable, Mapping
from contextlib import closing
from datetime import date, datetime, timezone
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import TypedDict

from rezono_compiler import batch, pack, rules

from run.exact_quote import total_micros
from run.price_capture import hourly_micros


class Edition(TypedDict):
    from_day: str
    body: bytes
    url: str
    sha256: str


def _active_editions(day: date, histories: Mapping[str, list[Edition]]) -> dict[str, list[Edition]]:
    facts: dict[str, list[tuple[str, str | int]]] = {
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
        facts["reference_point__on_axis"].append((series, series))
        facts["reference_point__position"].append((series, day.toordinal()))
        for number, (start, edition) in enumerate(dated):
            observation = f"{series}/{number}"
            rows[observation] = edition
            facts["interval__on_axis"].append((observation, series))
            facts["interval__start"].append((observation, start))
            if start in ends:
                facts["interval__end"].append((observation, ends[start]))
            else:
                facts["interval__unbounded"].append((observation, "end"))

    time_pack = Path(__file__).resolve().parents[1] / "packs" / "std-time"
    program = rules.load(pack.read(time_pack).rules)
    result: dict[str, list[Edition]] = {series: [] for series in histories}
    with closing(batch.connect(program, facts)) as connection:
        batch.compute(connection, program, relations={"holds_at", "begun_at"})
        for observation, reference in batch.read(connection, program, ["holds_at"])["holds_at"]:
            result[reference].append(rows[observation])
    return result


def _rate_documents(rates: Iterable[Edition]) -> tuple[list[Edition], dict[str, dict[str, object]]]:
    editions: list[Edition] = []
    documents: dict[str, dict[str, object]] = {}
    for edition in rates:
        digest = edition["sha256"]
        raw = edition["body"]
        if sha256(raw).hexdigest() != digest:
            raise ValueError("rate capture bytes do not match the SHA-256 digest")
        document = json.loads(raw)
        if not isinstance(document, dict) or any(
            not isinstance(document.get(field), str) for field in ("base", "quote")
        ):
            raise ValueError("rate capture requires a currency pair")
        if (document["base"], document["quote"]) == ("USD", "EUR"):
            editions.append(edition)
            documents[digest] = document
    return editions, documents


def quote_at(
    instant: str, lines: Iterable[Mapping[str, object]], prices: Iterable[Edition], rates: Iterable[Edition]
) -> dict[str, list[int] | list[str] | str]:
    """Return the exact USD and EUR amounts, or the price and exchange findings."""
    order_time = datetime.fromisoformat(instant)
    if order_time.utcoffset() is None:
        raise ValueError("an order instant requires a time zone")
    day = order_time.astimezone(timezone.utc).date()
    fx_editions, documents = _rate_documents(rates)
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
        priced_lines.append({**line, "period_price_micros": hourly[sku]})

    rate = documents[fx["sha256"]]
    numerator, denominator = rate.get("n"), rate.get("d")
    if type(numerator) is not int or type(denominator) is not int or numerator <= 0 or denominator <= 0:
        raise ValueError("rate capture must provide a positive integer ratio")
    usd = Fraction(total_micros(priced_lines, "USD"), 1_000_000)
    eur = usd * Fraction(numerator, denominator)
    return {
        "usd": [usd.numerator, usd.denominator],
        "eur": [eur.numerator, eur.denominator],
        "price_source": price["sha256"],
        "fx_source": fx["sha256"],
        "problems": [],
    }
