# Import and provenance

An import turns a pinned source into a reviewed pack change. It models the need expressed by the original evidence. Physical tables, files, staging identifiers and transport positions belong in the mapping and the provenance. The current compiler supports fact sources, slot roles, link kinds, source-aware edits and explicit selection. The general source import sequence below describes a wider design.

## Provenance per fact

A derivation proof explains which premises and rule produced a conclusion. Source metadata identifies the evidence behind a base row, where the proof reaches a fact. Both identify that row by a `RowRef` containing the relation and its canonical key. A kind membership has its own row, and each slot value has a separate row. Different values of one multivalued slot can therefore carry different sources.

### Real origins and intermediate storage

Identify the actual observation, decision, design choice or versioned publication. For a decision, cite the person or original decision evidence. A table, spreadsheet, export or Git path can record where data was stored or transported. That trail alone does not establish its origin. Preserve it as reference evidence for drift and keep unresolved origins explicit. A reference is usable as an acceptance oracle only when it independently supplies the expected answers for the pinned trial.

The [source contract](../../contracts/source.yaml) has a flat list of sources on an entry. It does not assign typed origin, transport and oracle roles. Validating a locator or finding it in the pinned history does not establish the evidentiary relationship. Proposal and base context stay outside the actual-origin leaves. A person's statement can be a cited source for a row the person wrote. It does not by itself establish who accepted a decision or that a decision was accepted.

### Source contract and locators

A `Source` has a kind, name and position. Git and proposal sources require their pinned revision. Git positions can name a path with a line, section or structured fragment. A structured query can use the resource in its name and the resource version in its position. The loader does no network lookup.

An external document cites an absolute HTTP(S) URL and a specific section or paragraph. It includes the SHA-256 of the cited fragment's exact UTF-8 bytes, its licence and attribution, and either a revision or the actual UTC retrieval time. Retrieval time differs from the time of the fact. The citation carries no fragment text. The importer checks the evidence, its licence and the fragment before recording it. Declared third-party ownership also requires licence and attribution. Ownership is explicit and does not follow from a hostname.

A `SourceEntry` carries the row reference, its sources and an optional message key for an exception reason. Per-role `SourceSet` references are pinned in the publication manifest. [Source and sidecar contract](../../contracts/source.yaml), [manifest](../../contracts/manifest.yaml).

### Fact files and exact rows

A fact file can have a companion `facts/<name>.sources.yaml`. Its default applies when there is no record override, and the record applies when there is no cell override. An exact entry in `rows` takes precedence over all three. A row selector must name an actually emitted relation and canonical key from the companion fact file, including typed integer and inline identifier representations. For a fact file without a companion, the pack file and line give the usual source locator.

```yaml
default: {kind: git, name: register, revision: "1111111111111111111111111111111111111111", position: data/items.json}
records:
  - {of: {kind: item, id: a}, position: /items/0}
  - {of: {kind: item, id: a, slot: label}, position: "data/labels.json#/items/0"}
```

A leading slash is a JSON Pointer shorthand only for the same compatible inherited file source, replacing its locator fragment. A source kind or name change needs a complete position. Exact entries instead carry complete sources.

```yaml
rows:
  - row: {relation: item__quantity, key: '["a","1"]'}
    sources: [{kind: person, name: reviewer, position: record-1}]
  - row: {relation: item__quantity, key: '["a","2"]'}
    sources: [{kind: person, name: reviewer, position: record-2}]
```

Sources for duplicate facts are combined in a deterministic order and deduplicated. The canonical sidecar codec can materialize a complete row ledger and check it by reading it back against the same fact bytes. Materializing a file-and-line source preserves its historical locator. It does not move the original evidence to a new line. Provenance has its own row ledger rather than a table per slot. It is not an input relation for rules. Where a rule needs a date or ordering, model that data as a typed slot with the appropriate role. [Provenance tests](../../compiler/tests/test_sources.py), [exact rows fixture](../../contracts/fixtures/source/SourceSidecar/valid/exact-rows.yaml).

### Writes, proposals and migrations

The source writer can plan edits and exact undo from pinned bytes, a typed delta, proposal context and explicit evidence for the touched rows. Its pure plan checks those inputs without IO. The trusted caller supplies the real origins. A locator, a scenario or a proposal identifier cannot stand in for that evidence. The ordinary writer updates a fact file and its companion together and preserves the sources of untouched rows. For an admitted proposing path, the verified statement can supply the source of what that person stated. A merge record is change context and does not add a source leaf or decide the provenance of facts. A scenario overlay replaces the scenario's record and tracks that the new premises are assumed.

