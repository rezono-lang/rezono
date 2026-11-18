# Exact calculated values as rule premises

A rule that reports a share must be able to carry the exact value that the calculation proved. For 26 units out of 41 at a price of 107 the share is 2782/41. Its proof identifies the selected calculation, its evaluation date, both unit counts and the price. Removing any of those grounds invalidates that proof.

## First step: verify a copy

Introduce the rule IR column type `rational` for the value of an open numeric calculation selection and its copy in a derived key. The calculation's existing four-part snapshot key supplies the subject, canonical value, state and reason. The rule binds the value through a positive premise with state `known` and empty reason. Its witness identifies the original selection row at that exact key. The existing Calc witness independently establishes how that value follows from the recorded facts.

Use the existing Calc spelling for keys and bindings. Whole values use signed decimal integers with no redundant zeros or negative zero. Fractions use a signed numerator and a positive denominator greater than one, in lowest terms. This representation introduces no digit limit. Unknown, invalid and inapplicable results cannot supply a value. Existing `integer` rule premises retain their whole-number semantics.

The first verifier accepts copying a rational variable into a rational column. It checks both declared types, the rule and calculation witnesses, and completeness when the copied relation is read in full. A text or integer destination, or an arithmetic or ordering operation on a rational variable, must be refused until that operation has its own semantics and evidence. The verifier recomputes the calculation even when the snapshot, conclusion and claimed witness value all agree.

The acceptance fixture in `compiler/tests/test_exact_selection_proof.py` runs the existing Calc producer on DuckDB and checks its calculation witness against the source snapshots. Its rule IR and rule witness are supplied independently of the compiler. This first task changes the rule contract and the independent checker. A subsequent compiler task can target this verifier.

## Later steps

1. Compile an opt-in exact selection and carry it through batch and incremental pipelines, snapshots and published witnesses. Preserve the existing integer projection. Verify insertions, replacements and retractions on the pinned hosted Feldera engine for the implementation revision.
2. Specify lossless input and number operations for arbitrary integer amounts. A product of 9223372036854775807 and 2 is 18446744073709551614. A wider fixed-width cast would only move the limit. Require an independently checkable exact result at and beyond each engine representation boundary, with a real backend and explicit failure behavior until supported.
3. Add typed numeric ordering and aggregation after those operations can preserve exact values and provenance. Selection must change when a rival has a better whole-order price. Shared-cost allocation must retain its measured population and period coverage and prove its balance from the resulting shares.

Rounding, splitting an attributed amount into unrelated facts, and silently dropping fractional selections would each change the evidence available to a consuming rule. Domain packs can use these operations after the relevant compiler, verifier and backend cases pass.
