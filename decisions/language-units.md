# Units and rounding

Keep the existing unit and rounding declarations. Resolve symbolic units, conversion factors and currency before lowering. Perform exact rational arithmetic until an explicit rounding operation. Inlining conversion factors loses the source unit.

```rezono
unit Credit = money EUR
```

The corresponding JSON fragment is

```json
{
  "unit": "Credit",
  "is": "money EUR"
}
```

A rounding declaration names what it rounds and the mode, as v0 section 5f writes it:

```rezono
rounding money down
```

The corresponding JSON fragment is

```json
{
  "rounding": "money",
  "mode": "down"
}
```

## Lowering

A unit lowers to a LinkML type of whole numbers with the annotation the compiler already reads for a unit (P10.3):

| Rezono | LinkML type |
|---|---|
| `unit Cents = money minor EUR` | `typeof: integer`, annotation `currency: EUR` |
| `unit GiB = 2^30 B` | `typeof: integer`, annotation `unit: 2^30 B` |

The compiled unit is then the one a schema file with that type gives: the same name, currency, factor and dimension.

`unit Euro = money EUR` names the major unit of a currency. The compiler stores money in minor units and knows no currency's number of minor digits, so this form is refused at its line with a message that names the minor form. Write `unit Cents = money minor EUR` and `unit Euro = 100 Cents` instead.

A base unit (`unit B = integer`) has no written dimension name, and the compiler needs one (`dimension: data`). Its spelling is a later decision, and the compiler refuses it until then. A rounding declaration lowers with the calculations that use it, not as part of the schema.
