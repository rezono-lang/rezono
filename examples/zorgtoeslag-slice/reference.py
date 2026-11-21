"""Independent Python reference for the healthcare allowance slice
(decisions/language-healthcare-allowance-slice.md, decisions/healthcare-allowance-three-sources.md,
decisions/no-green-by-cheapest-route.md).

`allowance(facts, claimant, as_of, known)` gives the monthly allowance of one claimant in whole cents, or the
pair `(state, reason)` of an allowance that is not known. It is evaluated on `as_of` with the versions known
on `known`.

Reads Rezono fact files (`.rezono`) with native ISO dates only (no integer `YYYYMMDD` / `*_day` day numbers
and no YAML fact shortcuts):
- transitional single-source first slice (`facts.rezono`, kind `Household` with `ann..kim`), paired with its
  strict red retirement test in `examples/test_zorgtoeslag_three_sources.py`, and
- three-source slice (`facts/` `.rezono` files with `Persoon`, `civil.Adres`, `civil.Partner`, `civil.Ouder`,
  `tax.Inkomen`, `tax.Partner`, `insurer.Polis`), deriving `toeslagpartner`, `insured`, and `joint_income`
  independently from the three sources while never reading `tax.Partner` as a benefit-partner fact.

It shares no code with the compiler or the reader. It reads `.rezono` fact files with its own parser, and
states the statutory parameter versions itself from the decision. Money is exact: whole cents and fractions,
with one rounding, the monthly allowance down to whole euros. Standard library only.
"""
import datetime
import pathlib
import re
import shutil
from fractions import Fraction

HERE = pathlib.Path(__file__).parent

# The state codes of a value that is not known, in the order of v0 section 7b.
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

HEADER = re.compile(r"^fact\s+([\w.]+)\s*$")
VERSION = re.compile(
    r"^fact\s+([\w.]+)\s+([\w-]+)\s*,\s*valid\s+(\d{4}-\d{2}-\d{2})\.\.(?:<(\d{4}-\d{2}-\d{2}))?"
    r"\s*,\s*known\s+(\d{4}-\d{2}-\d{2})\s*$"
)
ASSIGN = re.compile(r"^\s+(\w+)\s*=\s*(.+?)\s*$")


def scalar(text):
    text = text.strip()
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~", ""):
        return None
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"[A-Za-z0-9_.-]+", text):
        return text
    raise ValueError(f"facts: a value this reference does not read: {text}")


def strip(line):
    return line.split("--", 1)[0].rstrip()


def read_facts(path):
    """The fact table rows, `{kind: {id: {slot: value}}}`, and the dated versions,
    `[(kind, id, slot, valid from, valid until or None, known, value)]`."""
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
                versions.append((kind.lower(), ident, slot, day(start), until and day(until), day(known), scalar(value)))
                i += 1
        elif line.startswith("fact"):
            raise ValueError(f"facts: a line this reference does not read: {line}")
    return tables, versions


def select(rows, on, cut):
    """The value of the one version that applies on `on` with what is known on `cut`, or its state."""
    held = [
        (known, value)
        for start, until, known, value in rows
        if start <= on and (until is None or on < until) and known <= cut
    ]
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
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, str):
        return day(value)
    raise ValueError(f"expected ISO date, not {value!r}")


def _row_window(row):
    """Return `(valid_from, valid_until_or_None, known_from)` using native ISO dates only."""
    day_keys = sorted(k for k in row if str(k).endswith("_day"))
    if day_keys:
        raise ValueError(f"integer day-number slots are forbidden in zorgtoeslag-slice facts: {day_keys}")

    if row.get("valid_from") is not None:
        start = as_date(row["valid_from"])
    else:
        start = datetime.date.min

    if row.get("valid_until") is not None:
        until = as_date(row["valid_until"])
        if until >= datetime.date(9999, 12, 31):
            until = None
    else:
        until = None

    if row.get("known_from") is not None:
        known = as_date(row["known_from"])
    elif row.get("known") is not None:
        known = as_date(row["known"])
    else:
        known = datetime.date.min

    return start, until, known


