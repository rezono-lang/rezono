"""Registered refusals of the checker (decisions/checker-refusal-register.md).

A Refusal is a `str` whose text is the English sentence from `messages/en.json` with its named arguments
filled in, and which also carries `code` and `arguments` so a caller can inspect the code or render the
sentence in another language (`in_language("nl")`). `RefusalError` is a `ValueError` carrying a `Refusal`.
"""

from __future__ import annotations

from collections.abc import Mapping
import functools
from pathlib import Path
import re
import string
import types

from .canon import strict_json_loads

MESSAGES_DIR = Path(__file__).resolve().parent / "messages"
LANGUAGES = frozenset({"en", "nl"})
PLACEHOLDER_NAME = re.compile(r"^[a-z_]+$")
_FORMATTER = string.Formatter()


def _parse_template(language: str, code: str, template: str) -> frozenset[str]:
    """Validate a refusal message template and return its required placeholder names."""
    if not template.strip():
        raise RuntimeError(f"empty refusal template: {language}:{code}")
    names: set[str] = set()
    for _, field_name, format_spec, conversion in _FORMATTER.parse(template):
        if field_name is None:
            continue
        if not PLACEHOLDER_NAME.fullmatch(field_name) or format_spec or conversion is not None:
            raise RuntimeError(f"malformed refusal placeholder in {language}:{code}: {field_name!r}")
        names.add(field_name)
    return frozenset(names)


@functools.lru_cache(maxsize=None)
def _load_catalogue(language: str) -> tuple[Mapping[str, str], Mapping[str, frozenset[str]]]:
    path = MESSAGES_DIR / f"{language}.json"
    data = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise RuntimeError(f"malformed refusal catalogue: {language}")
    placeholders = {code: _parse_template(language, code, template) for code, template in data.items()}
    return types.MappingProxyType(dict(data)), types.MappingProxyType(placeholders)


def catalogue(language: str = "en") -> Mapping[str, str]:
    """Load the immutable refusal message catalogue for `language` (`en` or `nl`)."""
    if not isinstance(language, str) or language not in LANGUAGES:
        raise KeyError(f"unsupported refusal language: {language!r}")
    return _load_catalogue(language)[0]


def render(code: str, arguments: Mapping[str, object] | None = None, language: str = "en") -> str:
    """Render refusal `code` with exact named `arguments` in `language`."""
    if not isinstance(language, str) or language not in LANGUAGES:
        raise KeyError(f"unsupported refusal language: {language!r}")
    templates, placeholders = _load_catalogue(language)
    if not isinstance(code, str) or code not in templates:
        raise KeyError(f"unknown refusal code: {code!r}")
    provided = {} if arguments is None else dict(arguments)
    expected = placeholders[code]
    extra = set(provided) - expected
    if extra:
        raise TypeError(f"unexpected arguments for {code!r}: {sorted(extra)}")
    missing = expected - set(provided)
    if missing:
        raise KeyError(f"missing arguments for {code!r}: {sorted(missing)}")
    return templates[code].format(**provided)


class Refusal(str):
    """A refusal as its English sentence (`str`), carrying `code` and `arguments`."""

    code: str
    arguments: dict[str, object]

    def __new__(cls, code: str, **arguments: object) -> Refusal:
        text = render(code, arguments, "en")
        obj = super().__new__(cls, text)
        obj.code = code
        obj.arguments = dict(arguments)
        return obj

    def in_language(self, language: str) -> str:
        """Render this refusal in `language` (`en` or `nl`)."""
        return render(self.code, self.arguments, language)


class RefusalError(ValueError):
    """A `ValueError` carrying a `Refusal`."""

    def __init__(self, refusal: Refusal) -> None:
        if not isinstance(refusal, Refusal):
            raise TypeError("RefusalError requires a Refusal")
        super().__init__(str(refusal))
        self.refusal = refusal
