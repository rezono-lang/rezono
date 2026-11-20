---
decider: [core]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: in_force
subject: four-valued-logic-parity
---

# True decides disjunction with invalid

Source `docs/semantics/value-cases.yaml#tt-or-true-invalid`.

## Adopted behavior

A known true operand decides a disjunction even when the other operand is invalid. The result is a known Boolean true with no invalid reason carried into that result. Swapping the operands preserves it.

Include both orders and a control where false is paired with invalid. That control carries the invalid state. The [normative truth tables](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) and the [ordinary language evaluator](../rezono/test/evaluate.test.ts) exercise these cells. As specified in [`decisions/four-valued-and-or-parity.md`](four-valued-and-or-parity.md), `compiler/rezono_compiler/calc_sql.py` (DuckDB and Feldera SQL), `checker/rezono_checker/calc.py`, `compiler/rezono_compiler/rezono_calc.py`, and `rezono.rules/2` follow this exact table and the commutative UTF-8 least-reason rule of Appendix A.4.
