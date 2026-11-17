"""Closed structural views.yaml reader, and the bounded profile that executes (RV-C27).

This is a definition boundary, not a query evaluator, wire-ID constructor or
schema/type checker. Keep migrations' multiplicities and ordinary proofs intact.
A view inside the profile is lowered to ordinary rules by view_rules.bind; anything
else is refused before a rule is made.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .names import NAME

FORMAT = "rezono.views/1"
THEORY = re.compile(r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$")
# How an attribute map reads its source value: a name from this closed list, never an expression.
# days: a date to the whole number of days since EPOCH in the proleptic Gregorian calendar (what Arrow's
# date32 holds). yyyymmdd: a whole number written YYYYMMDD to that same count.
READINGS = ("identity", "days", "yyyymmdd")
EPOCH = "1970-01-01"


class ViewError(ValueError):
    """A view definition with a file and structural key in its error."""


@dataclass(frozen=True)
class ViewKindBranch:
    populated_from: str


@dataclass(frozen=True)
class ViewKindMap:
    name: str
    union: tuple[ViewKindBranch, ...]
    # Where the entry starts in views.yaml, counted from 1 (0: not read from a file). It names the origin of the
    # rules the entry is lowered to (view_rules) and is no part of the definition, so it is not compared.
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class ViewStep:
    """An unqualified source Slot.name, never its engine Slot.table or element id."""

    slot: str
    inverse: bool = False


@dataclass(frozen=True)
class ViewPath:
    populated_from: str
    steps: tuple[ViewStep, ...]


@dataclass(frozen=True)
class ViewArrowMap:
    """A theory slot component with alternative paths; kind tokens are resolved separately."""

    name: str
    paths: tuple[ViewPath, ...]
    assume_functional: bool = False
    # The theory kind that declares the arrow; needed only when two kinds of the theory share the slot name.
    of: str | None = None
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class ViewAttributeMap:
    """One attribute of a theory kind, read from one attribute of the kind mapped onto it (no path)."""

    of: str
    name: str
    populated_from: str
    reading: str = "identity"
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class ViewSpec:
    theory: str
    kinds: tuple[ViewKindMap, ...]
    arrows: tuple[ViewArrowMap, ...] = ()
    attributes: tuple[ViewAttributeMap, ...] = ()
    line: int = field(default=0, compare=False)  # of the `theory` key


@dataclass(frozen=True)
class ViewFile:
    views: tuple[ViewSpec, ...]
    format: str = FORMAT


class UniqueLoader(yaml.SafeLoader):
    """Safe YAML, rejecting duplicate fields rather than silently taking one."""


class _Lined(dict):
    """A mapping as read, with the line it starts on and the line of each of its keys, counted from 1."""

    line: int
    lines: dict[str, int]


def _mapping(loader, node, deep=False):
    result = _Lined()
    result.line, result.lines = node.start_mark.line + 1, {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(None, None, "field names must be strings", key_node.start_mark)
        if key in result:
            raise yaml.constructor.ConstructorError(None, None, f"duplicate field {key!r}", key_node.start_mark)
        result.lines[key] = key_node.start_mark.line + 1
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read(path: str | Path) -> ViewFile:
    """Read only the closed structural profile; no source pack/code is executed."""
    path = Path(path)

    def fail(key, message):
        raise ViewError(f"{path}: {key}: {message}")

    def obj(value, key, required, optional=()):
        if not isinstance(value, dict):
            fail(key, "expected an object")
        if not all(isinstance(k, str) for k in value):
            fail(key, "field names must be strings")
        extra = sorted(set(value) - set(required) - set(optional))
        missing = sorted(set(required) - set(value))
        if extra:
            fail(key, f"unknown field {extra[0]!r}")
        if missing:
            fail(key, f"missing field {missing[0]!r}")
        return value

    def items(value, key, *, empty=False):
        if not isinstance(value, list) or (not empty and not value):
            fail(key, "expected a non-empty list" if not empty else "expected a list")
        return list(enumerate(value))

    def name(value, key, pattern=NAME):
        if not isinstance(value, str) or not pattern.fullmatch(value):
            fail(key, "expected a valid name")
        return value

    def boolean(value, key):
        if type(value) is not bool:
            fail(key, "expected a boolean")
        return value

    def unique(values, key):
        if len(values) != len(set(values)):
            fail(key, "duplicate declaration")

    if path.is_symlink() or not path.is_file():
        fail("$", "expected a regular views file, not a symbolic link")
    try:
        doc = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        fail("$", f"cannot read view definitions ({error})")
    obj(doc, "$", ("format", "views"))
    if doc["format"] != FORMAT:
        fail("format", f"expected {FORMAT!r}")
    specs = []
    for i, given in items(doc["views"], "views"):
        key = f"views[{i}]"
        obj(given, key, ("theory", "kinds"), ("arrows", "attributes"))
        theory = name(given["theory"], key + ".theory", THEORY)
        kinds, arrows, attributes = [], [], []
        for j, raw in items(given["kinds"], key + ".kinds"):
            where = f"{key}.kinds[{j}]"
            obj(raw, where, ("name", "union"))
            target = name(raw["name"], where + ".name")
            branches = []
            for b, branch in items(raw["union"], where + ".union"):
                at = f"{where}.union[{b}]"
                obj(branch, at, ("populated_from",))
                branches.append(ViewKindBranch(name(branch["populated_from"], at + ".populated_from")))
            unique(branches, where + ".union")
            kinds.append(ViewKindMap(target, tuple(sorted(branches, key=lambda b: b.populated_from)), raw.line))
        unique([k.name for k in kinds], key + ".kinds")
        for j, raw in items(given.get("arrows", []), key + ".arrows", empty=True):
            where = f"{key}.arrows[{j}]"
            obj(raw, where, ("name", "paths"), ("assume_functional", "of"))
            target = name(raw["name"], where + ".name")
            paths = []
            for n, raw_path in items(raw["paths"], where + ".paths"):
                at = f"{where}.paths[{n}]"
                obj(raw_path, at, ("populated_from", "steps"))
                start = name(raw_path["populated_from"], at + ".populated_from")
                steps = []
                for p, step in items(raw_path["steps"], at + ".steps"):
                    step_key = f"{at}.steps[{p}]"
                    obj(step, step_key, ("slot",), ("inverse",))
                    steps.append(ViewStep(name(step["slot"], step_key + ".slot"),
                                          boolean(step.get("inverse", False), step_key + ".inverse")))
                paths.append(ViewPath(start, tuple(steps)))
            unique(paths, where + ".paths")
            paths.sort(key=lambda p: (p.populated_from, tuple((s.slot, s.inverse) for s in p.steps)))
            arrows.append(ViewArrowMap(target, tuple(paths),
                                       boolean(raw.get("assume_functional", False), where + ".assume_functional"),
                                       name(raw["of"], where + ".of") if "of" in raw else None, raw.line))
        unique([(a.of, a.name) for a in arrows], key + ".arrows")
        if {a.name for a in arrows if a.of is None} & {a.name for a in arrows if a.of is not None}:
            fail(key + ".arrows", "an arrow name is given both with and without 'of'")
        for j, raw in items(given.get("attributes", []), key + ".attributes", empty=True):
            where = f"{key}.attributes[{j}]"
            obj(raw, where, ("of", "name", "populated_from"), ("reading",))
            reading = raw.get("reading", "identity")
            if reading not in READINGS:
                fail(where + ".reading", f"expected one of {', '.join(READINGS)}")
            attributes.append(ViewAttributeMap(name(raw["of"], where + ".of"), name(raw["name"], where + ".name"),
                                               name(raw["populated_from"], where + ".populated_from"), reading,
                                               raw.line))
        unique([(a.of, a.name) for a in attributes], key + ".attributes")
        specs.append(ViewSpec(theory, tuple(sorted(kinds, key=lambda k: k.name)),
                              tuple(sorted(arrows, key=lambda a: (a.name, a.of or ""))),
                              tuple(sorted(attributes, key=lambda a: (a.of, a.name))), given.lines["theory"]))
    unique([s.theory for s in specs], "views")
    return ViewFile(tuple(sorted(specs, key=lambda s: s.theory)))


def document(value: ViewFile) -> dict:
    """Checked structural data in its deterministic order, with explicit defaults."""
    from dataclasses import asdict
    # Round-trip through safe plain data rather than leaking dataclass tuples to YAML.
    def plain(v):
        if isinstance(v, dict):  # what the file leaves out stays left out: an arrow's kind, no attribute maps;
            return {k: plain(x) for k, x in v.items()  # and a line is where a map stood, not what it says
                    if not (k == "of" and x is None) and not (k == "attributes" and not x) and k != "line"}
        if isinstance(v, (tuple, list)):
            return [plain(x) for x in v]
        return v
    return plain(asdict(value))


def refuse(pack_dir: str | Path) -> None:
    """A pack that may carry no view: an imported pack (a view of a view is outside the profile)."""
    path = Path(pack_dir) / "views.yaml"
    if path.exists() or path.is_symlink():
        read(path)  # Shape errors retain their file/key before the execution boundary.
        raise ViewError(f"{path}: view execution is not supported here; only the pack that is compiled has a "
                        "views.yaml, and an imported pack has none")


def admit(pack_dir: str | Path) -> ViewFile | None:
    """The views of the pack that is compiled, when they lie inside the profile that executes (RV-C27): one
    view per theory (the reader's rule), every kind map with one branch, every arrow map with one path and no
    assumption. What needs the schemas (types, readings, names) is checked by view_typing.resolve and
    view_rules.bind. None without a views.yaml; outside the profile a ViewError, before a schema is read."""
    path = Path(pack_dir) / "views.yaml"
    if not (path.exists() or path.is_symlink()):
        return None
    value = read(path)
    for spec in value.views:
        key = f"views[{spec.theory}]"
        for kind in spec.kinds:
            if len(kind.union) != 1:
                raise ViewError(f"{path}: {key}.kinds[{kind.name}]: view execution is not supported for a union "
                                "of source kinds; one source kind per theory kind")
        for arrow in spec.arrows:
            if len(arrow.paths) != 1 or arrow.assume_functional:
                raise ViewError(f"{path}: {key}.arrows[{arrow.name}]: view execution is not supported for "
                                "alternative paths or assume_functional; one path per arrow")
    return value
