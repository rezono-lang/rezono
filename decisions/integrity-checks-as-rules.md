# Integrity checks as invariant rules with witnesses

A rejected input is a conclusion like any other, so it gets a witness that the independent checker recomputes. Today the compiler writes the integrity checks as SQL: `checks.generic` builds the six generic check kinds (identification, reference, totality, functionality, value range, cardinality) over metadata tables, and `emit.integrity` writes pattern, unique key, path equation and class rule per check. A violation is a row of `validation_result`, without a witness and without Soufflé as an oracle. The rule IR already has what a check needs: stratified negation, `count`, comparisons and invariant relations that must be empty (`invariant_violated` in the checker). The compiler moves the checks into the rule program, one check kind at a time.

## What the compiler generates

The checks stay data, as the checks-as-data design made them: which slot has which check is a row of a metadata table, and the rule program depends only on which kinds, slots and enumerations exist. A change of a bound, of a required slot or of a cardinality limit stays a change of rows, and the engine program keeps its bytes (`compiler/tests/test_checks.py`, `test_a_schema_change_of_a_check_is_a_change_of_rows`).

**Metadata as base relations.** The metadata tables `rezono__<facet>` become base relations of the rule IR, closed, with the columns they have. `rezono__constant` splits into `rezono__constant` (text) and `rezono__constant_integer` (integer), because a rule compares values of one column type. The publisher publishes them as snapshots like every base relation the rules read. The checker's comparison of the loaded metadata with the bundle (`check_metadata`) stays, so a witness can only cite a metadata row the definition gives.

**Structural relations.** The compiler generates one rule per kind, slot or enumeration, and nothing per check:

```
rezono__in_kind("<kind>", x) :- <kind>(x).                    // every kind
rezono__text_value("<kind>", "<slot>", x, v) :- <kind>__<slot>(x, v).     // every text slot
rezono__integer_value("<kind>", "<slot>", x, v) :- <kind>__<slot>(x, v).  // every integer slot
rezono__enum_member("<enumeration>", v) :- <enumeration>(v).  // every enumeration
```

**One invariant relation per check kind and value type.** Each is generated with `@invariant` and `@absence`: an integrity check states what is recorded, in a closed and in an open world alike. The compiler's lint that a rule of an `@absence` relation must negate or count an open relation does not apply to these generated relations. The rules, with `k`, `s`, `x`, `v` the kind, slot, element and value:

| Check kind | Relation and key | Rules |
|---|---|---|
| cardinality | `rezono__cardinality_violation(kind, slot, id, n)`, `n` integer | `rezono__minimum_cardinality(k, s, m), rezono__in_kind(k, x), a = count : {rezono__text_value(k, s, x, _)}, b = count : {rezono__integer_value(k, s, x, _)}, n = a + b, n < m`; the same with `rezono__maximum_cardinality` and `n > m`. |
| reference | `rezono__reference_violation(kind, slot, id, value)`, value text; `rezono__reference_integer_violation` with an integer value | Parent kind: `rezono__is_a(k, p), rezono__in_kind(k, x), !rezono__in_kind(p, x)` gives `(k, "is_a", x, "")`. Owner: `rezono__text_value(k, s, x, v), !rezono__in_kind(k, x)`, and the same over `rezono__integer_value` into the integer relation. Target: `rezono__arrow(k, s, t), rezono__text_value(k, s, x, v), !rezono__in_kind(t, v)`. |
| totality | `rezono__totality_violation(kind, slot, id)` | `rezono__required(k, s), rezono__in_kind(k, x)`, the two counts as for cardinality, `a + b = 0`. |
| functionality | `rezono__functionality_violation(kind, slot, id, n)`, `n` integer | `rezono__single(k, s), rezono__text_value(k, s, x, _), n = count : {rezono__text_value(k, s, x, _)}, n > 1`, and the same over `rezono__integer_value`. A value of no element counts too, as today. |
| value range | `rezono__value_range_violation(kind, slot, id, value)`, value text; `rezono__value_range_integer_violation` with an integer value | Enumeration: `rezono__enum(k, s, e), rezono__text_value(k, s, x, v), !rezono__enum_member(e, v)`. Constant: `rezono__constant(k, s, _), rezono__text_value(k, s, x, v), !rezono__constant(k, s, v)`, and the same with `rezono__constant_integer` over integer values. Bounds: `rezono__minimum(k, s, m), rezono__integer_value(k, s, x, v), v < m`, and `rezono__maximum` with `v > m`. |
| unique key | `<kind>__<key>__unique(id)`, one relation per logical check, as the SQL is per check today | Two elements with equal values in every slot of the key and different ids. |
| path equation | `<kind>__<name>__path_equation(id, left, right)` | The two paths as joins and `left != right`. |
| class rule | `<kind>__<name>__rule(id)` | The pre- and postconditions as today, each condition "the element has a value that fails the test" as a helper relation of its own, so that "every value meets it" is a negation. |

The value of a generic violation is the value the SQL reports today: a count for cardinality and functionality, the offending value for reference and value range, nothing for totality and for a missing parent.

## Order

Cardinality first: its counts are the first aggregate over what is recorded, and its witness is the one the publisher would otherwise count itself. Then reference. Then the rest, in this order: totality, functionality, value range, unique key, path equation, class rule. One check kind at a time, in two steps:

1. The rules come next to the SQL. On every example, and on generated facts against Soufflé, the invariant rows of that kind and the `validation_result` rows of that kind are the same set. A difference is an error that gets its own repair before the next step. The pull request of cardinality states the duration of the checks, and the number of witnesses, on the largest example before and after.
2. The SQL of that kind goes. The bundle's check entry names the invariant relation in `relation`.

## What stays SQL, and why

- **Identification.** The rule program has set semantics: two equal rows of a kind are one row, so a rule cannot see a duplicate element. A duplicate is a property of the input rows, not a conclusion over them.
- **Pattern,** and a class rule with a pattern condition. The rule language has no pattern predicate. They move when it gets one.
- **A check on a value a rule cannot hold.** The rule IR has text and integer columns only. A check on a boolean or date slot, or on a kind whose identifier is neither, stays in the generic SQL. That SQL then reads only those slots; a pack without them has no SQL for that kind.

## `validation_result` during the transition

`validation_result` keeps its columns (type, subject, instantiates, path, value, info) and its rows on every example, so every reader keeps working. For a converted kind its branch reads the invariant relation: `type` is the check kind, `subject` the element, `instantiates` the kind, `path` the slot, `value` the relation's value as text or `''`, and `info` the logical check name `<kind>__<slot>__<check>`. In the batch backend the integrity SQL runs on the database of the rule program, which holds every table once the structural relations read them. `examples/test_checks_bundled.py` and the independent reference of `compiler/tests/test_generality.py` stay the guard that the rows are the same.

## The publisher reads the outcome

The compiler emits one view `check_outcome(name, violations, status)` with one row per check of the manifest: every logical check, every invariant and every check view of the rules, zero rows included, `status` red exactly when `violations` is greater than zero. The publisher copies these rows into the manifest. It counts no violations and decides no status itself.

## Alternatives

- **One rule per slot and check, with the bound as a constant.** Simpler witnesses and no structural relations, but every change of a check changes the rule program, so the incremental engine rebuilds on a changed bound. Rejected: the checks stay data.
- **Keep the SQL and add a witness to each row.** The checker could not recompute it from the rule IR, and Soufflé would not see it. Rejected.
- **One relation per check kind with every value as text.** The rule IR has no conversion from integer to text. Rejected; a second relation per value type costs one name.

The structural relations have a witness per slot value. That is the price of keeping the checks as data; the first pull request measures it.
