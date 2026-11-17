"""SHACL shapes of a publication schema (docs/publication/l0.md §5; lane M, M08): `<base>s-<hex>/shapes.ttl`.

The shapes are made from the schema document alone and validate the RDF view of a dataset under that schema
(`rezono_publication.rdf.to_graph`): what a SHACL validator accepts is what the library's reader accepts, as far as a
shape can say it. What a shape cannot say is in `shacl.losses.yaml`.

Per kind a node shape, closed, with one property shape per slot:

- **an element** is an IRI in the kind's own space, `<base><Kind>/<id>` (§3.4), and has the kind's slots only;
- **a single-valued slot** has exactly one object: a value, or a state the slot's `states` lists;
- **a many-valued slot** is its members, or `rd:emptySet` alone (not for `+`), or one state: never a mix;
- **a value** is a literal of the slot's datatype (§5), with what the type adds that SHACL can say: the pattern
  of a `Text` type, the members of a closed enum, the bounds of a slot of the core type `Integer`, the unit of a
  `Quantity`; a reference is an IRI in the target kind's space;
- **a state** is a blank node with one property, `rd:unknown`, `rd:notApplicable` or `rd:invalid`, whose value
  is the reason: empty, or a reason code the schema allows for that state (§2.3).

Every shape has an IRI, a fragment of the shapes document, so the Turtle is the same bytes for the same schema.
Like the converter, the shapes refuse what has no RDF form yet: a versioned kind (Q13) and a reference into
another pack (Q20).

    python edge/plugins/connectors/shacl.py <schema.json>   # prints shapes.ttl
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))  # publication lives at the repository root

from rdflib import BNode, Graph, Literal, Namespace, URIRef  # noqa: E402
from rdflib.collection import Collection  # noqa: E402
from rdflib.namespace import RDF, SH, XSD  # noqa: E402

from rezono_publication import l0, rdf  # noqa: E402

REASON_CODE = "^([a-z][a-z0-9_]*)?$"  # §2.3: empty, or a reason code


def document_iri(schema: dict) -> str:
    """`<base>s-<hex>/shapes.ttl` (§5)."""
    return rdf.schema_iri(schema) + "shapes.ttl"


def _list(g: Graph, subject, predicate, members):
    """One RDF list as the object of `subject predicate`. A shape has at most one list per predicate, so the
    serializer's order never depends on a blank node's label."""
    head = BNode()
    Collection(g, head, list(members))
    g.add((subject, predicate, head))


def _space(schema: dict, kind: str) -> str:
    """A pattern for the IRIs of a kind's elements: `<kind iri>/` and a non-empty spelled id (§3.4)."""
    return "^" + re.escape(rdf.element_space(schema, kind) + "/") + "(?:[A-Za-z0-9._-]|~[0-9A-F]{2})+$"


def _reasons(schema: dict, state: str):
    """The reason codes a state may carry when the schema declares `reasons` (else None), and the core codes
    that label other states only (§2.3)."""
    foreign = sorted(c for c, states in l0.CORE_REASONS.items() if state not in states)
    declared = schema.get("reasons")
    if declared is None:
        return None, foreign
    allowed = {c for c, states in l0.CORE_REASONS.items() if state in states and c not in declared}
    allowed |= {c for c, r in declared.items() if state in r["states"] and c not in foreign}
    return sorted(allowed), foreign


def _state_shape(g: Graph, ns: Namespace, schema: dict, state: str):
    shape = ns[f"state.{state}"]
    if (shape, RDF.type, SH.NodeShape) in g:
        return shape
    reason = ns[f"state.{state}.reason"]
    g.add((shape, RDF.type, SH.NodeShape))
    g.add((shape, SH.nodeKind, SH.BlankNode))
    g.add((shape, SH.closed, Literal(True)))
    g.add((shape, SH.property, reason))
    g.add((reason, RDF.type, SH.PropertyShape))
    g.add((reason, SH.path, rdf._STATE_TERMS[state]))
    g.add((reason, SH.minCount, Literal(1)))
    g.add((reason, SH.maxCount, Literal(1)))
    g.add((reason, SH.datatype, XSD.string))
    allowed, foreign = _reasons(schema, state)
    if allowed is not None:
        _list(g, reason, SH["in"], [Literal("")] + [Literal(c) for c in allowed])
    else:
        g.add((reason, SH.pattern, Literal(REASON_CODE)))
        if foreign:  # a core code labels its own states only
            other = ns[f"state.{state}.reason.of-another-state"]
            g.add((reason, SH["not"], other))
            g.add((other, RDF.type, SH.NodeShape))
            _list(g, other, SH["in"], [Literal(c) for c in foreign])
    return shape


