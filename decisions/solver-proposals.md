# Solver proposals and rule witnesses

Keep a choice in the pack's rules whenever they can enumerate the eligible candidates and compare them over a complete scope. The rule applies the declared ordering and tie policy, and its witness identifies the eligibility, completeness and comparison grounds. [Project vision](../docs/vision.md)

A pack may use the offload contract to request a proposal only when enumerating the search space is impractical. For example, placing workloads on eligible machines may require searching combinations of assignments even when a proposed placement is cheap to check. The offload returns a candidate assignment. Pack rules check that every workload is assigned as required, every machine is eligible and all capacity and other declared constraints hold. Each accepted proposal needs independently checkable rule witnesses against the input facts, including the grounds for any completeness or absence claim. A missing ground leaves the requirement unproved. Applying a proposal requires those checks and the pack's existing authorization. [Offload contract](../contracts/offload.yaml)

## Provenance and replay

Record the result as an observation with the solver job as its source. Admission matches the result to the current step, unit and `input_sha256`. That hash commits to the canonical payload hash, parameter-facts hash, exact model hash, solver name and version, seed and time limit through `InputHash`. Keep those pins with the admitted result so its origin can be checked. A current proposal uses evidence pinned to the current input. Earlier results remain historical evidence. [Freshness contract](../contracts/freshness.yaml)

Keep the admitted result bytes and provenance for replay. A time-limited run may return another candidate with the same parameters and seed. The first admitted result for the same step, unit and input serves as evidence for reproducible publication, and repeated delivery leaves it in place. Replay reads the persisted observation as an input and reproduces the publication bytes.

Report `optimal`, `best-found` and `infeasible` with the solver as their source. Rezono's witnesses establish what the rules checked about a stated candidate. Global optimality and exhaustiveness remain claims of the solver.

## Alternatives and activation

Enumerating every assignment would preserve rule witnesses for the choice itself. It is suitable when the search space stays tractable. Giving the solver authority over acceptance would make the pack's correctness depend on the solver's policy implementation. The proposal boundary permits a large search while preserving rule-based acceptance.

Leave the contract unused until a concrete acceptance question requires a choice that pack rules cannot enumerate in practice. The first use must demonstrate why enumeration is impractical, how a valid proposal earns independent witnesses, and how stale or invalid proposals fail to earn them.
