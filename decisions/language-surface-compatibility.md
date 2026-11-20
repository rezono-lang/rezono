---
decider: [core, language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: language-surface-compatibility
---

# Compare a pack's public surface with its last publication and refuse an unaccepted major change with R033

The [language reference](../docs/rezono/v0.md#4c-public-surface-and-compatibility), section 4c, designs a compatibility check: at publication the publisher compares a pack's public surface with the last published one, classifies the change as patch, minor or major, and refuses a major change with `R033` unless a proposal with an impact assessment accepts it. Nothing builds it yet: no code names `R033`, and nothing compares a pack's surface with what it published before. `rezono 1` is the first language with an external stability promise (section 4b), so the check is what makes that promise hold for a pack's own declarations. This decision fixes what the surface is in published bytes, where and against what the comparison runs, the classes, when `R033` refuses, and how the check meets pinned imports, deprecation and the one-time Rezono 1 migration. [Publisher](../edge/publisher/rezono_publisher/publish.py) · [Schema bundle](../contracts/bundle.yaml) · [Publication L0, change classes](../docs/publication/l0.md#24-change-classes)

## 1. The public surface

The public surface of a pack is every declaration visible to other packs, each with its type, cardinality, world, reader label, effect class and totality (v0 §4c, §5d). The check reads it from the compiled schema bundle (`bundle/schema-bundle.json`, [contract](../contracts/bundle.yaml)), never from source text: what is compared is what was published and what will be published, in the form readers read.

| Element | Its id in the bundle | Compared |
| --- | --- | --- |
| kind | `kinds[].id` | parent, abstract, identifier, its type and patterns, world, plane, relationship ends, IRI |
| slot (arrow or attribute) | `arrows[].id`, `attributes[].id`, written `<kind>.<slot>` | type (`semantic`, `type`, `schema_type`, `target`, `enum`, `currency`, `input_format`, `derivation`), cardinality (`required`, `multivalued`, `minimum_cardinality`, `maximum_cardinality`), world, refinements (`minimum`, `maximum`, `patterns`, `constant`) |
| enum and its values | `enums[].id`, `enums[].values[]`, written `<enum>.<value>` | the values; whether the enum is open |
| derived relation | `relations[].id` | its columns and their types, its world |
| check | `checks[]` | that it is there |
| pack | `pack.base`, `kinds[].iri`, `reasons[]` | the base, each namespace and each reason code |

- **Identity.** An element is matched by its id. A kind or slot whose `stable_id` the earlier bundle has under another id is renamed; the bundle records its first name in `renamed_from` (contracts/bundle.yaml, `stable_id` and `renamed_from` of `Kind` and `Slot`).
- **Rules.** A rule is compared through the relation it derives. Its body, its runtime id and its stable id are not surface: the runtime id renumbers when a rule is added, and what a rule derives from facts is data, held by the proofs.
- **Enum world.** The bundle carries an enum's openness only on the slots that take it (`semantic.open`, contracts/bundle.yaml `SemanticType`), so closing or opening an enum is reported on each such slot.
- **Not surface.** Spans, sentences, labels, messages, channels, pages, the kind order, questions and reader questions: text and layout for people. Doc comments do not reach the bundle at all.
- **What the bundle does not carry yet.** The reader label (`may_read`, v0 §7 item 7), the effect class and the totality (§5d), the `private` mark of a Rezono declaration and the interfaces of `modules:` in pack.yaml, a deprecation (section 6) and parameter versions. Each is compared from the step in which the compiler writes it into the bundle. Until the bundle marks what is private, every element of the bundle counts as public: over-strict, never too lax.
- **A property the earlier bundle does not carry is not compared:** it was never published, so nothing was promised. A compiler that starts to write a new property therefore changes no class. A property the later bundle drops is a change.
- **Imported modules.** The bundle also holds the modules of the packs this pack imports (`schemas`, `imports`). They are compared too, because the pack publishes rows of their kinds; a change names the module it comes from (section 7).

## 2. Where and against what

- **At publication, in `edge/publisher`, before anything is written.** `publish.plan` runs the check for a main publication: no proposal, no variant and no base manifest. A proposal and a variant carry the facts of their base on the base's definition, so they change no surface.
- **Against the newest main manifest**, found as the gate finds it: `publish.newest_main`, the first key under `<pack>/heads/`. Its bundle is the manifest's `compiled` entry for `bundle/schema-bundle.json`, stored at `<pack>/bundles/<definition_sha256>/<compiler_sha256>.json`. The check reads it through the uri that entry names and holds it to the entry's `sha256`, as every reader does.
- **No earlier main manifest:** the first publication. There is nothing to compare, and it publishes.
- **The same `definition_sha256` and `compiler_sha256`:** the same bundle. There is nothing to compare; this is the common case of a publication with new facts only.
- **Fail closed.** A head that is not a head, or a bundle whose bytes do not have the listed hash, is an error and nothing is written. It is not read as "no earlier publication". This differs on purpose from `reuse`, where a broken head only means that every object is written again.
- **Deterministic.** Two bundles in, one class and a sorted list of changes out. A date is compared with the day of the new epoch's knowledge time, never with a clock (AGENTS.md rule 3).
- **Interface.** `rezono_publisher/surface.py` has `compare(before, after)`: two parsed schema bundles in, `{"class": …, "changes": [...]}` out. Each change is `{"element", "change", "class"}`, and the list is sorted by element, then change. `publish.compatibility(epoch, store)` gives `{"against": <manifest id>, "class": …, "changes": [...]}` for a main publication with an earlier main manifest, and `None` otherwise. `plan` refuses on its result.
- **The manifest records nothing new in this step.** Recording the class in the manifest changes the manifest contract and what the gate reads; that is a step of its own (open points).

## 3. The classes

Every change of the surface is one of these. A change names the element by its id in the earlier bundle, and an added element by its new id.

| `change` | What changed | Class |
| --- | --- | --- |
| `added` | a kind, a single-valued slot or a `*` slot, an enum, a value of an open enum, a derived relation, a check, a reason code | minor |
| `added` | a value of a closed enum; a `+` slot | major |
| `widened` | a refinement or type admits more: a lower minimum, a higher maximum, a pattern or a constant dropped | minor |
| `removed` | a kind, slot, enum, enum value, derived relation, check or reason code | major |
| `renamed` | a kind or slot under the same stable id | major |
| `retyped` | the type of a slot or a column | major |
| `narrowed` | a refinement or type admits less | major |
| `cardinality` | `required`, `multivalued`, `minimum_cardinality` or `maximum_cardinality` | major |
| `closed` | an open world or an open enum becomes closed | major |
| `opened` | a closed world or a closed enum becomes open | major |
| `changed` | any other compared property: parent, abstract, identifier, plane, IRI, base, the states of a reason code | major |

- **Patch** is a publication in which no element of the surface changes: doc comments, messages, labels, reason labels, source references, spans and channels. Its `changes` list is empty.
- **The class of a publication** is the highest class of its changes, in the order patch < minor < major, and patch when there are none.
- **What the table of §4c does not name is major.** Correctness blocks (AGENTS.md rule 5): a change nobody classified is not known to be safe. This is why opening a closed world or enum, adding a value to a closed enum and every unlisted property change are major.
- **An added slot needs a declared state for old rows** (§4c). A single-valued slot declares it by its cardinality: a missing `T` is `unknown` and a missing `T?` is `n/a` (v0 §5, kinds and slots). A `T*` slot gives an old row the empty set. A `T+` slot can give an old row no state that holds, so adding one is major. Whether the old rows still pass the pack's own checks, such as the totality check of a required slot, is for those checks to decide, not this one.
- **The same classes as publication L0.** [Publication L0](../docs/publication/l0.md#24-change-classes), section 2.4, classifies the change between two published schema documents, and `rezono_publication.l0.classify` implements it. Where both speak they agree: a kind or slot added is minor, removed is major, a widened bound is minor, a value appended to an open enumeration is minor, any other change to a slot, a kind member, an enumeration, a base or a reason code's states is major, and a reason label is a patch. One difference remains. L0 calls a slot added without a `backfill` an invalid successor, and `rezono_publication.publication.schema_document` writes no `backfill` yet. The state that a slot's cardinality declares (above) is that backfill, with the core reason `added_later`. The role forms write it for a slot their earlier form lacks, in their own step. Until then, an added slot is minor here and an invalid successor to a reader of the L0 forms.

## 4. R033

- **A major change refuses the publication.** `plan` raises `Blocked` before anything is written, with `R033` and the first major change, for example `R033 alpha.size removed: a breaking change needs a reviewed proposal (docs/rezono/v0.md §4c)`. No manifest, head or object of the new epoch is written.
- **Unless an accepted proposal with an impact assessment names it** (section 5).
- **The promise starts at version 1.0.0 of the pack.** `R033` applies when the earlier publication promised a stable surface: its pack version (`pack.version` in the bundle, from pack.yaml, a semantic version per contracts/pack.yaml) is 1.0.0 or later. A pack at 0.y.z is in initial development, as Semantic Versioning item 4 says: the check computes and reports the class and refuses nothing. Every pack in the repository is at 0.y.z today, so no publication is refused until an owner declares a pack stable. A pack owner opts in by publishing 1.0.0. This answers "does Rezono need API versions like Kubernetes": the language version says how a text is read, the pack version says whether its surface is promised, and the class of each publication says what changed.
- **A deprecation date binds every pack** (section 6), whatever its version: its owner wrote that promise on purpose.

## 5. An accepted proposal with an impact assessment

This decision fixes what an acceptance must say. Its file form follows in its own step, with its own red test.

- It names the proposal that accepts the change, which is the reviewed pull request, and the main manifest whose surface it breaks. So it accepts the changes of one publication and never a later one.
- It names exactly the major changes that `compare` reports, by element and change. A major change it does not name is still `R033`. An acceptance that names a change that does not occur is an error: a stale acceptance accepts nothing.
- Its impact assessment names each pack known to import this one (pinned in that pack's `pack.yaml`) and whether that pack is unaffected, re-pins without a change, or changes with it. It also names the mapping view that carries old data to the new schema: §4c says "the data then gets a new schema with a mapping view".
- It is part of the pack's definition and is read before it lands, like the paths of the [checker and access review](checker-and-access-review.md): a green check alone does not accept a breaking change.

Until that step lands, a major change cannot be published on a pack at 1.0.0 or later. No pack is there yet.

## 6. Deprecation

- **Spelling and lowering** are settled by the [deprecated declarations decision](language-deprecation.md): a line `deprecated "…" until <date>` above a kind or an enum, lowered to the LinkML `deprecated` text and the annotation `deprecated_until`. The bundle does not carry it yet. It gets `deprecated` and `deprecated_until` on `Kind` and `PackEnum`, an additive extension of contracts/bundle.yaml, in its own step.
- **Where W107 stands.** The reader raises W107 today for a schema header line that writes its default (`rezono/src/module-metadata.ts`, listed in `rezono/src/module.ts`), with the message "`{0}` is deprecated". The W107 of v0 §4b and §10 is a different warning: a use from another pack of a declaration that is deprecated, with its note and its date. That one is not built. The compiler does warn, without a code, at a use of an element that a module interface in pack.yaml marks `deprecated` (`compiler/rezono_compiler/modules.py`). That date is the day from which the element is deprecated, while the Rezono line's date is the day until which it stays. The two meanings of W107, and the two meanings of the date, are open points below.
- **Adding a deprecation is a patch:** it changes nothing in the meaning of the declaration. Moving its date earlier is major. Moving it later, or removing the line, is a patch.
- **Removal before the date is `R033`, for every pack, and no acceptance lifts it** (v0 §4b). The date is a promise to the packs that read the note. The date is compared with the day of the new epoch's knowledge time.
- **Removal on or after the date is a major change** (v0 §4b), and the deprecation published over the whole window stands in for its acceptance: the note was reviewed and published, and every use from another pack was warned. It publishes without an acceptance of its own and is reported as major. This reads the [deprecated declarations decision](language-deprecation.md) ("a day after which removal is a minor change") as "publishes without a proposal", and v0 §4b as "is still recorded as a major change".
- **Only a published deprecation counts:** one the earlier bundle carries. A deprecation added in the same publication that removes the element does not.

## 7. Pinned imports

- An import is pinned on the SHA-256 of the imported pack's files (contracts/pack.yaml, `PackImport`). Any change of the imported pack, even a patch, changes that hash, and the compiler refuses the old pin. So a pack never takes a change it did not choose: it re-pins (for a fixture pack, see the [fixture pin update](fixture-pin-update.md)).
- The pin says whether something changed. The class says what a re-pin brings: after a patch or a minor change the importer needs no change of its own, and after a major change it may break, which is why an acceptance names it.
- The check runs at the imported pack's own publication. It cannot see packs that import it from outside the repository, so the acceptance names the ones its owner knows.
- An importing pack's bundle holds its imports' modules. A re-pin that brings a major change of an imported element is therefore a major change of the importing pack's publication too, named with the element's module (`<pack>:<path>`). The importing pack publishes rows of those kinds.
- The Rezono 1 decision already asks the same of a cross-pack consumer ([section 5.5](language-rezono-1.md#5-cross-module-readers-acceptance-tests-oraclepy-and-the-external-reader-contract)): an imported pack must not silently remove a public relation that downstream packs read. The check makes "silently" impossible for a pack at 1.0.0 or later.

## 8. The Rezono 1 migration is not blocked by R033

- The migration converts each pack's `.dl` files and `rules` blocks once, directly to `rezono 1` ([Rezono 1, section 6](language-rezono-1.md#6-single-pass-rule-conversion-and-readiness-gate)). It renames, reshapes and retires relations. For `examples/platform/rules/core.dl`, the [intended differences table](language-rezono-1.md#7-per-derivation-intended-semantic-differences-for-examplesplatformrulescoredl) lists every intended semantic difference and every bundle relation name change, such as `zone_of` becoming `service_zone`. Section 5.5 gives the external-reader contract.
- By section 3 these are major changes: relations removed, renamed and retyped. **R033 does not refuse them.** A publication whose bundle records a higher language version than the earlier publication's bundle is a language migration. The bundle records the pack's declared language version, `"0"` or `"1"` (Rezono 1, section 5.8 and rollout step 2). For a language migration the check computes and reports the class, and `R033` does not apply. Its impact assessment is the intended differences table together with the migration equivalence test ([migration equivalence](language-expression-semantics.md#4-migration-equivalence)), which compares every derived result with the legacy pack and fails on any difference the table does not list. Pinned importers are carried by the rule of section 5.5.
- Only the change of language version earns this. A migration publication carries the migration and nothing else; the equivalence test holds its converted rule files to that.
- From the next publication on, `rezono 1` to `rezono 1`, `R033` applies as in section 4. A later language version needs a decision of its own.
- Every pack is at 0.y.z today, so section 4 refuses nothing during the migration anyway. This section fixes the rule for a pack that reaches 1.0.0 before it converts, and makes clear that the check is no reason to hold the migration back.

## 9. What follows

The red tests in `edge/publisher/tests/test_surface_compatibility.py` take their expectations from the table of v0 §4c, on the minimal, domain-free fixture pack. Each builds on the one before.

1. `test_compare_classifies_each_change_as_section_4c_does`: `surface.compare` on compiled bundles. An added optional slot and a widened bound are minor. A removed, renamed or retyped slot and a changed cardinality are major. Closing an open enum is major and adding a value to it is minor. Doc, message and label edits are patch.
2. `test_compatibility_names_the_class_against_the_newest_main`: `publish.compatibility` against the newest main manifest. A minor and then a patch change publish on a pack at 1.0.0.
3. `test_a_removed_or_renamed_public_slot_is_refused_with_r033`: on a pack at 1.0.0 the publisher refuses both with `R033`, names the slot and writes nothing. On a pack at 0.1.0 the same removal publishes.

Later steps, each with its own test when it is taken up: the acceptance file of section 5; the bundle carrying deprecation, `private`, the reader label, the effect class, the totality and the language version; the role forms writing `backfill`; and recording the class in the manifest.

## Open points

1. **Which packs `R033` binds.** This decision gates on the earlier publication's pack version, 1.0.0 or later. Alternatives: from `rezono 1` on (the language's stability commitment, v0 §4b), or for every pack.
2. **The acceptance file** of section 5: where it lives, its format, and whether its path joins the paths read before landing.
3. **The pack version and the class.** Whether a publication's pack version must move at least as far as its class: a new major for an accepted major change, a new minor for a minor one.
4. **Strengthening changes.** `partial` to `total`, a lower effect class and opening a world are strictly safer for some readers. This decision keeps them major (fail closed) until someone classifies them.
5. **W107 and the deprecation date.** W107 has two meanings today (section 6), and the date of a module interface in pack.yaml means "from" while the date of a Rezono line means "until". One meaning each should remain.
6. **The milestone** of the red tests: `extra:` here. `M3` would tie them to the Rezono 1 release.

## Considered

- **Classify the two L0 schema documents with `rezono_publication.l0.classify`.** It is built and has conformance cases, so it would be the smallest code. It does not do for the whole check: `schema_document` is a projection for data readers that drops enum openness, renames, deprecation and, later, the effect class, totality and reader label. It refuses (`FormError`) a bundle L0 cannot express yet, so such packs would have nothing to compare. It also turns every added slot into an invalid successor while no `backfill` is written. The classes are held to agree with it instead (section 3).
- **Compare source text or module forms.** Rejected: the bundle is what was published and what readers read, the source of the earlier publication may be gone, and the bundle's path already names the definition and the compiler.
- **Keep the last surface as a committed file and compare at compile time.** Rejected: generated output stays out of Git (AGENTS.md), and a committed copy drifts from what was published.
- **Gate `R033` on `rezono 1`.** The language's stability commitment starts there, and the Rezono 1 decision kept W107 out of `rezono 0` for that reason. Rejected as the default: the language version says how a text is read, not whether its owner promises its surface; a pack on `rezono 1` may still be in development; and no bundle records the language version yet, so the check could not be built and tested now. The maintainer may choose it instead (open point 1).
- **No gate: refuse a major change on every pack.** Rejected for now: every pack is at 0.y.z and the acceptance path does not exist yet, so the first rename in an example would stop its publication.
- **A rename as a removal plus an addition.** Rejected: the bundle records the rename through its stable id, so the refusal can say what happened. The class is the same.
- **An unlisted change as minor.** Rejected: correctness blocks.
