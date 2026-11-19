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


def atom(program, value, aggregate_column=None) -> str:
    relation = program.relations[value.relation]
    terms = [term(argument, column.type) for argument, column in zip(value.terms, relation.key, strict=True)]
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
    for condition in rules.untyped_conditions(rule, "the Soufflé comparison"):
        type_ = types.get(condition.left) or types.get(condition.right) or rules.const_type(condition.left)
        body.append(f"{term(condition.left, type_)} {COMPARE[condition.op]} {term(condition.right, type_)}")
    return f"{atom(program, rule.head)} :- {', '.join(body)}."


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
        lines.append(f".output r_{output}")
        source = root / "proposal.dl"
        source.write_text("\n".join(lines) + "\n", encoding="utf-8")
        run(["souffle", "--no-preprocessor", "-j", "1", "-F", str(root), "-D", str(root), str(source)], timeout=120)
        columns = program.relations[output].key
        rows = (root / f"r_{output}.csv").read_text(encoding="utf-8").splitlines()
        return {tuple(value if column.type == "integer" else bytes.fromhex(value[1:]).decode("utf-8")
                      for value, column in zip(row.split("\t"), columns, strict=True)) for row in rows}
