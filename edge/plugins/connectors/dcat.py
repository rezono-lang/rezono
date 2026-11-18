"""The DCAT entry of a published epoch (lane M, M10): one `dcat:Dataset` per epoch and role.

A catalogue entry points at the data; it holds none. It is made from the schema document, the pins of the epoch
and the addresses the publisher gives its files, and it says four things:

- **which dataset:** its IRI is the epoch's own name, `rezono:m/m-<epoch>@d-<64 hex>`, the same resource the PROV-O
  export calls a bundle (`rezono_publication.rdf.witness_to_prov`); `dct:identifier` is the full pin in the order of
  docs/publication/l0.md §6.4, `<pack>@s-…@m-…@d-…`, and `dcat:version` is the manifest id;
- **under which schema:** `dct:conformsTo` the schema id's own space, `<base>s-<hex>/` (§5);
- **in which forms:** a `dcat:Distribution` per form the publisher wrote (§7), with its address and media type; an
  address is absolute, or relative to the entry's own address, as the publisher writes it beside a role's form
  (`rezono_publisher.forms`), so a reader resolves it against wherever it fetched the entry;
- **what each form holds to:** `dct:conformsTo` the profile of row JSON, the JSON-LD context, the SHACL shapes
  (shacl.py) and the ODCS contract (odcs.py), each beside the schema id (`descriptors`).

Plain DCAT 3 and Dublin Core terms only: no extension, no blank node, so the Turtle is the same bytes for the
same input. The entry has no title, description, publisher or licence: those are not in a schema document, and
an application profile that requires them (DCAT-AP) is not met. What a reader does not get is in
`dcat.losses.yaml`.

    python edge/plugins/connectors/dcat.py <schema.json> <m-epoch> <d-hash> <form>=<url> ...   # prints Turtle
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "publication"))

from rdflib import Graph, Literal, Namespace, URIRef  # noqa: E402
from rdflib.namespace import DCTERMS, RDF  # noqa: E402

from rezono_publication import l0, rdf  # noqa: E402

DCAT = Namespace("http://www.w3.org/ns/dcat#")  # rdflib's own is closed on DCAT 2: it has no `version`
MEDIA = "https://www.iana.org/assignments/media-types/"
PROFILE = str(rdf.RD).rstrip("#")  # the profile of §7, under the namespace of `rd:` until `<ns>` is fixed (Q1)
# A form of §7 the publisher may write: its media type, and the documents a file in that form holds to.
FORMS = {
    "row-json": ("application/json", ("profile",)),
    "json-ld": ("application/ld+json", ("profile", "context", "shapes")),
    "turtle": ("text/turtle", ("shapes",)),
    "parquet": ("application/vnd.apache.parquet", ("contract",)),
}
_IRI = re.compile(r"[a-z][a-z0-9+.-]*://\S+")
# A relative reference to a file beside the entry (the publisher's form index names each by its file name): no
# scheme, no host, no dot segment, so the same entry is the same bytes whatever site serves it.
_RELATIVE = re.compile(r"(?!\.\.?(/|$))[A-Za-z0-9_~-][A-Za-z0-9._~%-]*(/(?!\.\.?(/|$))[A-Za-z0-9._~%-]+)*")


class DcatError(l0.L0Error):
    """An epoch that has no catalogue entry here."""


def _fail(where: str, what: str):
    raise DcatError(f"{where}: {what}")


def descriptors(schema: dict) -> dict:
    """What is published beside a schema id, immutable (§5): the JSON-LD context, the SHACL shapes and the ODCS
    contract, and the profile every row JSON document names."""
    at = rdf.schema_iri(schema)
    return {"profile": PROFILE, "context": at + "context.jsonld", "shapes": at + "shapes.ttl",
            "contract": at + "contract.odcs.yaml"}


def dataset_iri(pin: dict) -> URIRef:
    """The epoch's name, as the PROV-O export writes it: `rezono:m/m-<epoch>@d-<64 hex>`."""
    if not isinstance(pin, dict) or set(pin) != {"manifest", "dataset"}:
        _fail("pin", "an epoch is pinned by `manifest` and `dataset`, and nothing else")
    if not (isinstance(pin["manifest"], str) and l0._MID.fullmatch(pin["manifest"])
            and isinstance(pin["dataset"], str) and l0._DID.fullmatch(pin["dataset"])):
        _fail("pin", "an epoch is `m-<epoch>` with its hash pin `d-<64 hex>` (§6.4)")
    return URIRef(f"{rdf.REZONO}m/{pin['manifest']}@{pin['dataset']}")


