# Rezono language coverage

Run `python compiler/tests/rezono/language_usage.py` from the repository root for the current inventory.
Counts use each authored file once per feature. Higher counts give higher priority among available tasks.
Support requires the applicable reader, form and lowering tests without expected-failure markers.
Pack readiness includes transitive local imports.
Mixed conversion uses legacy pipe blocks. Native conversion uses typed rules.
Native conversion requires reader, form, IR, signature and publication evidence. Review explicit state predicates.

| Feature | Files | Reader and lowering |
| --- | ---: | --- |
| relational-rule | 80 | Supported ([reader](../../rezono/test/test_relational_rule_block.py), [lowering](../../compiler/tests/rezono/test_rule_witness.py)) |
| kind | 58 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| schema-metadata | 56 | Pending |
| slot | 54 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| fact-table | 44 | Pending |
| named-dataset | 43 | Pending |
| reference | 36 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| extended-scalar | 33 | Pending |
| enum | 29 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| optional-slot | 25 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| numeric-limit | 23 | Supported ([reader](../../rezono/test/test_numeric_limits.py), [lowering](../../compiler/tests/rezono/test_lower_numeric_limits.py)) |
| fact-provenance | 13 | Pending |
| conditional-check | 9 | Pending |
| enum-metadata | 9 | Pending |
| repeated-slot | 9 | Pending |
| parent-kind | 8 | Supported ([reader](../../rezono/test/test_parent_kind.py), [lowering](../../compiler/tests/rezono/test_lower_parent_kind.py)) |
| scalar-alias | 8 | Supported ([reader](../../rezono/test/test_scalar_alias.py), [lowering](../../compiler/tests/rezono/test_lower_scalar_alias.py)) |
| slot-pattern | 8 | Pending ([reader](../../rezono/test/test_slot_pattern.py), [lowering](../../compiler/tests/rezono/test_lower_slot_pattern.py)) |
| structured-fact | 7 | Pending |
| abstract-kind | 6 | Supported ([reader](../../rezono/test/test_abstract_kind.py), [lowering](../../compiler/tests/rezono/test_lower_abstract_kind.py)) |
| calculation | 4 | Pending |
| time-policy | 4 | Pending |
| composite-key | 3 | Supported ([reader](../../rezono/test/test_composite_key.py), [lowering](../../compiler/tests/rezono/test_lower_composite_key.py)) |
| open-world | 3 | Pending |
| rule-metadata | 3 | Pending |
| embedded-kind | 2 | Supported ([reader](../../rezono/test/test_embedded_kind.py), [lowering](../../compiler/tests/rezono/test_lower_embedded_kind.py)) |
| embedded-reference | 2 | Supported ([reader](../../rezono/test/test_embedded_relation.py), [lowering](../../compiler/tests/rezono/test_lower_embedded_reference.py)) |
| module-import | 2 | Pending |
| parameters | 2 | Pending |
| path-equation | 2 | Supported ([reader](../../rezono/test/test_path_equation.py), [lowering](../../compiler/tests/rezono/test_lower_path_equation.py)) |
| boolean-slot | 1 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/rezono/test_library_boolean.py)) |
| bounded-slot | 1 | Supported ([reader](../../rezono/test/test_bounded_slot.py), [lowering](../../compiler/tests/rezono/test_lower_bounded_list.py)) |
| dated-fact | 1 | Pending |
| decision-table | 1 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_table.py)) |
| exceptions | 1 | Pending |
| explicit-identifier | 1 | Supported ([reader](../../rezono/test/test_explicit_identifier.py), [lowering](../../compiler/tests/rezono/test_lower_explicit_identifier.py)) |
| inverse-reference | 1 | Pending |
| relationship-kind | 1 | Pending |
| table-policy | 1 | Pending |
| unclassified-authored-syntax | 1 | Pending |
| units | 1 | Pending |

