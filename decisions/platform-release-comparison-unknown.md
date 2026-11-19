# An undecidable release comparison is a row

The platform register records a release date for a named product release. A rule compares it with the date in the publisher's pinned announcement and reports a difference as `product_release_date_drift`. The register date is open-world: a missing date leaves the comparison unknown. Before this decision, a missing date or a missing observation produced no row at all. A reader could not tell "unknown" from "no difference".

## Choice

Derive `product_release_date_comparison_unknown(reference, product_id, version, reason)` for every register reference whose comparison cannot be decided. There are two reasons:

- `register-date-missing`: the reference names a product and version but records no date. The open date table is negated only inside an `@absence` relation. That relation speaks about the register, not about the release.
- `observation-missing`: no observed release of the same product and version exists. An announcement for another version does not close the comparison.

Both reasons can hold together, and then both rows appear. A reference with both dates gives drift or nothing, never unknown. Without a register reference there is nothing to compare. The proof of an unknown row rests on the register entry it describes.

## Considered

A three-valued comparison relation (equal, different, unknown) would also make agreement explicit. It would change the shape of the existing drift relation and its published consumers. The unknown row alone closes the gap the open-world date leaves. An explicit agreement row can be added later without changing either relation.

## Acceptance

`examples/platform/acceptance/test_release_comparison_unknown.py` removes each ground in turn and expects the matching reason. It checks that drift stays separate and that the proof of the unknown row is valid.
