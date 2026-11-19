"""Physical relation names for the Feldera backend. Pack names and wire row contents stay logical."""

import re

from .sqltext import q

# Feldera rejects this predefined function name even as a quoted table or view.
# The leading underscores are outside the grammar of every pack and generated relation name.
PHYSICAL = {"interval": "__rezono_interval"}
LOGICAL = {physical: logical for logical, physical in PHYSICAL.items()}


def physical(name: str) -> str:
    """The name of the table or view at the Feldera API."""
    return PHYSICAL.get(name, name)


def quoted(name: str) -> str:
    return q(physical(name))


# The generator always quotes relations in declarations and sources. Consume complete literals,
# comments and other quoted identifiers first, so their contents cannot be mistaken for SQL.
_RELATIONS = re.compile(
    r"""'(?:''|[^'])*'|--[^\n]*|/\*[\s\S]*?\*/"""
    r'|"(?:""|[^"])*"'
    r'|(?P<prefix>\b(?:TABLE|VIEW|FROM|JOIN)\s+)"(?P<relation>(?:""|[^"])*)"',
    re.IGNORECASE,
)


def render(sql: str, names: dict[str, str] = PHYSICAL) -> str:
    """Lower the compiler's quoted relation references, leaving columns, tags and witnesses intact."""
    if not any(f'"{name}"' in sql for name in names):
        return sql

    def rename(match):
        name = match["relation"]
        if name in names:
            return f'{match["prefix"]}"{names[name]}"'
        return match[0]

    return _RELATIONS.sub(rename, sql)
