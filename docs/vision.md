# Vision

Rezono is a domain-neutral, verifiable reasoning layer.
It turns facts with an origin into conclusions with a proof, and publishes them so that every reader can check them.
This page says what that means in practice, so that every change can be held against it.
The working rules in `AGENTS.md` are the short form; this page is the reason behind them.

## Facts and conclusions

- A fact has an origin: a decision, a vendor publication, a design choice or an observation. A row without an origin is not a fact.
- A conclusion is derived by a rule. If a rule can derive it from what the same publication holds, it is not written down.
- A rule that only reads back one stored row concludes nothing. A conclusion combines independent grounds.
- What another system stored (a table, an export, a script step) is a source with provenance, never the origin of a fact.

## Rules, not scripts

- What follows from facts is a rule in a pack, written in Rezono with Datalog semantics including recursion, negation and counting. No production code walks a graph, sums a column or picks a winner. An independent oracle in the tests may, and should, compute the same answer its own way.
- Code may read input, render output from derived rows, apply a plan, and observe. It does not decide.
- Everything that follows is compiled: tables, checks, explanation queries, sentences, admission policy, firewall rules, publication. Generated output is never edited by hand.
- A standard pack (`packs/std-*`) is used wherever it fits: time, order, parts, identity, decisions, access, the loop and the view. An example does not grow its own variant.

## Proof

- Every derived row has a witness: the rule, its bindings and its premises.
- An independent checker verifies witnesses without trusting the engine.
- A witness names every ground it needs, including what was checked to be absent and the rows a count or a choice ranges over.
- The two engines (batch and incremental) must agree on conclusions and on witnesses.

## Exact and deterministic

- Money and ratios are exact fractions. There is no floating point.
- The same input gives the same bytes. A publication has one canonical hash, which any reader can recompute.
- No clock time is added when publishing, no unseeded randomness, a fixed order everywhere. Recorded observation times are data and may be part of a proof.

## Unknown is explicit

- A missing value is never read as "no", as zero, or as "fits".
- "Not observed" is unknown unless an observation was complete for that scope, and the completeness is itself a row in the proof.

## Access

- A role reads a publication of its own.
- A conclusion is published to a role only when its whole proof is readable to that role. There is no hidden step in a proof.
- What a role needs but may not see is published as a row of its own, by the party that may see it: for example, free capacity or a total. For the reader it is a fact with that party as its origin; its own proof stays in that party's publication.

## What if

- An assumption changes a fact; the same rules derive the world under it.
- The answer is a difference in rows, each with weight +1 or −1 and a witness. A changed row counts on both sides.
- Observations do not change under an assumption: the real world stays the same.
- A sweep runs one assumption over a range of values; the turning point is where the outcome changes, with the proof on both sides.

## The loop

- Rezono derives the desired state; existing tools apply it; their status comes back as an observation.
- Six relations carry the loop: needed, known, waiting on, ready to do, done, and stuck. They are rules in `std-loop`.
- A step is done only when an observation from the same run confirms it.
- Desired versus observed is a rule. A difference is a finding with a proof.

## What Rezono is not

Ticketing systems manage incidents and work queues. Monitoring and SIEM systems collect signals and manage alerts.
Identity services, secret stores and certificate authorities manage identities, secrets and certificates.
Scanners inspect systems, backup tools make and restore copies, and GitOps controllers reconcile configuration.
The CMDB maintains inventory. Procurement manages purchases and accounting maintains the ledger.

Rezono publishes the typed desired state, what independent evidence establishes about the actual state, and the next safe step justified by facts and decisions.
The reference platform reads external observations and records as evidence or comparison sources, with provenance for each.

## Two kinds of comparison

- An oracle checks that Rezono computes correctly. It is independent and runs only in tests. A difference blocks: it is a bug in Rezono, unless checking both against the rule shows that the oracle was wrong.
- A reference source checks that what Rezono derives agrees with what was observed, or with what another system registered. A difference is drift: a finding with a proof from both sides, shown to readers.
- Keep the comparisons separate. The [formal foundations](formal.md#11-independent-oracles) record which independent comparisons run and what each one checks.

## Reading

- A publication carries everything a view needs: rows, witnesses, messages, the key of signs, positions and precomputed answers. A view computes nothing.
- Texts for readers live in message catalogues per language, never in code.
- Every view has a table twin, a legend for every sign, and the verbs: why, what depends on this, what is missing, what if, compare, and propose.

## How to use this page

Before building, ask of each change:
1. Is this a fact with an origin, or a conclusion that a rule should derive?
2. Is a decision being made in code that belongs in a rule or a standard pack?
3. Does every derived row carry a complete witness, and could a role read all of it?
4. Is anything unknown being read as no, zero or fits?
5. Is this an oracle or a reference source, and is it kept apart?