def _value_shape(g: Graph, ns: Namespace, schema: dict, kind: str, slot_name: str, slot: dict):
    """What a known value, or a member of a set, is."""
    shape = ns[f"{kind}.{slot_name}.value"]
    g.add((shape, RDF.type, SH.NodeShape))
    if "ref" in slot:
        if "." in slot["ref"]:
            rdf._fail(slot["ref"], "a reference into another pack has no IRI here: its base is not imported (Q20)")
        g.add((shape, SH.nodeKind, SH.IRI))
        g.add((shape, SH.pattern, Literal(_space(schema, slot["ref"]))))
        return shape
    datatype = URIRef(rdf._type_iri(schema, slot["type"]))
    g.add((shape, SH.datatype, datatype))
    t = l0._local_type(schema, slot["type"])
    if t is None:  # an imported type: its members are in the other pack's schema document
        return shape
    if t["of"] == "Text" and "pattern" in t:
        g.add((shape, SH.pattern, Literal(f"^(?:{t['pattern']})$")))  # the reader matches the whole text
    elif t["of"] == "Enum":
        enum = schema["enums"][t["enum"]]
        if isinstance(enum, list):  # closed; an open enum may gain values, so its members are not a constraint
            _list(g, shape, SH["in"], [Literal(v, datatype=datatype) for v in enum])
    elif t["of"] == "Quantity" and "unit" in t:
        g.add((shape, SH.pattern, Literal(" " + re.escape(t["unit"]) + "$")))
    elif slot["type"] == "Integer":  # the core type is xsd:integer, which SHACL can compare
        for member, term in (("min", SH.minInclusive), ("max", SH.maxInclusive)):
            if member in slot:
                g.add((shape, term, Literal(slot[member], datatype=XSD.integer)))
    return shape


def _one_of(g: Graph, shape, alternatives: list):
    """`shape` holds when one of the alternatives does; a single alternative needs no `sh:or`."""
    if len(alternatives) == 1:
        g.add((shape, SH.node, alternatives[0]))
    else:
        _list(g, shape, SH["or"], alternatives)


def shapes(schema: dict) -> Graph:
    """The shapes graph of a schema document. The document is checked first (`l0.check_schema`)."""
    l0.check_schema(schema)
    ns = Namespace(document_iri(schema) + "#")
    g = Graph()
    g.bind("sh", SH)
    g.bind("rd", rdf.RD)
    g.bind("xsd", XSD)
    for name, kind in sorted(schema["kinds"].items()):
        if "versioned" in kind:
            rdf._fail(name, "a versioned kind has no RDF form yet (Q13)")
        shape = ns[name]
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetClass, URIRef(rdf.kind_iri(schema, name))))
        g.add((shape, SH.nodeKind, SH.IRI))
        g.add((shape, SH.pattern, Literal(_space(schema, name))))
        # An element of a subkind is an instance of this class too (`rdfs:subClassOf` in the view, §5), and it has
        # slots this kind has not. So an instance is an element of a subkind, held by that kind's own shape (which
        # restates every slot of this one), or it is an element of this kind itself and has these slots only.
        subkinds = sorted(k for k, other in schema["kinds"].items() if other.get("parent") == name)
        if subkinds:
            below = [ns[f"{name}.is.{k}"] for k in subkinds]
            for node, k in zip(below, subkinds):
                g.add((node, RDF.type, SH.NodeShape))
                g.add((node, SH["class"], URIRef(rdf.kind_iri(schema, k))))
            shape = ns[f"{name}.itself"]
            _list(g, ns[name], SH["or"], [*below, shape])
            g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.closed, Literal(True)))
        _list(g, shape, SH.ignoredProperties, [RDF.type])
        for slot_name, slot in sorted(kind["slots"].items()):
            if "inverse" in slot:  # the same relation as its forward slot; a writer does not emit it (§3.4)
                continue
            path = URIRef(rdf.slot_iri(schema, name, slot_name))
            prop = ns[f"{name}.{slot_name}"]
            g.add((shape, SH.property, prop))
            g.add((prop, RDF.type, SH.PropertyShape))
            g.add((prop, SH.path, path))
            g.add((prop, SH.name, Literal(slot_name)))
            g.add((prop, SH.minCount, Literal(1)))  # absence is a state, written explicitly (§3.1)
            value = _value_shape(g, ns, schema, name, slot_name, slot)
            states = [_state_shape(g, ns, schema, s) for s in slot["states"] if s != "known"]
            if slot["card"] in ("1", "?"):
                g.add((prop, SH.maxCount, Literal(1)))
                _one_of(g, prop, [value, *states])
                continue
            if slot["card"] == "+" and not states:  # members only
                g.add((prop, SH.node, value))
                continue
            # A set: its members, or rd:emptySet alone, or one state. Each is a property shape on the same path,
            # and the element conforms to one of them.
            members = ns[f"{name}.{slot_name}.members"]
            g.add((members, RDF.type, SH.PropertyShape))
            g.add((members, SH.path, path))
            g.add((members, SH.node, value))
            alternatives = [members]
            if slot["card"] == "*":
                empty = ns[f"{name}.{slot_name}.empty"]
                g.add((empty, RDF.type, SH.PropertyShape))
                g.add((empty, SH.path, path))
                g.add((empty, SH.hasValue, rdf.RD.emptySet))
                g.add((empty, SH.maxCount, Literal(1)))
                alternatives.append(empty)
            if states:
                state = ns[f"{name}.{slot_name}.state"]
                g.add((state, RDF.type, SH.PropertyShape))
                g.add((state, SH.path, path))
                g.add((state, SH.maxCount, Literal(1)))
                _one_of(g, state, states)
                alternatives.append(state)
            whole = ns[f"{name}.{slot_name}.set"]
            g.add((whole, RDF.type, SH.NodeShape))
            _list(g, whole, SH["or"], alternatives)  # two or three: `*` adds the empty set, `states` a state
            g.add((shape, SH.node, whole))
    return g


def to_turtle(schema: dict) -> str:
    """`shapes.ttl`: the same text for the same schema document."""
    return shapes(schema).serialize(format="turtle")


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    sys.stdout.write(to_turtle(json.loads(Path(args[0]).read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
