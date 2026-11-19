"""Lower native membership rules through the existing rule assembler."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import NoReturn

from . import modules, native_rule_signatures, rezono_module, rules_dl, spans
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
    statements, columns = [], []
    site = Site(where, text, offsets)
    for at, declaration in declarations:
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
            guard = declaration["when"]
            members = guard["and"] if set(guard) == {"and"} and guard["and"] else [guard]
            first = f"{at}/when/and/0" if members[0] is not guard else f"{at}/when"
            if members[0] is guard and first not in clause.memberships:
                atom, body = grounded(site, at, declaration, head, clause, first, guard, line)
                statements.append(("rule", atom, body, line))
                columns.append(column)
                continue
            variable, table = membership(where, at, line, column, members[0], head, clause, first)
            terms = [("var", variable)]
            atom = (clause.relation, terms, line)
            body = [("lit", "positive", (table, terms, line))]
            for index, node in enumerate(members[1:], 1):
                pointer = f"{at}/when/and/{index}"
                body.append(premise(site, linked, clause, pointer, node, variable))
            statements.append(("rule", atom, body, line))
            columns.append(column)
    return rules_dl.NativeSource(module.pack, module.file.stem, where, text, tuple(statements), tuple(columns))


def membership(where: str, at: str, line: int, column: int, guard: dict,
               head: list[dict], clause: native_rule_signatures.LinkedClause, pointer: str) -> tuple[str, str]:
    if set(guard) == {"in"} and (table := clause.memberships.get(pointer)):
        subject = guard["in"][0]
        if subject.keys() == {"path"} and len(subject["path"]) == 1:
            variable = subject["path"][0]
            if head == [subject] and rules_dl.VARIABLE.fullmatch(variable):
                return variable, table
    refuse(where, at, line, column, "This rule needs a single head variable bound by a positive kind membership")


def grounded(site: Site, at: str, declaration: dict, head: list[dict],
             clause: native_rule_signatures.LinkedClause, pointer: str, guard: dict, line: int) -> tuple[tuple, list]:
    """Lower a guard of one positive path or slot-call premise to the forward row that binds it.

    `x.rank = 0` reads the slot row `rank(?x, 0)`, `y in x.next` and `Stage.next(x, y)` read `next(?x, ?y)`.
    No kind membership or identifier premise is added: the typed head only declares a type
    (decisions/language-expression-semantics.md section 1). A head column that the row does not bind is R042.
    """
    table, terms = slot_row(clause, pointer, guard)
    if table is None:
        refuse(site.file, pointer, *site.span(pointer)[1:],
               "This rule needs a positive kind membership, slot row or relation call that binds its head")
    bound = {term[1] for term in terms if term[0] == "var"}
    names = "columns" if "args" not in declaration else "args"
    head_terms = []
    for index, argument in enumerate(head):
        place = f"{at}/{names}/{index}"
        name = argument["path"][0] if argument.keys() == {"path"} and len(argument["path"]) == 1 else None
        if name is None or not rules_dl.VARIABLE.fullmatch(name):
            refuse(site.file, place, *site.span(place)[1:], "A native rule head takes a variable in each column")
        if name not in bound:
            refuse(site.file, place, *site.span(place)[1:],
                   f"The head column {name!r} is declared with a type but no positive premise binds it", "R042")
        head_terms.append(("var", name))
    return (clause.relation, head_terms, line), [("lit", "positive", (table, terms, line))]


def slot_row(clause: native_rule_signatures.LinkedClause, pointer: str, guard: dict) -> tuple[str | None, list]:
    """The forward slot or relation row of a single positive premise, or no table when it has none."""
    if set(guard) == {"cmp"} and guard["cmp"][0] == "=":
        _, left, right = guard["cmp"]
        for side, path, other in ((1, left, right), (2, right, left)):
            table, _ = clause.paths.get(f"{pointer}/cmp/{side}", (None, None))
            if table is not None and len(path.get("path", ())) == 2 and (value := operand(other)) is not None:
                return table, [("var", path["path"][0]), value]
    elif set(guard) == {"in"}:
        subject, domain = guard["in"]
        table, _ = clause.paths.get(f"{pointer}/in/1", (None, None))
        if table is not None and len(domain.get("path", ())) == 2 and (value := operand(subject)) is not None:
            return table, [("var", domain["path"][0]), value]
    elif set(guard) == {"call"} and (table := clause.calls.get(pointer)) is not None:
        values = [operand(argument) for argument in guard["call"][1]]
        if all(value is not None and value[0] == "var" for value in values):
            return table, values
    return None, []


def operand(node: dict) -> tuple | None:
    """A variable or an integer literal as a rule term; anything else has no direct row term."""
    if node.keys() == {"path"} and len(node["path"]) == 1 and rules_dl.VARIABLE.fullmatch(node["path"][0]):
        return "var", node["path"][0]
    if node.keys() == {"lit"} and re.fullmatch(r"-?[0-9]+", node["lit"]):
        return "const", str(int(node["lit"])), "integer"
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
            pointer: str, node: dict, bound: str) -> tuple:
    """Lower one call or negated call of a guard, after proving that the link supplies the evidence it needs."""
    negative = set(node) == {"not"} and set(node["not"]) == {"call"}
    call = node["not"] if negative else node
    relation = clause.calls.get(f"{pointer}/not" if negative else pointer)
    line, column = site.span(pointer)[1:]

    def fail(message: str, code: str = "R049", related: tuple[spans.Span, ...] = ()) -> NoReturn:
        refuse(site.file, pointer, line, column, message, code, related)

    if set(call) != {"call"} or relation is None:
        fail("A rule guard needs a positive kind membership followed by relation calls")
    arguments = call["call"][1]
    if any(argument.keys() != {"path"} or argument["path"] != [bound] for argument in arguments):
        fail("A relation call in a native rule takes the head variable in each column")
    terms = [("var", bound)] * len(arguments)
    if negative:
        predicate = getattr(linked.signatures[relation], "predicate", None)
        if not predicate or predicate.get("relation") != relation or predicate.get("owner") != linked.signatures[
                relation].owner:
            fail(f"The predicate states of {relation!r} are not linked, so its negation is not proved two-valued",
                 "R047")
        if predicate.get("world") != "closed":
            fail(f"{relation!r} is read in an open world, so its negation needs an explicit absence", "R004")
        if predicate.get("states") != ["known"]:
            causes = tuple((place["file"], int(place["line"]), int(place["column"]))
                           for place in predicate.get("related", ()))
            fail(f"{relation!r} can be undecided, so its negation needs a checked outcome", "R047", causes)
    return "lit", "negative" if negative else "positive", (relation, terms, line)


def refuse(file: str, at: str, line: int, column: int, message: str, code: str = "R049",
           related: tuple[spans.Span, ...] = ()) -> NoReturn:
    diagnostic = Diagnostic(code, message, f"{file}#{at}", (file, line, column), related=related)
    raise CompileError(str(diagnostic), [diagnostic])
