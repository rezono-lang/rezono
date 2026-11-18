# Publication conformance cases for imported references

Each public case in `docs/publication/cases/` declares its ID, class, status,
schema, form and expected outcome. The Draft 2020-12 schema for these records
must validate the examples, reject misspelled top-level members and reject a
non-boolean `expect.accept`. A schema with no constraints would allow an
invalid example to appear in the published corpus.

Use the existing Host fixture for these settled cases. Add a required `zone`
reference to an imported kind named `Zone` in the examples that read a row.

| Case | Input and expected observation |
| --- | --- |
| S05 | Shorten a valid import's schema digest by one hex digit. Reject the import for lacking a full schema ID. |
| P01 | Pin the imported pack, schema, manifest and dataset. A reference to its `Zone/dmz` has the hash payload and column value `dmz`. The Arrow field carries the imported kind, pack and three pins. A Parquet reader reconstructs the complete row reference. |
| R13 | Change only the referenced pack in the row. Reject the disagreement with the import. |
| P02 | Keep the manifest pin and remove the dataset pin from the import. Reject the schema because an epoch requires its content hash. |
| P04 | Change just the dataset hash in the row reference to another well-formed hash. Reject the disagreement with the import. |

The schema identifies which publication a reference points to. Storing the
whole reference in each column value would duplicate that information and
would change the hash payload. The existing P03 example applies the same
epoch-and-hash requirement to Parquet table metadata.
