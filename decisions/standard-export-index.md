# Provenance of standard exports

The publisher produces five mappings: RDF (the view and its context), PROV-O, SHACL, ODCS and DCAT. An out-port declaration promises that consumers can trace the corresponding output from a checked epoch. Publish the declarations after the mappings fulfil this promise.

Implement row indexing first for the RDF view. Its exporter can expose an indexed variant taking the schema, visible rows and the role's mapping from (kind, element id) to authoritative row references. Return the existing Turtle bytes and an OutputFile record from contracts/output-index.yaml. At each emitted subject declaration record the actual one-based line and the originating row. Bind the record to the digest of the exact bytes. Source keys come from the supplied references: the displayed element id can differ from a source row's key. Refuse a missing binding instead of attributing the output to another row.

This first increment covers row identity. Complete the value-level and proof bindings before advertising the port. PROV-O has evidence from the role's witnesses. The context, SHACL and ODCS depend on the schema, and DCAT describes the published distributions. These fields require actual schema or manifest origins. Attaching arbitrary data rows to them would give false provenance. The checked-epoch publisher must eventually verify those origins and publish the index with the corresponding role's files.

For PROV-O, the indexed exporter takes the epoch id, dataset pin and the witnesses selected for the role. Return the Turtle bytes and the OutputFile record for prov.ttl. Bind each proof activity's subject line to its own conclusion row. The activity identifier is the canonical digest of that witness. A role's index and output may refer only to its supplied witnesses.

## Role-scoped document origins

The checked form already has two suitable source documents. The publisher archives the exact canonical schema as publication/schema.json. Its publication/index.json names the role, epoch, schema and dataset pins, plus each available object with its name and digest. OutputField currently represents only row and chart origins.

Extend OutputField with two document origins, schema and role_listing. Each requires exactly one document reference carrying file, SHA-256 of the exact source bytes and an RFC 6901 pointer into them. The filenames resolve beside the current role's form and must match the selected origin. Keep row witnesses and chart locations exclusive to their respective origins. Existing valid indexes still validate.

The independently implementable mapping increments use that same record shape:

- Context: the scoped JSON-LD type of Point.label originates at /kinds/Point/slots/label/type in schema.json.
- SHACL: the emitted property name comes from the key of the declaration at /kinds/Point/slots/label in schema.json. Record the actual Turtle line.
- ODCS: the contract's /name copies /pack in schema.json. Record the output pointer.
- DCAT: a relative access URL identifies the named object of that same checked role's publication listing. Bind the actual accessURL line to the matching /objects/i/name entry, finding the index by name. Refuse a different role or epoch and a missing entry. Hash the actual listing bytes.

Each increment returns the existing export bytes and their digest. These are individual fields, and do not establish complete value or proof coverage. For checked publication, validate all origins and output hashes against the immutable role objects, including the exact listing, before making the provenance sidecar visible. Keep that sidecar outside the listing it hashes to avoid a circular digest. Role filtering, selection of a checked epoch, and refusal of stale or missing source locations remain publisher integration work.
