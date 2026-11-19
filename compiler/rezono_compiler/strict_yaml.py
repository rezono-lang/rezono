"""YAML as the compiler reads a pack: safe, and a duplicate key is an error.

`yaml.safe_load` keeps the last of two equal keys and drops the first without a word, so a fact file that names
the same kind twice would lose a whole block. Every pack file the compiler reads goes through `load` or `read`
here instead; `compiler/tests/test_strict_yaml.py` holds the few `yaml` reads that are no pack file.
"""

from __future__ import annotations

from pathlib import Path

import yaml

MERGE = "tag:yaml.org,2002:merge"


class DuplicateKeyError(yaml.constructor.ConstructorError):
    """A mapping in a YAML document names the same key twice."""

    def __init__(self, key, mark, source: str | None = None):
        super().__init__(None, None, f"duplicate key {key!r}", mark)
        self.key, self.line, self.source = key, mark.line + 1, source

    def __str__(self) -> str:
        where = self.source if self.source is not None else getattr(self.problem_mark, "name", "<yaml>")
        return f"{where}: duplicate key {self.key!r} on line {self.line}"


class Loader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    """Safe YAML (with libyaml when it is there), refusing a key that a mapping already has."""

    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            seen = set()
            for key_node, _ in node.value:
                if key_node.tag == MERGE:
                    continue
                key = self.construct_object(key_node, deep=True)
                try:
                    duplicate = key in seen
                except TypeError:  # an unhashable key; the safe constructor refuses it itself
                    continue
                if duplicate:
                    raise DuplicateKeyError(key, key_node.start_mark)
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load(text: str, source: str | Path | None = None):
    """The document in `text`; `source` names it in the error for a duplicate key."""
    try:
        return yaml.load(text, Loader=Loader)
    except DuplicateKeyError as error:
        if source is not None:
            error.source = str(source)
        raise


def read(path: str | Path):
    """The document in the UTF-8 file at `path`."""
    return load(Path(path).read_text(encoding="utf-8"), path)