def identifier(schema: dict, pin: dict) -> str:
    """The full pin, in the order schema, epoch, hash (§6.4)."""
    return f"{schema['pack']}@{l0.schema_id(schema)}@{pin['manifest']}@{pin['dataset']}"


def entry(schema: dict, pin: dict, files: dict) -> Graph:
    """The catalogue entry of one epoch of one role's view. `files` maps a form (`FORMS`) to the address the
    publisher serves it at; a form that was not written is not named."""
    l0.check_schema(schema)
    dataset = dataset_iri(pin)
    if not isinstance(files, dict) or not files:
        _fail("files", "an entry names at least one form and its address")
    held = descriptors(schema)
    g = Graph()
    g.bind("dcat", DCAT)
    g.bind("dct", DCTERMS)
    g.add((dataset, RDF.type, DCAT.Dataset))
    g.add((dataset, DCTERMS.identifier, Literal(identifier(schema, pin))))
    g.add((dataset, DCAT.version, Literal(pin["manifest"])))
    g.add((dataset, DCTERMS.conformsTo, URIRef(rdf.schema_iri(schema))))
    for form, address in sorted(files.items()):
        if form not in FORMS:
            _fail(f"files.{form}", f"not a form this entry knows: {', '.join(FORMS)}")
        if not isinstance(address, str) or not (_IRI.fullmatch(address) or _RELATIVE.fullmatch(address)):
            _fail(f"files.{form}", "an address is an absolute IRI, or a path relative to the entry's own address")
        media, documents = FORMS[form]
        distribution = URIRef(f"{dataset}#{form}")
        g.add((dataset, DCAT.distribution, distribution))
        g.add((distribution, RDF.type, DCAT.Distribution))
        g.add((distribution, DCAT.accessURL, URIRef(address)))
        g.add((distribution, DCAT.mediaType, URIRef(MEDIA + media)))
        for document in documents:
            g.add((distribution, DCTERMS.conformsTo, URIRef(held[document])))
    return g


def to_turtle(schema: dict, pin: dict, files: dict) -> str:
    """The entry as Turtle: the same text for the same schema document, pin and addresses."""
    return entry(schema, pin, files).serialize(format="turtle")


def read(g: Graph) -> dict:
    """What an entry says, back from its graph: the identifier, the pin, the schema's space, and per form its
    address and the documents it holds to. The inverse of `entry`, up to the losses."""
    datasets = sorted(g.subjects(RDF.type, DCAT.Dataset))
    if len(datasets) != 1:
        _fail("graph", "an entry describes exactly one dataset")
    dataset = datasets[0]
    m = re.fullmatch(re.escape(rdf.REZONO) + r"m/(m-[0-9]+)@(d-[0-9a-f]{64})", str(dataset))
    if not m:
        _fail(str(dataset), "not the name of an epoch")
    media = {MEDIA + kind: form for form, (kind, _) in FORMS.items()}
    files, conforms = {}, {}
    for distribution in g.objects(dataset, DCAT.distribution):
        form = media.get(str(g.value(distribution, DCAT.mediaType)))
        if form is None or str(distribution) != f"{dataset}#{form}":
            _fail(str(distribution), "not a distribution of this entry")
        files[form] = str(g.value(distribution, DCAT.accessURL))
        conforms[form] = sorted(str(o) for o in g.objects(distribution, DCTERMS.conformsTo))
    return {"identifier": str(g.value(dataset, DCTERMS.identifier)), "version": str(g.value(dataset, DCAT.version)),
            "pin": {"manifest": m[1], "dataset": m[2]}, "schema": str(g.value(dataset, DCTERMS.conformsTo)),
            "files": files, "conforms": conforms}


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 4 or not all("=" in a for a in args[3:]):
        print(__doc__.strip().splitlines()[-1].strip(), file=sys.stderr)
        return 2
    schema = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    files = dict(a.split("=", 1) for a in args[3:])
    sys.stdout.write(to_turtle(schema, {"manifest": args[1], "dataset": args[2]}, files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
