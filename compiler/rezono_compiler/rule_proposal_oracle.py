"""Evaluate the typed proposal program independently in the pinned Soufflé interpreter."""

import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from . import rules

TYPES = {"integer": "number", "string": "symbol"}
COMPARE = dict(zip(rules.COMPARISONS, ("=", "!=", "<", "<=", ">", ">="), strict=True))
ARITHMETIC = dict(zip(rules.ARITHMETIC, ("+", "-", "*", "/"), strict=True))


def symbol(value: str) -> str:
    # Hex preserves UTF-8 order and keeps tabs, newlines and quotes out of the fact transport.
    return "s" + value.encode("utf-8").hex()


def term(value: str, type_: str) -> str:
    if value == "_":
        return value
    if rules.is_var(value):
        return "V_" + value[1:]
    return value if type_ == "integer" else f'"{symbol(value)}"'


def atom(program, value, aggregate_column=None, keep=None) -> str:
    relation = program.relations[value.relation]
    terms = [term(argument if keep is None or argument == keep or not rules.is_var(argument) else "_", column.type)
             for argument, column in zip(value.terms, relation.key, strict=True)]
    terms += ["_" for _ in relation.values]
    if aggregate_column is not None:
        columns = relation.key + relation.values
        terms[next(i for i, column in enumerate(columns) if column.name == aggregate_column)] = "AggregateValue"
    return f"r_{relation.name}({', '.join(terms)})"


def clause(program, rule) -> str:
    types = {expression.var: "integer" for expression in (*rule.aggregates, *rule.assignments)}
    body = []
    for literal in rule.body:
        value = literal.atom
        for argument, column in zip(value.terms, program.relations[value.relation].key, strict=True):
            if rules.is_var(argument):
                types[argument] = column.type
        body.append(("!" if literal.polarity == "negative" else "") + atom(program, value))
    for aggregate in rule.aggregates:
        expression = "count" if aggregate.function == "count" else f"{aggregate.function} AggregateValue"
        body.append(f"{term(aggregate.var, 'integer')} = {expression} : "
                    f"{{ {atom(program, aggregate.atom, aggregate.over)} }}")
    for assignment in rule.assignments:
        if assignment.op not in ARITHMETIC:
            raise ValueError(f"Soufflé comparison cannot represent assignment {assignment.op}")
        body.append(f"{term(assignment.var, 'integer')} = {term(assignment.left, 'integer')} "
                    f"{ARITHMETIC[assignment.op]} {term(assignment.right, 'integer')}")
    for index, condition in enumerate(rule.conditions):
        if condition.compare_as == "binary_text":   # the hex transport keeps the order of the UTF-8 bytes
            body.append(f"{term(condition.left, 'string')} {COMPARE[condition.op]} {term(condition.right, 'string')}")
            continue
        if condition.compare_as == "utc_instant":   # only a valid instant has a key; the key orders by its bytes
            left, right = f"UtcLeft{index}", f"UtcRight{index}"
            body.append(f"utc_key({term(condition.left, 'string')}, {left}), "
                        f"utc_key({term(condition.right, 'string')}, {right}), {left} {COMPARE[condition.op]} {right}")
            continue
        type_ = types.get(condition.left) or types.get(condition.right) or rules.const_type(condition.left)
        body.append(f"{term(condition.left, type_)} {COMPARE[condition.op]} {term(condition.right, type_)}")
    return f"{atom(program, rule.head)} :- {', '.join(body)}."


# --- typed comparisons (decisions/ordered-rule-scalars.md) ---
# Text travels as "s" + the hex of its UTF-8 bytes, so the byte order of two texts is the order of their symbols,
# provided the interpreter orders symbols by their characters. Each run that compares typed values proves that on
# a probe whose symbols it declares in the reverse of their order, against an expectation from Python's bytes.
PROBE = "rezono_symbol_order"
PROBE_SYMBOLS = sorted({"s", "s00", "s0f", "sf0", "sff", *(f"s{digit}" for digit in "0123456789abcdef"),
                        *(f"s{digit}0" for digit in "0123456789abcdef")}, reverse=True)
