"""Lower native membership rules through the existing rule assembler."""

from __future__ import annotations

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
            variable, table = membership(where, at, line, column, declaration["when"], head, clause)
            terms = [("var", variable)]
            atom = (clause.relation, terms, line)
            body = [("lit", "positive", (table, terms, line))]
            statements.append(("rule", atom, body, line))
            columns.append(column)
    return rules_dl.NativeSource(module.pack, module.file.stem, where, text, tuple(statements), tuple(columns))


def membership(where: str, at: str, line: int, column: int, guard: dict,
               head: list[dict], clause: native_rule_signatures.LinkedClause) -> tuple[str, str]:
    if set(guard) == {"in"} and (table := clause.memberships.get(f"{at}/when")):
        subject = guard["in"][0]
        if subject.keys() == {"path"} and len(subject["path"]) == 1:
            variable = subject["path"][0]
            if head == [subject] and rules_dl.VARIABLE.fullmatch(variable):
                return variable, table
    refuse(where, at, line, column, "This rule needs a single head variable bound by a positive kind membership")


def refuse(file: str, at: str, line: int, column: int, message: str) -> NoReturn:
    diagnostic = Diagnostic("R049", message, f"{file}#{at}", (file, line, column))
    raise CompileError(str(diagnostic), [diagnostic])
