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
