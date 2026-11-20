---
decider: [core]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: in_force
subject: four-valued-logic-parity
---

# False decides conjunction with invalid

Source `docs/semantics/value-cases.yaml#tt-and-false-invalid`.

## Adopted behavior

A known false operand decides a conjunction even when the other operand is invalid. The result is a known Boolean false with no invalid reason carried into that result. The truth table is symmetric in the two operands.

Include both orders and a control where true is paired with invalid, which does carry the invalid state. The [normative truth tables](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) and the [ordinary language evaluator](../rezono/test/evaluate.test.ts) cover every combination. As specified in [`decisions/four-valued-and-or-parity.md`](four-valued-and-or-parity.md), `compiler/rezono_compiler/calc_sql.py` (DuckDB and Feldera SQL), `checker/rezono_checker/calc.py`, `compiler/rezono_compiler/rezono_calc.py`, and `rezono.rules/2` follow this exact table and the commutative UTF-8 least-reason rule of Appendix A.4. Checks on the integrity of published inputs are evaluated separately.
