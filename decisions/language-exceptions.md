---
decider: [language]
decided_on: 2026-11-17
valid_from: 2026-11-17
state: in_force
subject: language-exceptions
---

# Ordered exceptions

Keep the existing unless form under a derived value, including ordered groups and source citations. Preserve the separation between an unconditional fallback and an unknown condition. Reordering exceptions could change a publication.

```rezono
unless paused then 0
```

The corresponding JSON fragment is

```json
{
  "unless": [
    [
      {
        "when": {
          "path": [
            "paused"
          ]
        },
        "then": {
          "lit": "0"
        }
      }
    ]
  ]
}
```

## Lowering

Ordered `unless` blocks under a derived value lower to `rezono.calc/1` definitions with `overrides`, preserving the semantics of [v0 section 5b](../docs/rezono/v0.md#5b-exceptions) without adding a new calculation operator:

- `compiler/rezono_compiler/rezono_exceptions.py` exposes `lower_unless(rule_id, base_value, unless_blocks, lower_expr) -> list[dict]`.
- The base value lowers to definition `base` with `when: {"boolean": True}` and `value: lower_expr(base_value)`.
- Each line `j` (1-based) in block `i` (1-based) of `unless_blocks` lowers to definition `unless_{i}_{j}` with `when: lower_expr(line["when"])`, `value: lower_expr(line["then"])`, and `overrides` containing `{"definition": f"{rule_id}#{earlier}", "reason": line.get("source") or "unless"}` for `base` and every definition from earlier blocks `1 .. i-1`. Sibling lines within the same block `i` do not override one another.
- Because `calc_sql.py` evaluates `overrides` with short-circuiting Kleene logic and rejects two simultaneously applying non-overriding definitions as `invalid`:
  1. When every exception condition is false, `base` applies.
  2. When a single exception line in the highest-precedence applying block is true and every other sibling in that block is false or `not_applicable`, it overrides all earlier blocks and `base` (even if an earlier block's condition is unknown).
  3. When two sibling lines in the same block both apply, the result state is `invalid` (never a silent pick).
  4. When an active block's condition is unknown, the result state is `unknown` (never an unconditional fallback to `base` or an earlier block).
  5. When one sibling line in the highest-precedence applying block is true and another sibling line in the same block is unknown (with no invalid condition or sibling conflict), the result state is `unknown`, because it cannot be ruled out that both siblings apply simultaneously and collide as `invalid`.

The lowering test is `compiler/tests/rezono/test_lower_exceptions.py`.
