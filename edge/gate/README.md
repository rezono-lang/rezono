# Local publication reader

Open a directory written by the publisher with `openLocalGate(directory, role)`. The caller selects the role before opening the reader and already has access to the directory. The handler reads only the selected role through a verified main publication. An earlier pin is read through its own retained head and remains available only when the current role still authorizes its recorded view.

The reader opens snapshots, a role-scoped catalogue, named proof questions that start from a visible row, and read-only `ask` expressions. Pages use canonical key order. A query that exceeds its read or evaluation budget returns a refusal.

A POST to the same pinned ask route can set scope to catalogue. The catalogue exposes the role's readable kind, slot and outcome metadata as CatalogueEntry rows. It uses the ordinary Rezono evaluator and the same answer format and paging rules. Callers can use the shared kinds and schema question templates without reading the raw bundle.

A POST with row scope projects the cells of one visible kind and ordered key into typed RowCell questions. REPL and MCP use the same query, answer pages, and per-relation source continuations under the selected manifest and role.

The bound sweep listing and the named sweep question use the current manifest's checked grid and published variant or diagnosis pointers. The role must see the swept cell. A role without full coverage receives the grid with unavailable statuses. Difference counts remain unavailable because their sidecar has no digest in the checked manifests.

Run the Node 24 tests with `npm test` from this component. Generate the shared contract types with `bash contracts/gen-types.sh` from the repository root.
