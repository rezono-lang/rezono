# Hiding an owner column in a sheet

Source `docs/semantics/value-cases.yaml#projection-viewer-column`.

## Deferral

This source concerns the viewer's projected cells. The corpus can exercise RowRefs and value states independently. The sheet projection must additionally preserve the RowRef, cardinality, state and reason of each displayed cell when the owner column is hidden.

Revisit when a viewer fixture renders the same sheet with and without that column and can compare the metadata of the remaining cells. A wire-format case alone would leave the projection untested.
