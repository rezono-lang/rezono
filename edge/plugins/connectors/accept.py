"""Acceptance of the connectors on one role's publication form (docs/standards.md, state "accepted"; lane M).

`accept(schema, rows, pin)` runs every out-connector on a role's view and checks each against its independent
reader, the same oracles as the tests, now on a real dataset instead of a fixture:

- **rdf:** the RDF view out and back (`publication.rdf`) gives the rows in normal form;
- **shacl:** pySHACL validates that view against the shapes (`shacl.py`), and it conforms;
- **odcs:** the contract (`odcs.py`) is valid against the official ODCS JSON Schema, and DuckDB counts no row
  against any of its quality rules on the library's own Arrow tables of the rows;
- **dcat:** the catalogue entry (`dcat.py`) reads back as written;
- **checks** (when the manifest carries the rule IR): pySHACL validates the view through the pack's invariants as
  SHACL-SPARQL (`shacl_sparql.py`), and reports per invariant exactly the rows Rezono holds for it.

A connector that refuses the schema with an open question (Q13, Q20) is reported as `refused`, with the reason:
that is the checklist's "refuses, and never guesses", not a failure. Anything else that goes wrong is `failed`.

`published(objects, at)` does the same on what the publisher wrote beside a role's form (RV-K20): the bytes the
role fetched through its index, each export against its reader, the DCAT entry's addresses against the index. It
runs in a pack's tests on a published store (examples/subsidy/test_subsidy_forms.py), never in the publish step.

The command takes a published store, as the probe of RD1 exports it (`probes/publication-thin/export.py`), and
prints one JSON report per role; it exits 1 when a connector failed for any role.

    python edge/plugins/connectors/accept.py <store dir> <pack> <manifest> [<role> ...]
"""

import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))  # publication lives at the repository root
sys.path.insert(0, str(HERE))  # the other connectors

import duckdb  # noqa: E402
import jsonschema  # noqa: E402
import open_data_contract_standard  # noqa: E402
import pyshacl  # noqa: E402
import yaml  # noqa: E402
from rdflib import Graph, Literal  # noqa: E402
from rdflib.namespace import PROV, RDF, SH  # noqa: E402
from rezono_compiler import rules as ir  # noqa: E402

import dcat  # noqa: E402
import odcs  # noqa: E402
import shacl  # noqa: E402
import shacl_sparql  # noqa: E402
from publication import arrow, l0, publication, rdf  # noqa: E402

OPEN = ("Q13", "Q20")  # the open questions a connector may refuse a schema for (docs/standards.md)
_OFFICIAL = json.loads((Path(open_data_contract_standard.__file__).parent / "schema.json").read_text(encoding="utf-8"))


class NotAccepted(AssertionError):
    """A connector whose output its independent reader does not accept."""


def _rdf(schema, rows, pin):
    back = rdf.from_turtle(schema, rdf.to_turtle(schema, rows))
    if arrow.normal_rows(schema, back) != arrow.normal_rows(schema, rows):  # row order is not significant (§4.1)
        raise NotAccepted("the rows read back from Turtle are not the rows written")
    return f"{len(rows)} rows out and back"


def _shacl(schema, rows, pin):
    conforms, _, text = pyshacl.validate(rdf.to_graph(schema, rows), shacl_graph=shacl.shapes(schema))
    if not conforms:
        raise NotAccepted(text[:2000])
    return f"{len(schema['kinds'])} node shapes, the view conforms"


def _invalid(con, table, column, rule) -> int:
    """How many rows break one rule (as test_odcs.count reads `invalidValues`)."""
    if rule["type"] == "sql":
        return con.execute(rule["query"]).fetchall()[0][0]
    arguments, c = rule["arguments"], '"' + column.replace('"', '""') + '"'
    if "validValues" in arguments:
        return con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {c} IS NOT NULL AND {c} NOT IN (SELECT unnest(?))',
                           [arguments["validValues"]]).fetchall()[0][0]
    return con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE {c} IS NOT NULL AND NOT regexp_matches({c}, ?)',
                       [arguments["pattern"]]).fetchall()[0][0]


