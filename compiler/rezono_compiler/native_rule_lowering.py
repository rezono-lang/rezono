"""Lower native membership rules through the existing rule assembler."""

from __future__ import annotations

from dataclasses import dataclass
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
        guard = declaration["when"]
        members = guard["and"] if set(guard) == {"and"} and guard["and"] else [guard]
        first = f"{at}/when/and/0" if members[0] is not guard else f"{at}/when"
        variable, table = membership(where, at, line, column, members[0], head, clause, first)
        terms = [("var", variable)]
        atom = (clause.relation, terms, line)
        body = [("lit", "positive", (table, terms, line))]
        for index, node in enumerate(members[1:], 1):
            pointer = f"{at}/when/and/{index}"
            body.append(premise(site, linked, clause, pointer, node, variable))
        statements.append(("rule", atom, body, line))
        columns.append(column)


def membership(where: str, at: str, line: int, column: int, guard: dict,
               head: list[dict], clause: native_rule_signatures.LinkedClause, pointer: str) -> tuple[str, str]:
    if set(guard) == {"in"} and (table := clause.memberships.get(pointer)):
        subject = guard["in"][0]
        if subject.keys() == {"path"} and len(subject["path"]) == 1:
            variable = subject["path"][0]
            if head == [subject] and rules_dl.VARIABLE.fullmatch(variable):
                return variable, table
    refuse(where, at, line, column, "This rule needs a single head variable bound by a positive kind membership")


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
