# Existence over an empty open set is unknown

Source `docs/semantics/value-cases.yaml#set-open-empty`.

## Adopted behavior

A many-valued slot of an open relation has no recorded members for its owner. The set is not known to be complete, and an unguarded count is refused with `R004`. No member is known to be absent. `any` over this set is `unknown` with reason `open_world` and no cause. It is not `false`.

The source record predates the shared expression semantics and gives `any: F`. The [expression decision](language-expression-semantics.md) §1 governs. For `S.any(p)`, a readable match suffices on an open domain, but an open scan with no matching evidence cannot establish `F`. Only a known empty and complete set gives `F`. The [language evaluator](../rezono/src/evaluate.ts) already gives `unknown` with `open_world`. The case `tests/conformance/value-set-open-empty.yaml` now expects that outcome and no longer marks the language as unsupported.

This changes no rule result. An ordinary rule emits a tuple only for `T`, so both readings derive no row. The difference is visible in a question and in a negation. `not S.any(p)` over the open empty set stays undecided instead of becoming true. The control is `value-set-closed-empty`. On a closed, fully read relation, the same rows give a complete empty set with count `0`, so `any` over it is `false`.

## Considered

- **Keep `F` from the source record.** That reads an absent row as evidence of absence on an open relation. It contradicts the open-world rule and would make `none` and negation true without coverage.
- **Mark the language as unsupported for this case.** That leaves two engines with different answers and no recorded choice.
