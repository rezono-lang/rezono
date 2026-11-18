"""A pack's checks as SHACL-SPARQL constraints (lane M, M08 second half; SHACL §5, SPARQL-based constraints).

Every invariant of the pack's rule IR (`ir/rules.json`, contracts/rules.yaml; `// @invariant`, a relation that
must be empty at the end of an epoch) becomes one node shape with a `sh:sparql` constraint. The constraint
recomputes the invariant from the base facts of the RDF view of a role (`rezono_publication.rdf.to_graph` on the publication
form of `rezono_publication.publication`), never from the derived rows the view also carries: so a validator that
knows SHACL and nothing of Rezono repeats the check, and a difference with Rezono's own result is a defect in one of
the two. The shapes are generated from the rule IR alone; none is written by hand.

The translation, one relation at a time (each call a subquery, so the variables of one rule never meet those of
another):

- **a base relation** is read from the view: `k(id)` as the elements of the kind, `k__a(id, v)` as the known
  values of the slot (a state is a blank node and `rd:emptySet` is no member, so neither is a row); an enum and
  a bound of a slot as their values (a union of `BIND`s); the seal's accepted and refused rows as
  below;
- **a value** is in one canonical form, so that a join is an equality of terms: an integer as an `xsd:integer`,
  a text as an element IRI spells an id (`rdf.spell`, §3.4), which for an element or a reference is the local
  part of its IRI, for a value is `ENCODE_FOR_URI` respelled (`_spelled`), and for a constant is spelled when
  the shapes are made (the IR compares texts by equality only, so the spelling changes no answer);
- **a derived relation** is the `UNION` of its rules, `DISTINCT`; a negative literal is `FILTER NOT EXISTS` on
  the variables it shares (all of them, as the IR requires); an aggregate is a grouped subquery joined on its
  group, as `rezono_compiler.rules_sql` does: `count` and `sum` over the rows and a zero for every group of the
  body, so an empty group is 0, and `min` and `max` by an inner join, so an empty group gives nothing; `div`
  truncates toward zero; a condition is a `FILTER`. No `MINUS`, `VALUES` or `SERVICE`: SHACL §5.3.1 forbids them
  in a constraint.

**The seal.** A rule reads only accepted rows; whether a row is refused depends on the hash of the row, which
the view does not carry. Without a close (no `closed_until` and no `covers` value of the period close) no row is
refused, and the translation is exact: accepted is every element, refused is empty. With a close, a second
constraint of the same shape reports that the check cannot be decided from the view, so the shapes never claim
that the data conforms when they cannot know.

**What is not translated** (and why) is a shape with `sh:deactivated true` and the reason as its `sh:message`:
a recursive relation (SPARQL has no fixpoint), an outcome, a calculation input
and a base relation the view does not carry. `shacl-sparql.losses.yaml` lists these losses.

A result names the invariant's relation in the view as its focus node (`<base><Relation>`, as the publication
names a derived relation) and the violating row as its value: its columns in the canonical form, joined by `/`
(which the encoding never leaves in a text). `report` writes Rezono's own rows of the invariants as the SHACL
validation report a validator writes through these constraints. pySHACL is the oracle in the tests and in
`accept.py`, never a dependency of this module.

    python edge/plugins/connectors/shacl_sparql.py <schema-bundle.json> <rules.json>   # prints checks.ttl
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "publication"))

from rdflib import Graph, Literal, Namespace, URIRef  # noqa: E402
from rdflib.namespace import RDF, RDFS, SH, XSD  # noqa: E402
from rezono_canon import canonical_sha256  # noqa: E402
from rezono_compiler import rules as ir  # noqa: E402

from rezono_publication import publication, rdf  # noqa: E402

INTEGER = f"<{XSD.integer}>"
COMPARE = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
ARITHMETIC = {"add": "+", "sub": "-", "mul": "*"}
BOUNDS = ("minimum", "maximum", "minimum_cardinality", "maximum_cardinality", "constant")


class Refused(ValueError):
    """A check that SHACL-SPARQL cannot carry on the view, with the reason."""


def text(value: str) -> str:
    """The canonical form of a text: spelled as an element IRI spells an id (§3.4)."""
    return rdf.spell(value)


def _spelled(term: str) -> str:
    """`rdf.spell` as a SPARQL expression over the text of `term`. `ENCODE_FOR_URI` leaves the unreserved
    characters and writes every other byte as `%` and two upper-case hex digits; the spelling differs in two
    ways: `~` is spelled too, and the mark is `~`, not `%`. The `~` goes first, so that no `~` of the text is
    left when `%` becomes one. `.` and `..` write their dots, as a segment of dots alone would be removed."""
    s = f"STR({term})"
    return (f'IF({s} = ".", "~2E", IF({s} = "..", "~2E~2E", '
            f'REPLACE(REPLACE(ENCODE_FOR_URI({s}), "~", "~7E"), "%", "~")))')


def row_key(values, types) -> str:
    """The value of a result: the columns of a row in their canonical form, joined by `/`."""
    return "/".join(str(int(v)) if t == "integer" else text(str(v)) for v, t in zip(values, types))


def _string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _constant(term: str, typ: str) -> str:
    if typ == "integer":
        return f'"{int(term)}"^^{INTEGER}'
    return _string(text(term))


class _Translator:
    def __init__(self, bundle: dict, rules_doc: dict):
        self.doc, self.plan = publication.schema_document(bundle)
        self.prog = ir.load(rules_doc)
        self.seals = rules_doc.get("seals", [])
        self.n = 0
        self.guarded = False  # whether the check read the seal
        self.bounds = {}
        for a in bundle.get("attributes", []) + bundle.get("arrows", []):
            for b in BOUNDS:
                if a.get(b) is not None:
                    self.bounds[f"{a['table']}__{b}"] = a[b]

    def fresh(self, stem="v") -> str:
        self.n += 1
        return f"?_{stem}{self.n}"

    # --- a relation: one subquery that binds the call's variables -------------------------------------------
    def call(self, name: str, terms, aggregate=False, negated=False) -> tuple[str, list[str]]:
        """The pattern of `name(terms)` as a subquery projecting the call's variables (and, in an aggregate,
        a fresh variable for every `_`), with the projected variables. Negated, it is a plain group that
        compares its columns with the call's variables, which are bound outside: `FILTER NOT EXISTS` sees them,
        and a SPARQL constraint may not hold `MINUS` (SHACL §5.3.1)."""
        rel = self.prog.relations[name]
        cols = [self.fresh("c") for _ in rel.key]
        lines = [self.columns(name, cols)]
        project, seen = [], {}
        for t, c, col in zip(terms, cols, rel.key):
            if t == "_":
                if aggregate:
                    project.append(c)
            elif ir.is_var(t):
                v = "?" + t[1:]
                if v in seen or negated:
                    lines.append(f"FILTER({c} = {seen.get(v, v)})")
                else:
                    seen[v] = v
                    lines.append(f"BIND({c} AS {v})")
                    project.append(v)
            else:
                lines.append(f"FILTER({c} = {_constant(t, col.type)})")
        if negated:
            return "{\n" + "\n".join(lines) + "\n}", []
        if not project:
            project = [self.fresh("u")]
            lines.append(f"BIND(1 AS {project[0]})")
        return "{ SELECT DISTINCT " + " ".join(project) + " WHERE {\n" + "\n".join(lines) + "\n} }", project

    def columns(self, name: str, cols: list[str]) -> str:
        """A group pattern binding `cols` to the columns of every row of `name`."""
        rel = self.prog.relations[name]
        if rel.role == "calc":
            raise Refused(f"reads {name}, a calculation input, which the view does not carry as rows")
        if rel.role == "base":
            return self.base_columns(name, cols)
        if rel.outcome:
            raise Refused(f"reads {name}, an outcome, whose states are not rows of the view")
        if self.prog.recursive(name) or name in self.prog.bounds:
            raise Refused(f"reads {name}, a recursive relation: SPARQL has no fixpoint")
        rules = self.prog.rules_for(name)
        if not rules:  # a relation nobody extends is the empty set
            return "FILTER(false)"
        return "\nUNION\n".join("{\n" + self.rule(r, cols) + "\n}" for r in sorted(rules, key=lambda r: r.id))

    def base_columns(self, name: str, cols: list[str]) -> str:
        rel = self.prog.relations[name]
        if name in self.plan["kinds"]:
            e = self.fresh("e")
            kind = self.plan["kinds"][name]
            space = f"{rdf.element_space(self.doc, kind)}/"
            # An element is typed once, at its most specific kind (§3.1), and the view states each `parent` as
            # `rdfs:subClassOf` (§5): the elements of a kind with subkinds are those of every kind below it too.
            typed = "a" if self.plan["family"][kind] == [kind] else f"a/<{RDFS.subClassOf}>*"
            return (f"{e} {typed} <{rdf.kind_iri(self.doc, kind)}> .\n"
                    f"FILTER(STRSTARTS(STR({e}), {_string(space)}))\n"
                    f"BIND({self.element(e, space, rel.key[0].type)} AS {cols[0]})")
        if name in self.plan["slots"]:
            kind, slot_name, _ = self.plan["slots"][name]
            slot = self.doc["kinds"][kind]["slots"][slot_name]
            e, o = self.fresh("e"), self.fresh("o")
            space = f"{rdf.element_space(self.doc, kind)}/"
            value = (self.element(o, f"{rdf.element_space(self.doc, slot['ref'])}/", rel.key[1].type) if "ref" in slot
                     else f"{INTEGER}(STR({o}))" if rel.key[1].type == "integer" else _spelled(o))
            return (f"{e} <{rdf.slot_iri(self.doc, kind, slot_name)}> {o} .\n"
                    f"FILTER(!isBlank({o}) && !sameTerm({o}, <{rdf.RD.emptySet}>))\n"
                    f"BIND({self.element(e, space, rel.key[0].type)} AS {cols[0]})\n"
                    f"BIND({value} AS {cols[1]})")
        # A SPARQL constraint may not hold VALUES (SHACL §5.3.1): a union of BINDs says the same.
        if name in self.doc.get("enums", {}) and isinstance(self.doc["enums"][name], list):
            values = [_constant(v, rel.key[0].type) for v in self.doc["enums"][name]]
            return "\nUNION\n".join(f"{{ BIND({v} AS {cols[0]}) }}" for v in values) or "FILTER(false)"
        if name in self.bounds:
            return f"BIND({_constant(str(self.bounds[name]), rel.key[0].type)} AS {cols[0]})"
        for seal in self.seals:
            parts = {p["accepted"]: p for p in seal.get("parts", [])}
            if name == seal["refused"]:
                self.guarded = True
                return "FILTER(false)"  # without a close no row is refused
            if name == seal["accepted"]:
                self.guarded = True
                return self.columns(seal["kind"], cols)
            if name in parts:  # a part counts when the element it is part of does
                self.guarded = True
                p = parts[name]
                owner = seal["accepted"] if p["owner"] == seal["kind"] else parts_accepted(seal, p["owner"])
                up = self.fresh("w")
                arrow, _ = self.call(p["arrow"], [cols[0], up])
                accepted, _ = self.call(owner, [up])
                return f"{arrow}\n{accepted}"
        raise Refused(f"reads {name}, which the view does not carry")

    def element(self, var: str, space: str, typ: str) -> str:
        local = f"STRAFTER(STR({var}), {_string(space)})"
        return f"{INTEGER}({local})" if typ == "integer" else local

    # --- a rule: the body binds the rule's variables, the head binds `cols` ---------------------------------
    def rule(self, rule, cols: list[str]) -> str:
        self.n += 1
        prefix = f"?r{self.n}_"

        def v(t):
            return prefix + t[1:]

        def renamed(terms):
            return ["?" + v(t)[1:] if ir.is_var(t) else t for t in terms]

        types = {}
        for b in rule.body:
            for t, c in zip(b.atom.terms, self.prog.relations[b.atom.relation].key):
                if ir.is_var(t):
                    types.setdefault(t, c.type)
        for a in rule.aggregates:
            types[a.var] = "integer"
        for s in rule.assignments:
            types[s.var] = "integer"

        def term(t, other):
            if ir.is_var(t):
                return v(t)
            return _constant(t, types.get(other) or ir.const_type(t))

        lines = []
        for b in rule.body:
            if b.polarity == "positive":
                lines.append(self.call(b.atom.relation, renamed(b.atom.terms))[0])
        for a in rule.aggregates:
            lines.append(self.aggregate(a, renamed(a.atom.terms), v(a.var), list(lines)))
        for s in rule.assignments:
            left, right = term(s.left, s.right), term(s.right, s.left)
            if s.op in ARITHMETIC:
                expr = f"({left} {ARITHMETIC[s.op]} {right})"
            elif s.op == "div":  # truncated toward zero, as rules_sql divides
                q = f"FLOOR(ABS({left}) / ABS({right}))"
                expr = f"{INTEGER}(IF(({left} < 0) = ({right} < 0), {q}, -{q}))"
            else:
                raise Refused(f"{rule.id}: the assignment {s.op} has no SPARQL form here")
            lines.append(f"BIND({expr} AS {v(s.var)})")
        for c in rule.conditions:  # the IR compares texts by equality only, so the canonical form keeps order
            lines.append(f"FILTER({term(c.left, c.right)} {COMPARE[c.op]} {term(c.right, c.left)})")
        for b in rule.body:
            if b.polarity == "negative":
                lines.append("FILTER NOT EXISTS " + self.call(b.atom.relation, renamed(b.atom.terms), negated=True)[0])
        rel = self.prog.relations[rule.head.relation]
        for t, c, col in zip(rule.head.terms, cols, rel.key):
            lines.append(f"BIND({v(t) if ir.is_var(t) else _constant(t, col.type)} AS {c})")
        return "\n".join(lines)

    def aggregate(self, a, terms, var: str, positives: list) -> str:
        rel = self.prog.relations[a.atom.relation]
        over = None
        if a.over is not None:
            i = [c.name for c in rel.key].index(a.over)
            over = self.fresh("x")
            terms = list(terms)
            if terms[i] != "_":
                raise Refused(f"{a.atom.relation}: the aggregated column is bound")
            terms[i] = over
        pattern, _ = self.call(a.atom.relation, terms, aggregate=True)
        keys = list(dict.fromkeys(t for t in terms if ir.is_var(t) and t != over))
        raw = self.fresh("g")
        group = f" GROUP BY {' '.join(keys)}" if keys else ""
        if a.function in ("count", "sum"):
            # An empty group is 0. Not an OPTIONAL: rdflib evaluates its right side with the left side's
            # bindings and then joins on nothing. Every group of the body weighs 0, every row of the atom 1 (count)
            # or its value (sum), and the group is the sum of the weights: the same in any SPARQL engine.
            w = self.fresh("w")
            weight = "1" if a.function == "count" else over
            rows = f"{{ {pattern}\nBIND({weight} AS {w}) }}"
            if keys:
                domain = f"{{ SELECT DISTINCT {' '.join(keys)} WHERE {{\n" + "\n".join(positives) + "\n} }"
                rows = f"{{ {domain}\nBIND(0 AS {w}) }}\nUNION\n{rows}"
            else:
                rows = f"{{ BIND(0 AS {w}) }}\nUNION\n{rows}"
            sub = f"SELECT {' '.join(keys)} (SUM({w}) AS {raw}) WHERE {{\n{rows}\n}}{group}"
            return f"{{ {sub} }}\nBIND({raw} AS {var})"
        sub = f"SELECT {' '.join(keys)} ({a.function.upper()}({over}) AS {raw}) WHERE {{\n{pattern}\n}}{group}"
        if not keys:
            sub += " HAVING (COUNT(*) > 0)"  # a min or max over nothing has no conclusion
        return f"{{ {sub} }}\nBIND({raw} AS {var})"


def parts_accepted(seal: dict, kind: str) -> str:
    return next(p["accepted"] for p in seal["parts"] if p["kind"] == kind)


def document_iri(bundle: dict, rules_doc: dict) -> str:
    """`<base>s-<hex>/checks/<sha256 of the rule IR>.ttl`: the checks change with the rules, not only the schema."""
    doc, _ = publication.schema_document(bundle)
    return f"{rdf.schema_iri(doc)}checks/{canonical_sha256(rules_doc)}.ttl"


def checks(bundle: dict, rules_doc: dict) -> Graph:
    """The shapes graph of a pack's invariants: one node shape per invariant, deactivated with its reason when
    SHACL-SPARQL cannot carry it on the view."""
    ns = Namespace(document_iri(bundle, rules_doc) + "#")
    g = Graph()
    g.bind("sh", SH)
    t = _Translator(bundle, rules_doc)
    for name, rel in sorted(t.prog.relations.items()):
        if not rel.invariant:
            continue
        shape = ns[name]
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.name, Literal(name)))
        g.add((shape, SH.targetNode, URIRef(t.doc["base"] + publication.pascal(name))))
        t.guarded = False
        cols = [f"?{c.name}" for c in rel.key]
        try:
            pattern, _ = t.call(name, cols)
        except Refused as e:
            g.add((shape, SH.deactivated, Literal(True)))
            g.add((shape, SH.message, Literal(f"not carried: {e}")))
            continue
        key = ', "/", '.join(f"STR({c})" for c in cols)
        rows = ns[f"{name}.rows"]
        g.add((shape, SH.sparql, rows))
        g.add((rows, RDF.type, SH.SPARQLConstraint))
        g.add((rows, SH.message, Literal(f"{name}: {{?value}}")))
        g.add((rows, SH.select, Literal(
            f"SELECT DISTINCT $this ?value WHERE {{\n{pattern}\nBIND(CONCAT({key}) AS ?value)\n}}")))
        if t.guarded:
            g.add((shape, SH.sparql, _seal_guard(g, ns, t, name)))
    return g


def _seal_guard(g: Graph, ns: Namespace, t: _Translator, name: str):
    """The constraint that reports a close: then the seal, and so the check, cannot be decided from the view."""
    patterns = []
    for seal in t.seals:
        for table in (seal["closed_until"], seal["covers"]):
            if table in t.plan["slots"]:
                kind, slot_name, _ = t.plan["slots"][table]
                o = t.fresh("o")
                patterns.append(f"?_e <{rdf.slot_iri(t.doc, kind, slot_name)}> {o} . "
                                f"FILTER(!isBlank({o}) && !sameTerm({o}, <{rdf.RD.emptySet}>))")
    guard = ns[f"{name}.seal"]
    g.add((guard, RDF.type, SH.SPARQLConstraint))
    g.add((guard, SH.message,
           Literal(f"{name}: not decided, a close of the seal is in the view and its row hash is not")))
    union = "\nUNION\n".join("{ " + p + " }" for p in patterns) or "FILTER(false)"
    g.add((guard, SH.select, Literal(f"SELECT DISTINCT $this WHERE {{\n{union}\n}}")))
    return guard


def report(bundle: dict, rules_doc: dict, derived: dict) -> Graph:
    """Rezono's own result as a SHACL validation report: one result per row of an invariant (`derived`: {relation:
    [row, ...]}, as the engine or the store holds them), named as a validator names it through `checks`, so the
    two reports hold the same results. A row of a deactivated invariant is reported too: Rezono checks it, a
    validator cannot."""
    ns = Namespace(document_iri(bundle, rules_doc) + "#")
    doc, _ = publication.schema_document(bundle)
    g = Graph()
    g.bind("sh", SH)
    top = ns["report"]
    g.add((top, RDF.type, SH.ValidationReport))
    conforms = True
    for name, rel in sorted(ir.load(rules_doc).relations.items()):
        if not rel.invariant:
            continue
        for value in sorted(row_key(r, [c.type for c in rel.key]) for r in derived.get(name, [])):
            conforms = False
            result = ns[f"report.{name}/{value}"]
            g.add((top, SH.result, result))
            g.add((result, RDF.type, SH.ValidationResult))
            g.add((result, SH.focusNode, URIRef(doc["base"] + publication.pascal(name))))
            g.add((result, SH.value, Literal(value)))
            g.add((result, SH.resultSeverity, SH.Violation))
            g.add((result, SH.sourceShape, ns[name]))
            g.add((result, SH.sourceConstraint, ns[f"{name}.rows"]))
            g.add((result, SH.sourceConstraintComponent, SH.SPARQLConstraintComponent))
            g.add((result, SH.resultMessage, Literal(f"{name}: {value}")))
    g.add((top, SH.conforms, Literal(conforms)))
    return g


def to_turtle(bundle: dict, rules_doc: dict) -> str:
    """`checks.ttl`: the same text for the same bundle and rule IR."""
    return checks(bundle, rules_doc).serialize(format="turtle")


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    bundle, rules_doc = (json.loads(Path(a).read_text(encoding="utf-8")) for a in args)
    sys.stdout.write(to_turtle(bundle, rules_doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
