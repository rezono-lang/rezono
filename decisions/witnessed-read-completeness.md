# Witnessed completeness of a role's reading

A role may report an absent value in a closed relation only when it has authority over the whole relevant population. Seeing every element currently present does not establish that authority. Empty populations make the distinction particularly important.

A pack can opt into an explicit relation `may_read_full(role, kind)`. The shared access pack declares it extensible with two symbols and no clauses, like the three-symbol element right `may_read(role, kind, element)`. Importing the shared definitions alone grants neither. Consumer rules supply the grants. A fact or rule used to derive the completeness row need not be a rule granting an individual element. A view of a theory still refers to the original element kind for its rights.

For an explicit program the publisher uses the evaluated role-and-kind row and its ordinary rule witness. It checks that every element in the covered kind, including elements reached through the existing kind hierarchy, is readable. A coverage claim confers no element rights. A role with individual rights alone may publish exactly those elements, even if they happen to be every current element. Neither an empty kind nor an unbound role acquires coverage by coincidence.

The checker derives the same authority independently from the complete snapshots and the checked rule instances. The evidence for an explicit grant names the kind, the actual deriving rule and the ground row `["may_read_full", role, kind]`; that row identifies the witness and its premises. A missing witness, a mismatched role or kind, or a missing underlying element right cannot certify completeness. The rule identifier is not fixed by the interface.

Programs predating the explicit relation retain the semantics of their own recorded access format so archived publications can still be checked. Newly migrated consumer packs state every completeness grant they need explicitly and update their pinned imports. An explicit program never falls back to recognizing the spelling or shape of its element rules.
