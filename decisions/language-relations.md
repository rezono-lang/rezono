# References and inline records

A kind-valued slot holds its target key. The embedded modifier instead places the target record inside its parent. Existing inverse and world modifiers keep their meanings. Resolve the target by its declared name across imported packs. Inferring embedding from the target shape would conflate storage with identity.

```rezono
address: Address embedded
```

The corresponding JSON fragment is

```json
{
  "slot": "address",
  "type": "Address",
  "embedded": true
}
```
