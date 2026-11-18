"""The diagnostic boundary shared by the module-lowering components."""

from typing import Protocol


class Refuse(Protocol):
    """Report a refusal at a source pointer with its specification section."""

    def __call__(self, at: str, what: str, section: str = "§6", /) -> None: ...
