"""Calculate a recorded quote exactly in millionths of its currency."""

from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping
from contextlib import closing, contextmanager
from pathlib import Path
from typing import NamedTuple

from rezono_compiler import batch, pack, rules


QUOTE = "quote"
# A normalization step adds a carry (at most the largest coefficient) to its column.
COLUMN_LIMIT = pack.BIGINT[1] // 2


class _Line(NamedTuple):
    quantity: int
    billed_periods: int
    period_price_micros: int
    setup_price_micros: int


Row = tuple[str | int, ...]


def _nonnegative_integer(line: Mapping[str, object], field: str) -> int:
    value = line.get(field)
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a nonnegative integer")
    return value


def _digits(value: int) -> Iterator[int]:
    while value >= 10:
        value, digit = divmod(value, 10)
        yield digit
    yield value


def _recorded_lines(lines: Iterable[Mapping[str, object]], currency: str) -> Iterator[_Line]:
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError("a quote requires a currency")
    for line in lines:
        if not isinstance(line, Mapping):
            raise ValueError("each quote line must be a mapping")
        if line.get("currency") != currency:
            raise ValueError("quote line currency must match the quote currency")
        yield _Line(*(_nonnegative_integer(line, field) for field in _Line._fields))


def _facts(lines: list[_Line]) -> dict[str, list[Row]]:
    facts = defaultdict(list, recorded_quote=[(QUOTE,)])
    for index, line in enumerate(lines):
        ref = f"line/{index}"
        facts["recorded_line"].append((ref,))
        facts["recorded_line__quote"].append((ref, QUOTE))
        for field, operand in zip(_Line._fields, line):
            for position, digit in enumerate(_digits(operand)):
                source = f"{ref}/{field}/{position}"
                facts["quote_digit"].append((source,))
                facts["quote_digit__line"].append((source, ref))
                facts["quote_digit__operand"].append((source, field))
                facts["quote_digit__position"].append((source, position))
                facts["quote_digit__value"].append((source, digit))
    return dict(facts)


def _provide_carries(connection, program: rules.Program, columns: Iterable[tuple[str, str, str]]) -> None:
    """Convert the pack's coefficients to candidate carries for the pack to verify."""
    amounts = defaultdict(dict)
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


@contextmanager
def _valued_quote(lines: list[_Line]):
    facts = _facts(lines)
    model = pack.read(Path(__file__).resolve().parent / "packs" / "exact-quote")
    program = rules.load(model.rules)
    dependent = program.downstream({"quote_carry__amount", "quote_carry__position", "quote_carry__value"})
    with closing(batch.connect(program, facts, threads=1)) as connection:
        batch.compute(connection, program, relations=set(program.derived()) - dependent)
        columns = batch.read(connection, program, ["amount_column"])["amount_column"]
        _provide_carries(connection, program, columns)
        batch.compute(connection, program, relations=dependent)
        yield model, program, connection


def _derive_total(lines: list[_Line]) -> int:
    with _valued_quote(lines) as (_, program, connection):
        amounts = batch.read(connection, program, ["amount_digit"])["amount_digit"]
    digits = [(int(position), int(digit)) for ref, position, digit in amounts if ref == QUOTE]
    if not digits:
        raise ValueError("the pack did not derive a complete quote total")
    # Decode the decimal representation of one amount. Line amounts are already
    # summed by the pack, including repeated lines with identical source values.
    value = 0
    for _, digit in sorted(digits, reverse=True):
        value = value * 10 + digit
    return value


def _column_bound(line: _Line) -> int:
    """Upper-bound an uncarried coefficient from the number of possible digit pairs."""
    quantity, periods, rate, setup = (max(1, value.bit_length()) for value in line)
    machine_width = max(periods + rate - 1, setup)
    machine_column = 81 * min(periods, rate) + 9
    return min(machine_width, quantity) * machine_column * 9


def _sum_subtotals(left: int, right: int) -> int:
    """Add two normalized amounts by entering each as one setup-only charge."""
    return _derive_total([_Line(1, 0, 0, left), _Line(1, 0, 0, right)])


def _evaluate(lines: list[_Line]) -> int:
    if sum(_column_bound(line) for line in lines) <= COLUMN_LIMIT:
        return _derive_total(lines)
    if len(lines) > 1:
        middle = len(lines) // 2
        return _sum_subtotals(_evaluate(lines[:middle]), _evaluate(lines[middle:]))

    # Split a wide factor into two radix slices. Each receiving pack sees only
    # the slice's own digits. Reapply its positional weight to the high subtotal.
    line, = lines
    factor = max(_Line._fields[:3], key=lambda field: getattr(line, field).bit_length())
    value = getattr(line, factor)
    offset = value.bit_length() // 2
    low = line._replace(**{factor: value & ((1 << offset) - 1)})
    high = line._replace(**{factor: value >> offset})
    if factor != "quantity":
        high = high._replace(setup_price_micros=0)
    return _sum_subtotals(_evaluate([low]), _evaluate([high]) << offset)


def total_micros(lines: Iterable[Mapping[str, object]], currency: str) -> int:
    """Read the exact derived total in millionths of the recorded currency."""
    return _evaluate(list(_recorded_lines(lines, currency)))
