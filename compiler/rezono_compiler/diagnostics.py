"""The compiler's errors in the diagnostic contract (D15, contracts/diagnostic.yaml): a code, a severity, a
logical place, a span and a hint.

A span is MOD2's (spans.py): the file as a rule origin names it, and the line and column of a key, each from 1.
An error that its site raises as a sentence only (most of the compiler's, today) is one diagnostic per line with
the code `compile_error`; a site that knows more gives its own code, place, span and hint (view typing does).
Admission's refusals keep their codes (rezono_admission.Refusal.diagnostic, which needs no compiler)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from . import spans

COMPILE_ERROR = "compile_error"  # the code of an error whose site gives none of its own yet


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str = ""
    where: str = ""
    span: spans.Span | None = None
    hint: str = ""
    severity: str = "error"
    related: tuple[spans.Span, ...] = ()

    def doc(self) -> dict:
        """As the contract writes it: what is not known is left out, never null."""
        out: dict[str, object] = {"code": self.code, "severity": self.severity}
        if self.message.strip():
            out["message"] = self.message
        if self.where.strip():
            out["where"] = self.where
        if self.span is not None:
            out["span"] = spans.doc(self.span)
        if self.hint.strip():
            out["hint"] = self.hint
        if self.related:
            out["related"] = [spans.doc(place) for place in self.related]
        return out

    def __str__(self) -> str:
        return self.message


def of_text(text: str, code: str = COMPILE_ERROR) -> tuple[Diagnostic, ...]:
    """An error raised as a sentence: one diagnostic per line, with no place but what the sentence says."""
    return tuple(Diagnostic(code, line) for line in text.splitlines() if line.strip())


def listed(found: Iterable[Diagnostic]) -> dict:
    """A DiagnosticList, in the order found."""
    return {"diagnostics": [d.doc() for d in found]}


class Diagnosed(Exception):
    """An error with its diagnostics. Raised with a message only, it has one `compile_error` per line; its str is
    the message as before, so a reader of the sentence sees no change."""

    def __init__(self, message: str = "", diagnostics: Iterable[Diagnostic] = ()):
        super().__init__(message)
        self.diagnostics: tuple[Diagnostic, ...] = tuple(diagnostics) or of_text(message)
