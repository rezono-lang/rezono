"""Independent Python reference for the first slice of the healthcare allowance
(decisions/language-healthcare-allowance-slice.md).

allowance(facts, household, as_of, known) gives the monthly allowance of one household in whole cents, or the
pair (state, reason) of an allowance that is not known. It is evaluated on the day `as_of` with the versions
known on `known`, as one `as of DAY known DAY` line of a publication is.

It shares no code with the compiler or the reader. It reads the fact rows of facts.rezono with its own reading,
and it states the parameter versions itself, from the decision, rather than reading the module. Money is exact:
whole cents and fractions, with one rounding, the monthly allowance down to whole euros.

Selection follows docs/rezono/v0.md section 5a: among the versions whose `valid` range holds on the day and
whose `known` date is at or before the knowledge cut, the one with the later `known` date applies; two with
the same `known` date give `invalid versions_overlap`, and none gives `unknown no_version_applies`. The
exceptions follow section 5b: the last `unless` block is read first, and a condition that is not known gives
the allowance its state. States follow section 7b. Standard library only.
"""
import datetime
import pathlib
import re
from fractions import Fraction

# The state codes of a value that is not known, in the order of section 7b.
STATES = ("n/a", "unknown", "invalid")
NO_VERSION = ("unknown", "no_version_applies")
OVERLAP = ("invalid", "versions_overlap")


def day(text):
    return datetime.date.fromisoformat(text)


# The parameter versions of the decision, in cents: (valid from, valid until or None, known, value).
PARAMETERS = {
    "standard_premium": (
        (day("2025-01-01"), day("2026-01-01"), day("2024-09-17"), 211200),
        (day("2026-01-01"), None, day("2025-09-16"), 218000),
        (day("2026-01-01"), None, day("2026-03-02"), 219000),
    ),
    "threshold_income": (
        (day("2025-01-01"), day("2026-01-01"), day("2024-09-17"), 2840600),
        (day("2026-01-01"), None, day("2025-09-16"), 2960000),
    ),
    "income_limit_single": (
        (day("2025-01-01"), day("2026-01-01"), day("2024-09-17"), 3852000),
        (day("2026-01-01"), None, day("2025-09-16"), 3971900),
    ),
    "income_limit_partner": (
        (day("2025-01-01"), day("2026-01-01"), day("2024-09-17"), 4822400),
        (day("2026-01-01"), None, day("2025-09-16"), 5020600),
    ),
}
RATE_SINGLE = Fraction("1.879") / 100
RATE_PARTNER = Fraction("4.256") / 100
RATE_ABOVE = Fraction("13.7") / 100

HEADER = re.compile(r"^fact\s+(\w+)\s*$")
VERSION = re.compile(r"^fact\s+(\w+)\s+(\w+)\s*,\s*valid\s+(\d{4}-\d{2}-\d{2})\.\.(?:<(\d{4}-\d{2}-\d{2}))?"
                     r"\s*,\s*known\s+(\d{4}-\d{2}-\d{2})\s*$")
ASSIGN = re.compile(r"^\s+(\w+)\s*=\s*(\S+)\s*$")


def scalar(text):
    if text in ("true", "false"):
        return text == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    raise ValueError(f"facts: a value this reference does not read: {text}")


def strip(line):
    return line.split("--", 1)[0].rstrip()


def read_facts(path):
    """The fact table rows, {kind: {id: {slot: value}}}, and the dated versions,
    [(kind, id, slot, valid from, valid until or None, known, value)]."""
    tables, versions = {}, []
    lines = [strip(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        header, version = HEADER.match(line), VERSION.match(line)
        if header:
            kind = header.group(1).lower()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([cell.strip() for cell in lines[i].strip().strip("|").split("|")])
                i += 1
            names = rows[0]
            table = tables.setdefault(kind, {})
            for row in rows[1:]:
                record = dict(zip(names, row))
                ident = record.pop("id")
                table[ident] = {slot: scalar(value) for slot, value in record.items()}
        elif version:
            kind, ident, start, until, known = version.groups()
            while i < len(lines) and ASSIGN.match(lines[i]):
                slot, value = ASSIGN.match(lines[i]).groups()
                versions.append((kind, ident, slot, day(start), until and day(until), day(known), scalar(value)))
                i += 1
        elif line.startswith("fact"):
            raise ValueError(f"facts: a line this reference does not read: {line}")
    return tables, versions


def select(rows, on, cut):
    """The value of the one version that applies on `on` with what is known on `cut`, or its state."""
    held = [(known, value) for start, until, known, value in rows
            if start <= on and (until is None or on < until) and known <= cut]
    if not held:
        return NO_VERSION
    latest = max(known for known, _ in held)
    values = [value for known, value in held if known == latest]
    return values[0] if len(values) == 1 else OVERLAP


def is_state(value):
    return isinstance(value, tuple)


def strict(*values):
    """The state of a strict operation over operands of which one is not known: the highest state, with the
    least reason among the operands in that state; None if every operand is known."""
    states = [value for value in values if is_state(value)]
    if not states:
        return None
    top = max(STATES.index(state) for state, _ in states)
    return STATES[top], min(reason for state, reason in states if STATES.index(state) == top)


def as_date(value):
    return value if isinstance(value, datetime.date) else day(str(value))


def allowance(facts, household, as_of, known):
    as_of, known = as_date(as_of), as_date(known)
    tables, versions = read_facts(facts)
    record = tables.get("household", {}).get(household)
    if record is None:
        raise ValueError(f"facts: no household {household}")

    def fact(slot):
        return select([row[3:] for row in versions if row[:3] == ("household", household, slot)], as_of, known)

    def param(name):
        return select(PARAMETERS[name], as_of, known)

    partner = record.get("partner", NO_VERSION)
    insured = fact("insured")
    joint_income = fact("joint_income")

    # income_limit = when partner then income_limit_partner else income_limit_single
    income_limit = partner if is_state(partner) else param("income_limit_partner" if partner else "income_limit_single")

    # The last block first: unless joint_income > income_limit then 0.
    state = strict(joint_income, income_limit)
    if state:
        return state
    if joint_income > income_limit:
        return 0
    # Then: unless not insured then 0.
    if is_state(insured):
        return insured
    if not insured:
        return 0

    # The base value: floor(yearly / 1200) * 100.
    standard_premium, threshold_income = param("standard_premium"), param("threshold_income")
    state = strict(partner, standard_premium, threshold_income, joint_income)
    if state:
        return state
    rate = RATE_PARTNER if partner else RATE_SINGLE
    household_premium = 2 * standard_premium if partner else standard_premium
    above = joint_income - threshold_income if joint_income > threshold_income else 0
    norm_premium = rate * threshold_income + RATE_ABOVE * above
    yearly = household_premium - norm_premium if household_premium > norm_premium else 0
    return int(Fraction(yearly) // 1200) * 100