def _classify_section(section_name, file_stem=""):
    key = section_name.lower()
    stem = file_stem.lower()
    if "partner" in key:
        if "civil" in key or ("tax" not in key and "civil" in stem):
            return "civil_partner"
        if "tax" in key or "fiscal" in key or "tax" in stem:
            return "tax_partner"
    if key == "persoon" or key.endswith(("_persoon", ".persoon")):
        return "persoon"
    if key == "adres" or key.endswith(("_adres", ".adres")):
        return "adres"
    if key == "ouder" or key.endswith(("_ouder", ".ouder")):
        return "ouder"
    if key == "inkomen" or key.endswith(("_inkomen", ".inkomen")):
        return "inkomen"
    if key == "polis" or key.endswith(("_polis", ".polis")):
        return "polis"
    if key == "household":
        return "household"
    return None


def _fact_files_in(source):
    path = pathlib.Path(source)
    if path.is_file():
        if path.suffix != ".rezono":
            raise ValueError(f"zorgtoeslag-slice facts must be .rezono files, not {path.name}")
        return [path]
    if path.is_dir():
        yaml_facts = [
            p
            for p in sorted(path.rglob("*"))
            if p.is_file() and p.suffix in {".yaml", ".yml"} and not p.name.endswith(".sources.yaml")
        ]
        if yaml_facts:
            raise ValueError(f"YAML fact files are forbidden in zorgtoeslag-slice: {[p.name for p in yaml_facts]}")
        return [p for p in sorted(path.rglob("*.rezono")) if p.is_file()]
    raise FileNotFoundError(f"facts source does not exist: {path}")


def read_three_source_facts(facts_source):
    """Read three-source `.rezono` fact rows from a directory or file into canonical source buckets."""
    data = {
        "persoon": {},
        "adres": [],
        "civil_partner": [],
        "ouder": [],
        "inkomen": [],
        "tax_partner": [],
        "polis": [],
    }
    for path in _fact_files_in(facts_source):
        tables, versions = read_facts(path)
        for kind, by_id in tables.items():
            bucket = _classify_section(kind, path.stem)
            if bucket is None or bucket == "household":
                continue
            if bucket == "persoon":
                for ident, attrs in by_id.items():
                    data["persoon"][str(ident)] = {"id": str(ident), **attrs}
            else:
                for ident, attrs in by_id.items():
                    data[bucket].append({"id": str(ident), **attrs})
        # Group dated Rezono rows per (kind, id, valid, known) into rows.
        grouped = {}
        for kind, ident, slot, start, until, known, val in versions:
            bucket = _classify_section(kind, path.stem)
            if bucket is None or bucket == "household":
                continue
            gkey = (bucket, str(ident), start, until, known)
            base = tables.get(kind, {}).get(ident, {})
            entry = grouped.setdefault(
                gkey,
                {
                    "id": str(ident),
                    **base,
                    "valid_from": start,
                    "valid_until": until,
                    "known_from": known,
                },
            )
            entry[slot] = val
        for (bucket, _, _, _, _), entry in grouped.items():
            data[bucket].append(entry)
    return data


def _is_legacy_household_source(facts_source):
    """Transitional detector for the pre-expansion single-source `facts.rezono` (`Household`).

    Paired with `examples/test_zorgtoeslag_three_sources.py::test_retire_legacy_single_source_household_branch_in_zorgtoeslag_slice`.
    """
    path = pathlib.Path(facts_source)
    if not path.is_file() or path.suffix != ".rezono":
        return False
    tables, _ = read_facts(path)
    return "household" in tables and "persoon" not in tables


def _active_rows(rows, as_of, known):
    out = []
    for row in rows:
        start, until, kf = _row_window(row)
        if start <= as_of and (until is None or as_of < until) and kf <= known:
            out.append((kf, row))
    return out


def _address_of(data, person, as_of, known):
    active = _active_rows([r for r in data["adres"] if str(r.get("persoon")) == person], as_of, known)
    if not active:
        return None
    latest = max(kf for kf, _ in active)
    addrs = {str(r["woonadres"]) for kf, r in active if kf == latest and r.get("woonadres") is not None}
    return next(iter(addrs)) if len(addrs) == 1 else None