def _odcs(schema, rows, pin):
    document = odcs.contract(schema, pin)
    errors = [e.message for e in jsonschema.Draft201909Validator(_OFFICIAL).iter_errors(document)]
    if errors:
        raise NotAccepted(f"not valid ODCS: {errors[:5]}")
    con = duckdb.connect()
    for name, table in arrow.to_arrow(schema, rows, pin).items():
        con.register(name, table)
    rules, broken = 0, []
    for o in document["schema"]:
        for column, rule in [(None, r) for r in o.get("quality", [])] + [
                (p["name"], r) for p in o["properties"] for r in p.get("quality", [])]:
            rules += 1
            n = _invalid(con, o["name"], column, rule)
            if n:
                broken.append(f"{o['name']}{'.' + column if column else ''}/{rule['id']}: {n} rows")
    if broken:
        raise NotAccepted("; ".join(broken))
    return f"{len(document['schema'])} tables, {rules} quality rules, no row breaks one"


def _dcat(schema, rows, pin):
    files = {form: f"https://data.example/{schema['pack']}/{pin['manifest']}/{form}" for form in dcat.FORMS}
    back = dcat.read(Graph().parse(data=dcat.to_turtle(schema, pin, files), format="turtle"))
    if back["files"] != files or back["pin"] != pin or back["identifier"] != dcat.identifier(schema, pin):
        raise NotAccepted("the entry does not read back as written")
    return f"{len(files)} distributions out and back"


CONNECTORS = {"rdf": _rdf, "shacl": _shacl, "odcs": _odcs, "dcat": _dcat}


def _checks(bundle, rules_doc, derived):
    def run(schema, rows, pin):
        result = checks(bundle, rules_doc, schema, rows, derived)
        undecided = sorted(n for n, r in result.items() if r["state"] == "undecided")
        if undecided:  # the shapes said they cannot decide: refused at validation, not a defect
            raise l0.L0Error(f"Q-seal: not decided from the view, a close of the seal is in it: {undecided}")
        carried = {n: len(r["rows"]) for n, r in result.items() if r["state"] == "carried"}
        off = {n: r["reason"] for n, r in result.items() if r["state"] == "deactivated"}
        return f"{len(carried)} invariants carried, Rezono and pySHACL agree on every row {carried}; deactivated: {off}"
    return run


def accept(schema: dict, rows: list, pin: dict, rules=None) -> dict:
    """Per connector `{"state": "accepted" | "refused" | "failed", "detail": …, "seconds": …}`. With `rules`, the
    schema bundle, the rule IR and Rezono's derived rows, the pack's checks as SHACL-SPARQL too (`checks`)."""
    l0.check_schema(schema)
    l0.read_rows(schema, rows)
    report = {}
    connectors = dict(CONNECTORS, **({"checks": _checks(*rules)} if rules else {}))
    for name, run in connectors.items():
        start = time.monotonic()
        try:
            state, detail = "accepted", run(schema, rows, pin)
        except l0.L0Error as e:
            state, detail = ("refused" if any(q in str(e) for q in OPEN + ("Q-seal",)) else "failed"), str(e)
        except NotAccepted as e:
            state, detail = "failed", str(e)
        report[name] = {"state": state, "detail": detail, "seconds": round(time.monotonic() - start, 1)}
    return report


