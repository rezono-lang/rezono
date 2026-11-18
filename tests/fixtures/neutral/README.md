# Neutral conformance fixture

The pack supplies common declarations and a small synthetic dataset for
conformance cases. It defines items in groups and links between items.
The `outgoing_link` rule reverses the typed `Link.tail` reference.
An item has one group and one or two labels. Each link has one tail and one
head.

Both roles can read all items and groups. The `reader` role also reads links,
while the `summary` role has no link grant. The grants use the capabilities
declared in the pinned `std-access` pack.

The ratio divides an item's quantity by its weight using exact arithmetic.
The four items exercise the four value states:

| Item | Inputs | State of the ratio |
| --- | --- | --- |
| `item-a` | Quantity 7 and weight 3 | Known, exactly 7/3 |
| `item-b` | Quantity absent in a closed optional relation | Not applicable |
| `item-c` | Weight absent in an open relation | Unknown |
| `item-d` | Weight 0 | Invalid, division by zero |

The source sidecar identifies the authored data and pinpoints the recorded
zero. The compiler produces the schema bundle and the rule and calculation IR.
The publication schema comes from the bundle through the standard publication
API. Build output is generated as needed.

The fixture schemas and rules are CC0 1.0. The synthetic records and this
guide are CC BY 4.0.
