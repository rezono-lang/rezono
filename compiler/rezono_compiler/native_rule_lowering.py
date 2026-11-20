"""Lower native membership rules through the existing rule assembler."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import NoReturn

from . import diagnostics, modules, native_rule_groups, native_rule_signatures, rezono_module, rules, rules_dl, spans
from .diagnostics import Diagnostic
from .pack import CompileError


def lower_modules(meta: dict, definitions: list[modules.Module], imports: dict[str, modules.Imported],
                  names: modules.Names) -> tuple[rules_dl.NativeSource, ...]:
    authored = [(m, form) for m in definitions
                if (form := m.form) is not None and form["format"] == rezono_module.NATIVE_FORMAT]
    if not authored:
        return ()
    forms = {(m.pack, m.rel): form for m, form in authored}
    linked = native_rule_signatures.link_modules(meta, definitions, imports, names, forms)
    result = []
    for module, form in authored:
        if source := lower_source(module, form, meta["name"], linked):
            result.append(source)
    return tuple(result)


def lower_source(module: modules.Module, form: dict, root: str,
                 linked: native_rule_signatures.Linked) -> rules_dl.NativeSource | None:
    declarations = [(f"/decls/{i}", d) for i, d in enumerate(form["module"]["decls"]) if "rule" in d]
    if not declarations:
        return None
    where = spans.where(module.pack, root, module.rel)
    try:
        text = module.file.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise CompileError(f"{where}: cannot read the native rule positions") from error
    offsets = {place["at"]: place["start"] for place in form["spans"]}
    statements, columns, refused = [], [], []
    site = Site(where, text, offsets)
    for at, declaration in declarations:
        # Every declaration is checked, so a refusal in one does not hide the refusal of another; a module with
        # any refusal lowers no rule at all.
        try:
            lower_declaration(site, linked, module, at, declaration, statements, columns)
        except CompileError as error:
            refused.extend(error.diagnostics)
    if refused:
        raise CompileError("\n".join(str(diagnostic) for diagnostic in refused), refused)
    return rules_dl.NativeSource(module.pack, module.file.stem, where, text, tuple(statements), tuple(columns))


def lower_declaration(site: Site, linked: native_rule_signatures.Linked, module: modules.Module, at: str,
                      declaration: dict, statements: list, columns: list) -> None:
    where, text, offsets = site.file, site.text, site.offsets
    start = offsets[at]
    if len(start) > len(str(len(text))) or int(start) >= len(text):
        refuse(where, at, 1, 1, "A rule head needs a position in its authored source")
    offset = int(start)
    line = text.count("\n", 0, offset) + 1
    column = offset - text.rfind("\n", 0, offset)
    options = declaration.get("options")
    if set(declaration) - {"rule", "columns", "args", "when", "options"} or (
        options is not None and
        (len(options) != 1 or options[0].keys() != {"extend"} or options[0]["extend"] is not True)
    ):
        refuse(where, at, line, column, "Rule options and locals are not lowered yet")
    if "columns" in declaration:
        name = declaration["rule"]
        signature = linked.signatures[name]
        key = [(col, storage) for col, _, storage in signature.key]
        statements.append(("decl", name, key, line, None, False, False, None, signature.extend, None, False))
    if "when" in declaration:
        clause = linked.clauses[module.pack, module.rel, at]
        signature = linked.signatures[clause.relation]
        head = declaration.get("args", [{"path": [name]} for name, _, _ in signature.key])
        names = "columns" if "args" not in declaration else "args"
        branches = alternatives(f"{at}/when", declaration["when"])
        for premises in branches:
            body: list[tuple] = []
            bound: set[str] = set()
            positive: set[str] = set()
            used = mentioned(head) | mentioned([node for _, node in premises])
            for pointer, node in premises:
                body.extend(premise(site, linked, clause, pointer, node, bound, positive, used, line))
            head_terms = []
            for index, argument in enumerate(head):
                place = f"{at}/{names}/{index}"
                head_name = variable(argument)
                if head_name is None:
                    refuse(where, place, *site.span(place)[1:], "A native rule head takes a variable in each column")
                if head_name not in bound:
                    reason = ("is not bound by every alternative of the guard" if len(branches) > 1
                              else "is declared with a type but no positive premise binds it")
                    refuse(where, place, *site.span(place)[1:], f"The head column {head_name!r} {reason}", "R042")
                head_terms.append(("var", head_name))
            statements.append(("rule", (clause.relation, head_terms, line), body, line))
            columns.append(column)


def alternatives(pointer: str, node: dict) -> list[list[tuple[str, dict]]]:
    """The guard as one premise list per alternative, each in binding order (language-expression-semantics §1).

    `a and b` joins every alternative of `a` with every alternative of `b`; `a or b` keeps the alternatives of
    both. Each alternative becomes one rule of the head relation, so a binding only reaches the head when every
    alternative binds it.
    """
    if set(node) == {"and"} and node["and"]:
        result: list[list[tuple[str, dict]]] = [[]]
        for index, member in enumerate(node["and"]):
            result = [left + right for left in result for right in alternatives(f"{pointer}/and/{index}", member)]
        return result
    if set(node) == {"or"} and node["or"]:
        return [branch for index, member in enumerate(node["or"])
                for branch in alternatives(f"{pointer}/or/{index}", member)]
    return [[(pointer, node)]]


def slot_row(clause: native_rule_signatures.LinkedClause, pointer: str, guard: dict) -> tuple[str | None, list]:
    """The forward slot or relation row of a single positive premise, or no table when it has none."""
    if set(guard) == {"cmp"} and guard["cmp"][0] == "=":
        _, left, right = guard["cmp"]
        for side, path, other in ((1, left, right), (2, right, left)):
            at = f"{pointer}/cmp/{side}"
            table, _ = clause.paths.get(at, (None, None))
            if (table is not None and at not in clause.collections
                    and len(path.get("path", ())) == 2 and (value := operand(other)) is not None):
                return table, [("var", path["path"][0]), value]
    elif set(guard) == {"in"}:
        subject, domain = guard["in"]
        table, _ = clause.paths.get(f"{pointer}/in/1", (None, None))
        if table is not None and len(domain.get("path", ())) == 2 and (value := operand(subject)) is not None:
            return table, [("var", domain["path"][0]), value]
    elif set(guard) == {"call"} and (table := clause.calls.get(pointer)) is not None:
        values = [("wild",) if argument == {"wildcard": True} else operand(argument) for argument in guard["call"][1]]
        if all(value is not None for value in values):
            return table, values
    return None, []


def operand(node: dict) -> tuple | None:
    """A variable or a representable literal as a rule term; anything else has no direct row term."""
    if node.keys() == {"path"} and len(node["path"]) == 1 and rules_dl.VARIABLE.fullmatch(node["path"][0]):
        return "var", node["path"][0]
    if node.keys() == {"neg"} and isinstance(node["neg"], dict) and node["neg"].keys() == {"lit"}:
        if re.fullmatch(r"[0-9]+", node["neg"]["lit"]):
            return "const", str(-int(node["neg"]["lit"])), "integer"
    if node.keys() == {"lit"}:
        token = node["lit"]
        if re.fullmatch(r"-?[0-9]+", token):
            return "const", str(int(token)), "integer"
        if token.startswith('"'):
            try:
                value = json.loads(token)
            except ValueError:
                return None
            if isinstance(value, str) and value != "_" and not value.startswith("?"):
                return "const", value, "string"
    return None


@dataclass(frozen=True)
class Site:
    """Where the authored rules are written: the file, its text and the start offset of each tree node."""

    file: str
    text: str
    offsets: dict[str, str]

    def span(self, at: str) -> spans.Span:
        offset = int(self.offsets[at])
        return self.file, self.text.count("\n", 0, offset) + 1, offset - self.text.rfind("\n", 0, offset)


def premise(site: Site, linked: native_rule_signatures.Linked, clause: native_rule_signatures.LinkedClause,
            pointer: str, node: dict, bound: set[str], positive: set[str], used: set[str], line: int) -> list[tuple]:
    """Lower one premise of an alternative in binding order and add the names it binds to `bound`.

    A kind membership, a forward slot row or a relation call binds its variables positively. `n = k + 1` and
    aggregates bind a fresh computed result from prior bindings. A scalar comparison or its negation reads
    positive slot rows and emits an IR condition without exporting bindings. A negated call exports no binding
    and needs every key positively bound.
    """
    if set(node) == {"not"} and set(node["not"]) == {"call"} and (relation := clause.calls.get(f"{pointer}/not")):
        return [negated(site, linked, pointer, node["not"], relation, positive, line)]
    if set(node) == {"in"} and (kind := clause.memberships.get(pointer)) is not None:
        name = variable(node["in"][0])
        if name is None:
            refuse(site.file, pointer, *site.span(pointer)[1:], "A kind membership in a native rule takes a variable")
        bound.add(name)
        positive.add(name)
        return [("lit", "positive", (kind, [("var", name)], line))]
    if (computed := assignment(site, pointer, node, bound)) is not None:
        return [computed]
    if (grouped := aggregate(site, linked, clause, pointer, node, bound, positive, used, line)) is not None:
        return grouped
    table, terms = slot_row(clause, pointer, node)
    if table is not None:
        new = {term[1] for term in terms if term[0] == "var"}
        bound.update(new)
        positive.update(new)
        return [("lit", "positive", (table, terms, line))]
    if (compared := scalar_comparison(site, clause, pointer, node, bound, used, line)) is not None:
        return compared
    if (annotation := typed_annotation(site, pointer, node)) is not None:
        refuse(site.file, pointer, *site.span(pointer)[1:], f"{annotation[0]}(…) only as an operand of a comparison")
    refuse(site.file, pointer, *site.span(pointer)[1:],
           "A native rule premise needs a kind membership, a slot row, a relation call, a negated relation call, "
           "a scalar comparison, an aggregate or a computed assignment")


# Negation of a strict scalar comparison swaps T and F on known values while preserving undecided states.
NEGATED_COMPARE = {"=": "!=", "!=": "=", "<": ">=", "<=": ">", ">": "<=", ">=": "<"}


def typed_annotation(site: Site, at: str, node: dict) -> tuple[str, dict] | None:
    """`utc_instant(x)` or `binary_text(x)` on a comparison operand: (mode, operand)."""
    if set(node) == {"call"}:
        name, args = node["call"]
        if name in rules.COMPARE_AS:
            if len(args) != 1:
                refuse(site.file, at, *site.span(at)[1:], f"{name!r} takes 1 column, got {len(args)}", "R041")
            return name, args[0]
    return None


def scalar_comparison(site: Site, clause: native_rule_signatures.LinkedClause, pointer: str, node: dict,
                      bound: set[str], used: set[str], line: int) -> list[tuple] | None:
    """Lower a scalar comparison or its negation to positive slot rows and an IR condition.

    Never lowers a scalar negation as an anti-join: an absent or undecided slot has no positive slot row, so
    the rule derives nothing for it (decisions/language-expression-semantics.md §1, §2 rule 1).
    """
    flipped = False
    at = pointer
    inner = node
    while set(inner) == {"not"}:
        flipped = not flipped
        at = f"{at}/not"
        inner = inner["not"]
    if set(inner) != {"cmp"}:
        return None
    symbol, left, right = inner["cmp"]
    if symbol not in rules_dl.COMPARE:
        refuse(site.file, at, *site.span(at)[1:], f"Comparison {symbol!r} is not lowered in a native rule")
    operator = NEGATED_COMPARE[symbol] if flipped else symbol
    left_typed = typed_annotation(site, f"{at}/cmp/1", left)
    right_typed = typed_annotation(site, f"{at}/cmp/2", right)
    if (left_typed is None) != (right_typed is None):
        mode = (left_typed or right_typed)[0]
        refuse(site.file, at, *site.span(at)[1:],
               f"{mode}(…) on one side of a comparison only; write it on both operands")
    mode = None
    if left_typed is not None and right_typed is not None:
        if left_typed[0] != right_typed[0]:
            refuse(site.file, at, *site.span(at)[1:],
                   f"Cannot compare {left_typed[0]} with {right_typed[0]}", "R003")
        mode = left_typed[0]
    items: list[tuple] = []
    terms = []
    for side, child, annotation in ((1, left, left_typed), (2, right, right_typed)):
        child_at = f"{at}/cmp/{side}/call/1/0" if annotation is not None else f"{at}/cmp/{side}"
        operand_node = annotation[1] if annotation is not None else child
        term, reads = scalar_operand(site, clause, child_at, operand_node, bound, used, line)
        if mode is not None and term[0] != "var":
            refuse(site.file, child_at, *site.span(child_at)[1:],
                   f"{mode}(…) takes a bound text variable or scalar slot path")
        items.extend(reads)
        terms.append(term)
    cmp_item: tuple = ("cmp", rules_dl.COMPARE[operator], terms[0], terms[1])
    if mode is not None:
        cmp_item = (*cmp_item, mode)
    items.append(cmp_item)
    return items


def scalar_operand(site: Site, clause: native_rule_signatures.LinkedClause, at: str, node: dict,
                   bound: set[str], used: set[str], line: int) -> tuple[tuple, list[tuple]]:
    """Lower one operand of a scalar comparison: a single-hop scalar slot read, a bound variable or a literal."""
    if at in clause.paths:
        if at in clause.collections:
            refuse(site.file, at, *site.span(at)[1:],
                   "A scalar comparison cannot read a multivalued slot", "R005")
        path = node.get("path", ())
        if len(path) != 2 or not rules_dl.VARIABLE.fullmatch(path[0]):
            refuse(site.file, at, *site.span(at)[1:],
                   "A scalar comparison path in a native rule takes a single slot hop")
        subject = path[0]
        if subject not in bound:
            refuse(site.file, at, *site.span(at)[1:],
                   f"The subject {subject!r} has no positive binding before the comparison", "R042")
        table, _ = clause.paths[at]
        if table is None:
            return ("var", subject), []
        value = fresh_variable(used)
        return ("var", value), [("lit", "positive", (table, [("var", subject), ("var", value)], line))]
    term = operand(node)
    if term is None:
        refuse(site.file, at, *site.span(at)[1:],
               "A scalar comparison operand in a native rule is a bound variable, a scalar slot path or a literal")
    if term[0] == "var" and term[1] not in bound:
        refuse(site.file, at, *site.span(at)[1:],
               f"The operand {term[1]!r} has no positive binding before the comparison", "R042")
    return term, []


def mentioned(value: object) -> set[str]:
    """Every root variable name written in a head or branch, so fresh slot variables never collide."""
    names: set[str] = set()
    if isinstance(value, dict):
        path = value.get("path")
        if isinstance(path, list) and path and isinstance(path[0], str):
            names.add(path[0])
        for child in value.values():
            names.update(mentioned(child))
    elif isinstance(value, list):
        for item in value:
            names.update(mentioned(item))
    return names


def fresh_variable(used: set[str]) -> str:
    """Next deterministic rule variable name not yet used in this clause."""
    index = 1
    while (name := f"v{index}") in used:
        index += 1
    used.add(name)
    return name


def assignment(site: Site, pointer: str, node: dict, bound: set[str]) -> tuple | None:
    """`n = k + 1` with a fresh `n` as an IR assignment, after proving that each operand is bound before it."""
    if set(node) != {"cmp"} or node["cmp"][0] != "=":
        return None
    _, left, right = node["cmp"]
    for target, side, expression in ((left, 2, right), (right, 1, left)):
        name = variable(target)
        if name is None or name in bound or set(expression) != {"arith"}:
            continue
        symbol, *operands = expression["arith"]
        place = f"{pointer}/cmp/{side}"
        if symbol not in COMPUTED or len(operands) != 2:
            refuse(site.file, place, *site.span(place)[1:], f"Arithmetic {symbol!r} is not lowered in a native rule")
        terms = []
        for index, child in enumerate(operands, 1):
            at = f"{place}/arith/{index}"
            term = operand(child)
            if term is None or (term[0] == "const" and term[2] != "integer"):
                refuse(site.file, at, *site.span(at)[1:],
                       "An arithmetic operand in a native rule is a variable or an integer literal")
            if term[0] == "var" and term[1] not in bound:
                refuse(site.file, at, *site.span(at)[1:],
                       f"The operand {term[1]!r} has no positive binding before the assignment", "R042")
            terms.append(term)
        bound.add(name)
        return "arith", name, rules_dl.ARITH[symbol], *terms
    return None


# Exact integer operations; `/` is exact division in the language and has no exact rule IR assignment.
COMPUTED = ("+", "-", "*")


def require_decided(site: Site, pointer: str, relation: str,
                    signature: native_rule_signatures.Signature | None,
                    operation: str) -> native_rule_signatures.Signature:
    """Require a linked, closed, two-valued signature before negating or aggregating a relation."""
    span = site.span(pointer)[1:]
    predicate = getattr(signature, "predicate", None)
    owner = getattr(signature, "owner", None)
    if signature is None or not owner or not predicate or predicate.get("relation") != relation or predicate.get(
            "owner") != owner:
        refuse(site.file, pointer, *span,
               f"The predicate states of {relation!r} are not linked, so its {operation} is not proved two-valued",
               "R047")
    if predicate.get("world") != "closed":
        refuse(site.file, pointer, *span,
               f"{relation!r} is read in an open world, so its {operation} needs an explicit absence", "R004")
    if predicate.get("states") != ["known"]:
        causes = tuple((place["file"], int(place["line"]), int(place["column"]))
                       for place in predicate.get("related", ()))
        refuse(site.file, pointer, *span,
               f"{relation!r} can be undecided, so its {operation} needs a checked outcome", "R047", causes)
    return signature


def aggregate(site: Site, linked: native_rule_signatures.Linked, clause: native_rule_signatures.LinkedClause,
              pointer: str, node: dict, bound: set[str], positive: set[str], used: set[str],
              line: int) -> list[tuple] | None:
    """Lower a filtered or unfiltered relation aggregate through `native_rule_groups`."""
    if set(node) != {"cmp"} or node["cmp"][0] != "=":
        return None
    _, left, right = node["cmp"]
    if set(right) == {"agg"}:
        target, target_at, invocation, agg_at = left, f"{pointer}/cmp/1", right["agg"], f"{pointer}/cmp/2"
    elif set(left) == {"agg"}:
        target, target_at, invocation, agg_at = right, f"{pointer}/cmp/2", left["agg"], f"{pointer}/cmp/1"
    else:
        return None
    name = variable(target)
    if name is None or name in bound:
        refuse(site.file, target_at, *site.span(target_at)[1:],
               "An aggregate result in a native rule needs a fresh variable", "R045")
    agg_line, agg_column = site.span(agg_at)[1:]
    if not isinstance(invocation, list) or len(invocation) not in (2, 3) or not isinstance(invocation[1], dict):
        refuse(site.file, agg_at, agg_line, agg_column,
               "An aggregate in a native rule needs a function and a relation domain", "R044")
    function, domain, *measure = invocation
    filtered = set(domain) == {"filter"} and isinstance(domain["filter"], list) and len(domain["filter"]) == 2
    source = domain["filter"][0] if filtered else domain
    call_at = f"{agg_at}/agg/1/filter/0" if filtered else f"{agg_at}/agg/1"
    if not isinstance(source, dict) or set(source) != {"call"}:
        refuse(site.file, agg_at, agg_line, agg_column,
               "An aggregate in a native rule needs a single relation range", "R044")
    relation = clause.calls.get(call_at)
    if relation is None:
        refuse(site.file, call_at, *site.span(call_at)[1:],
               "An aggregate in a native rule needs a linked relation call", "R044")
    signature = linked.signatures.get(relation)
    if signature is None:
        require_decided(site, agg_at, relation, None, "aggregation")
    relations = [{"name": relation, "key": [{"name": col, "type": storage} for col, _, storage in signature.key]}]
    resolved_call = {"call": [relation, source["call"][1]]}
    resolved_domain = {"filter": [resolved_call, domain["filter"][1]]} if filtered else resolved_call
    origin = {"file": site.file, "line": str(agg_line), "column": str(agg_column)}
    try:
        fn, (_, terms, _), over = native_rule_groups.lower_aggregate(
            [function, resolved_domain, *measure], relations, origin=origin,
        )
    except diagnostics.Diagnosed as error:
        first = error.diagnostics[0]
        refuse(site.file, agg_at, agg_line, agg_column, first.message, first.code)
    except rules_dl.RuleError as error:
        refuse(site.file, agg_at, agg_line, agg_column, str(error), "R044")
    for term in terms:
        if term[0] == "var" and term[1] not in positive:
            refuse(site.file, agg_at, agg_line, agg_column,
                   f"The group key {term[1]!r} has no positive binding before the aggregate", "R042")
    require_decided(site, agg_at, relation, signature, "aggregation")
    target_var: str | None = None
    if over is not None:
        index = next(i for i, (col, _, _) in enumerate(signature.key) if col == over)
        target_var = fresh_variable(used)
        terms = list(terms)
        terms[index] = ("var", target_var)
    bound.add(name)
    return [("agg", name, fn, target_var, (relation, terms, line))]


def negated(site: Site, linked: native_rule_signatures.Linked, pointer: str, call: dict, relation: str,
            positive: set[str], line: int) -> tuple:
    """Lower a negated call after proving that its key is bound and the link supplies the evidence it needs."""
    terms = []
    for index, argument in enumerate(call["call"][1]):
        at = f"{pointer}/not/call/1/{index}"
        term = operand(argument)
        if term is None:
            refuse(site.file, at, *site.span(at)[1:],
                   "A negated relation call takes a variable or an integer literal in each column")
        if term[0] == "var" and term[1] not in positive:
            refuse(site.file, at, *site.span(at)[1:],
                   f"The negated key {term[1]!r} has no positive binding before the negation", "R042")
        terms.append(term)
    require_decided(site, pointer, relation, linked.signatures.get(relation), "negation")
    return "lit", "negative", (relation, terms, line)


def variable(node: dict) -> str | None:
    """The name of a single-variable path, or none."""
    if node.keys() == {"path"} and len(node["path"]) == 1 and rules_dl.VARIABLE.fullmatch(node["path"][0]):
        return node["path"][0]
    return None

def refuse(file: str, at: str, line: int, column: int, message: str, code: str = "R049",
           related: tuple[spans.Span, ...] = ()) -> NoReturn:
    diagnostic = Diagnostic(code, message, f"{file}#{at}", (file, line, column), related=related)
    raise CompileError(str(diagnostic), [diagnostic])