def checks(bundle: dict, rules_doc: dict, schema: dict, rows: list, derived: dict) -> dict:
    """The pack's invariants as SHACL-SPARQL (`shacl_sparql.py`) against Rezono's own result: pySHACL validates the
    view `rows` through the constraints, and per invariant the rows it reports must be the rows Rezono derived
    (`derived`: {relation: [row, ...]}, as the engine or the store holds them). Raises NotAccepted on a
    difference. Returns, per invariant, `carried` with its rows, `deactivated` with the reason, or `undecided`
    (a close of the seal is in the view)."""
    shapes = shacl_sparql.checks(bundle, rules_doc)
    _, report, _ = pyshacl.validate(rdf.to_graph(schema, rows), shacl_graph=shapes, advanced=True)
    if not hasattr(report, "subjects"):  # pySHACL refused the shapes themselves
        raise NotAccepted(str(report))
    found, undecided = {}, set()
    for r in report.subjects(SH.focusNode, None):
        relation = str(report.value(r, SH.focusNode))[len(schema["base"]):]
        if str(report.value(r, SH.sourceConstraint)).endswith(".seal"):  # the seal guard: no value of its own
            undecided.add(relation)
        else:
            found.setdefault(relation, set()).add(str(report.value(r, SH.value)))
    out, differ = {}, []
    for name, rel in sorted(ir.load(rules_doc).relations.items()):
        if not rel.invariant:
            continue
        shape = next(shapes.subjects(SH.name, Literal(name)))
        if shapes.value(shape, SH.deactivated) is not None:
            out[name] = {"state": "deactivated", "reason": str(shapes.value(shape, SH.message))}
            continue
        pascal = publication.pascal(name)
        if pascal in undecided:
            out[name] = {"state": "undecided"}
            continue
        want = {shacl_sparql.row_key(r, [c.type for c in rel.key]) for r in derived.get(name, [])}
        got = found.get(pascal, set())
        if want != got:
            differ.append(f"{name}: Rezono {sorted(want)[:5]}, SHACL {sorted(got)[:5]}")
        out[name] = {"state": "carried", "rows": sorted(want)}
    if differ:
        raise NotAccepted("; ".join(differ))
    return out


def _prov_witnesses(g: Graph) -> dict:
    """Each witness of a role's `prov.ttl`, read back one activity at a time (`rdf.prov_to_witness` reads one)."""
    out = {}
    for a in g.subjects(RDF.type, PROV.Activity):
        sub = Graph()
        sub.add((a, RDF.type, PROV.Activity))
        for p, o in g.predicate_objects(a):
            sub.add((a, p, o))
            if p in (rdf.RD.binding, PROV.qualifiedUsage):
                for t in g.triples((o, None, None)):
                    sub.add(t)
        for c in g.subjects(PROV.wasGeneratedBy, a):
            sub.add((c, PROV.wasGeneratedBy, a))
        out[str(a)] = rdf.prov_to_witness(sub)
    return out


