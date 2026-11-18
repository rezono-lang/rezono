# Missing optional cell in the viewer

Source `docs/semantics/value-cases.yaml#viewer-missing-optional`.

## Deferral

The language evaluator and the conformance engines can establish the state of an optional value in a fully read, closed slot. The source also asks for the viewer's label and hatching. The viewer's data projection and rendering are outside the current engine corpus.

Revisit this case with a viewer fixture that compares a readable missing optional cell with an unknown cell and shows the actual label and hatching for each. The evaluator's state alone cannot establish the rendering.
