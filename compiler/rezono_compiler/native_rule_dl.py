"""Plan a native rewrite of Datalog without writing sources or changing the active program."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import subprocess

from . import rules_dl
from .rules import BIGINT


RAW_TYPES = {"symbol", "number", "string", "integer"}
COMPARE = {native: source for source, native in rules_dl.COMPARE.items()}
ARITHMETIC = {native: source for source, native in rules_dl.ARITH.items()}
OPTION_NAMES = {"extend", "invariant", "absence", "outcome", "closes", "explain"}


def inventory(root: str | Path) -> list[str]:
    """The authored Datalog files in the current Git index."""
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", "*.dl"], cwd=root)
    return sorted(path for path in tracked.decode("utf-8").split("\0")
                  if path and "fixtures" not in PurePosixPath(path).parts)


@dataclass(frozen=True)
class Source:
    pack: str
    file: str

    @property
    def stem(self) -> str:
        return PurePosixPath(self.file).stem


@dataclass(frozen=True)
class Signature:
    source: Source
    line: int
    order: int
    columns: tuple
    options: tuple

    def has(self, name: str) -> bool:
        return any(name in option for option in self.options)


@dataclass(frozen=True)
class Clause:
    source: Source
    line: int
    column: int
    order: int
    head: tuple
    body: tuple


class Refusal(ValueError):
    def __init__(self, code: str, subject: str, message: str, line: int | None = None):
        super().__init__(message)
        self.code, self.subject, self.line = code, subject, line


def options_for(comments) -> tuple:
    options = []
    for comment in comments:
        fields = comment.removeprefix("//").split(maxsplit=1)
        if not fields:
            continue
        marker, *argument = fields
        name = marker.removeprefix("@")
        if marker.startswith("@") and name in OPTION_NAMES:
            value = (argument[0] if argument else "") if name in {"outcome", "closes", "explain"} else True
            option = {name: value}
            if option not in options:
                options.append(option)
    return tuple(options)


class TypeEvidence:
    """Nominal column evidence shared by variables, recursive calls and all defining clauses."""

    def __init__(self):
        self.parents: dict[tuple, tuple] = {}
        self.nominal: dict[tuple, set[str]] = defaultdict(set)
        self.scalar: dict[tuple, set[str]] = defaultdict(set)

    def root(self, key: tuple) -> tuple:
        root = key
        while root in self.parents:
            root = self.parents[root]
        while key != root:
            parent = self.parents[key]
            self.parents[key] = root
            key = parent
        return root

    def join(self, left: tuple, right: tuple) -> None:
        a, b = self.root(left), self.root(right)
        if a != b:
            self.parents[b] = a
            self.nominal[a].update(self.nominal.pop(b, set()))
            self.scalar[a].update(self.scalar.pop(b, set()))

    def bind(self, key: tuple, term: tuple, clause: int) -> None:
        if term[0] == "var":
            self.join(key, ("variable", clause, term[1]))
        elif term[0] == "const":
            self.scalar[self.root(key)].add("Int" if term[2] == "integer" else "Text")

    def type_of(self, key: tuple) -> str | None:
        root = self.root(key)
        choices = self.nominal[root] or self.scalar[root]
        return next(iter(choices)) if len(choices) == 1 else None

    def ambiguous(self, key: tuple) -> bool:
        root = self.root(key)
        return len(self.nominal[root] or self.scalar[root]) > 1


def check_bindings(rule: dict) -> None:
    """Use the legacy variable names to check the bindings the plan has to preserve."""
    premises = [item for item in rule["body"] if item["polarity"] == "positive"]
    if not premises and (rule["body"] or not rule.get("aggregates")):
        raise Refusal("R042", rule["id"], "A body needs a positive row premise or an aggregate over the whole range")
    positive = {var for item in premises for var in item["terms"] if var.startswith("?")}
    bound = set(positive)
    for item in rule["body"]:
        if item["polarity"] == "negative" and any(t.startswith("?") and t not in positive for t in item["terms"]):
            raise Refusal("R042", item["relation"], "A negative key must be fully bound by positive premises")
    for aggregate in rule.get("aggregates", ()):
        name = aggregate["as"]
        if name in bound:
            raise Refusal("R042", name, "An aggregate must bind a fresh result")
        bound.add(name)
    for assignment in rule.get("assignments", ()):
        name = assignment["var"]
        if name in bound or any(t.startswith("?") and t not in bound for t in (assignment["left"], assignment["right"])):
            raise Refusal("R045", name, "An assignment needs bound operands and a fresh result")
        bound.add(name)
    for var in rule["head"]["terms"]:
        if var.startswith("?") and var not in bound:
            raise Refusal("R042", var, "A head variable needs a positive binding or a computed result")


class Conversion:
    def __init__(self, schema: Mapping, imports: Mapping):
        self.tables = schema
        self.imports = imports
        self.signatures: dict[str, Signature] = {}
        self.clauses: list[Clause] = []
        self.directives: list[tuple] = []
        self.sources: dict[tuple[str, str], Source] = {}
        self.issues: list[dict] = []
        self.refused: set[Source] = set()
        self.types = TypeEvidence()
        self.kinds = {table["kind"] for table in schema.values() if "kind" in table}
        self.enums = {name for table in schema.values() for name in table.get("enums", ())}
        for name, table in schema.items():
            for i, kind in enumerate(table["columns"].values()):
                if isinstance(kind, str) and kind not in RAW_TYPES:
                    self.types.nominal[(name, i)].add(kind)

    def issue(self, source: Source, line: int, failure: Refusal) -> None:
        self.refused.add(source)
        self.issues.append({"code": failure.code, "file": source.file, "line": failure.line or line,
                            "subject": failure.subject, "message": str(failure)})

    def column_names(self, name: str) -> tuple:
        if name in self.tables:
            return tuple(self.tables[name]["columns"])
        return tuple(column for column, _ in self.signatures[name].columns)

    def storage(self, name: str) -> list[str] | None:
        if name in self.signatures:
            return [kind for _, kind in self.signatures[name].columns]
        if name not in self.tables:
            return None
        table = self.tables[name]
        storage = table.get("storage", {})
        return [storage.get(column, "integer" if kind in {"Int", "number", "integer"} else "string")
                for column, kind in table["columns"].items()]

    def reference(self, source: Source, name: str) -> str:
        if name in self.tables:
            return name
        owner = self.signatures.get(name)
        if owner is None:
            raise Refusal("R001", name, f"{name} is neither a schema input nor a declared relation")
        if owner.source.pack == source.pack:
            return name
        aliases = [alias for alias, target in self.imports.get(source.pack, {}).items()
                   if target == owner.source.pack]
        if len(aliases) != 1:
            raise Refusal("R046", name, f"{name} needs one visible import of its owner {owner.source.pack}")
        return f"{aliases[0]}.{name}"

    def read(self, pack: str, file: str, text: str) -> None:
        source = Source(pack, file)
        key = pack, source.stem
        if key in self.sources:
            first = self.sources[key]
            failure = Refusal("R040", source.stem, f"The rule module is also supplied by {first.file}")
            self.issue(first, 1, failure)
            if source != first:
                self.issue(source, 1, failure)
            return
        self.sources[key] = source
        columns = []
        try:
            statements = rules_dl.parse_file(text, file, columns)
        except rules_dl.RuleError as error:
            where, _, message = str(error).removeprefix(file + ":").partition(": ")
            self.issue(source, int(where) if where.isdecimal() else 1,
                       Refusal("R000", source.stem, message or str(error)))
            return
        positions = iter(columns)
        comments = iter(token.comments for token in rules_dl.tokens(text, file)
                        if token.kind == "directive" and token.text == ".decl")
        for order, statement in enumerate(statements):
            match statement:
                case ("decl", name, raw_columns, line, *_):
                    signature = Signature(source, line, order, tuple(raw_columns), options_for(next(comments)))
                    self.declare(name, signature)
                case ("io", direction, names, line):
                    self.directives.append((source, direction, names, line))
                case ("rule", head, body, line):
                    self.clauses.append(Clause(source, line, next(positions), order, head, tuple(body)))

    def declare(self, name: str, signature: Signature) -> None:
        source, line = signature.source, signature.line
        if name in self.tables:
            if signature.options or [t for _, t in signature.columns] != self.storage(name):
                self.issue(source, line, Refusal("R040", name, f"The input declaration does not match {name}"))
            return
        owner = self.signatures.get(name)
        if owner is None:
            self.signatures[name] = signature
            return
        try:
            self.reference(source, name)
            if (owner.source.pack == source.pack or not owner.has("extend")
                    or owner.columns != signature.columns or owner.options != signature.options):
                raise Refusal("R040", name, f"The declaration conflicts with its owner {owner.source.file}")
        except Refusal as error:
            self.issue(source, line, error)

    def check_directives(self) -> None:
        for source, direction, names, line in self.directives:
            for name in names:
                try:
                    self.reference(source, name)
                    if name not in (self.tables if direction == "input" else self.signatures):
                        raise Refusal("R040", name, f".{direction} {name} does not name the required relation")
                except Refusal as error:
                    self.issue(source, line, error)

    def check_atom(self, source: Source, atom: tuple) -> None:
        name, terms, line = atom
        self.reference(source, name)
        if len(terms) != len(self.column_names(name)):
            raise Refusal("R041", name, f"{name} takes {len(self.column_names(name))} columns, got {len(terms)}", line)

    def prepare(self) -> list[tuple[int, Clause, dict]]:
        prepared = []
        self.check_directives()
        for number, clause in enumerate(self.clauses):
            name = clause.head[0]
            owner = self.signatures.get(name)
            try:
                if owner is None:
                    raise Refusal("R040", name, f"{name} needs an owning derived signature")
                self.check_atom(clause.source, clause.head)
                if owner.source != clause.source and (owner.source.pack == clause.source.pack or not owner.has("extend")):
                    raise Refusal("R046", name, f"{name} cannot be extended from {clause.source.file}")
                atoms = [clause.head, *(item[-1] for item in clause.body if item[0] in {"lit", "agg"})]
                for atom in atoms[1:]:
                    self.check_atom(clause.source, atom)
                legacy = rules_dl.to_rule(name, owner.source.stem, clause.source.file,
                                          clause.head, clause.body, clause.line, self.storage)
                check_bindings(legacy)
            except rules_dl.RuleError as error:
                self.issue(clause.source, clause.line, Refusal("R042", name, str(error)))
                continue
            except Refusal as error:
                self.issue(clause.source, clause.line, error)
                continue
            for atom in [clause.head, *(item[-1] for item in clause.body if item[0] == "lit")]:
                for i, term in enumerate(atom[1]):
                    self.types.bind((atom[0], i), term, number)
            for item in clause.body:
                if item[0] == "arith" or (item[0] == "agg" and item[2] == "count"):
                    self.types.scalar[self.types.root(("variable", number, item[1]))].add("Int")
                elif item[0] == "cmp":
                    self.types.bind(("comparison", number, item), item[2], number)
                    self.types.bind(("comparison", number, item), item[3], number)
            ranges = (item[-1] for item in clause.body if item[0] == "agg")
            for aggregate, atom in zip(legacy.get("aggregates", ()), ranges, strict=True):
                for i, (term, lowered) in enumerate(zip(atom[1], aggregate["terms"], strict=True)):
                    if lowered != "_":
                        self.types.bind((atom[0], i), term, number)
                if "over" in aggregate:
                    position = aggregate["over"]["position"]
                    self.types.join(("variable", number, aggregate["as"][1:]), (atom[0], position))
            prepared.append((number, clause, legacy))
        return prepared

    def term(self, term: tuple, kind: str | None) -> dict:
        if term[0] == "wild":
            return {"wildcard": True}
        if term[0] == "var":
            return {"path": [term[1]]}
        value, storage = term[1:]
        if storage == "integer" and not BIGINT[0] <= int(value) <= BIGINT[1]:
            raise Refusal("R049", value, "The integer literal is outside the rule engine's signed range")
        if kind in self.kinds:
            if not value or "`" in value or "\n" in value or "\r" in value:
                raise Refusal("R049", kind, "The identifier cannot be written as a native kind literal")
            return {"lit": f"{kind}:`{value}`"}
        written = json.dumps(value, ensure_ascii=False) if storage == "string" else value
        if kind in self.enums:
            written = kind + written
        elif kind is not None and kind not in {"Text", "Int"}:
            raise Refusal("R049", kind, "The literal needs evidence for its native nominal type")
        return {"lit": written}

    def atom(self, source: Source, legacy: tuple, ranged: list[str] | None = None) -> dict:
        name, terms, line = legacy
        table = self.tables.get(name, {})
        arguments = []
        for i, term in enumerate(terms):
            if ranged is not None and ranged[i] == "_":
                term = ("wild",)
            if term[0] != "wild" and self.types.ambiguous((name, i)):
                column = self.column_names(name)[i]
                raise Refusal("R049", f"{name}.{column}", "The row pattern needs compatible nominal types", line)
            arguments.append(self.term(term, self.types.type_of((name, i))))
        kind, slot = table.get("kind"), table.get("slot")
        if kind and not slot and ranged is None and len(arguments) == 1:
            return {"in": [arguments[0], {"kind": kind}]}
        if kind and not slot and ranged is not None:
            if ranged == ["_"]:
                return {"kind": kind}
            raise Refusal("R044", name, "The kind range needs an explicit row pattern for its fixed key")
        target = table.get("call") or (f"{kind}.{slot}" if kind and slot else self.reference(source, name))
        return {"call": [target, arguments]}

    def body(self, clause: Clause, number: int, aggregates, opened: set[str]) -> dict:
        nodes = []
        source = clause.source
        for item in clause.body:
            if item[0] in {"lit", "agg"}:
                name, _, line = item[-1]
                if ((item[0] == "agg" or item[1] == "negative") and name in opened
                        and not self.signatures[clause.head[0]].has("absence")):
                    raise Refusal("R047", name, "An open register needs scoped completeness evidence", line)
            match item:
                case ("lit", polarity, atom):
                    node = self.atom(source, atom)
                    nodes.append({"not": node} if polarity == "negative" else node)
                case ("agg", var, function, _, atom):
                    aggregate = next(aggregates)
                    arguments = [function, self.atom(source, atom, aggregate["terms"])]
                    if "over" in aggregate:
                        over = self.column_names(atom[0])[aggregate["over"]["position"]]
                        if self.storage(atom[0])[aggregate["over"]["position"]] != "integer":
                            raise Refusal("R044", over, "The aggregate measure needs a ranged integer column")
                        arguments.append({"path": ["it", over]})
                    nodes.append({"cmp": ["=", {"path": [var]}, {"agg": arguments}]})
                case ("cmp", op, left, right):
                    key = ("comparison", number, item)
                    if self.types.ambiguous(key):
                        raise Refusal("R049", clause.head[0], "The comparison needs compatible nominal types")
                    kind = self.types.type_of(key)
                    nodes.append({"cmp": [COMPARE[op], self.term(left, kind), self.term(right, kind)]})
                case ("arith", var, op, left, right):
                    terms = [self.term(left, "Int"), self.term(right, "Int")]
                    if op == "div" and (right[0] != "const" or right[1] == "0"):
                        raise Refusal("R045", var, "quotient needs a nonzero constant divisor")
                    result = {"call": ["quotient", terms]} if op == "div" else {"arith": [ARITHMETIC[op], *terms]}
                    nodes.append({"cmp": ["=", {"path": [var]}, result]})
        return nodes[0] if len(nodes) == 1 else {"and": nodes}

    def opened(self, prepared) -> set[str]:
        opened = {name for name, table in self.tables.items() if table.get("world") == "open"}
        while True:
            more = {clause.head[0] for _, clause, ir in prepared
                    if not self.signatures[clause.head[0]].has("absence")
                    and any(lit["polarity"] == "positive" and lit["relation"] in opened for lit in ir["body"])}
            if more <= opened:
                return opened
            opened.update(more)

    def signature_tree(self, name: str, signature: Signature) -> dict:
        columns, options = [], []
        for i, (column, _) in enumerate(signature.columns):
            kind = self.types.type_of((name, i))
            if kind is None:
                raise Refusal("R049", f"{name}.{column}", "The column needs unambiguous nominal type evidence")
            columns.append({"name": column, "type": kind})
        for option in signature.options:
            if "outcome" in option:
                outcome = self.tables.get(option["outcome"], {}).get("kind")
                if not outcome:
                    raise Refusal("R049", option["outcome"], "The outcome needs a resolved kind")
                option = {"outcome": outcome}
            elif "closes" in option:
                option = {"closes": self.reference(signature.source, option["closes"])}
            elif "explain" in option and option["explain"] not in {"fold", "on_demand", "materialize"}:
                raise Refusal("R048", name, "Explain must choose on_demand, materialize or fold")
            options.append(option)
        return {"rule": name, "columns": columns, **({"options": options} if options else {})}

    def plan(self) -> dict:
        prepared = self.prepare()
        opened = self.opened(prepared)
        declarations: dict[Source, dict] = defaultdict(dict)
        total = Counter(clause.head[0] for clause in self.clauses)
        seen: Counter[str] = Counter()
        ordinals = []
        for clause in self.clauses:
            name = clause.head[0]
            seen[name] += 1
            ordinals.append(seen[name])
        for name, signature in self.signatures.items():
            if signature.source not in self.refused:
                try:
                    if not total[name] and not signature.has("extend"):
                        raise Refusal("R048", name, "An ordinary signature needs a defining clause")
                    declarations[signature.source][signature.order] = self.signature_tree(name, signature)
                except Refusal as error:
                    self.issue(signature.source, signature.line, error)
        provenance = []
        for number, clause, legacy in prepared:
            name, raw_args, _ = clause.head
            ordinal = ordinals[number]
            owner = self.signatures[name]
            if clause.source in self.refused:
                continue
            try:
                node = {"rule": self.reference(clause.source, name),
                        "args": [self.term(term, self.types.type_of((name, i))) for i, term in enumerate(raw_args)],
                        "when": self.body(clause, number, iter(legacy.get("aggregates", ())), opened)}
            except Refusal as error:
                self.issue(clause.source, clause.line, error)
                continue
            entries = declarations[clause.source]
            if (ordinal == 1 and owner.source == clause.source and owner.order in entries
                    and node["args"] == [{"path": [column]} for column, _ in owner.columns]):
                node = entries.pop(owner.order) | {"when": node["when"]}
            entries[clause.order] = node
            rule_id = name if total[name] == 1 else f"{name}_{ordinal}"
            provenance.append((clause.source, {"id": rule_id, "owner_pack": owner.source.pack,
                                               "owner_module": owner.source.stem, "file": clause.source.file,
                                               "line": clause.line, "column": clause.column}))
        return {"modules": [{"pack": source.pack, "stem": source.stem,
                             "decls": [node for _, node in sorted(declarations[source].items())]}
                            for source in self.sources.values() if source not in self.refused],
                "clauses": [record for source, record in provenance if source not in self.refused],
                "issues": self.issues}


def convert_modules(sources: Sequence[Mapping], schema: Mapping, imports: Mapping) -> dict:
    """Read resolved tables and Datalog files in legacy assembly order and plan their native declarations.

    A table supplies ordered column types, its optional kind and slot names, and its world. A source
    supplies a pack, a relative file, and its text. Imports map each consumer's aliases to verified packs.
    A refusal keeps the affected source in Datalog. The plan never writes or replaces a file.
    """
    conversion = Conversion(schema, imports)
    for source in sources:
        conversion.read(source["pack"], source["file"], source["text"])
    return conversion.plan()