| Pack or source directory | Direct features | Imported features | Pending features | Mixed conversion | Native conversion |
| --- | --- | --- | --- | --- | --- |
| examples/library | abstract-kind, boolean-slot, bounded-slot, composite-key, conditional-check, embedded-kind, embedded-reference, enum, explicit-identifier, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, parent-kind, path-equation, reference, repeated-slot, schema-metadata, slot, slot-pattern, structured-fact | — | conditional-check, extended-scalar, fact-table, named-dataset, repeated-slot, schema-metadata, slot-pattern, structured-fact | Pending: conditional-check, extended-scalar, fact-table, named-dataset, repeated-slot, schema-metadata, slot-pattern, structured-fact | Pending: conditional-check, extended-scalar, fact-table, named-dataset, repeated-slot, schema-metadata, slot-pattern, structured-fact |
| examples/platform | abstract-kind, enum, enum-metadata, extended-scalar, fact-provenance, fact-table, kind, named-dataset, numeric-limit, optional-slot, parent-kind, reference, relational-rule, repeated-slot, scalar-alias, schema-metadata, slot, slot-pattern, structured-fact | abstract-kind, composite-key, conditional-check, enum, enum-metadata, extended-scalar, fact-table, kind, named-dataset, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot | conditional-check, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, open-world, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot-pattern, structured-fact | Pending: conditional-check, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, open-world, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot-pattern, structured-fact | Pending: conditional-check, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, native-rule-publication-parity, open-world, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot-pattern, structured-fact |
| examples/platform/tenant-capacity/interface | extended-scalar, fact-table, kind, named-dataset, numeric-limit, relational-rule, schema-metadata, slot | — | extended-scalar, fact-table, named-dataset, schema-metadata | Pending: extended-scalar, fact-table, named-dataset, schema-metadata | Pending: extended-scalar, fact-table, named-dataset, native-rule-publication-parity, schema-metadata |
| examples/projects | composite-key, enum, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, path-equation, reference, scalar-alias, schema-metadata, slot, structured-fact | — | extended-scalar, fact-table, named-dataset, schema-metadata, structured-fact | Pending: extended-scalar, fact-table, named-dataset, schema-metadata, structured-fact | Pending: extended-scalar, fact-table, named-dataset, schema-metadata, structured-fact |
| examples/subsidy | calculation, conditional-check, embedded-kind, embedded-reference, enum, enum-metadata, extended-scalar, fact-provenance, fact-table, kind, named-dataset, numeric-limit, optional-slot, reference, relational-rule, repeated-slot, scalar-alias, schema-metadata, slot, structured-fact, time-policy | abstract-kind, calculation, composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, parameters, parent-kind, reference, relational-rule, relationship-kind, repeated-slot, rule-metadata, scalar-alias, schema-metadata, slot, slot-pattern, time-policy | calculation, conditional-check, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, open-world, parameters, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot-pattern, structured-fact, time-policy | Pending: calculation, conditional-check, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, open-world, parameters, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot-pattern, structured-fact, time-policy | Pending: calculation, conditional-check, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, native-rule-publication-parity, open-world, parameters, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot-pattern, structured-fact, time-policy |
| examples/subsidy-scheme | calculation, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, parameters, parent-kind, reference, relational-rule, scalar-alias, schema-metadata, slot, slot-pattern, time-policy | composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, schema-metadata, slot | calculation, conditional-check, enum-metadata, extended-scalar, open-world, parameters, relationship-kind, repeated-slot, schema-metadata, slot-pattern, time-policy | Pending: calculation, conditional-check, enum-metadata, extended-scalar, open-world, parameters, relationship-kind, repeated-slot, schema-metadata, slot-pattern, time-policy | Pending: calculation, conditional-check, enum-metadata, extended-scalar, native-rule-publication-parity, open-world, parameters, relationship-kind, repeated-slot, schema-metadata, slot-pattern, time-policy |
| examples/zorgtoeslag | calculation, dated-fact, decision-table, enum, exceptions, extended-scalar, fact-table, inverse-reference, kind, module-import, optional-slot, parameters, repeated-slot, schema-metadata, slot, table-policy, time-policy, unclassified-authored-syntax, units | — | calculation, dated-fact, exceptions, extended-scalar, fact-table, inverse-reference, module-import, parameters, repeated-slot, schema-metadata, table-policy, time-policy, unclassified-authored-syntax, units | No owning pack | No owning pack |
| packs/std-access | enum, enum-metadata, kind, optional-slot, relational-rule, repeated-slot, schema-metadata, slot | — | enum-metadata, repeated-slot, schema-metadata | Pending: enum-metadata, repeated-slot, schema-metadata | Pending: enum-metadata, native-rule-publication-parity, repeated-slot, schema-metadata |
| packs/std-decision | composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, schema-metadata, slot | — | conditional-check, enum-metadata, extended-scalar, open-world, relationship-kind, repeated-slot, schema-metadata | Pending: conditional-check, enum-metadata, extended-scalar, open-world, relationship-kind, repeated-slot, schema-metadata | Pending: conditional-check, enum-metadata, extended-scalar, native-rule-publication-parity, open-world, relationship-kind, repeated-slot, schema-metadata |
| packs/std-explain | — | — | No language sources | No language sources | No language sources |
| packs/std-identity | abstract-kind, conditional-check, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | conditional-check, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, native-rule-publication-parity, repeated-slot, rule-metadata, schema-metadata |
| packs/std-loop | enum, extended-scalar, kind, numeric-limit, optional-slot, parent-kind, reference, relational-rule, schema-metadata, slot | abstract-kind, conditional-check, extended-scalar, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | conditional-check, extended-scalar, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, extended-scalar, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, extended-scalar, native-rule-publication-parity, repeated-slot, rule-metadata, schema-metadata |
| packs/std-order | abstract-kind, conditional-check, extended-scalar, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | conditional-check, extended-scalar, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, extended-scalar, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, extended-scalar, native-rule-publication-parity, repeated-slot, rule-metadata, schema-metadata |
| packs/std-part | abstract-kind, conditional-check, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, schema-metadata, slot | — | conditional-check, extended-scalar, schema-metadata | Pending: conditional-check, extended-scalar, schema-metadata | Pending: conditional-check, extended-scalar, native-rule-publication-parity, schema-metadata |
| packs/std-time | abstract-kind, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | conditional-check, enum-metadata, extended-scalar, open-world, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, enum-metadata, extended-scalar, open-world, repeated-slot, rule-metadata, schema-metadata | Pending: conditional-check, enum-metadata, extended-scalar, native-rule-publication-parity, open-world, repeated-slot, rule-metadata, schema-metadata |
| packs/std-view | — | — | No language sources | No language sources | No language sources |
| run/packs/cleanup | enum, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/cleanup-deadline | enum, extended-scalar, kind, optional-slot, relational-rule, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/dispatch | enum, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/exact-quote | enum, extended-scalar, kind, numeric-limit, reference, relational-rule, slot | — | extended-scalar | Pending: extended-scalar | Pending: extended-scalar, native-rule-publication-parity |
| run/packs/invoice-drift | enum, extended-scalar, kind, numeric-limit, optional-slot, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/offer-selection | enum, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, reference, relational-rule, schema-metadata, slot | — | extended-scalar, fact-table, named-dataset, schema-metadata | Pending: extended-scalar, fact-table, named-dataset, schema-metadata | Pending: extended-scalar, fact-table, named-dataset, native-rule-publication-parity, schema-metadata |

