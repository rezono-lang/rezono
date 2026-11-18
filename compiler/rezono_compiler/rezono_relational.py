"""Pass authored relational blocks to the ordinary rule parser with their original coordinates."""

from __future__ import annotations

import json
import re

from . import rezono_module, rules_dl


HEADER = re.compile(r"[ \t]*rules[ \t]+([a-z][a-z0-9_]*)[ \t]*(?:--.*)?")
PIPE = re.compile(r"[ \t]+\| ")


def valid_block(decl: dict) -> bool:
    return (set(decl) == {"rules", "lines"} and isinstance(decl["rules"], str)
            and re.fullmatch(r"[a-z][a-z0-9_]*", decl["rules"]) is not None
            and isinstance(decl["lines"], list) and bool(decl["lines"])
            and all(isinstance(line, str) and "\n" not in line and "\r" not in line for line in decl["lines"]))


def aligned_text(text: str, blocks: dict[int, dict], pack: str, where: str) -> str:
    """Keep only the rule text, replacing each pipe prefix with the same number of spaces."""
    lines = text.split("\n")
    header_lines = [content.split() for line in lines if (content := line.partition("--")[0].strip())]
    expected = [["rezono", "0"], ["pack", pack]]
    if header_lines[:2] != expected:
        raise rules_dl.RuleError(f"{where}: the authored module header does not match its form")
    output = [""] * len(lines)
    found = set()
    for i, line in enumerate(lines):
        header = HEADER.fullmatch(line)
        if header is None:
            continue
        decl = blocks.get(i + 1)
        if decl is None or decl["rules"] != header[1]:
            raise rules_dl.RuleError(f"{where}:{i + 1}: rules block does not match the module form")
        found.add(i + 1)
        actual = []
        for j in range(i + 1, len(lines)):
            prefix = PIPE.match(lines[j])
            if prefix is None:
                break
            content = lines[j][prefix.end():]
            actual.append(content)
            output[j] = " " * prefix.end() + content
        if actual != decl["lines"]:
            raise rules_dl.RuleError(f"{where}:{i + 1}: rules lines do not match the module form")
    if missing := blocks.keys() - found:
        raise rules_dl.RuleError(f"{where}:{min(missing)}: rules block from the module form is absent")
    return "\n".join(output)


def sources(modules) -> tuple[rules_dl.Embedded, ...]:
    """Read the declared rule blocks of the root pack and its pinned imports."""
    result = []
    for module in modules:
        if module.form is None:
            continue
        form = json.loads(module.form.read_bytes())  # validated by the module loader
        if form["format"] != rezono_module.RULES_FORMAT:
            continue
        places = rezono_module.lines(form)
        blocks = {}
        for i, decl in enumerate(form["module"]["decls"]):
            if "rules" not in decl:
                continue
            line = places.get(f"/decls/{i}", 1)
            if line in blocks:
                raise rules_dl.RuleError(f"{module.rel}:{line}: rules blocks cannot share a source position")
            blocks[line] = decl
        if not blocks:
            continue
        stem = module.rel.removeprefix("rezono/").removesuffix(".rezono").replace("/", "_")
        try:
            text = module.file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise rules_dl.RuleError(f"{module.rel}: cannot read the authored module as UTF-8") from error
        text = aligned_text(text, blocks, form["module"]["pack"], module.rel)
        result.append(rules_dl.Embedded(module.pack, stem, module.rel, text))
    return tuple(result)
