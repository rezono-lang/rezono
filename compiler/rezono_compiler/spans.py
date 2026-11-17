"""Where an element is written (MOD2): a span is the file, the line and the column of its key, each from 1.

A file is named as a rule's origin names it: relative to its pack, with `<pack>:` before the path of an
imported pack's file. The column counts characters, as the line does lines, so a span says the same on every
machine. Nothing here reads a clock or a directory: the same files give the same spans."""

from __future__ import annotations

from pathlib import Path

import yaml

Span = tuple[str, int, int]


def where(pack: str, root: str, rel: str) -> str:
    """The file of a span: `rel` in the pack being compiled, `<pack>:<rel>` in an imported pack."""
    return rel if pack == root else f"{pack}:{rel}"


def marks(path: Path) -> dict[tuple, tuple[int, int]]:
    """The (line, column) of every key and list item of a YAML file, by its path of keys and indexes. A scalar
    list item is found also by `("=", value)` in place of its index, as a class lists the slots it uses."""
    out: dict[tuple, tuple[int, int]] = {}

    def walk(node, at):
        if isinstance(node, yaml.MappingNode):
            for k, v in node.value:
                if isinstance(k, yaml.ScalarNode):
                    out.setdefault(at + (k.value,), (k.start_mark.line + 1, k.start_mark.column + 1))
                    walk(v, at + (k.value,))
        elif isinstance(node, yaml.SequenceNode):
            for i, v in enumerate(node.value):
                out[at + (i,)] = (v.start_mark.line + 1, v.start_mark.column + 1)
                if isinstance(v, yaml.ScalarNode):
                    out.setdefault(at + (("=", v.value),), out[at + (i,)])
                walk(v, at + (i,))

    walk(yaml.compose(path.read_text("utf-8"), Loader=yaml.SafeLoader), ())
    return out


def first(found: dict[tuple, tuple[int, int]], file: str, *paths: tuple) -> Span | None:
    """The span of the first path that is in `found`."""
    for p in paths:
        if p in found:
            return (file, *found[p])
    return None


def doc(span: Span) -> dict:
    """A span as the bundle writes it, numbers as decimal text."""
    return {"file": span[0], "line": str(span[1]), "column": str(span[2])}
