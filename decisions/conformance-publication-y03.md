# Dataset hash across indistinguishable answer worlds

Source `docs/publication/cases/Y03.yaml#Y03`.

## Deferral

The [language cases E49](../docs/rezono/cases/E49.yaml) and [E50](../docs/rezono/cases/E50.yaml) define indistinguishable worlds for a role. This publication case asks for the dataset hash returned by the answer endpoint in each world. The evaluator's local two-world comparisons do not supply that endpoint evidence.

Revisit with one pinned answer request per world and compare the emitted dataset hashes. Include an otherwise identical case with a changed readable input so the comparison detects a real change.
