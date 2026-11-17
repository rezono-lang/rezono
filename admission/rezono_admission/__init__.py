"""Admission: the one step every fact passes, for the compiler's batch loading and for the live service (LS0).

It imports nothing of the compiler (a test asserts it): a fact never needs the compiler.
"""

from .rows import CODES, Refusal, rows
from .schema import Schema
from .step import Admission, Admitted

__all__ = ["CODES", "Admission", "Admitted", "Refusal", "Schema", "rows"]