HEX_DIGIT = "3[0-9]"   # an ASCII digit in the hex transport
# YYYY-MM-DDTHH:mm:ss[.digits]Z in the hex transport: "-" is 2d, "T" 54, ":" 3a, "." 2e and "Z" 5a.
UTC_SHAPE = (f"s({HEX_DIGIT}){{4}}2d({HEX_DIGIT}){{2}}2d({HEX_DIGIT}){{2}}54({HEX_DIGIT}){{2}}3a({HEX_DIGIT}){{2}}"
             f"3a({HEX_DIGIT}){{2}}(2e({HEX_DIGIT})+)?5a")
UTC_SECONDS = 19   # characters of YYYY-MM-DDTHH:mm:ss
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def typed(program) -> set[str]:
    return {c.compare_as for rule in program.rules.values() for c in rule.conditions if c.compare_as}


def number(first: int, count: int) -> str:
    """The whole number written by `count` ASCII digits from character `first` of the transported text x."""
    digits = (f"{10 ** (count - 1 - k)} * to_number(substr(x, {2 + 2 * (first + k)}, 1))" for k in range(count))
    return "(" + " + ".join(digits) + ")"


def utc_rules(program) -> list[str]:
    """`utc_key(x, k)`: x is a valid UTC instant and k its key, without the terminal Z, the trailing zeros of the
    fraction and a fraction that becomes empty. The fields are read only from a text of the right shape."""
    lines = [".decl utc_in(x: symbol)", ".decl utc_shape(x: symbol)", ".decl utc_month(m: number, last: number)",
             ".decl utc_fields(x: symbol, y: number, m: number, d: number, h: number, i: number, s: number)",
             ".decl utc_ok(x: symbol)", ".decl utc_cut(x: symbol, t: symbol)", ".decl utc_key(x: symbol, k: symbol)"]
    operands = {}   # a typed operand is bound by a positive literal; its values are the candidates for a key
    for rule in program.rules.values():
        for condition in rule.conditions:
            if condition.compare_as != "utc_instant":
                continue
            for operand in (condition.left, condition.right):
                literal = next(b for b in rule.body if b.polarity == "positive" and operand in b.atom.terms)
                operands[f"utc_in({term(operand, 'string')}) :- {atom(program, literal.atom, keep=operand)}."] = None
    lines += [*operands, *(f"utc_month({month}, {last})." for month, last in enumerate(MONTH_DAYS, 1))]
    fields = ", ".join(f"{name} = {number(first, count)}" for name, first, count in
                       (("Y", 0, 4), ("M", 5, 2), ("D", 8, 2), ("H", 11, 2), ("I", 14, 2), ("S", 17, 2)))
    clock = "Y >= 1, H <= 23, I <= 59, S <= 59"
    whole = 1 + 2 * (UTC_SECONDS + 1)   # the transported length of an instant without a fraction
    return lines + [
        f'utc_shape(x) :- utc_in(x), match("{UTC_SHAPE}", x).',
        f"utc_fields(x, Y, M, D, H, I, S) :- utc_shape(x), {fields}.",
        f"utc_ok(x) :- utc_fields(x, Y, M, D, H, I, S), {clock}, utc_month(M, L), D >= 1, D <= L.",
        f"utc_ok(x) :- utc_fields(x, Y, 2, 29, H, I, S), {clock}, Y % 4 = 0, Y % 100 != 0.",
        f"utc_ok(x) :- utc_fields(x, Y, 2, 29, H, I, S), {clock}, Y % 400 = 0.",
        f"utc_key(x, substr(x, 0, {whole - 2})) :- utc_ok(x), strlen(x) = {whole}.",
        f"utc_cut(x, substr(x, 0, strlen(x) - 2)) :- utc_ok(x), strlen(x) > {whole}.",
        'utc_cut(x, substr(t, 0, strlen(t) - 2)) :- utc_cut(x, t), substr(t, strlen(t) - 2, 2) = "30".',
        'utc_key(x, substr(t, 0, strlen(t) - 2)) :- utc_cut(x, t), substr(t, strlen(t) - 2, 2) = "2e".',
        'utc_key(x, t) :- utc_cut(x, t), substr(t, strlen(t) - 2, 2) != "30", substr(t, strlen(t) - 2, 2) != "2e".']


