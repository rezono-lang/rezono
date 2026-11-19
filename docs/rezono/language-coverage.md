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
| schema-metadata | 56 | Pending ([reader](../../rezono/test/test_schema_metadata.py), [reader](../../rezono/test/test_schema_mappings.py), [lowering](../../compiler/tests/rezono/test_lower_schema_metadata.py), [lowering](../../compiler/tests/rezono/test_lower_schema_mappings.py), [lowering](../../compiler/tests/rezono/test_lower_schema_annotations.py)) |
| slot | 54 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| fact-table | 44 | Pending ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/rezono/test_lower_fact_table.py)) |
| named-dataset | 43 | Supported ([reader](../../rezono/test/test_named_dataset.py), [lowering](../../compiler/tests/rezono/test_named_dataset_discovery.py)) |
| reference | 36 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| extended-scalar | 33 | Pending ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/rezono/test_lower_extended_scalar.py)) |
| enum | 29 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| optional-slot | 26 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| numeric-limit | 23 | Supported ([reader](../../rezono/test/test_numeric_limits.py), [lowering](../../compiler/tests/rezono/test_lower_numeric_limits.py)) |
| fact-provenance | 13 | Pending ([reader](../../rezono/test/test_fact_provenance.py), [lowering](../../compiler/tests/rezono/test_lower_fact_provenance.py)) |
| conditional-check | 10 | Supported ([reader](../../rezono/test/test_conditional_check.py), [lowering](../../compiler/tests/rezono/test_lower_conditional_check.py)) |
| enum-metadata | 9 | Supported ([reader](../../rezono/test/test_schema_metadata.py), [lowering](../../compiler/tests/rezono/test_lower_enum_metadata.py)) |
| repeated-slot | 9 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| parent-kind | 8 | Supported ([reader](../../rezono/test/test_parent_kind.py), [lowering](../../compiler/tests/rezono/test_lower_parent_kind.py)) |
| scalar-alias | 8 | Supported ([reader](../../rezono/test/test_scalar_alias.py), [lowering](../../compiler/tests/rezono/test_lower_scalar_alias.py)) |
| slot-pattern | 8 | Supported ([reader](../../rezono/test/test_slot_pattern.py), [lowering](../../compiler/tests/rezono/test_lower_slot_pattern.py)) |
| structured-fact | 7 | Pending ([reader](../../rezono/test/test_structured_fact.py), [lowering](../../compiler/tests/rezono/test_structured_library_dataset.py)) |
| abstract-kind | 6 | Supported ([reader](../../rezono/test/test_abstract_kind.py), [lowering](../../compiler/tests/rezono/test_lower_abstract_kind.py)) |
| calculation | 4 | Pending ([reader](../../rezono/test/test_calculation.py), [lowering](../../compiler/tests/rezono/test_lower_calculation.py)) |
| open-world | 4 | Pending ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/rezono/test_lower_open_world.py)) |
| time-policy | 4 | Pending ([reader](../../rezono/test/module-json.test.ts), [reader](../../rezono/test/test_time_policy.py), [lowering](../../compiler/tests/rezono/test_lower_time_policy.py)) |
| composite-key | 3 | Supported ([reader](../../rezono/test/test_composite_key.py), [lowering](../../compiler/tests/rezono/test_lower_composite_key.py)) |
| rule-metadata | 3 | Supported ([reader](../../rezono/test/test_rule_metadata.py), [lowering](../../compiler/tests/rezono/test_lower_rule_metadata.py)) |
| embedded-kind | 2 | Supported ([reader](../../rezono/test/test_embedded_kind.py), [lowering](../../compiler/tests/rezono/test_lower_embedded_kind.py)) |
| embedded-reference | 2 | Supported ([reader](../../rezono/test/test_embedded_relation.py), [lowering](../../compiler/tests/rezono/test_lower_embedded_reference.py)) |
| module-import | 2 | Pending ([reader](../../rezono/test/test_module_import.py), [lowering](../../compiler/tests/rezono/test_lower_module_import.py)) |
| parameters | 2 | Pending ([reader](../../rezono/test/test_parameters.py), [reader](../../rezono/test/test_version_replaces.py), [lowering](../../compiler/tests/rezono/test_lower_parameters.py)) |
| path-equation | 2 | Supported ([reader](../../rezono/test/test_path_equation.py), [lowering](../../compiler/tests/rezono/test_lower_path_equation.py)) |
| boolean-slot | 1 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/rezono/test_library_boolean.py)) |
| bounded-slot | 1 | Supported ([reader](../../rezono/test/test_bounded_slot.py), [lowering](../../compiler/tests/rezono/test_lower_bounded_list.py)) |
| dated-fact | 1 | Pending ([reader](../../rezono/test/test_dated_fact.py), [reader](../../rezono/test/test_fact_context_axes.py), [lowering](../../compiler/tests/rezono/test_lower_dated_fact.py)) |
| decision-table | 1 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_table.py)) |
| exceptions | 1 | Pending ([reader](../../rezono/test/test_exceptions.py), [lowering](../../compiler/tests/rezono/test_lower_exceptions.py)) |
| explicit-identifier | 1 | Supported ([reader](../../rezono/test/test_explicit_identifier.py), [lowering](../../compiler/tests/rezono/test_lower_explicit_identifier.py)) |
| inverse-reference | 1 | Pending ([reader](../../rezono/test/test_inverse_reference.py), [lowering](../../compiler/tests/rezono/test_lower_inverse_reference.py)) |
| relationship-kind | 1 | Pending ([reader](../../rezono/test/test_relationship_kind.py), [lowering](../../compiler/tests/rezono/test_lower_relationship_kind.py)) |
| table-policy | 1 | Pending ([reader](../../rezono/test/test_table_policy.py), [lowering](../../compiler/tests/rezono/test_lower_table_policy.py), [lowering](../../compiler/tests/rezono/test_lower_table_policy.py)) |
| units | 1 | Pending ([reader](../../rezono/test/test_units.py), [reader](../../rezono/test/test_unit_definition.py), [lowering](../../compiler/tests/rezono/test_lower_units.py)) |

