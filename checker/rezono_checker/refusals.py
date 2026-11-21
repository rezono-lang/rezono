"""Registered refusals of the checker (decisions/checker-refusal-register.md).

A Refusal is a `str` whose text is the English sentence from `messages/en.json` with its named arguments
filled in, and which also carries `code` and `arguments` so a caller can inspect the code or render the
sentence in another language (`in_language("nl")`). `RefusalError` is a `ValueError` carrying a `Refusal`.
"""

from __future__ import annotations

import functools
from pathlib import Path

from .canon import strict_json_loads

MESSAGES_DIR = Path(__file__).resolve().parent / "messages"


@functools.lru_cache(maxsize=None)
def catalogue(language: str = "en") -> dict[str, str]:
    """Load the refusal message catalogue for `language` (`en` or `nl`)."""
    path = MESSAGES_DIR / f"{language}.json"
    data = strict_json_loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise RuntimeError(f"malformed refusal catalogue: {language}")
    return data


def render(code: str, arguments: dict[str, object] | None = None, language: str = "en") -> str:
    """Render refusal `code` with `arguments` in `language`."""
    template = catalogue(language)[code]
    return template.format(**(arguments or {}))


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
