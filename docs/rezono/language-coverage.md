# Rezono language coverage

Run `python compiler/tests/rezono/language_usage.py` from the repository root for the current inventory.
Counts use each authored file once per feature. Higher counts give higher priority among available tasks.
Support requires the applicable reader, form and lowering tests without expected-failure markers.
Pack readiness includes transitive local imports.
Publication parity is checked separately.

| Feature | Files | Reader and lowering |
| --- | ---: | --- |
| relational-rule | 74 | Pending ([reader](../../rezono/test/test_relational_rule_block.py), [lowering](../../compiler/tests/rezono/test_rule_witness.py)) |
| kind | 53 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| schema-metadata | 51 | Pending |
| slot | 49 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| fact-table | 38 | Pending |
| named-dataset | 37 | Pending |
| extended-scalar | 31 | Pending |
| reference | 31 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| enum | 27 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| optional-slot | 24 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_module.py)) |
| numeric-limit | 21 | Pending ([reader](../../rezono/test/test_numeric_limits.py), [lowering](../../compiler/tests/rezono/test_lower_numeric_limits.py)) |
| fact-provenance | 10 | Pending |
| conditional-check | 9 | Pending |
| enum-metadata | 9 | Pending |
| repeated-slot | 9 | Pending |
| parent-kind | 8 | Pending ([reader](../../rezono/test/test_parent_kind.py), [lowering](../../compiler/tests/rezono/test_lower_parent_kind.py)) |
| scalar-alias | 7 | Pending ([reader](../../rezono/test/test_scalar_alias.py), [lowering](../../compiler/tests/rezono/test_lower_scalar_alias.py)) |
| structured-fact | 7 | Pending |
| abstract-kind | 6 | Pending ([reader](../../rezono/test/test_abstract_kind.py), [lowering](../../compiler/tests/rezono/test_lower_abstract_kind.py)) |
| slot-pattern | 5 | Pending ([reader](../../rezono/test/test_slot_pattern.py), [lowering](../../compiler/tests/rezono/test_lower_slot_pattern.py)) |
| calculation | 4 | Pending |
| time-policy | 4 | Pending |
| composite-key | 3 | Pending ([reader](../../rezono/test/test_composite_key.py), [lowering](../../compiler/tests/rezono/test_lower_composite_key.py)) |
| open-world | 3 | Pending |
| rule-metadata | 3 | Pending |
| embedded-kind | 2 | Pending ([reader](../../rezono/test/test_embedded_kind.py), [lowering](../../compiler/tests/rezono/test_lower_embedded_kind.py)) |
| embedded-reference | 2 | Pending ([reader](../../rezono/test/test_embedded_relation.py), [lowering](../../compiler/tests/rezono/test_lower_embedded_reference.py)) |
| module-import | 2 | Pending |
| parameters | 2 | Pending |
| path-equation | 2 | Pending ([reader](../../rezono/test/test_path_equation.py), [lowering](../../compiler/tests/rezono/test_lower_path_equation.py)) |
| boolean-slot | 1 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/rezono/test_library_boolean.py)) |
| bounded-slot | 1 | Pending ([reader](../../rezono/test/test_bounded_slot.py), [lowering](../../compiler/tests/rezono/test_lower_bounded_list.py)) |
| dated-fact | 1 | Pending |
| decision-table | 1 | Supported ([reader](../../rezono/test/module-json.test.ts), [lowering](../../compiler/tests/test_rezono_table.py)) |
| exceptions | 1 | Pending |
| explicit-identifier | 1 | Supported ([reader](../../rezono/test/test_explicit_identifier.py), [lowering](../../compiler/tests/rezono/test_lower_explicit_identifier.py)) |
| inverse-reference | 1 | Pending |
| relationship-kind | 1 | Pending |
| table-policy | 1 | Pending |
| unclassified-authored-syntax | 1 | Pending |
| units | 1 | Pending |

