# Cross-check publication epochs during acceptance

A single role index describes one epoch. An export that is syntactically valid for another epoch must fail the independent reader comparison.

For a catalogue, the dataset URI names the manifest and the dataset pin. Its DCAT version literal must describe that same manifest. Enforce this invariant in the DCAT reader, which already extracts the URI pin.

For a published ODCS document, compare its version against the schema id of schema.json and the manifest id and dataset pin in index.json. Syntactic validation against the pinned ODCS schema and running quality rules on Arrow tables provide complementary checks. Both reader disagreements are failures. A named Q13 refusal, in contrast, describes an unsupported RDF mapping of a versioned kind and does not prevent other readers from running.
