---
decider: [core]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: publication-conclusion-addresses
---

# Canonical IRIs for derived conclusions and witnesses

Base elements in a publication already receive canonical IRIs under the schema's `base` (`<kind iri>/<spelled id>`, [Publication 1.0 (L0)](../docs/publication/l0.md#34-references-and-iris)), with bijective segment spelling and epoch/hash pins ([L0 §6.4](../docs/publication/l0.md#64-pins), [source contract](../contracts/source.yaml)). Derived rows and witnesses, however, currently use opaque `rezono:` URIs (`rezono:r/<relation>/<key>` and `rezono:w/<hash>`) in PROV-O and `$why`, disconnected from the pack's `<base>` IRI space and from the element IRIs of the RDF view. Moreover, there is no canonical way to pin a conclusion or witness IRI to an epoch and dataset hash, nor a canonical resolver that maps such an IRI back to its single row.

This decision gives every derived row and every witness a canonical IRI in the same style as element IRIs, defines epoch/hash pinning and single-row resolution, and aligns the RDF view and PROV-O exports on those IRIs.

## 1. Canonical conclusion IRIs

Every row of a derived kind receives an unpinned canonical IRI built in the exact same style as an element IRI ([L0 §3.4](../docs/publication/l0.md#34-references-and-iris)):

```text
<kind iri>/<spelled id>
```

- `<kind iri>` is `element_space(schema, kind)`: the kind's declared `iri`, or `<base><Kind>` when omitted. A `map` entry never names a conclusion space.
- `<spelled id>` is `spell(row["$id"])` under L0 §3.4 segment spelling: ASCII letters, digits, `-`, `.` and `_` stay as written; every other character (including `~`) is written as `~` followed by two upper-case hex digits per UTF-8 byte; `.` and `..` are written `~2E` and `~2E~2E`.

Row identity follows the kind's schema declaration:

- **Keyed derived kind** (a derived kind without `tuple_key`, whose `$id` holds its identifying key and whose derived slots hold the derived values, such as a calculation view, a named outcome or a single-key derived property): `$id` contains only the key, never the derived value. When a derived value changes in a later epoch while the key stays the same, the row retains the exact same unpinned conclusion IRI.
- **Tuple-keyed derived kind** (`tuple_key` listing every slot, [L0 §2.1](../docs/publication/l0.md#derived-tuples)): `$id` is the canonical JSON of its cells in `tuple_key` order, and its conclusion IRI is `<kind iri>/<spell($id)>`.

`rezono_publication.rdf.conclusion_iri(schema, kind, row_id, *, manifest=None, dataset=None)` validates `schema` (`l0.check_schema`), verifies that `kind` is declared in `schema["kinds"]` and `row_id` is non-empty text, and returns the canonical conclusion IRI, pinned via section 3 when `dataset` or `manifest` is given.

## 2. Canonical witness IRIs

Every witness receives an unpinned canonical IRI under the schema's `base`, in the same style as element IRIs and schema documents (`<base>s-<hex>/`, [L0 §5](../docs/publication/l0.md#5-the-rdf-view)):

```text
<base>witness/<H(witness)>
```

- `<base>` is the schema's `base` (an absolute IRI ending in `/`, L0 §2).
- `<H(witness)>` is `canonical_sha256(witness)` as 64 lower-case hex digits.

Because kind names begin with an upper-case ASCII letter (L0 §1), `<base>witness/` cannot collide with any default kind IRI. `l0.check_schema` refuses any kind whose explicit `iri` equals `<base>witness` or starts with `<base>witness/` or `<base>m-`.

`rezono_publication.rdf.canonical_witness_iri(schema, witness, *, manifest=None, dataset=None)` validates `schema`, computes `canonical_sha256(witness)`, and returns `<base>witness/<H(witness)>`, pinned via section 3 when `dataset` or `manifest` is given.

## 3. Epoch and hash pinning

Any canonical conclusion IRI, witness IRI or element IRI may be pinned to a dataset hash, or to an epoch and its dataset hash ([L0 §6.4](../docs/publication/l0.md#64-pins)), using the `pin` query parameter:

- Epoch and hash pin: `<iri>?pin=m-<epoch>@d-<64 hex>`
- Hash pin alone: `<iri>?pin=d-<64 hex>`

Consistent with L0 §6.4 and `Source.revision` in [contracts/source.yaml](../contracts/source.yaml), an epoch pin `m-<epoch>` without its dataset hash pin `d-<64 hex>` is always refused with `l0.L0Error`.

Because kind IRIs contain no `?` or `#` (L0 §2.1) and §3.4 segment spelling never emits `?`, `#` or `@`, the unpinned IRI and its pin separate unambiguously:

- `rezono_publication.rdf.pin_iri(iri, *, dataset, manifest=None)` validates `dataset` (`d-<64 hex>`) and optional `manifest` (`m-<epoch>`), refuses an `iri` that already carries `?` or `#`, and returns `<iri>?pin=...`.
- `rezono_publication.rdf.parse_pin(iri)` returns `(unpinned_iri, None)` for an unpinned IRI, or `(unpinned_iri, {"dataset": d})` / `(unpinned_iri, {"manifest": m, "dataset": d})` for a pinned IRI. It refuses fragments, unknown query parameters, malformed pins and `m-<epoch>` without `d-<64 hex>` with `l0.L0Error`.

When the same keyed derived row takes a different value across two epochs, its unpinned conclusion IRI stays identical while its dataset hash changes, giving a different epoch and hash pin (`?pin=m-<e1>@d-<h1` vs `?pin=m-<e2>@d-<h2`).

## 4. Resolution back to one row

`rezono_publication.rdf.resolve_iri(schema, rows, iri, *, witnesses=(), manifest=None, dataset=None)` resolves a canonical conclusion IRI or canonical witness IRI (pinned or unpinned) back to **exactly one** row of `rows`:

1. Validate `schema` and `rows` with `l0.read_rows(schema, rows)` and split any pin with `parse_pin(iri)`.
2. When a pin is present, verify `pin["dataset"]` against the dataset hash of `(schema, rows)` (computed via `rezono_publication.hash.hashes` when `dataset` is omitted, or verified against `dataset` when given), and when `pin` carries `manifest`, require `manifest` to be supplied and equal to `pin["manifest"]`. Any mismatch raises `l0.L0Error`.
3. For a **conclusion IRI** (`<kind iri>/<spelled id>`): match the unique root kind space in `schema["kinds"]`, strictly decode `<spelled id>` with `unspell`, and return the single row in `rows` whose root kind and `$id` match. A missing row, unknown kind or non-canonical segment raises `l0.L0Error`.
4. For a **witness IRI** (`<base>witness/<64 hex>`): locate the witness in `witnesses` whose `canonical_sha256` equals `<64 hex>`, map its `conclusion` (`RowRef`, [contracts/proof.yaml](../contracts/proof.yaml)) to `(kind, row_id)` under `schema` (for a `tuple_key` kind, `row_id` is `key`; for a kind without `tuple_key`, `key` is `CJ([row_id])`), verify that it resolves to one row in `rows` (and agrees with that row's `$why["$id"]` when present), and return that single row. An unknown witness hash, malformed hex or missing conclusion row raises `l0.L0Error`.

## 5. RDF and PROV-O publication outputs

- **RDF view (`to_graph`, `to_turtle`, `to_jsonld`, `from_graph`):** Every derived row uses its canonical conclusion IRI `<kind iri>/<spelled id>` as its subject. When `publication.row_json` writes `$why` for a derived row under a schema, it emits `canonical_witness_iri(doc, witness)` so `rd:why` annotations in the RDF view carry the canonical witness IRI.
- **PROV-O (`witness_to_prov`, `prov_to_witness`, `prov_index.indexed_prov`, `forms.exports`):**
  - `witness_to_prov(witness, manifest, dataset, sources=None, *, schema=None)` and `prov_to_witness(graph, *, schema=None)` accept the publication `schema`.
  - When `schema` is supplied, the epoch `prov:Bundle` uses `<base>m-<epoch>@d-<64 hex>`, the witness `prov:Activity` uses `canonical_witness_iri(schema, witness)`, the conclusion `prov:Entity` uses `conclusion_iri(schema, kind, row_id)` (matching the RDF view directly), and each premise `prov:Entity` whose relation maps to a kind in `schema` uses its canonical element or conclusion IRI (using `rezono:r/...` only for relations outside `schema`).
  - Mapping between `RowRef(relation, key)` and `(kind, row_id)` under `schema` is bijective: for a kind without `tuple_key`, `key` is `CJ([row_id])`; for a kind with `tuple_key`, `key` is `row_id`. `prov_to_witness(graph, schema=schema)` recovers the exact witness without loss and verifies that the activity IRI equals `canonical_witness_iri(schema, witness)`.
  - `edge/publisher/rezono_publisher/forms.py` and `edge/plugins/connectors/accept.py` pass `schema` when writing and verifying `prov.ttl`.
- **Backward compatibility:** `l0.py` continues to accept opaque absolute proof URIs such as `rezono:w/...` in standalone L0 fixtures, and `witness_to_prov(..., schema=None)` retains its standalone `rezono:` URIs when no schema is supplied.

## Alternatives considered

- **Keep opaque `rezono:r/...` and `rezono:w/...` in PROV-O while RDF uses `<base><Kind>/<id>`.** That leaves the RDF view and PROV-O exports naming the same derived row with two unrelated IRIs and prevents joining them in a triple store without custom rewriting.
- **Carry the epoch/hash pin in a URL fragment (`#m-1@d-...`).** HTTP clients strip fragments before sending a request, so a pinned citation could never be resolved directly against an HTTP publication reader.
- **Embed derived values into every derived row's IRI.** Changing a derived value in a new epoch would mint a different IRI instead of addressing the same derived row at a different epoch and hash pin.