| Pack or source directory | Direct features | Imported features | Pending features |
| --- | --- | --- | --- |
| examples/library | abstract-kind, boolean-slot, bounded-slot, composite-key, conditional-check, embedded-kind, embedded-reference, enum, explicit-identifier, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, parent-kind, path-equation, reference, repeated-slot, schema-metadata, slot, slot-pattern, structured-fact | — | abstract-kind, bounded-slot, composite-key, conditional-check, embedded-kind, embedded-reference, extended-scalar, fact-table, named-dataset, numeric-limit, parent-kind, path-equation, repeated-slot, schema-metadata, slot-pattern, structured-fact |
| examples/platform | abstract-kind, enum, enum-metadata, extended-scalar, fact-provenance, fact-table, kind, named-dataset, numeric-limit, optional-slot, parent-kind, reference, relational-rule, repeated-slot, schema-metadata, slot, slot-pattern, structured-fact | abstract-kind, composite-key, conditional-check, enum, enum-metadata, extended-scalar, fact-table, kind, named-dataset, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot | abstract-kind, composite-key, conditional-check, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, numeric-limit, open-world, parent-kind, relational-rule, relationship-kind, repeated-slot, rule-metadata, schema-metadata, slot-pattern, structured-fact |
| examples/platform/tenant-capacity/interface | extended-scalar, fact-table, kind, named-dataset, numeric-limit, relational-rule, schema-metadata, slot | — | extended-scalar, fact-table, named-dataset, numeric-limit, relational-rule, schema-metadata |
| examples/projects | composite-key, enum, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, path-equation, reference, scalar-alias, schema-metadata, slot, structured-fact | — | composite-key, extended-scalar, fact-table, named-dataset, numeric-limit, path-equation, scalar-alias, schema-metadata, structured-fact |
| examples/subsidy | calculation, conditional-check, embedded-kind, embedded-reference, enum, enum-metadata, extended-scalar, fact-provenance, fact-table, kind, named-dataset, numeric-limit, optional-slot, reference, relational-rule, repeated-slot, scalar-alias, schema-metadata, slot, structured-fact, time-policy | abstract-kind, calculation, composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, parameters, parent-kind, reference, relational-rule, relationship-kind, repeated-slot, rule-metadata, scalar-alias, schema-metadata, slot, slot-pattern, time-policy | abstract-kind, calculation, composite-key, conditional-check, embedded-kind, embedded-reference, enum-metadata, extended-scalar, fact-provenance, fact-table, named-dataset, numeric-limit, open-world, parameters, parent-kind, relational-rule, relationship-kind, repeated-slot, rule-metadata, scalar-alias, schema-metadata, slot-pattern, structured-fact, time-policy |
| examples/subsidy-scheme | calculation, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, parameters, parent-kind, reference, relational-rule, scalar-alias, schema-metadata, slot, slot-pattern, time-policy | composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, schema-metadata, slot | calculation, composite-key, conditional-check, enum-metadata, extended-scalar, numeric-limit, open-world, parameters, parent-kind, relational-rule, relationship-kind, repeated-slot, scalar-alias, schema-metadata, slot-pattern, time-policy |
| examples/zorgtoeslag | calculation, dated-fact, decision-table, enum, exceptions, extended-scalar, fact-table, inverse-reference, kind, module-import, optional-slot, parameters, repeated-slot, schema-metadata, slot, table-policy, time-policy, unclassified-authored-syntax, units | — | calculation, dated-fact, exceptions, extended-scalar, fact-table, inverse-reference, module-import, parameters, repeated-slot, schema-metadata, table-policy, time-policy, unclassified-authored-syntax, units |
| packs/std-access | enum, enum-metadata, kind, optional-slot, relational-rule, repeated-slot, schema-metadata, slot | — | enum-metadata, relational-rule, repeated-slot, schema-metadata |
| packs/std-decision | composite-key, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, relationship-kind, repeated-slot, schema-metadata, slot | — | composite-key, conditional-check, enum-metadata, extended-scalar, numeric-limit, open-world, relational-rule, relationship-kind, repeated-slot, schema-metadata |
| packs/std-explain | — | — | No language sources |
| packs/std-identity | abstract-kind, conditional-check, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | abstract-kind, conditional-check, relational-rule, repeated-slot, rule-metadata, schema-metadata |
| packs/std-loop | extended-scalar, kind, optional-slot, parent-kind, reference, relational-rule, schema-metadata, slot | abstract-kind, conditional-check, extended-scalar, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | abstract-kind, conditional-check, extended-scalar, parent-kind, relational-rule, repeated-slot, rule-metadata, schema-metadata |
| packs/std-order | abstract-kind, conditional-check, extended-scalar, kind, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | abstract-kind, conditional-check, extended-scalar, relational-rule, repeated-slot, rule-metadata, schema-metadata |
| packs/std-part | abstract-kind, conditional-check, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, schema-metadata, slot | — | abstract-kind, conditional-check, extended-scalar, numeric-limit, relational-rule, schema-metadata |
| packs/std-time | abstract-kind, conditional-check, enum, enum-metadata, extended-scalar, kind, numeric-limit, open-world, optional-slot, reference, relational-rule, repeated-slot, rule-metadata, schema-metadata, slot | — | abstract-kind, conditional-check, enum-metadata, extended-scalar, numeric-limit, open-world, relational-rule, repeated-slot, rule-metadata, schema-metadata |
| packs/std-view | — | — | No language sources |
| run/packs/cleanup | enum, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, numeric-limit, relational-rule, scalar-alias, schema-metadata |
| run/packs/cleanup-deadline | enum, extended-scalar, kind, optional-slot, relational-rule, schema-metadata, slot | — | extended-scalar, relational-rule, schema-metadata |
| run/packs/dispatch | enum, extended-scalar, kind, numeric-limit, optional-slot, reference, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, numeric-limit, relational-rule, scalar-alias, schema-metadata |
| run/packs/exact-quote | enum, extended-scalar, kind, numeric-limit, reference, relational-rule, slot | — | extended-scalar, numeric-limit, relational-rule |
| run/packs/invoice-drift | enum, extended-scalar, kind, numeric-limit, optional-slot, relational-rule, scalar-alias, schema-metadata, slot | — | extended-scalar, numeric-limit, relational-rule, scalar-alias, schema-metadata |
| run/packs/offer-selection | enum, extended-scalar, fact-table, kind, named-dataset, numeric-limit, optional-slot, reference, relational-rule, schema-metadata, slot | — | extended-scalar, fact-table, named-dataset, numeric-limit, relational-rule, schema-metadata |

