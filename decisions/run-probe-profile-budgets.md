# Probe profiles and phase budgets

The Run pack `run/packs/probe-profiles` owns the reader question `probe-profile-budgets`. A reader needs to see the cells and cluster sizes a profile calls for, which cells require physical machines, and the time budget for each phase of each storage variant. Use the profile and cell identifiers from the approved design. Use separate variants for assisted installation and installation without manual work, even when they use the same storage technology.

A shared installation budget would give a single limit for different installation work. Separate terms let the authority approve each variant and let the witness show which limit applies.

## Facts and decisions

| Input | Origin and purpose |
| --- | --- |
| Profile, cell, planned cluster and member | An approved probe design identifies the profile, its cells and the planned memberships. These identities describe the scope of the question independently of any machine inventory or provider request. |
| Phase and storage variant | The design identifies the phases, their ordering scale, and the installation method of each variant. A phase retains the same identity when another variant sets a different budget for it. |
| Physical requirement | A platform design authority records the requirement for a specific profile or cell in a dated decision. The term records what applies, including an explicit permission where physical machines are optional. |
| Phase budget | The probe authority records an approved duration in seconds for an exact profile, storage variant and phase. Each term identifies its decision, actor and decision date, its effective interval and the originating record. |
| Reference time and coverage | A recorded planning snapshot identifies the evaluation time and whether the profile membership and decision terms are complete for the stated scope. A partial snapshot can still support individually present facts. |

A requirement or budget carries the identity of its own `std-decision` record. A narrow typed term gives that decision its profile, cell or variant and phase. The decision register supplies the actor, date and standing. The phase budget is an authorized limit. Run measurements have their own observations and provenance.

## Derivation and publication

Use `std-part` to resolve members through cells and clusters and `std-order` for phase order. Count the planned members in a complete scope to publish the cluster sizes and profile totals. Use `std-time` for the evaluation interval and `std-decision` for the terms in force. Resolve any sourced alternate identifiers through `std-identity`.

The latest recorded snapshot of a profile governs, whether it is complete or partial, and its reference day is the evaluation time for every requirement and budget term. Earlier snapshots are history. A term that ended or was replaced on or before the governing day is not published, even when it was in force on an earlier snapshot. Choosing the latest complete snapshot instead was considered and rejected: a newer partial snapshot still fixes the evaluation time and supports the facts that are present, so falling back to an older complete one would republish terms that have since ended.

Select a budget only when the profile, variant and phase all match. Derive the physical requirement from the applicable decision for the requested scope. Publish the known amounts and requirement decisions, with separate status rows for an unresolved requirement or budget. A certified complete scope with no applicable term supports a missing-term finding. Partial coverage or conflicting applicable terms leave the affected answer unknown. An automation-only budget requires a term for that exact variant.

The question in `questions.yaml` links the profile cells and phase budget rows to `grounds` from `std-explain`. A witness cites the design membership, the relevant coverage for a count or absence, the phase and variant, and the effective decision. A role receives a row when it can read a complete witness. Keep the question title, description and headings in the pack's message catalogue. Pack rules derive the counts and apply the terms. Adapters carry the recorded inputs into the pack.

## Independent acceptance evidence

Use a handwritten design with one control member and two worker members. The separate dated budget decisions allow 600 seconds for provisioning and 300 seconds for cleanup in each variant. They specify 900 seconds for assisted installation and 420 seconds for automation-only installation. A handwritten expectation gives the membership counts and the distinct budget rows. Removing the automation-only installation term from a certified complete register yields the corresponding missing-term finding. Withholding coverage leaves that term unknown. Withdrawing the physical decision removes the supported requirement while retaining the independently supported budget rows.

Give `run/tests/test_probe_profile_budgets.py` its own acceptance expectation. Read the published question, rows and witnesses through the ordinary publication path, including a role that lacks a required ground. The fixture's handwritten counts and budget values are the oracle. A later measured duration is an observation for a different question.
