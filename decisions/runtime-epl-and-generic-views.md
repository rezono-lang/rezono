# EPL-2.0 runtime packages and generic views

Decision maker: Rezono project owner.

## Runtime licence

Allow EPL-2.0 dependencies at runtime under the same unmodified-package
condition as MPL-2.0. This makes the upstream `elkjs` layout engine eligible
for generic flow diagrams. Keep its source code verbatim. The viewer may
bundle the package as part of its ordinary build.

When integrating and distributing the package, preserve the upstream notices.
Include the EPL-2.0 licence text and a reference to the exact upstream source
of the shipped version in `NOTICE`. Make that source available under EPL-2.0
and tell recipients how to obtain it.
[Eclipse Public License](https://www.eclipse.org/legal/epl-2.0/)
[elkjs licence](https://github.com/kieler/elkjs/blob/master/LICENSE.md)

## Publication and viewer

Rezono derives the contents of a drawing as relations with proof. The view
key, palette, and messages belong in `std-view`. At publication time, a
generic layout computes positions from the derived content without domain
knowledge. The publication carries those positions.
[View contract](../contracts/view.yaml)
[Standard view pack](../packs/std-view/pack.yaml)

A later reference viewer renders any Rezono publication using its published
content and positions. It offers a table twin, a legend, proof per row, and
the verbs why, what depends on this, what is missing, what if, compare, and
propose. The viewer renders these results and submits requests for those verbs
to the publication's interfaces. Computation belongs to Rezono's rules and
publication process.
[View and interaction principles](../docs/vision.md)

Domain-specific views belong to their domain. Hosting is external to Rezono.
Keep the role-based access gate outside Rezono while the deployment serves a
single role.

## Release order

Add published positions and the reference viewer after the first installable
release. Bring either forward only when an acceptance question requires it.
The 27 deferred drawing-view tests cover positions in the publication. Make
them eligible for work as soon as positions are published, including when the
reference viewer is still pending.