| Pack or source directory | Direct features | Imported features | Pending features | Mixed conversion | Native conversion |
| --- | --- | --- | --- | --- | --- |
| examples/library | abstract-kind, boolean-slot, bounded-slot, composite-key, conditional-check, embedded-kind, embedded-reference, enum, explicit-identifier, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, parent-kind, path-equation, reference, repeated-slot, schema-metadata, slot, slot-pattern, structured-fact | — | extended-scalar, fact-table, schema-metadata, structured-fact | Pending: extended-scalar, fact-table, schema-metadata, structured-fact | Pending: extended-scalar, fact-table, schema-metadata, structured-fact |
| examples/platform | abstract-kind, enum, enum-metadata, extended-scalar, fact-provenance, fact-table, kind, named-dataset, numeric-limit, open-world, optional-slot, parent-kind, reference, relational-rule, repeated-slot, scalar-alias, schema-metadata, slot, slot-pattern, structured-fact | abstract-kind, composite-key, conditional-check, enum, enum-metadata, extended-scalar, fact-table, kind, named-dataset, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot | extended-scalar, fact-provenance, fact-table, open-world, relationship-kind, schema-metadata, structured-fact | Pending: extended-scalar, fact-provenance, fact-table, open-world, relationship-kind, schema-metadata, structured-fact | Pending: extended-scalar, fact-provenance, fact-table, native-rule-publication-parity, open-world, relationship-kind, schema-metadata, structured-fact |
| examples/platform/tenant-capacity/interface | extended-scalar, fact-table, kind, named-dataset, numeric-limit, relational-rule, schema-metadata, slot | — | extended-scalar, fact-table, schema-metadata | Pending: extended-scalar, fact-table, schema-metadata | Pending: extended-scalar, fact-table, native-rule-publication-parity, schema-metadata |
| examples/projects | composite-key, enum, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, path-equation, reference, scalar-alias, schema-metadata, slot, structured-fact | — | extended-scalar, fact-table, schema-metadata, structured-fact | Pending: extended-scalar, fact-table, schema-metadata, structured-fact | Pending: extended-scalar, fact-table, schema-metadata, structured-fact |
| examples/subsidy | calculation, conditional-check, embedded-kind, embedded-reference, enum, enum-metadata, extended-scalar, fact-provenance, fact-table, kind, named-dataset, numeric-limit, optional-slot, reference, relational-rule, repeated-slot, scalar-alias, schema-metadata, slot, structured-fact, time-policy | abstract-kind, calculation, composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, parameters, parent-kind, reference, relational-rule, relationship-kind, repeated-slot, rule-metadata, scalar-alias, schema-metadata, slot, slot-pattern, time-policy | calculation, extended-scalar, fact-provenance, fact-table, open-world, parameters, relationship-kind, schema-metadata, structured-fact, time-policy | Pending: calculation, extended-scalar, fact-provenance, fact-table, open-world, parameters, relationship-kind, schema-metadata, structured-fact, time-policy | Pending: calculation, extended-scalar, fact-provenance, fact-table, native-rule-publication-parity, open-world, parameters, relationship-kind, schema-metadata, structured-fact, time-policy |
| examples/subsidy-scheme | calculation, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, parameters, parent-kind, reference, relational-rule, scalar-alias, schema-metadata, slot, slot-pattern, time-policy | composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, schema-metadata, slot | calculation, extended-scalar, open-world, parameters, relationship-kind, schema-metadata, time-policy | Pending: calculation, extended-scalar, open-world, parameters, relationship-kind, schema-metadata, time-policy | Pending: calculation, extended-scalar, native-rule-publication-parity, open-world, parameters, relationship-kind, schema-metadata, time-policy |
| examples/zorgtoeslag | calculation, conditional-check, dated-fact, decision-table, enum, exceptions, extended-scalar, fact-table, inverse-reference, kind, module-import, optional-slot, parameters, repeated-slot, schema-metadata, slot, table-policy, time-policy, units | — | calculation, dated-fact, exceptions, extended-scalar, fact-table, inverse-reference, module-import, parameters, schema-metadata, table-policy, time-policy, units | No owning pack | No owning pack |
| packs/std-access | enum, enum-metadata, kind, optional-slot, relational-rule, repeated-slot, schema-metadata, slot | — | schema-metadata | Pending: schema-metadata | Pending: native-rule-publication-parity, schema-metadata |
| packs/std-decision | composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, schema-metadata, slot | — | extended-scalar, open-world, relationship-kind, schema-metadata | Pending: extended-scalar, open-world, relationship-kind, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, open-world, relationship-kind, schema-metadata |
| packs/std-explain | — | — | No language sources | No language sources | No language sources |
| packs/std-identity | abstract-kind, conditional-check, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | schema-metadata | Pending: schema-metadata | Pending: native-rule-publication-parity, schema-metadata |
| packs/std-loop | enum, extended-scalar, kind, numeric-limit, optional-slot, parent-kind, reference, relational-rule, schema-metadata, slot | abstract-kind, conditional-check, extended-scalar, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| packs/std-order | abstract-kind, conditional-check, extended-scalar, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| packs/std-part | abstract-kind, conditional-check, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| packs/std-time | abstract-kind, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | extended-scalar, open-world, schema-metadata | Pending: extended-scalar, open-world, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, open-world, schema-metadata |
| packs/std-view | — | — | No language sources | No language sources | No language sources |
| run/packs/cleanup | enum, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/cleanup-deadline | enum, extended-scalar, kind, optional-slot, relational-rule, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/dispatch | enum, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/exact-quote | enum, extended-scalar, kind, numeric-limit, reference, relational-rule, slot | — | extended-scalar | Pending: extended-scalar | Pending: extended-scalar, native-rule-publication-parity |
| run/packs/invoice-drift | enum, extended-scalar, kind, numeric-limit, optional-slot, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, schema-metadata | Pending: extended-scalar, schema-metadata | Pending: extended-scalar, native-rule-publication-parity, schema-metadata |
| run/packs/offer-selection | enum, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, reference, relational-rule, schema-metadata, slot | — | extended-scalar, fact-table, schema-metadata | Pending: extended-scalar, fact-table, schema-metadata | Pending: extended-scalar, fact-table, native-rule-publication-parity, schema-metadata |

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