## Native rules in module form 3

The expression syntax and migration are specified in the language decision. [Native rules decision](../../decisions/language-native-rules.md)
The rule census includes 80 distinct source files, with 80 using Datalog or interim pipes and 0 using native rules.
A mixed file counts once in the total and in each spelling it uses.
Native reader, form and IR proof gate: **Supported** ([reader](../../rezono/test/test_native_rule_reader_roundtrip.py), [form](../../compiler/tests/rezono/test_native_rule_form_contract.py), [IR and witness](../../compiler/tests/rezono/test_native_rule_ir_listed.py)).
This gate covers initial integration. Whole-pack migration also requires [signature linking](../../compiler/tests/rezono/test_native_rule_signatures.py) and [publication parity](../../compiler/tests/rezono/test_native_rule_publication_parity.py).

An explicit state predicate needs a review of its evidence. Keep the legacy rule where a general scalar state lacks authenticated evidence. [state-evidence test](../../compiler/tests/rezono/test_native_rule_state_evidence.py)
The census cannot infer general state checks from a legacy file. Ordinary relation negation and explicit outcome values are separate.
No pack has a confirmed general state blocker in this census.

| Pack or source directory | Direct legacy files | Direct native files | General state evidence |
| --- | ---: | ---: | --- |
| examples/platform | 38 | 0 | Unknown until legacy conversion |
| examples/platform/tenant-capacity/interface | 1 | 0 | Unknown until legacy conversion |
| examples/subsidy | 4 | 0 | Unknown until legacy conversion |
| examples/subsidy-scheme | 4 | 0 | Unknown until legacy conversion |
| packs/std-access | 1 | 0 | Unknown until legacy conversion |
| packs/std-decision | 1 | 0 | Unknown until legacy conversion |
| packs/std-identity | 1 | 0 | Unknown until legacy conversion |
| packs/std-loop | 18 | 0 | Unknown until legacy conversion |
| packs/std-order | 1 | 0 | Unknown until legacy conversion |
| packs/std-part | 1 | 0 | Unknown until legacy conversion |
| packs/std-time | 1 | 0 | Unknown until legacy conversion |
| run/packs/cleanup | 2 | 0 | Unknown until legacy conversion |
| run/packs/cleanup-deadline | 1 | 0 | Unknown until legacy conversion |
| run/packs/dispatch | 1 | 0 | Unknown until legacy conversion |
| run/packs/exact-quote | 1 | 0 | Unknown until legacy conversion |
| run/packs/invoice-drift | 2 | 0 | Unknown until legacy conversion |
| run/packs/offer-selection | 2 | 0 | Unknown until legacy conversion |
