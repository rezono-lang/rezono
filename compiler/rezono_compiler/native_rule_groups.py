"""Lower a checked native group clause through the shared rule-IR builder."""

from collections.abc import Iterable, Iterator, Mapping
import json
import re
from typing import Literal, Never

from . import diagnostics, rules, rules_dl


Term = tuple[Literal["var", "wild"], str] | tuple[Literal["const"], str, Literal["string", "integer"]]
Atom = tuple[str, list[Term], str]
COMPARISONS = {"=": "eq", "!=": "ne", "<": "lt", "<=": "le", ">": "gt", ">=": "ge"}
ARITHMETIC = {"+": "add", "-": "sub", "*": "mul"}


def _conjuncts(expression: dict) -> Iterator[dict]:
    """Preserve the written order of the members of one conjunction."""
    if "and" in expression:
        for member in expression["and"]:
            yield from _conjuncts(member)
    else:
        yield expression


class _GroupClause:
    def __init__(self, relations: Iterable[dict], origin: Mapping[str, str]):
        self.relations = {relation["name"]: relation for relation in relations}
        self.file = origin["file"]
        self.line = origin["line"]
        self.column = origin.get("column", "1")

    def refuse(self, message: str) -> Never:
        raise rules_dl.RuleError(f"{self.file}:{self.line}: {message}")

    def unrepresentable(self, message: str,
                        hint: str = "Fix each ranged key column of the group by equality.") -> Never:
        """Refuse a sound expression that the group IR cannot hold (R044), leaving no partial rule."""
        where = f"{self.file}:{self.line}"
        # A rule is a top-level declaration, so its origin starts the line unless the origin names a column.
        span = (self.file, int(self.line), int(self.column))
        raise diagnostics.Diagnosed(f"{where}: {message}", [
            diagnostics.Diagnostic("R044", message, where, span, hint=hint)])

    def columns(self, name: str) -> list[str]:
        return [column["type"] for column in self.relations[name]["key"]]

    def integer(self, token: str) -> Term:
        try:
            number = int(token)
        except ValueError:
            self.refuse(f"{token!r} is not a representable whole number")
        if not rules.BIGINT[0] <= number <= rules.BIGINT[1]:
            self.refuse(f"{token!r} does not fit in a signed 64-bit integer")
        return ("const", str(number), "integer")

    def text(self, token: str) -> Term:
        if token == "_" or rules.is_var(token):
            self.refuse(f"{token!r} collides with a rule-IR term")
        return ("const", token, "string")

    def term(self, expression: dict, expected: str | None = None) -> Term:
        if expression.get("wildcard") is True:
            return ("wild", "_")
        path = expression.get("path", ())
        if len(path) == 1 and rules.VAR.fullmatch("?" + path[0]):
            return ("var", path[0])
        if "neg" in expression and re.fullmatch(r"[0-9]+", expression["neg"].get("lit", "")):
            return self.integer("-" + expression["neg"]["lit"])
        token = expression.get("lit")
        if not isinstance(token, str):
            self.refuse("a rule term needs a bound name, a wildcard or a representable literal")
        if re.fullmatch(r"-?[0-9]+", token):
            return self.integer(token)
        if rules.iso_date(token):
            return self.text(token)
        if match := re.fullmatch(r'[A-Za-z][A-Za-z0-9_.]*:`([^`]+)`', token):
            identity = match[1]
            if expected == "integer" and re.fullmatch(r"-?[0-9]+", identity):
                return self.integer(identity)
            if expected == "string":
                return self.text(identity)
            self.refuse("a typed identifier needs a checked relation column with a matching representation")
        if match := re.fullmatch(r'(?:[A-Za-z][A-Za-z0-9_.]*)?("(?:[^"\\]|\\.)*")', token):
            try:
                value = json.loads(match[1])
            except ValueError:
                self.refuse(f"{token!r} is not a valid text literal")
            return self.text(value)
        self.refuse(f"{token!r} has no rule-IR representation")

    def atom(self, name: str, arguments: list[dict]) -> Atom:
        if name not in self.relations:
            self.refuse(f"{name!r} has no supplied relation signature")
        columns = self.columns(name)
        if len(arguments) != len(columns):
            self.refuse(f"{name!r} takes {len(columns)} columns, got {len(arguments)}")
        return name, [self.term(term, column) for term, column in zip(arguments, columns, strict=True)], self.line

    def result(self, expression: dict) -> str:
        term = self.term(expression)
        if term[0] != "var":
            self.refuse("an aggregate or an integer assignment needs a fresh result variable")
        return term[1]

    def range(self, domain: dict) -> Atom:
        row = domain["filter"][0] if "filter" in domain else domain
        if "call" not in row:
            self.refuse("an aggregate needs a single relation range")
        name, terms, line = self.atom(*row["call"])
        if "filter" not in domain:
            return name, terms, line

        columns = {column["name"]: (index, column["type"])
                   for index, column in enumerate(self.relations[name]["key"])}
        for condition in _conjuncts(domain["filter"][1]):
            cmp = condition.get("cmp", ())
            if len(cmp) != 3 or cmp[0] != "=":
                self.unrepresentable("an aggregate filter must fix a ranged key column by equality")
            _, left, right = cmp
            if right.get("path", ())[:1] == ["it"]:
                left, right = right, left
            column = left.get("path", ())
            if len(column) != 2 or column[0] != "it" or column[1] not in columns:
                self.refuse("an aggregate filter must compare one ranged key column of it")
            index, type_ = columns[column[1]]
            term = self.term(right, type_)
            if terms[index][0] != "wild" or term[0] == "wild":
                self.refuse("an aggregate filter must fix a previously ranged column to one value")
            terms[index] = term
        return name, terms, line

    def measure(self, operator: str, expression: dict | None, atom: Atom) -> str | None:
        if operator == "count":
            if expression is not None:
                self.refuse("count does not take a measure")
            return None
        name, terms, _ = atom
        path = expression.get("path", ()) if expression is not None else ()
        if len(path) != 2 or path[0] != "it":
            self.refuse(f"{operator} needs a measure of the form it.column")
        column = path[1]
        signature = self.relations[name]
        if any(item["name"] == column for item in signature.get("values", ())):
            # A Value can be not_applicable or unknown, and an IR fold would silently drop such a member.
            self.unrepresentable(f"{operator} over the value column {column!r} of {name!r} cannot keep the state "
                                 "of a not_applicable or unknown member",
                                 hint="Aggregate a ranged integer key column, whose members are always known.")
        ranged_types = {item["name"]: item["type"] for item, term in zip(signature["key"], terms, strict=True)
                        if term[0] == "wild"}
        if ranged_types.get(column) != "integer":
            self.refuse(f"{operator} needs a ranged integer key column of {name!r}")
        return column

    def aggregate(self, invocation: list) -> tuple[str, Atom, str | None]:
        if not isinstance(invocation, list) or len(invocation) not in (2, 3):
            self.refuse("an aggregate invocation needs a function, a domain and an optional measure")
        function, domain, *measure = invocation
        if function not in rules.FUNCTIONS or len(measure) > 1:
            self.refuse(f"{function!r} is not a supported aggregate invocation")
        atom = self.range(domain)
        over = self.measure(function, measure[0] if measure else None, atom)
        return function, atom, over

    def body(self, guard: dict) -> tuple[list[tuple], list[str | None]]:
        statements: list[tuple] = []
        measures: list[str | None] = []
        positive: set[str] = set()
        groups: list[Atom] = []
        for node in _conjuncts(guard):
            if "call" in node:
                atom = self.atom(*node["call"])
                positive.update(term[1] for term in atom[1] if term[0] == "var")
                statements.append(("lit", "positive", atom))
            elif "not" in node and "call" in node["not"]:
                statements.append(("lit", "negative", self.atom(*node["not"]["call"])))
            elif "cmp" in node:
                operator, left, right = node["cmp"]
                if operator == "=" and "agg" in right:
                    function, atom, over = self.aggregate(right["agg"])
                    groups.append(atom)
                    measures.append(over)
                    # The native measure names a column. There is no local Datalog variable to recover.
                    statements.append(("agg", self.result(left), function, None, atom))
                elif operator == "=" and "arith" in right:
                    op, first, second = right["arith"]
                    if op not in ARITHMETIC:
                        self.refuse(f"{op!r} is not an integer rule operation")
                    statements.append(("arith", self.result(left), ARITHMETIC[op], self.term(first), self.term(second)))
                elif operator == "=" and right.get("call", [None])[0] == "quotient":
                    operands = right["call"][1]
                    if len(operands) != 2:
                        self.refuse("quotient takes two operands")
                    statements.append(("arith", self.result(left), "div", *(self.term(arg) for arg in operands)))
                elif operator in COMPARISONS:
                    statements.append(("cmp", COMPARISONS[operator], self.term(left), self.term(right)))
                else:
                    self.refuse(f"{operator!r} is not a rule comparison")
            else:
                self.refuse("a group clause needs a conjunction of first-order rule premises")

        # Only an explicit wildcard ranges over keys. A written name always fixes a positively bound key.
        for name, terms, _ in groups:
            for term in terms:
                if term[0] == "var" and term[1] not in positive:
                    self.refuse(f"{term[1]} in the group over {name} needs a positive premise")
        return statements, measures