def published(objects: dict, at: str) -> dict:
    """The standards exports of one role's published form (RV-K20), each checked by its independent reader on the
    bytes the role fetched: `objects` maps every name the role's index lists to its bytes, `at` is the address the
    role fetched them under (the index's own directory). Per export `{"state", "detail"}`, as `accept`."""
    index = json.loads(objects["index.json"])
    schema = json.loads(objects["schema.json"])
    rows = l0.read_collection(schema, json.loads(objects["rows.json"]))
    pin = {"manifest": index["manifest"]["id"], "dataset": index["dataset"]}
    named = {o["name"]: o for o in index["objects"]}

    def view():
        back = rdf.from_turtle(schema, objects["view.ttl"].decode("utf-8"))
        if arrow.normal_rows(schema, back) != arrow.normal_rows(schema, rows):
            raise NotAccepted("view.ttl does not read back to the rows of rows.json")
        ctx = json.loads(objects["context.jsonld"])
        if ctx != rdf.context(schema):
            raise NotAccepted("context.jsonld is not the context of schema.json")
        return f"{len(rows)} rows read back from the view"

    def prov():
        g = Graph().parse(data=objects["prov.ttl"].decode("utf-8"), format="turtle")
        witnesses = _prov_witnesses(g)
        why = set()
        for r in rows:
            for proof in r.get("$why", {}).values():
                why.update(proof.values() if isinstance(proof, dict) else [proof])
        if set(witnesses) != why:
            raise NotAccepted(f"prov.ttl holds {len(witnesses)} witnesses, the rows name {len(why)}")
        return f"{len(witnesses)} witnesses read back, each the hash its activity is named by"

    def shapes():
        conforms, _, text = pyshacl.validate(Graph().parse(data=objects["view.ttl"].decode("utf-8"), format="turtle"),
                                             shacl_graph=Graph().parse(data=objects["shapes.ttl"].decode("utf-8"),
                                                                       format="turtle"))
        if not conforms:
            raise NotAccepted(text[:2000])
        return "the published view conforms to the published shapes"

    def contract():
        document = yaml.safe_load(objects["contract.odcs.yaml"])
        errors = [e.message for e in jsonschema.Draft201909Validator(_OFFICIAL).iter_errors(document)]
        if errors:
            raise NotAccepted(f"not valid ODCS: {errors[:5]}")
        con = duckdb.connect()
        for name, table in arrow.to_arrow(schema, rows, pin).items():
            con.register(name, table)
        broken = [f"{o['name']}/{r['id']}" for o in document["schema"]
                  for column, r in [(None, r) for r in o.get("quality", [])] + [
                      (p["name"], r) for p in o["properties"] for r in p.get("quality", [])]
                  if _invalid(con, o["name"], column, r)]
        if broken:
            raise NotAccepted(f"rows break {broken[:5]}")
        return f"{len(document['schema'])} tables, no row breaks a rule"

    def entry():
        back = dcat.read(Graph().parse(data=objects["dcat.ttl"].decode("utf-8"), format="turtle",
                                       publicID=at + "dcat.ttl"))
        if back["pin"] != pin or back["schema"] != rdf.schema_iri(schema):
            raise NotAccepted("the entry names another epoch or schema")
        for form, address in back["files"].items():
            name = address[len(at):] if address.startswith(at) else None
            if name not in named:
                raise NotAccepted(f"{form}: {address} is not an object the role's index names")
        return f"{len(back['files'])} distributions, each an object of the role's index"

    def losses():
        for o in index["objects"]:
            if "losses" in o and yaml.safe_load(objects[o["losses"]]).get("direction") != "out":
                raise NotAccepted(f"{o['losses']} is not the loss list of an out-connector")
        return "each export names its loss list, and the list is there"

    report = {}
    for name, run in {"view.ttl": view, "prov.ttl": prov, "shapes.ttl": shapes, "contract.odcs.yaml": contract,
                      "dcat.ttl": entry, "losses": losses}.items():
        try:
            state, detail = "accepted", run()
        except (NotAccepted, l0.L0Error, KeyError) as e:
            state, detail = "failed", f"{type(e).__name__}: {e}"
        report[name] = {"state": state, "detail": detail}
    return report


def _probe():
    spec = importlib.util.spec_from_file_location("rd_export", ROOT / "probes" / "publication-thin" / "export.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 3:
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    store, pack, manifest, roles = Path(args[0]), args[1], args[2], args[3:]
    probe = _probe()
    failed = False
    for role in roles or [probe.COMPLETE]:
        result = probe.export(store, pack, manifest, role)
        pin = {"manifest": manifest, "dataset": result["hashes"]["dataset"]}
        epoch = probe.load(store, pack, manifest, role)
        m = json.loads((store / pack / "manifests" / f"{manifest}.json").read_bytes())
        compiled = next((c for c in m["compiled"] if c["file"] == "ir/rules.json"), None)
        rules = (epoch["bundle"], json.loads(probe.read(store, compiled)), epoch["rows"]) if compiled else None
        report = accept(result["schema"], result["rows"], pin, rules)
        failed |= any(r["state"] == "failed" for r in report.values())
        print(json.dumps({"pack": pack, "manifest": manifest, "role": role, "dataset": pin["dataset"],
                          "schema": l0.schema_id(result["schema"]), "kinds": len(result["schema"]["kinds"]),
                          "rows": len(result["rows"]), "connectors": report}, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
