# Schema operations and views

A view interprets one schema through another while the original pack remains in place. A schema operation changes a pack and emits a migration and an impact report. Both work with typed kinds, slots and rows. The [formal foundations](../formal.md#4-between-layers-functorial-data-migration) describe the relationship with data migration. LinkML remains an interchange form at the schema boundary.

## Structural view-file boundary

A top-level `views.yaml` is part of the definition bytes covered by [import pins](pack.md). The closed `rezono.views/1` reader accepts kind branches, arrow paths and named attribute readings. It rejects unknown or duplicate fields, empty branches and paths, and non-boolean flags. Kind names are resolved engine-kind names. An arrow name and each path step name an unqualified slot, as in `left`. The reader orders alternative branches deterministically and preserves the step order within a path. [View reader](../../compiler/rezono_compiler/views.py), [structural fixture](../../compiler/tests/fixtures/views/structural.yaml).

Structural reading checks the shape and renders normalized definitions. Executable views also require type checking and lowering. An unsupported top-level view fails pack loading or replay at the relevant boundary, including when it occurs in the pinned import closure. A file named `views.yaml` elsewhere in the pack does not declare a view.

## Views that execute

The executable profile allows a view of an imported, fact-free theory in the pack being compiled. Each kind map preserves identifiers and has a single source kind. Each arrow map uses a single nonempty path without `assume_functional`. Use `of` to qualify a theory slot when necessary. An attribute map uses one own or inherited source attribute. The following shape supplies a `span` from a `term` and reads its `starts` date.

```yaml
format: rezono.views/1
views:
  - theory: spans
    kinds:
      - {name: span, union: [{populated_from: term}]}
    attributes:
      - {of: span, name: first, populated_from: starts, reading: days}
```

| Reading | Input | Result |
| --- | --- | --- |
| `identity` | Text or an integer | The same value |
| `days` | A date | Days since 1970-01-01 in the proleptic Gregorian calendar |
| `yyyymmdd` | An integer encoded as YYYYMMDD | The same day count, with invalid calendar values reported through an integrity relation |

Lowering supplies a derived relation for each mapped table. A pass-through of the theory's own rows and the rows supplied by the domain meet at that relation. The compiler binds ordinary rule reads to it. It preserves the kind identity used by typed access grants. Generated names must be collision-free. The course of a proof reaches the source row even when a reading converts its representation. A missing source value leaves no row. An open source propagates its world, and the ordinary rule and access checks still apply.

Mapped limits can generate a blocking range check. The compiler refuses unsupported combinations of patterns, constants, cardinalities, keys, seals and theory constraints. General unions, alternative paths, expressions, enum mappings and views of views are outside this profile. Check the scope of a view's supplied coverage separately from the totality of a required slot in ordinary fact data. [Executable profile tests](../../compiler/tests/test_view_execute.py), [type tests](../../compiler/tests/test_view_typing.py), [coverage certificate tests](../../compiler/tests/test_view_coverage_certificate.py).

## Design: theories and views

A theory pack declares `theory: true`, carries no fact files and cannot publish an instance by itself. It can declare constraints and rules. A domain pins a theory in its imports and can bind that vocabulary through the executable profile above. Replaying a theory descriptor still requires the verified pack definition. [Theory tests](../../compiler/tests/test_theory.py), [pack pins](pack.md).

The fuller view design would type-check unions and composition, totality, cardinality, enum coverage, named options and any cycle before taking a binding as a valid interpretation. A requested functional view needs an explicit obligation and a blocking check when it cannot be proved from the declarations. A scalar extension would require an explicit typed expression tree. The bounded implementation already uses ordinary rule lowering. A general satisfaction theorem and a general-purpose view mapper remain design. LinkML Map terminology informs the interchange shape without making arbitrary expressions executable. [Theory satisfaction tests](../../compiler/tests/test_theory_satisfaction.py), [theories and colimits](../formal.md#design-theories-views-and-colimits).

## Schema operations

Apply an operation set to a checkout inside a disposable `rezono-work-*` directory. The command checks the complete change before applying it. It writes a forward mapping per step, an inverse where the step is lossless, and the combined `impact.json`.

```bash
python -m rezono_compiler operate "$WORK/library" operations.yaml "$OUT"
```

| Operation | Row-level effect | Round-trip condition |
| --- | --- | --- |
| `rename` | Transport a kind, slot, enum or enum value to a new name | The accepted rename is an isomorphism |
| `move` | Transport slot rows up or down the kind hierarchy or across one single-valued arrow | Every value and its identity can be recovered |
| `drop` | Remove a slot or kind and its owned rows | Explicit loss acceptance is required |
| `split_by` | Make subkinds by selecting on one existing attribute | The split and inverse account for the discriminator values |
| `combine` | Move the slots of an absorbed kind along a one-to-one arrow | The absorbed rows and identifiers can be recovered |
| `select` | Keep a declared inventory of local kinds and slots | Every excluded item has a reason and loss is explicitly accepted |

The proposed citation conversion, derivation, rerouting, merge and extraction operations belong to the wider import and migration design. [Operation contract](../../contracts/operation.yaml), [import sequence](import.md#one-source-import).

### The operation file

`rezono.operations/1` has one pack name and an ordered list of operations. Each operation names a schema element and may provide fields such as `to`, `via`, `absorb`, `key`, `cases`, `world`, `accept_loss` or `accept_access` when allowed by the contract. Qualify an ambiguous schema name with its module. The declarative order is significant. The result of one step is the input to the next. [Operation reader](../../compiler/rezono_compiler/operate/spec.py).

### What an operation means

The operations act on the normalized row state, including rows that violate a schema obligation. Dropping a kind also removes its memberships on ancestors and recursively owned elements. A move toward the source of an arrow joins the slot rows on the referenced identifier. A move in the other direction can carry several sources to one target only when their retained values agree. A split introduces a subkind for each declared discriminator case. An abstract parent requires every record to land in a case. A combine joins the surviving and absorbed kinds along the declared arrow and can keep the absorbed identifier in a key slot.

A selection accounts for each local kind once. For retained kinds, the retained slots and omission reasons account for the local declarations, with identifiers kept automatically. Selection is simultaneous, so mutually referring omitted kinds can be removed together. A kept dependency on a removed element blocks the change. Implicit identifiers for inline elements move with the owner's identity, kind and slot. Explicit identifiers are preserved. The engine-name mapping can also change when an ambiguity disappears, and the impact report includes those changes.

### What moves along

Schema references, fact states, selected rule references, labels and channel bindings follow the operation. The writer reloads fact files after changing them and requires the intended rows. Rules follow inverse definitions of affected base tables. A simple rename substitutes a table name. A move across an arrow may need a join and a fresh variable. A literal that refers to a dropped table, an ambiguous constant or an affected identifier that cannot be translated blocks the operation. Message keys for presentation templates stay fixed. A definition change produces a new compiled program and a new definition pin. [Operation execution](../../compiler/rezono_compiler/operate/execution.py).

### World, outcomes and access

Moving a slot to a table with a different world requires an explicit world declaration. The resulting rules are checked again, including absence and aggregate reads. An outcome annotation follows a renamed kind or remains on the parent of a split. Its kind cannot silently disappear. Migration checks compare rule results on the relevant old and new fact states. They detect new violation or outcome rows, new access grants, and whether moving values would let more readers see them. Where the operation supports `accept_access`, that flag explicitly records widened access to moved values. It does not waive an untranslatable access rule or a new grant. [Rule world and outcomes](rules.md#open-world-and-named-outcomes), [operation checks](../../compiler/rezono_compiler/operate/checks.py).

### Other places that name an element

The impact is wider than a class name in a schema. Relation declarations, typed access grants, derived inline identifiers, labels and channel bindings can name the same element. A reference is translated only where its role is known. The operation refuses unsupported dependent inputs such as calculation or sweep definitions that could retain a stale name. A broader migration needs to handle those references before it can change the schema.

### The migration

The forward and inverse documents use a bounded LinkML Map shape such as `class_derivations`, `slot_derivations` and `populated_from`. A split records its checked selection with the `where` extension. An arrow transfer can render a path such as `address.street`. External readers need to support the emitted subset and any extension they consume. The compiler checks its own typed migration rather than relying on an external mapper to establish losslessness. [Migration writer](../../compiler/rezono_compiler/operate/migration.py).

### The migration plan

A checked plan makes data movement explicit as projections, filters, joins and branch combinations. The plan records how output rows follow input rows. It carries row multisets, so an equal output from distinct input branches can retain separate lineage. Source sidecars follow that lineage with deterministic merging and deduplication of source entries. It is the executed plan's result that must equal the rows reloaded from the rewritten pack. [Plan implementation](../../compiler/rezono_compiler/plan.py), [operation sources tests](../../compiler/tests/test_operate_sources.py).

### The lossless contract

For every tested fact state X in the operation's domain, the forward operation M and its inverse must give M⁻¹(M(X)) = X as row multisets, with the original typed source entries when they are present. An operation compares multiplicities as well as membership. This matters when an invalid input contains a duplicate, an extra value or a dangling reference. Where loss is declared, list the exact lost rows and track the admissible new state. A round trip does not excuse a newly introduced integrity or access violation.

### The oracle: Catlab

A separate Julia implementation evaluates the migration comparison and returns forward and reverse row multisets. The harness compares them with Rezono's rows for the supported operation cases. The Catlab workflow selects relevant changes on main and also supports manual dispatch. Graph rewriting, general pushouts and a general test for view composition are outside the covered cases. [Oracle comparison](../../compiler/tests/catlab/compare.py), [workflow](../../.github/workflows/catlab-oracle.yml).

### Worked example: the library pack

The [library pack](../../examples/library/README.md) and its [operation fixture](../../contracts/fixtures/operation/OperationSet/valid/library.yaml) show how the steps compose. To run this sequence, use a disposable copy of the example with only `facts/valid.yaml` as its fact state. The intentionally invalid fact file includes a discriminator without a case, which causes the abstract split to fail.

```yaml
format: rezono.operations/1
pack: library
operations:
  - {op: rename, kind: Copy, to: Item}
  - op: split_by
    kind: Member
    slot: membership
    cases:
      - {value: adult, kind: AdultMember}
      - {value: youth, kind: YouthMember}
    abstract: true
  - {op: move, kind: Member, slot: home_branch, to: AdultMember}
  - {op: combine, kind: Branch, absorb: Address, via: Branch.address}
  - {op: drop, kind: Item, slot: reference_only, accept_loss: true}
```

The rename changes the kind targeted by a loan without changing the path through its copy and branch. The split selects the adult and youth rows from the membership value. The move retains the home branch value on the adult subkind and is lossless for the fixture's valid state. The combine makes street, city and postcode available on the branch by following its address reference. The final drop explicitly loses the reference-only values and lists them in the impact. A rule that still read a dropped slot would block the change. [Expected impact for the drop](../../contracts/fixtures/operation/Impact/valid/library-drop.yaml).

### Implementation and limits

The implemented operations share the same reader, checked execution, impact and mapping output. Each new operation needs its own typing and loss behavior on that path, including counterexamples. Among the current limits, a split requires a kind without subkinds, and another slot that still points to a removed kind blocks its removal. A move that would strand a key or constraint needs a supported translation. The inverse of an optional inline absorption can exceed what the exported mapping represents exactly, even when the compiler's own round trip succeeds. A source import must first establish an accepted source state. Displaying a proof across migrations remains a separate design.

## The canonical writer

The writer applies typed deltas in a disposable `rezono-work-*` checkout. A delta inserts or deletes a record or sets or unsets a slot. An insert names the fact file. For existing records without a file in the delta, the writer requires one unambiguous location.

```bash
python -m rezono_compiler.writer apply "$WORK/library" delta.json --inverse undo.json
```

The writer edits the affected lines, preserving existing order, quoting, comments and line endings where they still apply. It reads the changed facts back and compares them to the intended typed state before writing. It writes replacement files atomically one at a time inside the disposable checkout. If the multi-file operation fails, discard that checkout and start from the pinned base. The inverse uses recorded byte edits when the base still matches and otherwise uses the inverse values where permitted. A fact file with a source companion is edited together with it, and undo can restore both sets of bytes.

The writer and source writer share the source-format boundary for edits. Schema operations use that boundary to locate the relevant inputs. Support for writing a fact in one syntax does not imply a schema operation can rewrite that syntax's complete pack. [Writer tests](../../compiler/tests/test_writer.py), [writer source tests](../../compiler/tests/test_writer_sources.py), [source-format tests](../../compiler/tests/test_source_format.py).