During a schema operation, sources move with the typed output rows. Splits retain the source of each incoming row and a combine can accumulate sources from its inputs. The lossless check covers the retained entries. [Source writer](../../compiler/rezono_compiler/source_writer.py), [writer source tests](../../compiler/tests/test_writer_sources.py), [proposal path](../../edge/publisher/rezono_publisher/proposal.py), [migration plan](schema-operations.md#the-migration-plan).

### Publication and access

The publisher writes source sets for the base rows in each role's snapshot and pins them under `fact_sources`. The typed row keys agree with the rows and proofs the role reads. The independent checker verifies coverage, ordering, source validity and the absence of entries for unreadable rows. The manifest's own source pins identify the loaded publication inputs. A fact-entry source addresses the evidence for one particular row.

Provenance follows typed row references. Searching a source string for a hidden identifier would make unrelated hidden facts affect the visible bytes. The source name and position are published metadata of the visible row, so write locators that are safe to publish with that row. The per-relation source index supports proof leaves by row. An answer can show the authorized base source without adding an edge to the derivation graph. [Publisher source sets](../../edge/publisher/rezono_publisher/sources.py), [source checks](../../checker/rezono_checker/sources.py), [explanation](rules.md#explanation).

## Slot roles

The compiler recognizes slot roles through a declared `slot_uri`, given as a qualified name or its full IRI. A role may occur once per kind, including inherited slots. A role requires the appropriate scalar type. The bundle carries the bindings so a reader or parameter selection can use the declared meaning.

| Role | Slot URI | Accepted type |
| --- | --- | --- |
| Name | `rdfs:label` | Text |
| Description | `schema:description` | Text |
| Image | `schema:image` | Text naming a pack asset |
| Order | `schema:position` | Whole number |
| Valid from | `schema:validFrom` | Date |
| Valid until | `schema:validThrough` | Date |
| Known from | `prov:generatedAtTime` | Date |

An order role supplies an ordering rather than the fact's caption. The validity and knowledge roles can select parameter rows at the relevant date. A kind without a knowledge-time role has no separate date at which a parameter row becomes known. Timestamp resolution is outside the current accepted role types. [Compiler role tests](../../compiler/tests/test_slot_roles.py).

## Link kinds

Use a relationship kind when a relation has its own facts or several typed ends. The LinkML declaration `represents_relationship: true` requires a unique key of at least two distinct scalar reference slots and no name attribute. The bundle records those ends in key order. A relationship's display name can follow its ends. An enum used by an old source to distinguish sides does not itself identify an end.

A binary link can appear as a line, and more ends can be shown through a junction in a supporting reading. Its own row and attributes remain available in a table. Each endpoint must be backed by that row and its actual typed reference. [Link-kind tests](../../compiler/tests/test_link_kinds.py), [publication readings](../rezono/publication.md).

## Proposed rules

An import can propose an ordinary rule when an upstream relation appears to store a conclusion. The acceptance design starts from pinned rows R. Withhold those rows and recompute dependent relations before evaluating the candidate. DuckDB and Soufflé must agree on the complete typed rows inferred, and every inferred row must belong to R.

Every unexplained row that remains as a fact needs a verified original source and a reason. A stored result without such evidence remains an open gap. Restore the justified remainder and evaluate the candidate again in both engines. Their output must reproduce R exactly. The canonical byte count of the rule files and all facts they require must be strictly smaller than the canonical byte count of the explained rows. This includes supporting facts already present in the pinned input, new facts and any required completeness evidence.

An author, an agent or a learner can supply a candidate. An absence can label a negative example only when the kind is closed and read in full or a verified completeness row covers the tuple at the relevant snapshot. The candidate proceeds through ordinary review with pinned acceptance cases and independent expectations. The general derive-and-admit operation remains design. [Import rule proposals](../../decisions/import-rule-proposals.md), [independent comparisons](../formal.md#11-independent-oracles), [proposal contract](../../contracts/proposal.yaml).

## One source import

The proposed reusable import artifact is an ordered operation set paired with a source definition and a pinned source revision. The source's schema and data form the input state. The destination models the original evidence and the questions it needs to answer. A repeat run over the same pin, inputs and mapping must give the same bytes. A new revision yields a proposed delta.

1. Use `select` to state what is retained and give a reason for each omission. The checked operation requires explicit loss acceptance.
2. Use the supported `rename`, `move`, `split_by` and `combine` operations to express the domain's types and identities.
3. In the proposed `to_sources` step, move citations out of domain slots and into typed row sources. A lossless step can reconstruct the original citations.
4. In the proposed `derive` step, replace supported stored results with a rule and keep only justified exceptions under the acceptance above.
5. In the proposed `reroute` step, read a copied fact at its actual upstream origin using a separate pinned source and selection. Record why the intermediate copy is excluded.

The workflow would write canonical schema and fact files with companion sources and an impact report. Prior answers can serve as independent acceptance evidence for a migration. Explain every accepted difference against the evidence and the model. Keep external machine-readable specifications at a separately pinned interchange boundary and account for unsupported constructs explicitly. A generic ingestion runner, further schema operations and the end-to-end derive and reroute path are not implied by the implemented selection operation. [Schema operations](schema-operations.md#schema-operations), [canonical writer](schema-operations.md#the-canonical-writer).

The model review checks whether the design has inherited source layout rather than domain meaning. It considers layout-based identifiers and fields, source references embedded as content, unmarked relationship kinds, unexplained base rows matching derived data, and missing or contradictory origin claims. Missing provenance is a correctness problem wherever the row contract requires it. Automatic classification of this wider inventory remains design.

## Fact classes

Use the following inventory to decide how evidence crosses the import boundary.

| Class | Evidence | Destination |
| --- | --- | --- |
| `primary` | An observation or publication from its actual origin | A base row with that origin |
| `derived` | A conclusion from other cited evidence | A rule with a witness |
| `copy` | A stored representation of an upstream fact or result | A reference for drift and acceptance, then consult the real origin |
| `decision` | An actual decision or design choice | A base row with original decision evidence |

Only primary and decision rows belong in the design's base fact inventory. The inventory keeps the unexplained and unresolved rows explicit. A copy is not automatically primary after one hop. General fact-class enforcement and projection into the bundle remain design. [Project vision](../vision.md#facts-and-conclusions).
