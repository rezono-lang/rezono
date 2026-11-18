# Reading a projected answer as a kind

Source `docs/rezono/cases/E53.yaml#E53`.

## Deferral

The source reserves reading an answer as a kind. It expects composition to retain the upstream undecided row, its reason and the same witnesses as the equivalent single question. The [typed answer tests](../rezono/test/evaluate.test.ts) exercise the output of one question.

Revisit when the language can use an answer as a typed input and can compare the composed and single-question results, including `Undecided` and the witness identity. Agreement on known rows alone would leave the reserved behavior untested.
