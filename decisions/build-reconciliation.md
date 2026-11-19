# Derive build choices from observations

Use the build selection pack to derive which suites a recorded change reaches. Keep the existing CI and claim policies authoritative during comparison. The first executable slice publishes pull-request suite selection through the ordinary publisher and verifies it with the independent Python selector on the same captured input. It uses the pinned `std-loop` sweep receipt, which in turn imports `std-order`. Task placement and claim release use the later relations specified below. [Project vision](../docs/vision.md) · [Loop rules](../packs/std-loop/pack.yaml) · [Safe transition rounds](safe-step-rounds.md)

## Observed kinds

| Kind | Independent origin and acceptance question |
| --- | --- |
| `BuildRun` | A GitHub event and a protected engine checkout identify one input. Can a reviewer establish the event kind, exact diff base and head, engine commit and recorded observation time for a selection? |
| `BuildComponent` | Test-suite discovery observes an executable check standard. Which suite was available to select in this run, and was it a Python, Node or contract suite? A manifest alone does not establish test discovery. |
| `BuildManifest` | An exact regular Git blob contains a Python or Node declaration. Was a dependency declared at either endpoint of this observed range, and which blob carried it? |
| `BuildTestFile` | A source inventory records an actual file in a suite. Which test file can the suite account for? A package declaration does not enumerate its test files. |
| `BuildDependency` | The typed manifest import resolves a declared local dependency, or an explicit read binding establishes a file consumer. Is there a sourced dependency from this suite to that consumer at this cut? |
| `BuildPath` | The recorded Git diff contains a changed path. Was that path in the reader map's scope? A known path with an empty reader set is distinct from an unknown path. |
| `BuildPathReader` | The reader inventory identifies a path's owner or consumer. Does the observation make it directly selectable or supply a root whose transitive dependents also run? |

The typed capture reads manifests and source inventory without running candidate code. Read regular manifest blobs from both exact endpoints, recording their path, revision and blob. Use the package imports and the published test-file/read map for dependency and reader observations. A change that removes a declaration can still reach a suite through an edge observed at the base. The existing Python implementation provides a test oracle for manifest resolution, range and selection. Its result is not an input to the pack rules. [Current selector](../scripts/components.py)

Bind one immutable observation to each run attempt. Preserve the raw PR event head separately from the effective exact checkout when they differ. Preserve the actual merge-group event range. A complete capture binds the suite universe, diff paths, both endpoint manifest inventories and reader mapping to the same run and recorded time. A matching `LoopSweepReceipt` supplies the positive coverage relation. Input capture uses the recorded source event time. It never substitutes the wall clock. Verify the range, source identities, input digest and protected-main engine commit before trusting the manifest. Unknown or incomplete input, engine failure, or an invalid publication all require full checks with the reason in the run summary. [Observation contract](../contracts/observation.yaml) · [Manifest contract](../contracts/manifest.yaml)

## Selection and publication

A mapped path's direct readers run. Its transitive readers also seed ordinary recursive dependency rules. Treat file consumers and both endpoint declaration graphs as parts of this evidence. Direct-only readers do not seed closure. A known readerless document adds no suite. An unknown path requests every suite, with the source path as evidence. A missing same-run receipt, invalid dependency origin or invalid reader binding produces an explicit full-selection reason.

Publish `build_selected_job(run, component, reason)` with a proof per row. Publish `build_full_selection(run, reason)` separately. Verify one manifest per observed run attempt and read the selected suite set after the checker verifies the publication. Trusted output glue expands the suite IDs to the configured job and shard matrix. The first slice handles PR selection with supplied verified observations. A merge-group observation in this slice yields an explicit unsupported-policy reason. The existing merge-group checks remain in effect until their separate policy is modeled and compared. Fetching an untrusted revision is sufficient for capture. The pack, engine, dependencies and verifier execute from a pinned protected-main checkout.

## Task and queue observations

Derive task states from the imported `std-loop` relations using task prerequisites, current claims and observed PR state. Observe PR checks and run minutes with dated origins. Use `std-decision` to hold the effective claim lease, queue bounds and task priority limits. When choices are available, the language task precedes the core task, a queue of thirty denies a planner slot under the named decision, and an unfinished prerequisite keeps its task waiting. An outranked task cites its rank and the winning work. Unknown queue coverage or an incomplete inventory does not prove planner capacity: only the admitted member inventory of a pull listing does ([admission transport](admission-transport.md), section 6, queue pulls). [Decision library](../packs/std-decision/pack.yaml) · [Order library](../packs/std-order/pack.yaml)

| Kind | Independent origin and acceptance question |
| --- | --- |
| `BuildTask` | An observed task declaration identifies a step and track. Which observed tasks does the standard loop class as ready, waiting or stuck at this cut? |
| `BuildPolicyDate` | The observation adapter derives the reference day from the recorded cut. Which policy day applies to this run? |
| `BuildTrackRank` | An effective decision assigns a track priority. Which ready task precedes another under those decision rows? |
| `BuildQueueLimit` | A decision supplies the planner threshold. Which threshold establishes or denies a free planner slot? |
| `BuildQueueReading` | An independent queue reader reports a count and event time. It establishes no count, because no rule can check a reported number against the pull requests it counts; it remains a record to compare. |
| `BuildQueueListing` | A pull listing of one base at the run's cut names the receipt of its protected read. Do the admitted `queue-listing` and `queue-pull` members of that receipt establish the queue, or is it missing, stale or contradicted? |

Publish the witnessed task relations and planner decisions as read-only findings. The first task-order slice accepts supplied `std-loop` step and requirement observations. It consults effective policy at the recorded reference date. The real red-list, PR observation and claim adapters remain separate integration work.

## Claim release

Evaluate expiry at the observation's recorded time. Read the effective lease duration from its decision, starting with four hours. Eligibility alone can yield only a plan. The same lease/generation authority must guard both opening a PR and deleting a claim, and the adapter must conditionally recheck generation, expiry and PR absence at deletion. A reopened or newly created PR, a renewed lease, or unreadable state prevents deletion. Verify absence of that exact generation with a completed read in the same run before reporting completion. An uncertain effect is reconciled under its original claim. Exercise expired, renewed and renewed-during-delete leases, a PR opened between the initial check and deletion, and a replacement ref before absence confirmation. [Effect protocol](../contracts/effect.yaml) · [Claim model](../formal/Claims.tla)

## Transition evidence

Compare the pack and the existing Python selector and claim policy against the same immutable observation, including its time and both Git endpoints, for a full week. Compare sets of selected suites and eligible claims before expanding jobs. Record and repair each disagreement, and use the Python result while a verified result disagrees. Capture or verification failure requests full checks. Switching merge-group selection additionally requires at least one completed day of PR-selection evidence with no merge-group failure that the PR selection should have caught. Both gates apply independently. Until then the Python decision routes and the native merge-group behavior stay in use. Once those gates and the proof-bearing acceptance cases hold, retain input and output adapters and retire the duplicated policy.
