# Module imports

A module names the packs whose declarations it reads with `use`, after its `pack` line: `use std-decision`, or `use lib.terms as terms` with a prefix. The module form keeps the lines in order under `use`, each as `use` with the dotted pack name and, when written, `as` with the prefix (contracts/rezono-module.yaml, `Use`). The [native rules decision](language-native-rules.md), section Imports, already gives `use` its meaning for rules. This decision applies the same meaning to the kinds, enums and types of a schema module.

```rezono
use std-decision
use lib.terms as terms
```

The corresponding JSON fragment is

```json
{
  "use": [
    {"use": "std-decision"},
    {"use": "lib.terms", "as": "terms"}
  ]
}
```

## Lowering

- **Only a pinned pack.** The name after `use` must be the `name` of an entry under `imports` in `pack.yaml`. Any other name is refused at its `use` line (R046). A pack gains no visibility through a pack that it does not import itself.
- **An unaliased `use` makes the pack's names visible unqualified.** A slot of the module may name a kind, an enum or a type that the used pack declares, by its declared name. A name that two used packs declare is ambiguous and needs a prefix.
- **The LinkML import.** The lowered schema of the module lists `linkml:types` and then `<pack>:<module>` for each schema module of the used pack, in the order of the module ids. This is the import a schema file of the same pack writes for the same reference, so the bundle, the arrows and the checks are the ones the schema file gives.
- **A name without `use` stays unknown.** A slot that names a kind of an imported pack without a `use` line in its module is refused as before. Visibility is per module, as a LinkML import is per schema file.

A dotted pack name lowers in a later step. Until then the compiler refuses it at its `use` line.

### Lowering a prefix

- **A prefix makes the pack's names visible only with the prefix.** After `use lib as terms` a slot names the kind `Party` of `lib` as `terms.Party`. The bare name `Party` stays unknown in that module, unless an unaliased `use` line makes it visible too.
- **The prefix leaves no trace in the schema.** A slot of type `terms.Party` lowers as a slot of type `Party` does under `use lib`: its range is the declared name `Party`, and the lowered schema imports `linkml:types` and then `<pack>:<module>` for each schema module of `lib`, as above. The bundle, the arrows and the checks are the ones the schema file gives for the same reference.
- **A prefix names a pinned pack.** The pack after `use` is checked as for an unaliased line (R046). A prefix that no `use` line of the module declares, and a prefixed name that the pack does not declare, are refused at the slot that names them.

## Reading a prefixed type

A slot names a kind, an enum or a type of an aliased pack with the prefix, a dot and the declared name, as v0 section 4 writes `net.Zone`. The slot member `type` keeps it as written, `terms.Party`, with the cardinality in `card` as for any other type. The prefix is a name and the type a type name, so `Terms.Party` and `terms.party` are refused. The module form contract widens the type text by one optional prefix.

```rezono
use lib as terms

kind Holder world closed
  party: terms.Party
```

The corresponding JSON fragment is the slot:

```json
{
  "slot": "party",
  "type": "terms.Party"
}
```

## Considered

- **Visibility through `pack.yaml` alone.** Every pinned pack would be visible in every module. A reader could then not tell from a module which packs it depends on, and a new import could make an unqualified name ambiguous in a module that never asked for it.
- **Import only the modules that declare a referenced name.** The import list would change whenever a slot changes. Importing every schema module of the used pack keeps the list a function of the `use` lines.
- **A LinkML-style import line in the module (`import "std-decision:decision"`).** It names files rather than packs and repeats what `pack.yaml` pins. `use` already exists in the grammar and in the native rules.
