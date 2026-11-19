# Reserve standard pack names

The standard packs under `packs/` (`std-access`, `std-time`, `std-loop` and the others) carry rules that other packs and the engine rely on. Some of them will read protected inputs, such as `std-completeness` reading `verified_receipt`. Until now any pack could call itself `std-*`, and an import named `std-time` could pin any bytes with their own hash. A pack could then take the place of a standard pack and its meaning without anything showing it.

## Choice

- **A `std-*` name is the standard pack.** The name stands only for the bytes of `packs/<name>` at the compiler's revision. The compiler identifies them by their pack hash. The standard packs and their hashes form a table that ships with the compiler and is generated from `packs/`. A test recomputes the table, so it cannot drift.
- **No pack calls itself `std-*`** unless its bytes are that standard pack. A pack named after a standard pack that does not exist yet, such as `std-completeness` before it is added, is refused.
- **An import named `std-*` pins the standard hash.** Whatever path it uses, its pinned hash and its bytes must be the table's entry for that name. Changed bytes under a standard name are refused, even when their own hash is pinned correctly. So is an unknown `std-*` name.
- **Other names stay free.** A copied and changed standard pack under an ordinary name is an ordinary pack. It gets none of a standard pack's standing.
- **Protected relations are separate.** Whatever its name, no pack may supply or derive a protected relation. The compiler refuses that, as the [admission transport](admission-transport.md) fixes. A standard pack reads protected relations like any other pack.

Adding a standard pack means adding it under `packs/` and regenerating the table in the same change.

## Alternatives considered

- **Trust the import pin alone.** A pin proves which bytes were meant, not that they are the standard ones.
- **Reserve by location** (`packs/` relative to the importer). Locations differ between a checkout, an archive and a release. The hash does not.
- **Sign standard packs.** That needs key handling the project does not have yet. The hash table gives the same check for packs that ship with the compiler.
