# Admit a typed theory mapping at the kept replay boundary

Kept replay reinstalls the archived publisher and makes a publication again, byte for byte. Before installing anything, the current code checks the unpacked archive (`kept.archived_pack`). The archive holds one main pack and the imports it pins, and nothing else. Until now that check refused every archive with a theory mapping (`views.yaml`) in any pack of the closure, so an example that maps a theory, such as the subsidy example onto `std-time`, could not be replayed. The refusal was a placeholder: no mapping boundary had been specified.

## Choice

- **Type before install.** The current verifier reads every `views.yaml` in the archive's pinned closure and types it against the archived packs, with the same reader and typing that compilation uses. Only the current code runs, and nothing from the archive executes.
- **Refuse what cannot be typed.** A mapping that is not valid YAML, is not a views file, names a source kind or slot the domain lacks, or fails typing is refused. The refusal names the file as `pack/<path>/views.yaml` and says `theory views.yaml`. Nothing is installed.
- **Admit what can be typed.** A typed mapping lets the archive pass the boundary. The archived publisher then makes the publication with its own code.
- **Bytes decide the rest.** Replay compares the new publication with the kept manifest, byte for byte. The rows of mapped relations are part of those bytes. A replay that dropped or changed the view component cannot match.
- **The other checks stay.** Import pins are checked first, as before, and a wrong pin is refused without reading any mapping. Files outside the closure and a second main pack are still refused.

## Alternatives considered

- **Keep refusing every mapping.** The placeholder blocks every example that uses a theory. The byte comparison already proves that the view component was replayed.
- **Let the archived publisher read the mapping unchecked.** A malformed mapping would then reach archived code, which the boundary exists to prevent.
- **Compare the mapped rows separately from the bytes.** That is redundant: the bytes contain them, and a second comparison would need its own reference.