def probe_rules() -> list[str]:
    return ([f".decl {PROBE}_symbol(x: symbol)", f".decl {PROBE}(x: symbol, y: symbol)"]
            + [f'{PROBE}_symbol("{value}").' for value in PROBE_SYMBOLS]
            + [f"{PROBE}(x, y) :- {PROBE}_symbol(x), {PROBE}_symbol(y), x < y.", f".output {PROBE}"])


def check_probe(root: Path) -> None:
    got = {tuple(line.split("\t")) for line in (root / f"{PROBE}.csv").read_text(encoding="utf-8").splitlines()}
    want = {(a, b) for a in PROBE_SYMBOLS for b in PROBE_SYMBOLS if a.encode() < b.encode()}
    if got != want:
        raise ValueError("the pinned Soufflé does not order symbols by their bytes")


def run(command, **kwargs) -> str:
    try:
        return subprocess.run(command, check=True, capture_output=True, encoding="utf-8", **kwargs).stdout
    except FileNotFoundError as error:
        raise ValueError("rule proposals require the repository-pinned Soufflé interpreter") from error
    except subprocess.CalledProcessError as error:
        raise ValueError(f"Soufflé failed: {error.stderr.strip()}") from error
    except subprocess.TimeoutExpired as error:
        raise ValueError("Soufflé did not complete the proposal comparison") from error


def verified_interpreter() -> None:
    version = run(["souffle", "--version"], timeout=30)
    if not re.search(r"^Version: 2\.5(?:\s|$)", version, re.M) or "Word size: 64 bits" not in version:
        raise ValueError("rule proposals require the repository-pinned 64-bit Soufflé 2.5")


def evaluate(program, inputs: dict, output: str) -> set[tuple[str, ...]]:
    with TemporaryDirectory(prefix="rezono-proposal-oracle-") as directory:
        root = Path(directory)
        lines = []
        for name, relation in sorted(program.relations.items()):
            columns = relation.key + relation.values
            types = ", ".join(f"c{i}:{TYPES[column.type]}" for i, column in enumerate(columns))
            lines.append(f".decl r_{name}({types})")
            if relation.role == "base":
                lines.append(f".input r_{name}")
                rows = ("\t".join(str(value) if column.type == "integer" else symbol(str(value))
                                  for value, column in zip(row, columns, strict=True))
                        for row in inputs.get(name, ()))
                (root / f"r_{name}.facts").write_text("".join(row + "\n" for row in rows), encoding="utf-8")
        lines.extend(clause(program, rule) for rule in program.rules.values())
        kinds = typed(program)
        if kinds:
            lines.extend(probe_rules())
        if "utc_instant" in kinds:
            lines.extend(utc_rules(program))
        lines.append(f".output r_{output}")
        source = root / "proposal.dl"
        source.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run(["souffle", "--no-preprocessor", "-j", "1", "-F", str(root), "-D", str(root), str(source)], timeout=120)
        if kinds:
            check_probe(root)
        columns = program.relations[output].key
        rows = (root / f"r_{output}.csv").read_text(encoding="utf-8").splitlines()
        return {tuple(value if column.type == "integer" else bytes.fromhex(value[1:]).decode("utf-8")
                      for value, column in zip(row.split("\t"), columns, strict=True)) for row in rows}
