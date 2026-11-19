# Index the standards exports of a publication form

An out-port writes a projection in which each written value names where it came from (`row_source: output_index` in the [port contract](../contracts/port.yaml)). The publisher already makes five standards mappings for each filtered role: RDF with its JSON-LD context, PROV-O, SHACL, ODCS and DCAT. They can be declared as out-ports only once their output carries that index. This decision fixes how the publisher writes it, using the existing [output index contract](../contracts/output-index.yaml).

## Choice

- **One index per role form.** The publisher writes `exports.index.json`, an `OutputIndex`, under the same prefix as the role's exports. The role's `index.json` lists it like any other object of the form. The publisher writes it only after the exports are verified.
- **Identity.** `pack` and `manifest` are those of the form. `render.step` is `standards_exports`. `render.input_sha256` is the SHA-256 of the canonical JSON object `{"connectors", "dataset", "manifest", "rows", "schema"}`. Here `rows` and `schema` are the SHA-256 of the role's `rows.json` and `schema.json` bytes, `dataset` is the form's dataset hash, and `connectors` is the exporters' source hash (`forms.component()`, which the build record names under `forms`).
- **Files.** The index lists every export file that the form made, sorted by path, each with the SHA-256 of its published bytes. A refused export (an open question in the connector) is absent from both the form and the index.
- **Fields.** A field is a value the export took from the form, found by its 1-based line:
  - a value of a published row has origin `knowledge`, and its witness is the `RowRef` of that row: relation and canonical JSON key. A derived row is its own conclusion. A fact row is cited the same way.
  - a value taken from the role's schema has origin `schema` and points into `schema.json`, with that file's hash.

  Every line that holds a row value carries a knowledge field. Syntax the exporter writes itself, such as prefixes and punctuation, is not a field.

## Alternatives considered

- **An index per export file.** This would double the listing for every role. One render step makes all exports from one input, so one index fits the contract.
- **Indexing every line, with a renderer constant origin.** The contract has no origin for exporter syntax, and such a field would ground nothing. Only values from the form are fields.
- **Declaring the ports first.** The port contract would then promise an index that no one writes. The declarations wait for the index.
