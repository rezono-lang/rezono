# Reject negative zero in canonical integer text

Source `docs/semantics/value-cases.yaml#hash-negative-zero`.

## Adopted behavior

Canonical integer payloads accept the spelling `0` for zero and reject `-0`. This decision applies to typed integer payloads in the snapshot and calculation key, whose spelling is validated before use as evidence.

Use both spellings for the same typed slot. The [exact-calculation decision](exact-calculation-premises.md), [publication case R06](../docs/publication/cases/R06.yaml) and [checker integer tests](../checker/tests/test_negative_zero.py) independently exercise canonical spelling.
