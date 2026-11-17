"""Resolve the closed view profile against normally admitted Pack/schema objects.

The caller supplies theory models from its already verified import closure. This
module is not another loader/parser or pin attestation. It records static spans,
positive membership requirements, pending obligations and each union's typed
identity (`identity`: root kind plus id, B11); it performs no lowering, instance
evaluation, publication or O8/M3 conformance check. The existing views-file
execution refusals remain in force.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, NoReturn

from . import identity, spans
from .diagnostics import Diagnosed, Diagnostic
from .pack import Pack, Slot
from .views import ViewError, ViewFile


class ViewTypingError(ViewError, Diagnosed):
    """A typed refusal at a logical definition key, with its diagnostic (D15): a code, the key as its place, and
    the span of the entry it is in when the views file is read from disk, never an invented line number."""
    def __init__(self, source: str, key: str, reason: str, *, code: str, hint: str = '',
                 span: spans.Span | None = None):
        self.source, self.key, self.reason, self.code = source, key, reason, code
        message = f"{source}: {key}: {reason}"
        Diagnosed.__init__(self, message, (Diagnostic(code, message, key, span, hint),))

    @property
    def diagnostic(self) -> Diagnostic:
        return self.diagnostics[0]


class PathTypingError(ValueError):
    """A directed path that does not type: the position of the step it fails at, a code, a reason and a hint.
    A caller places it in its own text (a view key, a Reckon span)."""
    def __init__(self, step: int, code: str, reason: str, hint: str = ''):
        self.step, self.code, self.reason, self.hint = step, code, reason, hint
        super().__init__(reason)


@dataclass(frozen=True)
class SourceKind:
    name: str
    root: str
    id_type: str


@dataclass(frozen=True)
class KindMap:
    name: str
    union: tuple[SourceKind, ...]
    # Elements are (root, id) pairs: equal ids of different roots stay distinct elements.
    identity: identity.Union
    line: int = field(default=0, compare=False)  # of the entry in views.yaml (views.ViewKindMap.line)


@dataclass(frozen=True)
class Membership:
    position: int
    kind: str


@dataclass(frozen=True)
class Step:
    owner: str
    slot: str
    relation: str
    inverse: bool
    near: str
    far: str
    many: bool


@dataclass(frozen=True)
class TypedPath:
    start: str
    end: str
    steps: tuple[Step, ...]
    memberships: tuple[Membership, ...]
    # Alternative end-theory membership proofs, never a conjunction of all branches.
    target_branches: tuple[str, ...]
    # The identity roots of the start and the end element: (root of start, root of end).
    roots: tuple[str, str]


@dataclass(frozen=True)
class Obligation:
    """Pending functionality compares distinct typed targets, never witness counts."""
    kind: Literal['functionality', 'totality', 'unmapped_kind', 'unmapped_arrow', 'axiom']
    symbol: str


@dataclass(frozen=True)
class ArrowMap:
    owner: str
    name: str
    target: str
    functional: bool
    paths: tuple[TypedPath, ...]
    line: int = field(default=0, compare=False)


@dataclass(frozen=True)
class AttributeMap:
    """One theory attribute read from one attribute of the source kind, by a named reading (views.READINGS)."""
    owner: str      # the theory kind
    name: str       # its slot
    source: str     # the source kind mapped onto the owner
    relation: str   # the table of the source slot
    reading: str
    line: int = field(default=0, compare=False)


# The source and target value types each reading takes: SQL types, as Slot.sql_type has them.
READING_TYPES = {"identity": (("VARCHAR", "VARCHAR"), ("BIGINT", "BIGINT")), "days": (("DATE", "BIGINT"),),
                 "yyyymmdd": (("BIGINT", "BIGINT"),)}


@dataclass(frozen=True)
class TypedView:
    theory: str
    # The caller's ordinary loader checked this declaration; this is not a new attestation.
    import_sha256: str
    kinds: tuple[KindMap, ...]
    arrows: tuple[ArrowMap, ...]
    obligations: tuple[Obligation, ...]
    attributes: tuple[AttributeMap, ...] = ()
    line: int = field(default=0, compare=False)  # of the view's `theory` key


@dataclass(frozen=True)
class TypedViews:
    views: tuple[TypedView, ...]


def _arrows(model: Pack) -> tuple[Slot, ...]:
    return tuple(sorted((s for k in model.kinds.values() for s in k.slots.values() if s.arrow), key=lambda s: s.table))


def _compatible(model: Pack, actual: str, required: str) -> bool:
    # Root identity equality is not a static downcast or sibling cast.
    return required in model.ancestors(actual)


def directed_path(model: Pack, start: str, steps: Iterable[tuple[str, bool]]
                  ) -> tuple[str, tuple[Step, ...], tuple[Membership, ...]]:
    """Type a directed path from kind `start` over `steps`, each an arrow slot by its name and whether it is
    walked backwards: its end kind, its typed steps and the kind each position must be a member of. This is the
    one path resolver (D15, #394 A6) for views and the Reckon resolver; what a view adds (its source unions,
    targets and obligations) stays in `resolve`. Narrowing is never implicit: a step leaves from the current
    kind or an ancestor of it, and an inverse step needs exactly one type-compatible incoming arrow."""
    incoming, current = _arrows(model), start
    typed, memberships = [], [Membership(0, start)]
    for i, (name, inverse) in enumerate(steps):
        if inverse:
            choices = [s for s in incoming if s.name == name and _compatible(model, current, s.range)]
            if len(choices) != 1:
                raise PathTypingError(i, 'inverse_not_unique' if choices else 'inverse_missing',
                                      'expected one type-compatible incoming arrow; inverse is missing or ambiguous',
                                      '' if choices else 'name an arrow that points to the current kind or an ancestor of it')
            slot = choices[0]
        else:
            slot = model.slot(current, name)
            if slot is None or not slot.arrow:
                raise PathTypingError(i, 'not_an_arrow', 'expected an arrow slot of the current kind or an ancestor',
                                      'a path walks arrows; an attribute ends it and is read by an attribute map')
        near, far = (slot.range, slot.kind) if inverse else (slot.kind, slot.range)
        if not _compatible(model, current, near):
            raise PathTypingError(i, 'path_incompatible', 'incompatible directed path; narrowing is not implicit')
        typed.append(Step(slot.kind, slot.name, slot.table, inverse, near, far, inverse or slot.multivalued))
        memberships.extend((Membership(i, near), Membership(i + 1, far)))
        current = far
    return current, tuple(typed), tuple(dict.fromkeys(memberships))


def _start(found: dict[tuple, tuple[int, int]], file: str, line: int) -> spans.Span | None:
    """The span of the entry that starts on `line`: its first key or list item (spans.marks). None for a line
    that is not known (0: the definition was not read from a file)."""
    columns = [c for (n, c) in found.values() if n == line]
    return (file, line, min(columns)) if line and columns else None


def resolve(value: ViewFile, domain: Pack, theories: Mapping[str, Pack], *, source: str | Path = 'views.yaml') -> TypedViews:
    """Type a mapping fragment; pending obligations explicitly prevent a conformance claim. A refusal is a
    ViewTypingError whose diagnostic has the span of the entry it is in when `source` is a file on disk: a
    views file lies at its pack's root (views.admit), so the span names it by its file name."""
    file = Path(source)
    source = str(source)
    found: dict | None = None

    def fail(key: str, reason: str, code: str, line: int = 0, hint: str = '') -> NoReturn:
        nonlocal found
        if found is None:
            found = spans.marks(file) if line and file.is_file() else {}
        raise ViewTypingError(source, key, reason, code=code, hint=hint, span=_start(found, file.name, line))

    result = []
    for spec in sorted(value.views, key=lambda v: v.theory):
        key = f"views[{spec.theory}]"
        theory = theories.get(spec.theory)
        pin = next((p for p in domain.imports if p['name'] == spec.theory), None)
        if theory is None or pin is None:
            fail(key + '.theory', 'expected a theory from the admitted pinned import closure', 'theory_not_imported',
                 spec.line, 'import the theory pack in pack.yaml with its pinned hash')
        if theory.meta.get('theory') is not True or theory.meta.get('name') != spec.theory or theory.meta.get('version') != pin['version']:
            fail(key + '.theory', 'the supplied model does not match the declared theory metadata', 'theory_mismatch',
                 spec.line)
        kinds = []
        for mapped in spec.kinds:
            where = key + f'.kinds[{mapped.name}]'
            if mapped.name not in theory.kinds:
                fail(where, 'unknown theory kind', 'unknown_theory_kind', mapped.line)
            branches = []
            for branch in mapped.union:
                name = branch.populated_from
                if name not in domain.kinds:
                    fail(where + f'.union[{name}]', 'unknown source kind', 'unknown_source_kind', mapped.line)
                branches.append(SourceKind(name, domain.root(name), domain.kinds[name].id_type))
            try:
                typed = identity.union(domain, [b.name for b in branches])
            except identity.IdentityError as error:
                fail(where + '.union', str(error), 'union_identity', mapped.line)
            expected = theory.kinds[theory.root(mapped.name)].id_type
            if typed.id_type != expected:
                fail(where + '.union', f'source identifier type {typed.id_type} is not the theory kind identifier type {expected}; '
                     'no conversion is selected', 'identifier_type', mapped.line)
            kinds.append(KindMap(mapped.name, tuple(sorted(branches, key=lambda b: b.name)), typed, mapped.line))
        by_kind = {k.name: tuple(b.name for b in k.union) for k in kinds}
        target_arrows = _arrows(theory)
        arrows, obligations, mapped_arrows = [], [], set()
        for mapped in spec.arrows:
            where = key + f'.arrows[{mapped.name}]'
            candidates = [s for s in target_arrows if s.name == mapped.name and mapped.of in (None, s.kind)]
            if len(candidates) != 1:
                fail(where, 'expected one unambiguous theory arrow slot component', 'theory_arrow_not_unique', mapped.line,
                     "name the theory kind that declares the arrow with 'of'")
            target = candidates[0]
            if target.kind not in by_kind or target.range not in by_kind:
                fail(where, 'the theory arrow needs mapped source and target kinds', 'arrow_kinds_unmapped', mapped.line,
                     'map both ends of the theory arrow in kinds')
            paths = []
            for n, path in enumerate(mapped.paths):
                at = where + f'.paths[{n}]'
                if path.populated_from not in by_kind[target.kind]:
                    fail(at + '.populated_from', 'path start is not a declared source-union branch', 'path_start_unmapped',
                         mapped.line, "start the path at a source kind of the union mapped onto the arrow's owner")
                try:
                    current, steps, memberships = directed_path(domain, path.populated_from,
                                                                ((s.slot, s.inverse) for s in path.steps))
                except PathTypingError as error:
                    fail(at + f'.steps[{error.step}]', error.reason, error.code, mapped.line, error.hint)
                branches = tuple(k for k in by_kind[target.range] if _compatible(domain, current, k))
                if not branches:
                    fail(at, 'path end does not reach a mapped target branch', 'path_end_unmapped', mapped.line,
                         "end the path at a source kind of the union mapped onto the arrow's target")
                paths.append(TypedPath(path.populated_from, current, steps, memberships, branches,
                                       (domain.root(path.populated_from), domain.root(current))))
            possible_many = len(paths) > 1 or any(s.many for p in paths for s in p.steps)
            if not target.multivalued and possible_many and not mapped.assume_functional:
                fail(where, 'not statically functional; an explicit assume_functional check is required', 'not_functional',
                     mapped.line, 'add assume_functional: true to the arrow map, which becomes a pending obligation')
            if mapped.assume_functional:
                obligations.append(Obligation('functionality', target.table))
            if target.required:
                obligations.append(Obligation('totality', target.table))
            arrows.append(ArrowMap(target.kind, target.name, target.range, not target.multivalued, tuple(paths),
                                   mapped.line))
            mapped_arrows.add(target.table)
        attributes = []
        for mapped in spec.attributes:
            where = key + f'.attributes[{mapped.of}.{mapped.name}]'
            if len(by_kind.get(mapped.of, ())) != 1:
                fail(where, 'an attribute map needs its theory kind mapped from one source kind', 'attribute_kind_not_single',
                     mapped.line)
            source = by_kind[mapped.of][0]
            target = theory.kinds[mapped.of].slots.get(mapped.name)
            if target is None or target.arrow or target.enum or target.multivalued:
                fail(where, 'expected a single-valued attribute the theory kind declares, not an arrow or an enum',
                     'attribute_target_invalid', mapped.line)
            slot = domain.slot(source, mapped.populated_from)
            if slot is None or slot.arrow or slot.enum or slot.multivalued:
                fail(where + '.populated_from', 'expected a single-valued attribute of the source kind or an '
                     'ancestor, not an arrow, an enum or a path', 'attribute_source_invalid', mapped.line)
            if (slot.sql_type, target.sql_type) not in READING_TYPES[mapped.reading]:
                fail(where + '.reading', f'{mapped.reading} does not read {slot.sql_type} as {target.sql_type}',
                     'reading_type', mapped.line, 'choose a reading whose source and target types fit (views.READINGS)')
            attributes.append(AttributeMap(mapped.of, mapped.name, source, slot.table, mapped.reading, mapped.line))
        obligations.extend(Obligation('unmapped_kind', k) for k in sorted(set(theory.kinds) - set(by_kind)))
        obligations.extend(Obligation('unmapped_arrow', s.table) for s in target_arrows if s.table not in mapped_arrows)
        for kind in theory.kinds.values():
            obligations.extend(Obligation('axiom', f'{kind.name}.{name}') for name, _, _ in kind.path_equations)
            obligations.extend(Obligation('axiom', f'{kind.name}.rule[{i}]') for i, _ in enumerate(kind.rules))
        result.append(TypedView(spec.theory, pin['sha256'], tuple(sorted(kinds, key=lambda k: k.name)),
                                tuple(sorted(arrows, key=lambda a: (a.owner, a.name))), tuple(sorted(obligations, key=lambda o: (o.kind, o.symbol))),
                                tuple(sorted(attributes, key=lambda a: (a.owner, a.name))), spec.line))
    return TypedViews(tuple(result))
