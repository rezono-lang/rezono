"""SQL text: the one place that quotes an identifier and escapes a text literal (RV-M01).

Every engine name and every string constant the compiler writes into SQL goes through here, for both
dialects (Feldera and DuckDB): the two quote the same way.
"""


def q(name: str) -> str:
    """A quoted identifier, so a name like `order` stays a name; a `"` in it is doubled."""
    return '"' + name.replace('"', '""') + '"'


def literal(v) -> str:
    """A text literal of the value's text; a `'` in it is doubled."""
    return "'" + str(v).replace("'", "''") + "'"