def lower_aggregate(invocation: list, relations: Iterable[dict], *,
                    origin: Mapping[str, str]) -> tuple[str, Atom, str | None]:
    """Lower one checked native aggregate invocation `(fn, domain[, measure])` to `(fn, atom, over)`.

    Uses the same fixed-key filter and measure rules as `lower_group_clause`, returning the resolved
    relation atom (with wildcards replaced by any fixed-column filter terms) and the measured column
    name (or None for `count`).
    """
    return _GroupClause(relations, origin).aggregate(invocation)


def lower_group_clause(clause: dict, relations: Iterable[dict], *, module: str, origin: Mapping[str, str]) -> dict:
    """Lower one checked conjunction of resolved relation calls and aggregates.

    The caller assembles the program and runs the IR stratifier. Negated keys, aggregate safety and
    evidence bindings are therefore subject to the same checks as in a Datalog rule.
    """
    lowerer = _GroupClause(relations, origin)
    name = clause["rule"]
    if "args" in clause:
        arguments = clause["args"]
    else:
        arguments = [{"path": [column["name"]]} for column in clause["columns"]]
    head = lowerer.atom(name, arguments)
    statements, measures = lowerer.body(clause["when"])
    rule = rules_dl.to_rule(name, module, lowerer.file, head, statements, lowerer.line, lowerer.columns)
    for aggregate, column in zip(rule.get("aggregates", ()), measures, strict=True):
        if column is not None:
            aggregate["over"] = column
    return rule
