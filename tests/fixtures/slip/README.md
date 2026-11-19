# Slip fixture

A small, domain-neutral pack for the tests of the slip, the first sheet of the
reference viewer ([decision](../../../decisions/viewer-slip.md)). The tests in
`tests/slip/` publish it, ask the local reader about it, and draw the page over it.

Items belong to groups; a hold can name an item; a link runs from one item to another.

| Rule | What it derives |
| --- | --- |
| `held` | an item that a hold names |
| `flagged` | an item whose amount is at least ten and that no hold names (a negative premise) |
| `recorded_amount` | the amount of an item, as an open relation for the calculation |
| `group_size` | the number of items in a group (an aggregate) |
| `busy` | a group with at least two items (a conclusion on a conclusion) |
| `linked` | the item a link starts from |
| `too_large` | an invariant: no amount above twenty-five |

The calculation `capped_amount` is the smaller of an item's recorded amount and 20.
The constant has no step, so it has no line on a slip.

| Item | Group | Amount | Flagged | Capped amount |
| --- | --- | --- | --- | --- |
| `item-a` | `group-a` | 12 | yes | 12 |
| `item-b` | `group-a` | 4, held by `hold-b` | no | 4 |
| `item-c` | `group-b` | none | no | unknown |

The home claim is `flagged`, which has one row: `item-a`.
The sweep `item_amount` moves the amount of `item-a` over 0 to 30 in steps of 5.
At 30 the invariant fails, so that stop is red.

Two roles read the pack through `std-access`. `reader` holds `read` and
`read_restricted` and reads every relation in full. `summary` holds `read` only:
it reads no link and no role, so it reads not every relation in full.
The pack imports `std-explain` for the questions `grounds`, `reach`, `sweep` and `scenario`.

The fixture schemas and rules are CC0 1.0. The synthetic records and this guide are CC BY 4.0.
