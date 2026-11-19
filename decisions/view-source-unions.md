# Populate a theory kind from several source kinds

A theory view maps each theory kind onto source kinds of the domain. One theory kind often gathers elements that the domain keeps apart. A day on the `std-time` line, for example, may come from a backup copy, an inventory reading and a decision. Each of those has its own date slot. So far the view lowering accepted exactly one source branch per theory kind.

## Choice

- **One rule per branch.** A theory kind with several branches is lowered to one ordinary rule per branch into the same theory relation. An attribute or an arrow names the branch it is populated from, as it does now. Every theory row keeps the witness of the branch rule that derived it.
- **Plain identifiers.** The theory element keeps the source identifier unchanged, so a rule joins it with the source kinds directly. All branches must have the theory kind's identifier type, and no conversion is selected, as before.
- **Disjoint branches.** An identifier that occurs in two branches would make two domain elements one theory element. The lowering adds one invariant relation per theory kind with several branches. It holds every identifier found in more than one branch. A row there is an integrity violation that blocks the publication. It is never a silent merge.

Paths of arrows stay one per arrow, as now. A union of paths is a separate question.

## Alternatives considered

- **A tagged identity with root and identifier,** as a union in a typed identity keeps it. This is sound, but the theory relation has a single identifier column, and every rule joining a theory element back to its source would have to decode a tag. Disjointness keeps rules plain, and a violation still catches the case that tagging would hide.
- **One view per source kind into separate theory kinds.** The theory would then not describe one day line. Its rules would have to be repeated per source.
- **Refusing several branches,** as before. Packs work around it by copying dates into one kind, which loses the link to their source.