## Native rules in module form 3

The expression syntax and migration are specified in the language decision. [Native rules decision](https://github.com/rezono-lang/rezono/blob/27ff4dc926166484e549e4da0c95d400d067a18b/decisions/language-native-rules.md)
The rule census includes 74 distinct source files, with 74 using Datalog or interim pipes and 0 using native rules.
A mixed file counts once in the total and in each spelling it uses.
Native reader, form and IR proof gate: **Pending** ([reader](https://github.com/rezono-lang/rezono/blob/bd9a459f0e8c4934c92bd39b862208e25eb64363/rezono/test/test_native_rule_reader_roundtrip.py), [form](https://github.com/rezono-lang/rezono/blob/bd9a459f0e8c4934c92bd39b862208e25eb64363/compiler/tests/rezono/test_native_rule_form_contract.py), [IR and witness](https://github.com/rezono-lang/rezono/blob/bd9a459f0e8c4934c92bd39b862208e25eb64363/compiler/tests/rezono/test_native_rule_ir_listed.py)).
This gate covers initial integration. Whole-pack migration also requires [signature linking](https://github.com/rezono-lang/rezono/blob/cb086e32909e616fdca40541c9d61c7a7401e14d/compiler/tests/rezono/test_native_rule_signatures.py) and [publication parity](https://github.com/rezono-lang/rezono/blob/bd9a459f0e8c4934c92bd39b862208e25eb64363/compiler/tests/rezono/test_native_rule_publication_parity.py).

An explicit state predicate needs a review of its evidence. Keep the legacy rule where a general scalar state lacks authenticated evidence. [state-evidence test](https://github.com/rezono-lang/rezono/blob/bd9a459f0e8c4934c92bd39b862208e25eb64363/compiler/tests/rezono/test_native_rule_state_evidence.py)
The census cannot infer general state checks from a legacy file. Ordinary relation negation and explicit outcome values are separate.
No pack has a confirmed general state blocker in this census.
For example, [the subsidy assessment](../../examples/subsidy-scheme/rules/assessment.dl) derives an explicit outcome,
and [its findings](../../examples/subsidy-scheme/rules/findings.dl) read a known-only calculation selection.

| Pack or source directory | Direct legacy files | Direct native files | General state evidence |
| --- | ---: | ---: | --- |
| examples/platform | 34 | 0 | Unknown until legacy conversion |
| examples/platform/tenant-capacity/interface | 1 | 0 | Unknown until legacy conversion |
| examples/subsidy | 4 | 0 | Unknown until legacy conversion |
| examples/subsidy-scheme | 4 | 0 | Unknown until legacy conversion |
| packs/std-access | 1 | 0 | Unknown until legacy conversion |
| packs/std-decision | 1 | 0 | Unknown until legacy conversion |
| packs/std-identity | 1 | 0 | Unknown until legacy conversion |
| packs/std-loop | 16 | 0 | Unknown until legacy conversion |
| packs/std-order | 1 | 0 | Unknown until legacy conversion |
| packs/std-part | 1 | 0 | Unknown until legacy conversion |
| packs/std-time | 1 | 0 | Unknown until legacy conversion |
| run/packs/cleanup | 2 | 0 | Unknown until legacy conversion |
| run/packs/cleanup-deadline | 1 | 0 | Unknown until legacy conversion |
| run/packs/dispatch | 1 | 0 | Unknown until legacy conversion |
| run/packs/exact-quote | 1 | 0 | Unknown until legacy conversion |
| run/packs/invoice-drift | 2 | 0 | Unknown until legacy conversion |
| run/packs/offer-selection | 2 | 0 | Unknown until legacy conversion |
