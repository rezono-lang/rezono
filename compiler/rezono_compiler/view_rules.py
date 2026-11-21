"""A conservative view fragment -> ordinary RuleIR, with no runtime caller.

Inputs must be genuine normally admitted Pack models and a validated Program;
there is no serializable trust flag, loader, new parser or pin attestation here.
The retained model fields are checked independently of TypedView.obligations.
Normal reader refusals (including mixins) remain part of that existing boundary;
missing parsed fields are not a claim to understand arbitrary LinkML semantics.

Only single-branch/single-path, closed, unconstrained relation theories whose
mapped endpoints share one source root/type are admitted. Raw ID identity is
this subcase, not a general encoder. Intermediate link variables remain in the
ordinary witness. No theory-rule rebinding, caller/publication activation or
satisfaction/O8 claim is made. All unsupported profiles fail before emission.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from . import rules as ir
from . import rules_dl, view_typing, views
from .diagnostics import Diagnosed, Diagnostic
from .pack import ACCESS, Pack
from .view_typing import TypedView


class ViewRuleError(ValueError):
    """The requested fragment cannot be lowered without a wider reviewed boundary."""


class ProtectedRelation(ViewRuleError, Diagnosed):
    """A relation the view would make under the name of a protected admission input (rules_dl.PROTECTED). Only
    admission fills such a relation (decisions/admission-transport.md, section 6), so the name is reserved."""
    CODE = 'view_relation_protected'

    def __init__(self, source: str, theory: str, name: str):
        where = f'views[{theory}]'
        message = (f'{source}: {where}: the generated relation {name} has the name of a protected admission input; '
                   'that name is reserved')
        hint = 'rename the theory or its kind or slot, so the view makes another relation'
        Diagnosed.__init__(self, message, (Diagnostic(self.CODE, message, where, hint=hint),))


# The origin file of every rule `bind` lowers when pack.read binds a view; a rule file's origin is rules/<module>.dl
# (rules_dl.read), so no rule of a rule file carries it.
SOURCE = 'views.yaml'


def table_relation(module: str, table: str) -> str:
    """The relation `bind` makes in a view's module `view_<prefix>` to hold a theory table: the table under
    another name (fold.helpers judges it as the table)."""
    return f"{module.removeprefix('view_')}_{table.replace('__', '_')}"


@dataclass(frozen=True)
class RelationMap:
    kinds: Mapping[str, str]
    arrows: Mapping[str, str]  # declared theory Slot.table -> fresh derived relation


def _profile(theory: Pack) -> None:
    if (theory.meta.get('theory') is not True or theory.enums or theory.rules or theory.calc
            or theory.seals or theory.sweeps or theory.questions):
        raise ViewRuleError('unsupported theory profile: expected a fact-free plain relation theory')
    for kind in theory.kinds.values():
        if (kind.parent or kind.abstract or kind.world != 'closed' or not kind.identifier
                or kind.unique_keys or kind.path_equations or kind.rules or kind.id_patterns
                or kind.seal or kind.sealed_with):
            raise ViewRuleError(f'unsupported theory constraints/world: {kind.name}')
        for slot in kind.slots.values():
            if (not slot.arrow or slot.required or not slot.multivalued or slot.inlined or slot.enum
                    or slot.world != 'closed' or slot.minimum is not None or slot.maximum is not None
                    or slot.minimum_cardinality is not None or slot.maximum_cardinality is not None
                    or slot.patterns or slot.constant is not None or slot.explore or slot.names or slot.currency):
                raise ViewRuleError(f'unsupported theory scalar/arrow constraint: {slot.element}')


def _checked(view: TypedView, domain: Pack, theory: Pack) -> TypedView:
    _profile(theory)
    if view.obligations or domain.seals:
        raise ViewRuleError('unsupported pending obligations or sealed source profile')
    if any(len(a.paths) != 1 for a in view.arrows):
        raise ViewRuleError('unsupported union: one path per arrow only')
    if {k.name for k in view.kinds} != set(theory.kinds):
        raise ViewRuleError('incomplete theory kind map')
    declared = {s.table for k in theory.kinds.values() for s in k.slots.values() if s.arrow}
    if {f'{a.owner}__{a.name}' for a in view.arrows} != declared:
        raise ViewRuleError('incomplete theory arrow map')
    # Reuse the admitted structural and static AST; do not trust forged/stale span fields.
    spec = views.ViewSpec(view.theory,
        tuple(views.ViewKindMap(k.name, tuple(views.ViewKindBranch(b.name) for b in k.union)) for k in view.kinds),
        tuple(views.ViewArrowMap(a.name, tuple(views.ViewPath(p.start,
            tuple(views.ViewStep(s.slot, s.inverse) for s in p.steps)) for p in a.paths)) for a in view.arrows))
    try:
        checked = view_typing.resolve(views.ViewFile((spec,)), domain, {theory.meta['name']: theory}).views[0]
    except view_typing.ViewTypingError as error:
        raise ViewRuleError(str(error)) from error
    if checked != view:
        raise ViewRuleError('typed view is stale or inconsistent with the admitted schemas')
    roots = {domain.root(k.union[0].name) for k in view.kinds}
    if len(roots) != 1:
        raise ViewRuleError('unsupported endpoint identity: expected one canonical source root')
    root = next(iter(roots))
    id_type = domain.kinds[root].id_type
    if (id_type not in rules_dl.SQL or any(theory.kinds[theory.root(k.name)].id_type != id_type for k in view.kinds)
            or any(domain.kinds[domain.root(b.name)].id_type != id_type for k in view.kinds for b in k.union)):
        raise ViewRuleError('unsupported endpoint ID types; no conversion or encoder is selected')
    return checked


def lower(view: TypedView, domain: Pack, theory: Pack, program: ir.Program,
          names: RelationMap, *, namespace: str, source: str = 'views.yaml') -> ir.Program:
    """Append ordinary rules; returned Program is executable only through existing explicit callers.

    A rule's origin is the line of the entry of views.yaml it is lowered from, as views.read kept it.
    Existing source RowRefs, snapshots, substitutions and checker verification supply the proof lineage.
    """
    _checked(view, domain, theory)  # what it returns equals the view; the view has the lines it was read with
    if program.pack != domain.meta['name'] or not isinstance(namespace, str) or not ir.NAME.fullmatch(namespace):
        raise ViewRuleError('expected this domain Program and a valid fresh rule namespace')
    program = ir.load(ir.to_doc(program))
    if namespace in {r.module for r in program.rules.values()}:
        raise ViewRuleError('generated rule namespace collides with an existing module')
    doc = ir.to_doc(program)
    kinds, arrows = dict(names.kinds), dict(names.arrows)
    expected_kinds = {k.name for k in view.kinds}
    expected_arrows = {f'{a.owner}__{a.name}' for a in view.arrows}
    if set(kinds) != expected_kinds or set(arrows) != expected_arrows:
        raise ViewRuleError('relation map must name every theory kind/arrow exactly once')
    values = list(kinds.values()) + list(arrows.values())
    if any(not isinstance(n, str) or not ir.NAME.fullmatch(n) for n in values) or len(set(values)) != len(values):
        raise ViewRuleError('relation map requires distinct valid derived names')
    tables, worlds = rules_dl.base_tables(domain), rules_dl.base_worlds(domain)
    reserved = set(tables) | set(program.relations) | set(program.rules) | {r.witness_relation for r in program.rules.values()}
    if set(values) & reserved:
        raise ViewRuleError('derived relation map collides with an existing/base/witness name')
    # A kind with one branch has one rule `m_<kind>`; a kind with several has `m_<kind>_<branch>` per branch and
    # `u_<kind>_<i>_<j>` per pair of branches into the invariant relation `<namespace>_disjoint_<kind>`.
    def branch_ids(i, mapped):
        n = len(mapped.union)
        return [f'{namespace}_m_{i}' if n == 1 else f'{namespace}_m_{i}_{b}' for b in range(n)]

    def pair_ids(i, mapped):
        n = len(mapped.union)
        return [f'{namespace}_u_{i}_{a}_{b}' for a in range(n) for b in range(a + 1, n)]

    rule_ids = ([r for i, k in enumerate(view.kinds) for r in branch_ids(i, k) + pair_ids(i, k)]
                + [f'{namespace}_a_{i}' for i, _ in enumerate(view.arrows)])
    disjoint = {i: f'{namespace}_disjoint_{i}' for i, k in enumerate(view.kinds) if len(k.union) > 1}
    added = rule_ids + [f'{r}__witness' for r in rule_ids]
    if (len(set(added)) != len(added) or set(added) & (reserved | set(values))
            or set(disjoint.values()) & (reserved | set(values) | set(added))):
        raise ViewRuleError('generated rule/witness namespace collides')
    relations = {r['name']: r for r in doc['relations']}

    def need(name):
        cols = tables.get(name)
        if cols is None or any(t not in ir.TYPES for _, t in cols) or worlds.get(name) != 'closed':
            raise ViewRuleError(f'unsupported source signature/world: {name}')
        expected = [{'name': n, 'type': t} for n, t in cols]
        if name in relations:
            old = relations[name]
            if old['role'] != 'base' or old['key'] != expected or old.get('values') or old.get('world', 'closed') != 'closed':
                raise ViewRuleError(f'source signature does not match the admitted schema: {name}')
        else:
            relations[name] = {'name': name, 'role': 'base', 'key': expected}

    def derived(name, signature):
        relations[name] = {'name': name, 'role': 'derived', 'module': namespace, 'explain': 'on_demand',
                           'key': [{'name': n, 'type': t} for n, t in signature]}

    def atom(relation, terms):
        return {'relation': relation, 'terms': list(terms)}

    def rule(rid, relation, terms, body, line):
        # Duplicate typed guards at one position need only one positive premise.
        body = tuple(dict.fromkeys((name, tuple(ts)) for name, ts in body))
        doc['rules'].append({'id': rid, 'module': namespace, 'head': atom(relation, terms),
            'body': [dict(atom(n, ts), polarity='positive') for n, ts in body],
            'origin': {'file': source, 'line': str(line)}})

    theory_tables = rules_dl.base_tables(theory)
    for i, mapped in enumerate(view.kinds):
        derived(kinds[mapped.name], theory_tables[mapped.name])
        for rid, branch in zip(branch_ids(i, mapped), mapped.union):
            need(branch.name)
            rule(rid, kinds[mapped.name], ('?v0',), [(branch.name, ('?v0',))], mapped.line)
        if i in disjoint:
            # An identifier in two branches would make two domain elements one theory element: a violation.
            relations[disjoint[i]] = {'name': disjoint[i], 'role': 'derived', 'module': namespace, 'invariant': True,
                                      'explain': 'on_demand', 'key': [{'name': n, 'type': t}
                                                                      for n, t in theory_tables[mapped.name]]}
            pairs = [(a, b) for a in range(len(mapped.union)) for b in range(a + 1, len(mapped.union))]
            for rid, (a, b) in zip(pair_ids(i, mapped), pairs):
                rule(rid, disjoint[i], ('?v0',), [(mapped.union[a].name, ('?v0',)), (mapped.union[b].name, ('?v0',))],
                     mapped.line)
    for i, mapped in enumerate(view.arrows):
        path = mapped.paths[0]
        variables = tuple(f'?v{n}' for n in range(len(path.steps) + 1))
        symbol = f'{mapped.owner}__{mapped.name}'
        derived(arrows[symbol], theory_tables[symbol])
        body = [(kinds[mapped.owner], (variables[0],)), (kinds[mapped.target], (variables[-1],))]
        for membership in path.memberships:
            need(membership.kind)
            body.append((membership.kind, (variables[membership.position],)))
        for branch in path.target_branches:
            need(branch)
            body.append((branch, (variables[-1],)))
        for n, step in enumerate(path.steps):
            need(step.relation)
            pair = (variables[n + 1], variables[n]) if step.inverse else (variables[n], variables[n + 1])
            body.append((step.relation, pair))
        rule(f'{namespace}_a_{i}', arrows[symbol], (variables[0], variables[-1]), body, mapped.line)
    doc['relations'] = sorted(relations.values(), key=lambda r: r['name'])
    return ir.load(ir.with_strata(doc))


# --- A view that executes ----------------------------------------------------------------------------------
#
# bind() lowers a view inside the profile of views.admit to ordinary rules and binds every rule of the program to
# them. For each theory table the view maps (a kind, an attribute, an arrow) there is one derived relation; it holds
# the theory's own table (a pass-through rule, so a kind bound by `is_a` and a kind bound by a view meet in one
# relation) and what the view supplies from the domain's tables. Every rule that read the theory's table reads that
# relation instead: the theory's rules are not copied or edited, only their relation names are bound, as S8 binds
# kind names. A table the view does not map stays the base table it was.
#
# World: a relation is open when a rule reads an open relation positively, so the pass-through keeps an open
# theory table open whatever its source is, and an open source opens the relation; a theory rule that negates it is
# then refused by the ordinary check. A source value that is missing gives no row.

def _split(x):
    """Assignments that split the whole number ?x, written YYYYMMDD, into ?y, ?m and ?d."""
    return [('?y', 'div', x, '10000'), ('?y0', 'mul', '?y', '10000'), ('?md', 'sub', x, '?y0'),
            ('?m', 'div', '?md', '100'), ('?m0', 'mul', '?m', '100'), ('?d', 'sub', '?md', '?m0')]


def _count(out):
    """Assignments that give the days from 1970-01-01 to the day ?y-?m-?d of the proleptic Gregorian calendar:
    the Julian day number without a branch (the year starts in March, so the leap day is its last day), less
    2440588. Every division has a constant divisor and non-negative operands for a year from 1 on."""
    return [('?a0', 'sub', '14', '?m'), ('?a', 'div', '?a0', '12'), ('?y1', 'add', '?y', '4800'),
            ('?yy', 'sub', '?y1', '?a'), ('?m1', 'mul', '?a', '12'), ('?m2', 'add', '?m', '?m1'),
            ('?mm', 'sub', '?m2', '3'), ('?c0', 'mul', '?mm', '153'), ('?c1', 'add', '?c0', '2'),
            ('?c2', 'div', '?c1', '5'), ('?c3', 'mul', '?yy', '365'), ('?c4', 'div', '?yy', '4'),
            ('?c5', 'div', '?yy', '100'), ('?c6', 'div', '?yy', '400'), ('?n0', 'add', '?d', '?c2'),
            ('?n1', 'add', '?n0', '?c3'), ('?n2', 'add', '?n1', '?c4'), ('?n3', 'sub', '?n2', '?c5'),
            ('?n4', 'add', '?n3', '?c6'), (out, 'sub', '?n4', '2472633')]


def _rest(name, divisor):
    """Assignments that give in `<name>1` what the year ?y leaves after division by a constant. A remainder
    compared with 0, not a product compared with ?y: Soufflé reads an equality of two variables as one name."""
    return [(name, 'div', '?y', divisor), (f'{name}0', 'mul', name, divisor), (f'{name}1', 'sub', '?y', f'{name}0')]


IN_MONTH = [('ge', '?y', '1'), ('le', '?y', '9999'), ('ge', '?m', '1'), ('le', '?m', '12'), ('ge', '?d', '1'),
            ('le', '?d', '31')]
# When a whole number YYYYMMDD is no calendar day: (extra assignments, conditions), one rule each.
NO_DAY = [([], [('lt', '?m', '1')]), ([], [('gt', '?m', '12')]), ([], [('lt', '?d', '1')]), ([], [('gt', '?d', '31')]),
          *(([], [('eq', '?m', m), ('gt', '?d', '30')]) for m in ('4', '6', '9', '11')),
          ([], [('eq', '?m', '2'), ('gt', '?d', '29')]),
          ([*_rest('?q', '4')], [('eq', '?m', '2'), ('eq', '?d', '29'), ('ne', '?q1', '0')]),
          ([*_rest('?h', '100'), *_rest('?f', '400')],
           [('eq', '?m', '2'), ('eq', '?d', '29'), ('eq', '?h1', '0'), ('ne', '?f1', '0')]),
          ([], [('lt', '?y', '1')]), ([], [('gt', '?y', '9999')])]  # the years `days` reads, 1 to 9999


def _held(view, theory: Pack, source: str) -> None:
    """Refuse a map onto a theory kind or slot that carries a constraint the lowering does not hold on the rows
    the view supplies: the theory's own checks read only its own table. A limit on a mapped attribute is held,
    by the invariant `bind` makes for it; `required` is the totality left open under "Not built"."""
    def no(what):
        raise ViewRuleError(f'{source}: views[{view.theory}]: {what}: the theory declares a constraint the view '
                            'does not hold on the rows it supplies')
    if any(o.kind == 'axiom' for o in view.obligations):
        no('a path equation or a class rule')
    for mapped in view.kinds:
        for name in theory.ancestors(mapped.name):
            kind = theory.kinds[name]
            if kind.unique_keys or kind.path_equations or kind.rules or kind.id_patterns or kind.seal or kind.sealed_with:
                no(f'kind {name}')
    for mapped in [*view.attributes, *view.arrows]:
        slot = theory.slot(mapped.owner, mapped.name)
        if slot.patterns or slot.constant is not None or slot.minimum_cardinality is not None \
                or slot.maximum_cardinality is not None or (slot.arrow and (slot.minimum, slot.maximum) != (None, None)):
            no(f'{mapped.owner}.{mapped.name}')


def bind(doc: dict | None, view: TypedView, domain: Pack, theory: Pack, names: Mapping[str, str], *,
         source: str = 'views.yaml') -> dict:
    """The rule IR document of the domain with the view lowered into it. `doc` is the IR of the pinned rule closure
    (rules_dl.read), `names` the theory's kind names under the domain's. Raises ViewRuleError before anything
    is added when the view lies outside the profile or a generated name collides. A rule made here has the origin
    `source` at the line of the entry of the view it comes from (a kind, an attribute or an arrow map); the
    pass-through of a theory table comes from no entry and has the line of the view's `theory` key."""
    import copy
    if doc is None:
        raise ViewRuleError(f'{source}: views[{view.theory}]: the theory has no rules to run over the view')
    if any(len(k.union) != 1 for k in view.kinds) or any(len(a.paths) != 1 for a in view.arrows) or \
            any(o.kind == 'functionality' for o in view.obligations):
        raise ViewRuleError(f'{source}: views[{view.theory}]: outside the profile that executes: one source kind per '
                            'theory kind, one path per arrow, no assumed functionality')
    _held(view, theory, source)
    doc = copy.deepcopy(doc)
    prefix = view.theory.replace('-', '_')
    module = f'view_{prefix}'
    relations = {r['name']: r for r in doc['relations']}
    tables, worlds = rules_dl.base_tables(domain), rules_dl.base_worlds(domain)
    taken = set(tables) | set(relations) | {r['id'] for r in doc['rules']} | {f"{r['id']}__witness" for r in doc['rules']}
    if module in {r['module'] for r in doc['rules']} | {r.get('module') for r in relations.values()}:
        raise ViewRuleError(f'{source}: views[{view.theory}]: the generated module {module} collides with a rule file')
    rebound, made = {}, {}   # theory table -> its relation; relation -> its rules, in order

    def fresh(name):
        if name in rules_dl.PROTECTED:  # read after rules_dl.read refused the tables, so refused here
            raise ProtectedRelation(source, view.theory, name)
        if not ir.NAME.fullmatch(name) or name in taken or name in made:
            raise ViewRuleError(f'{source}: views[{view.theory}]: the generated relation {name} collides with an '
                                'existing relation, rule or table')
        made[name] = []
        return name

    def base(name, date=None):
        """A table as a base relation of the program; `date` names a column read as ISO text by `days` alone."""
        cols = tables.get(name)
        if cols is None or any(t is None and n != date for n, t in cols):
            raise ViewRuleError(f'{source}: views[{view.theory}]: {name} is no table a view can read')
        key = [{'name': n, 'type': 'string' if n == date else t} for n, t in cols]
        old = relations.get(name)
        if old is not None and (old['role'] != 'base' or old['key'] != key):
            raise ViewRuleError(f'{source}: views[{view.theory}]: {name} does not match its table')
        relations[name] = dict(name=name, role='base', key=key, world=worlds.get(name, 'closed'))

    def derived(table, **flags):
        relation = fresh(table_relation(module, table))
        relations[relation] = dict(name=relation, role='derived', module=module, **flags,
                                   key=[dict(name=n, type=t) for n, t in tables[table]])
        return relation

    def rule(relation, terms, body, assignments=(), conditions=(), *, line):
        body = list(dict.fromkeys((n, tuple(ts)) for n, ts in body))  # one premise per atom
        doc_rule = dict(module=module, head=dict(relation=relation, terms=list(terms)),
                        body=[dict(relation=n, terms=list(ts), polarity='positive') for n, ts in body])
        if assignments:
            doc_rule['assignments'] = [dict(zip(('var', 'op', 'left', 'right'), s)) for s in assignments]
        if conditions:
            doc_rule['conditions'] = [dict(zip(('op', 'left', 'right'), c)) for c in conditions]
        doc_rule['origin'] = dict(file=source, line=str(line))
        made[relation].append(doc_rule)

    def through(table):
        """The relation of a theory table, holding the table itself."""
        if table not in tables or any(t is None for _, t in tables[table]):
            raise ViewRuleError(f'{source}: views[{view.theory}]: {table} is no table of the theory that rules read')
        base(table)
        relation = rebound[table] = derived(table)
        variables = [f'?v{i}' for i, _ in enumerate(tables[table])]
        rule(relation, variables, [(table, variables)], line=view.line)
        return relation

    for mapped in view.kinds:
        kind, branch = names.get(mapped.name, mapped.name), mapped.union[0].name
        relation = through(kind)
        if branch != kind:
            base(branch)
            rule(relation, ['?v0'], [(branch, ['?v0'])], line=mapped.line)
    for mapped in view.attributes:
        relation = through(f"{names.get(mapped.owner, mapped.owner)}__{mapped.name}")
        base(mapped.source)
        base(mapped.relation, date='v' if mapped.reading == 'days' else None)
        body = [(mapped.source, ['?v0']), (mapped.relation, ['?v0', '?v1'])]

        def invariant(name):
            made_name = fresh(name)
            relations[made_name] = dict(name=made_name, role='derived', module=module, invariant=True,
                                        key=[dict(name='id', type=tables[mapped.source][0][1])])
            return made_name

        if mapped.reading == 'identity':
            value, assignments, conditions = '?v1', [], []
        elif mapped.reading == 'days':
            value, assignments, conditions = '?v2', [('?v2', 'days', '?v1', views.EPOCH)], []
        else:  # yyyymmdd; no row here outside IN_MONTH; a value that is no calendar day (31 February) is counted
            # from the first of its month and gives a row in the invariant below, which blocks publication
            # (docs/compiler/schema-operations.md, "Views that execute")
            value, assignments, conditions = '?v2', _split('?v1') + _count('?v2'), IN_MONTH
        rule(relation, ['?v0', value], body, assignments, conditions, line=mapped.line)
        if mapped.reading == 'yyyymmdd':
            no_day = invariant(f'{relation}_no_day')
            for extra, when in NO_DAY:
                rule(no_day, ['?v0'], body, _split('?v1') + extra, when, line=mapped.line)
        target = theory.slot(mapped.owner, mapped.name)
        if (target.minimum, target.maximum) != (None, None):
            # The theory's limit, held on the value the view supplies: a row here blocks publication.
            out = invariant(f'{relation}_out_of_range')
            for op, limit in (('lt', target.minimum), ('gt', target.maximum)):
                if limit is not None:
                    rule(out, ['?v0'], body, assignments, [*conditions, (op, value, str(limit))], line=mapped.line)
    for mapped in view.arrows:
        relation = through(f"{names.get(mapped.owner, mapped.owner)}__{mapped.name}")
        path = mapped.paths[0]
        variables = [f'?v{n}' for n in range(len(path.steps) + 1)]
        body = [(m.kind, [variables[m.position]]) for m in path.memberships]
        body += [(b, [variables[-1]]) for b in path.target_branches]
        for n, step in enumerate(path.steps):
            pair = [variables[n + 1], variables[n]] if step.inverse else [variables[n], variables[n + 1]]
            body.append((step.relation, pair))
        for name, _ in body:
            base(name)
        rule(relation, [variables[0], variables[-1]], body, line=mapped.line)

    for existing in doc['rules']:  # bind every rule that read a theory table to the view's relation
        head = existing['head']
        for atom in [head, *existing.get('body', []), *existing.get('aggregates', [])]:
            # An access rule (std-access) names elements, and an element is typed (kind, id): a view supplies rows
            # to the theory's relations and retypes no element. So `K(?x)` under a head that grants `?x` as kind K
            # stays the kind's own table. The rule then still grants every element of K by its shape, which is
            # how a role reads K in full and may rely on an absence in a theory table the view leaves alone.
            if head['relation'] in ACCESS and atom is not head and atom['relation'] in head['terms'] \
                    and len(atom['terms']) == 1 and atom['terms'][0].startswith('?') and atom['terms'][0] in head['terms']:
                continue
            atom['relation'] = rebound.get(atom['relation'], atom['relation'])
    for relation, rules in made.items():
        for n, r in enumerate(rules, 1):
            r['id'] = relation if len(rules) == 1 else f'{relation}_{n}'
            if r['id'] in taken or f"{r['id']}__witness" in taken or (r['id'] != relation and r['id'] in made):
                raise ViewRuleError(f"{source}: views[{view.theory}]: the generated rule {r['id']} collides")
            doc['rules'].append(r)
    doc['relations'] = sorted(relations.values(), key=lambda r: r['name'])
    doc['rules'] = sorted(doc['rules'], key=lambda r: r['id'])
    try:
        doc = ir.with_strata(doc)
        program = ir.load(doc)
    except ir.IRError as error:
        raise ViewRuleError(f'{source}: views[{view.theory}]: {error}') from None
    for r in doc['relations']:  # the explain mode, chosen as for a relation of a rule file (R6)
        if r['name'] in made:
            r['explain'] = 'on_demand' if any(x.projects for x in program.rules_for(r['name'])) else 'materialize'
    ir.load(doc)
    return doc