def _toeslagpartner_in(data, person_a, person_b, as_of, known):
    """Independent statutory toeslagpartner(a, b) derivation (@ awr#art-5a, @ awir#art-3).

    Reads ONLY civil.Partner, civil.Adres, and civil.Ouder; never reads tax.Partner.
    """
    a, b = str(person_a), str(person_b)
    if a == b:
        return False
    addr_a = _address_of(data, a, as_of, known)
    addr_b = _address_of(data, b, as_of, known)
    living_apart = addr_a is not None and addr_b is not None and addr_a != addr_b
    same_address = addr_a is not None and addr_b is not None and addr_a == addr_b

    # 1. Civil union without separation-plus-divorce-petition (@ awr#art-5a, @ awir#art-3).
    pair = {a, b}
    for _, row in _active_rows(data["civil_partner"], as_of, known):
        if {str(row.get("persoon_a")), str(row.get("persoon_b"))} != pair:
            continue
        petition = bool(row.get("echtscheidingsverzoek", False))
        if not (petition and living_apart):
            return True

    # 2. Unmarried cohabiting parents of a joint child (@ awir#art-3).
    if same_address:
        children_a = {str(r["kind"]) for r in data["ouder"] if str(r.get("ouder")) == a}
        children_b = {str(r["kind"]) for r in data["ouder"] if str(r.get("ouder")) == b}
        if children_a & children_b:
            return True
    return False


def toeslagpartner(facts_source, person_a, person_b, as_of, known):
    as_of, known = as_date(as_of), as_date(known)
    data = read_three_source_facts(facts_source)
    return _toeslagpartner_in(data, person_a, person_b, as_of, known)


def _all_persons(data):
    persons = set(data["persoon"])
    for r in data["adres"]:
        if "persoon" in r:
            persons.add(str(r["persoon"]))
    for r in data["civil_partner"]:
        for k in ("persoon_a", "persoon_b"):
            if k in r:
                persons.add(str(r[k]))
    for r in data["ouder"]:
        for k in ("ouder", "kind"):
            if k in r:
                persons.add(str(r[k]))
    for r in data["inkomen"]:
        if "persoon" in r:
            persons.add(str(r["persoon"]))
    for r in data["polis"]:
        if "persoon" in r:
            persons.add(str(r["persoon"]))
    return sorted(persons)


def _partners_of(data, person, as_of, known):
    person = str(person)
    return [other for other in _all_persons(data) if other != person and _toeslagpartner_in(data, person, other, as_of, known)]


def _insured_in(data, person, as_of, known):
    person = str(person)
    active = _active_rows([r for r in data["polis"] if str(r.get("persoon")) == person], as_of, known)
    if not active:
        return NO_VERSION
    latest = max(kf for kf, _ in active)
    soorten = {str(r.get("soort")) for kf, r in active if kf == latest}
    return "basis" in soorten


def insured(facts_source, person, as_of, known):
    as_of, known = as_date(as_of), as_date(known)
    data = read_three_source_facts(facts_source)
    return _insured_in(data, person, as_of, known)


def _own_income_in(data, person, as_of, known):
    person = str(person)
    rows = [
        (*_row_window(r), int(r["bedrag"]))
        for r in data["inkomen"]
        if str(r.get("persoon")) == person and r.get("bedrag") is not None
    ]
    return select(rows, as_of, known)


def _joint_income_in(data, person, as_of, known):
    person = str(person)
    partners = _partners_of(data, person, as_of, known)
    if len(partners) > 1:
        return ("invalid", "multiple_partners")
    own = _own_income_in(data, person, as_of, known)
    if not partners:
        return own
    other = _own_income_in(data, partners[0], as_of, known)
    state = strict(own, other)
    return state if state else own + other


def joint_income(facts_source, person, as_of, known):
    as_of, known = as_date(as_of), as_date(known)
    data = read_three_source_facts(facts_source)
    return _joint_income_in(data, person, as_of, known)


