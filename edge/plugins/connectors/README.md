# connectors

Connectors to standards (lane M of #401, decision N7): what a connector is, the checklist it meets and each standard with its state are in [docs/standards.md](../../../docs/standards.md). This directory holds the connectors that are not part of the publication library, and every loss list.

| File | What |
|---|---|
| `shacl.py` | The SHACL shapes of a publication schema document ([publication §5](../../../docs/publication/l0.md#5-the-rdf-view)): `python edge/plugins/connectors/shacl.py <schema.json>` prints `shapes.ttl` |
| `shacl_sparql.py` | A pack's invariants as SHACL-SPARQL constraints, from the rule IR, and Rezono's own rows as a SHACL validation report: `python edge/plugins/connectors/shacl_sparql.py <schema-bundle.json> <ir/rules.json>` prints the shapes. `fixtures/checks` is the domain-free pack its test runs on |
| `odcs.py` | The ODCS data contract of a publication schema document ([publication §2.5](../../../docs/publication/l0.md#25-data-contracts)), for the columnar form: `python edge/plugins/connectors/odcs.py <schema.json>` prints it as YAML |
| `dcat.py` | The DCAT entry of a published epoch for one role: `python edge/plugins/connectors/dcat.py <schema.json> <m-epoch> <d-hash> <form>=<url> ...` prints Turtle |
| `linkml_schema.py` | A pack's schema as plain LinkML and back (M02, P10.7): `python edge/plugins/connectors/linkml_schema.py export <pack> <out-dir>` writes one LinkML schema per module and a root `<pack>.yaml` that imports them; `... import <root.yaml> <pack>` writes the modules of a LinkML schema into the pack's `schema/` and has the compiler read it. `fixtures/linkml` is a pack with the constructs no example pack uses, for the round trip; `fixtures/linkml-standard` a schema written the way LinkML's own examples write one, and the pack it goes into |
| `accept.py` | Every out-connector on one role's form from a published store, against its independent reader: `python edge/plugins/connectors/accept.py <store> <pack> <manifest> [<role> ...]` ([accepted](../../../docs/standards.md#accepted-on-a-published-pack)) |
| `*.losses.yaml` | The loss list of a connector, in the form of `contracts/connector.yaml`: `rdf` and `prov-o` for `publication/rezono_publication/rdf.py`, `shacl` for `shacl.py`, `shacl-sparql` for `shacl_sparql.py`, `odcs` for `odcs.py`, `dcat` for `dcat.py`, `linkml` (out) and `linkml.in` (in) for `linkml_schema.py`. A connector that maps both ways has a list per direction, the one for `in` named `<standard>.in.losses.yaml` |
| `test_losses.py`, `test_shacl.py`, `test_shacl_sparql.py`, `test_odcs.py`, `test_dcat.py`, `test_linkml_schema.py`, `test_accept.py` | Each loss list against what its export writes; the shapes against pySHACL and the library's reader; the invariants' constraints against Rezono's batch engine (DuckDB), pySHACL reporting exactly Rezono's rows; the contract against the official ODCS JSON Schema, the standard's model and DuckDB; the catalogue entry by its triples, a round trip and rdflib's DCAT and Dublin Core terms; the LinkML of every pack that compiles on its own out and back to the same schema bundle, against LinkML's metamodel, SchemaView and validator; the acceptance runner on the fixtures |

The publisher runs `shacl.py`, `odcs.py` and `dcat.py` (with `publication/rezono_publication/rdf.py`) on each filtered role's form and writes their output and loss lists beside it (`rezono_publisher.forms`, RV-K20; [published per role](../../../docs/standards.md#published-per-role)); `accept.py`'s `published` checks those bytes in a pack's tests. Until ports run as Jobs (M6) a connector runs in-process. Its port declaration follows the port contract (O12a, PC1) once that is on `main`.

```bash
cd edge/plugins/connectors && python -m pytest -q test_losses.py test_shacl.py test_shacl_sparql.py test_odcs.py test_dcat.py test_linkml_schema.py test_accept.py   # with canon and the compiler installed
```
