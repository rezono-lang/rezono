# Require readable proofs for designated publication conclusions

A pack can derive `publication_required(role, relation, first, second)` from independent requirements. The last two columns name the first two key values of one required conclusion. The target must be a derived relation. The complete epoch must contain a unique conclusion for that key prefix, and the filtered role must have a checked proof of the same row. A requirement applies only when its role is in the publication in `may_read` mode.

The publisher checks requirements before writing any objects. The normal proof checker still verifies the complete and role snapshots. A withheld required conclusion refuses the whole publication. A withheld conclusion with no applicable requirement continues to be filtered out. The refusal contains no required key or proof contents.

The platform example derives its requirements from participation and measured pool periods. Withdrawing a notice leaves the requirement in place. Deriving requirements from the notices or the conclusions would lose the requirement when its source disappeared. Requiring every row of a relation would also block on other tenants' conclusions.

The platform imports an explicitly extensible declaration for the tenant summary. This allows an alternate proof in a separate rule file under the same module ownership checks as other extensions.
