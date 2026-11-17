# --- The model of a pack: its modules, engine names and fact states ------------------------------------------

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import modules, scenarios, source_format
from .. import pack as packs

from .spec import FACT_DIRS, REF, OperationError


@dataclass
class Model:
    dir: Path
    pack: packs.Pack
    meta: dict
    mods: dict[str, modules.Module]
    names: modules.Names
    classes: dict[tuple[str, str], str]  # (module id, class name) -> engine kind
    enums: dict[tuple[str, str], str]  # (module id, enum name) -> engine enum
    local: list[str] = field(default_factory=list)  # module ids of this pack, sorted

    def kind_of(self, engine: str) -> tuple[str, str]:
        return next(key for key, k in self.classes.items() if k == engine)


def model(pack_dir: Path, pack: packs.Pack | None = None) -> Model:
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_text("utf-8"))
    errors: list[str] = []
    mods, _ = modules.load(pack_dir, meta, errors)
    names = modules.Names(mods, packs.snake, errors)
    if errors:
        raise OperationError("\n".join(errors))
    classes = {(m.id, c): names.name(m.id, c) for m in mods for c in m.sv.all_classes(imports=False)}
    enums = {(m.id, e): names.name(m.id, e) for m in mods for e in m.sv.all_enums(imports=False)}
    return Model(pack_dir, pack if pack is not None else packs.read(pack_dir), meta, {m.id: m for m in mods},
                 names, classes, enums, sorted(m.id for m in mods if m.pack == meta["name"]))


def engine_names(pack_dir: Path) -> tuple[dict, dict]:
    """The engine names of classes and enums from the schema files alone (before the rest is consistent)."""
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_text("utf-8"))
    errors: list[str] = []
    mods, _ = modules.load(pack_dir, meta, errors)
    names = modules.Names(mods, packs.snake, errors)
    if errors:
        raise OperationError("\n".join(errors))
    return ({(m.id, c): names.name(m.id, c) for m in mods for c in m.sv.all_classes(imports=False)},
            {(m.id, e): names.name(m.id, e) for m in mods for e in m.sv.all_enums(imports=False)})


def fact_files(m: Model) -> list[tuple[str, Path]]:
    """The fact files of every state directory, through the source-format boundary (B13)."""
    return source_format.YAML_DATALOG.fact_files(m.dir, FACT_DIRS)


def rule_files(m: Model) -> list[tuple[str, Path]]:
    """The rule files, through the source-format boundary (B13)."""
    return source_format.YAML_DATALOG.rule_files(m.dir)


def rule_tokens(text: str, where: str) -> list:
    """The tokens of a rule file, through the source-format boundary (B13)."""
    return source_format.YAML_DATALOG.rule_tokens(text, where)


def states(m: Model) -> list[tuple[str, str, str | None, dict[str, list[tuple]]]]:
    """Every fact state of the pack, diagnostics included (scenarios.fact_states)."""
    return scenarios.fact_states(m.pack, m.dir)


def resolve(m: Model, ref: str, table: dict, what: str) -> tuple[str, str, str]:
    """(module, LinkML name, engine name) of a class or enum of this pack, named `Name` or `module#Name`."""
    r = REF.match(str(ref))
    if not r:
        raise OperationError(f"'{ref}' is not a {what} name (Name or module#Name)")
    hits = sorted(k for k in table if k[1] == r["name"] and (r["module"] is None or k[0] == r["module"]))
    if not hits:
        raise OperationError(f"no {what} '{ref}' in this pack")
    if len(hits) > 1:
        raise OperationError(f"{what} '{ref}' is declared in modules {', '.join(h[0] for h in hits)}; "
                             f"write <module>#{r['name']}")
    if hits[0][0] not in m.local:
        raise OperationError(f"{what} '{ref}' belongs to an imported pack; change it there")
    return hits[0][0], hits[0][1], table[hits[0]]
