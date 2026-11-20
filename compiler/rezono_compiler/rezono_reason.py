"""Lower reason declarations to MessageFormat 2 sentences in the pack's default language (decisions/language-reasons.md)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Set
from pathlib import Path

from .rezono_lowering import Refuse


CODE = re.compile(r"[a-z][a-z0-9_]*")
TEXT = re.compile(r'"(?:\\[^\n\r]|[^"\\\n\r])*"')
ENTRY = re.compile(r"^([a-z][a-z0-9_.]*)\s*=\s*", re.M)
PLACEHOLDER = re.compile(r"(\{\$[A-Za-z_][A-Za-z0-9_]*\})")


def unquote(raw: str) -> str:
    """Decode a Rezono text literal to its label string."""
    return re.sub(r"\\(.)", r"\1", raw[1:-1], flags=re.DOTALL)


def escape_pattern(text: str, *, keep_placeholders: bool = False) -> str:
    """Escape `\\`, `{` and `}` in `text` for MessageFormat 2, optionally keeping `{$name}` placeholders."""
    if not keep_placeholders:
        return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
    parts = PLACEHOLDER.split(text)
    return "".join(
        part if index % 2 == 1 else part.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
        for index, part in enumerate(parts)
    )


def message_entry(key: str, text: str, *, keep_placeholders: bool = False) -> str:
    """Format one MessageFormat 2 resource line `<key> = {{TEXT}}`."""
    escaped = escape_pattern(text, keep_placeholders=keep_placeholders)
    return f"{key} = {{{{{escaped}}}}}\n"


def mf2_entry(code: str, label: str) -> str:
    """Format a reason sentence as one MessageFormat 2 resource line."""
    return message_entry(f"reason.{code}", label)


def append_messages(body: str, items: Iterable[tuple[str, str]], *, keep_placeholders: bool = False) -> str:
    """Append `<key> = {{TEXT}}` lines to a MessageFormat 2 resource body."""
    added = "".join(message_entry(key, text, keep_placeholders=keep_placeholders) for key, text in items)
    if not added:
        return body
    return (body + "\n" if body and not body.endswith("\n") else body) + added


def append_entries(body: str, items: Iterable[tuple[str, str]]) -> str:
    """Append lowered reason sentences to a MessageFormat 2 resource body."""
    return append_messages(body, ((f"reason.{code}", label) for code, label in items))


def defined_in_catalog(pack_dir: Path, default_language: object) -> set[str]:
    """Message ids already defined in `messages/<default_language>.mf2`."""
    if not isinstance(default_language, str) or not default_language:
        return set()
    path = pack_dir / "messages" / f"{default_language}.mf2"
    if not path.is_file():
        return set()
    try:
        _, sep, body = path.read_text("utf-8").replace("\r\n", "\n").partition("\n---\n")
    except (OSError, UnicodeDecodeError):
        return set()
    return set(ENTRY.findall(body)) if sep else set()


def codes(form: dict) -> set[str]:
    """Reason codes declared in one module form."""
    out: set[str] = set()
    for decl in form["module"]["decls"]:
        if isinstance(decl, dict) and isinstance(code := decl.get("reason"), str) and CODE.fullmatch(code):
            out.add(code)
    return out


def lower(
    decl: dict,
    at: str,
    refuse: Refuse,
    *,
    seen: Set[str] = frozenset(),
    elsewhere: Iterable[str] = (),
    defined: Set[str] = frozenset(),
    default_language: str = "",
) -> tuple[str, str] | None:
    """Validate and lower one `ReasonDecl` to `(code, label)` or report a refusal."""
    code, raw = decl.get("reason"), decl.get("text")
    if (
        decl.keys() != {"reason", "text"}
        or not isinstance(code, str)
        or CODE.fullmatch(code) is None
        or not isinstance(raw, str)
        or TEXT.fullmatch(raw) is None
    ):
        refuse(at, "a reason needs a code and a text label", "§6")
        return None
    if code in seen:
        refuse(at, f"reason {code} is declared twice in this module", "§3")
        return None
    others = list(elsewhere)
    if others:
        refuse(at, f"reason {code} is also declared by module {others[0]}; a reason of the pack is declared once", "§3")
        return None
    if f"reason.{code}" in defined:
        refuse(at, f"reason {code} is also given in messages/{default_language}.mf2; a reason sentence has one source", "§3")
        return None
    return code, unquote(raw)