def _compute_allowance(partner, insured_val, joint_income_val, as_of, known):
    def param(name):
        return select(PARAMETERS[name], as_of, known)

    # income_limit = when partner then income_limit_partner else income_limit_single
    income_limit = (
        partner
        if is_state(partner)
        else param("income_limit_partner" if partner else "income_limit_single")
    )

    # The last block first: unless joint_income > income_limit then 0 (@ wzt#art-2.2).
    state = strict(joint_income_val, income_limit)
    if state:
        return state
    if joint_income_val > income_limit:
        return 0
    # Then: unless not insured then 0 (@ wzt#art-2.1).
    if is_state(insured_val):
        return insured_val
    if not insured_val:
        return 0

    # The base value: floor(yearly / 1200) * 100.
    standard_premium, threshold_income = param("standard_premium"), param("threshold_income")
    state = strict(partner, standard_premium, threshold_income, joint_income_val)
    if state:
        return state
    rate = RATE_PARTNER if partner else RATE_SINGLE
    household_premium = 2 * standard_premium if partner else standard_premium
    above = joint_income_val - threshold_income if joint_income_val > threshold_income else 0
    norm_premium = rate * threshold_income + RATE_ABOVE * above
    yearly = household_premium - norm_premium if household_premium > norm_premium else 0
    return int(Fraction(yearly) // 1200) * 100


def allowance(facts, household, as_of, known):
    as_of, known = as_date(as_of), as_date(known)
    if _is_legacy_household_source(facts):
        tables, versions = read_facts(facts)
        record = tables.get("household", {}).get(household)
        if record is None:
            raise ValueError(f"facts: no household {household}")

        def fact(slot):
            return select(
                [row[3:] for row in versions if row[:3] == ("household", household, slot)],
                as_of,
                known,
            )

        return _compute_allowance(
            record.get("partner", NO_VERSION),
            fact("insured"),
            fact("joint_income"),
            as_of,
            known,
        )

    data = read_three_source_facts(facts)
    claimant = str(household)
    if claimant not in _all_persons(data):
        raise ValueError(f"facts: no person {claimant}")
    partners = _partners_of(data, claimant, as_of, known)
    if len(partners) > 1:
        return ("invalid", "multiple_partners")
    return _compute_allowance(
        bool(partners),
        _insured_in(data, claimant, as_of, known),
        _joint_income_in(data, claimant, as_of, known),
        as_of,
        known,
    )


def merge_tax_partner_into_civil(facts_dir, dest_dir):
    """Counterexample helper: copy three-source `.rezono` facts to `dest_dir` and silently merge every
    `tax.Partner` row into `civil.Partner` (without `echtscheidingsverzoek`, as a bare-name merge across
    sources would do) as native `.rezono` facts. Never mutates `facts_dir`."""
    src = pathlib.Path(facts_dir)
    dst = pathlib.Path(dest_dir)
    if dst.exists():
        shutil.rmtree(dst)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst / src.name)

    data = read_three_source_facts(dst)
    lines = ["rezono 1", "pack zorgtoeslag-slice", ""]
    for idx, row in enumerate(data["tax_partner"], start=1):
        ident = f"merged-tax-partner-{idx}"
        start, until, kf = _row_window(row)
        start_s = "1970-01-01" if start == datetime.date.min else start.isoformat()
        kf_s = "1970-01-01" if kf == datetime.date.min else kf.isoformat()
        span = f"{start_s}..<{until.isoformat()}" if until is not None else f"{start_s}.."
        lines.append(f"fact civil.Partner {ident}, valid {span}, known {kf_s}")
        lines.append(f"  persoon_a = {row['persoon_a']}")
        lines.append(f"  persoon_b = {row['persoon_b']}")
        lines.append("  soort = huwelijk")
        lines.append("  echtscheidingsverzoek = false")
        lines.append("")

    (dst / "merged_civil_partner.rezono").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return dst


def states():
    """Yield `(state_label, three_source_data)` for `examples/test_rules.py`."""
    facts_dir = HERE / "facts"
    if not facts_dir.is_dir():
        return
    files = sorted(facts_dir.glob("*.rezono"))
    if not files:
        return
    data = read_three_source_facts(facts_dir)
    yield f"0-{files[0].stem}", data
    scenarios_dir = HERE / "scenarios"
    if scenarios_dir.is_dir():
        for sc in sorted(scenarios_dir.glob("*.rezono")):
            extra = read_three_source_facts(sc)
            merged = {
                key: (data[key] | extra[key] if isinstance(data[key], dict) else data[key] + extra[key])
                for key in data
            }
            data = merged
            yield sc.stem, data


def rules(data, as_of=datetime.date(2026, 2, 1), known=datetime.date(2026, 2, 10)):
    """Independent derived rule relations (`toeslagpartner`, `joint_income`) for `examples/test_rules.py`."""
    as_of, known = as_date(as_of), as_date(known)
    persons = _all_persons(data)
    tp = [(a, b) for a in persons for b in persons if a != b and _toeslagpartner_in(data, a, b, as_of, known)]
    ji = []
    for p in persons:
        inc = _joint_income_in(data, p, as_of, known)
        if not is_state(inc):
            ji.append((p, inc))
    return {"toeslagpartner": sorted(tp), "joint_income": sorted(ji)}
