# Missing and stale access epochs on an answer request

Source `docs/publication/cases/Y02.yaml#Y02`.

## Deferral

The source expects refusal for a missing access epoch and for a stale one. It leaves the response status open. The evaluator's in-process question input has no public answer-request boundary at which to test either refusal.

Revisit with an answer request against a current access epoch as a positive control and the same request with each invalid epoch condition. Keep the transport status separate from the refusal until the endpoint specifies it.
