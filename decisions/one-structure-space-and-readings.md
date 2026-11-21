---
decider: [language, core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: one-structure-space-and-readings
---

# Space is a theory, and a reading is a morphism whose losses are published

Rezono's foundations ([formal](../docs/formal.md)) already give one structure:
- a schema is a category, and a state is a functor into it;
- rules derive with provenance, so every conclusion has a witness;
- increments are exact (DBSP);
- facts have two times and four states;
- a view interprets a theory in a domain.

Two kinds of work were arriving beside that structure, as separate features with their own contracts.

**Place**
- An exact-geometry design was carried over from the predecessor: integer grids, exact predicates, bounded values.
- The viewer asked for an anchor field per row.
- There were cell covers for overlap and the fusion of two classifications.

**Sight**
- Each viewer sheet asked for a publication of its own (#1424, #1450).
- The viewer asked for alternative witnesses (#1445) and a stratum field.
- The viewer measured its own geometry.
- The checker has three functions that measure what a picture keeps (`checker/rezono_checker/semiotic.py`, `semiotic_order.py`, `semiotic_coverage.py`: containment, lane order, coverage), but only tests call them.

The owner decided on 21-11 to treat both as instances of Rezono's core, not as features beside it.

## Decision

### 1. Space is a theory

- A theory pack `std-space` declares, without facts:
  - **places;**
  - **parts,** with `part_of` reused from `std-part`;
  - **the region relations as axioms:** the eight relations of region connection, plus "on the boundary" as an answer of its own.
- It has two models:
  - **symbolic:** the part-of tree alone. For example, "this rack is in that hall", with no coordinates.
  - **geometric:** integer coordinates on a declared grid per reference system, with exact predicates and certificates. This is the exact-geometry design, as `std-geo`.
- A theory morphism connects the two: geometric containment implies `part_of`. Its satisfaction is tested like the other theory satisfaction tests, including a reversed case that must fail.

### 2. Anchoring is a view

- A domain binds its kinds to places with an ordinary view, like any theory binding.
- No contract has an anchor field.
- An anchor is a derived row, so it has what every row has:
  - **two times,** so an anchor per epoch;
  - **four states:** an unknown place, or `invalid` when two sources give two places, with both sources in the witness;
  - **a source and a witness;**
  - **access:** a place can be personal, and [personal data handling](personal-data-handling.md) applies to it as to any personal attribute;
  - **incremental maintenance.**

### 3. Spatial uncertainty uses the four states

- **Inside or outside.** Membership of a point or a cell is known true when inside and known false when outside.
- **Undecided.** On the boundary, or not yet decided by the cells, it is `unknown` with the reason `straddles`.
- **Absent needs a sweep.** "No overlap anywhere" is `absent` only with a complete sweep as its witness.
- **Contradictions are invalid.** Contradictory classifications of one place are `invalid`.
- **No separate model.** There is no separate rough-set or egg-yolk model. Those are the state order of Rezono, applied to space.

### 4. The proof graph is data that rules read

- Some things are derived relations over the published witness graph:
  - the derivation depth of a row (its stratum);
  - the founded alternative witnesses of a conclusion (#1445);
  - whether a premise is load-bearing.
- Rules derive them, and the checker checks them.
- They are not fields added for one consumer.

### 5. A reading is a morphism, and its losses are published

- **A reading** is a binding from a role's publication to marks: a sheet, a map, a 3D scene. It is declared in Rezono, in a pack's channels. A theory's channels give default readings to every domain bound to that theory.
- **The checker measures** each reading's preservation, per role, as exact counts, with the elements that break it. The measures:
  - order;
  - containment;
  - coverage;
  - distinctness;
  - conservation;
  - scale;
  - economy.
- **The report is published** beside the reading, as a view of its own.
- **Every preservation measure warns, and none blocks** (owner, 21-11). A broken obligation, even one a reading declares as its own (the part-of containment of a place layout, the incidence of a proof), is a warning with its offending elements. The checks that block today keep their status: exact quantities, invariants, witnesses, access.
- **A viewer draws** the reading and its report, and computes neither.

### 6. Layouts are readings of one publication

- **One graph, many layouts.** The derivation layout and the place layout are two readings of the same publication. The derivation layout preserves proof order; the place layout preserves the part-of tree and the geometry. Each has its own report.
- **Motion is the served delta.** Motion between epochs draws the delta between two publications, which the engine already computes. A viewer does not derive it.

### 7. The theory chooses the form

- **A theory's channels give its default readings.**
  - `std-part` already declares a Flow of parts.
  - `std-time` will declare its intervals and the bitemporal staircase over valid time and knowledge time.
  - `std-space` will declare the place layout.
- **A bound domain only adds labels.** A domain bound to the theory gets these readings, with only labels and house style of its own.
- **One reading per need, not one publication per sheet.** A viewer sheet that needs a new publication is first asked for as a reading of a theory.

## Order

None of this blocks release 1 (M1 to M4). It reframes work that is not built yet: the geometry design, the viewer's anchor request, #1445 and #1450. Everything here is `extra:`, in this order:

1. **`std-space`** as a theory, with the symbolic model and one domain bound by a view.
2. **The reading report.** The three existing checker functions grow from the old layout format to the reading contract. The report is published per reading and role, and warns.
3. **`std-geo`** as the geometric model, measured first: integer width in every engine, and point in polygon as rules against an independent reference.
4. **Relations over the witness graph:** stratum, alternatives, load-bearing.
5. **Default readings per theory,** starting with the bitemporal staircase of `std-time`. That answers #1450 for every domain bound to `std-time`.

## Red tests

A planner adds them as strict red tests marked `extra:`, each failing on current `main` for the reason it names:
1. `std-space` is a theory pack with places, `part_of` and the region relations, and it has no facts.
2. The morphism from the symbolic to the geometric model is checked, and a reversed binding fails.
3. An anchor bound by a view is a row with four states and a witness. Two sources that give two places make it `invalid`, with both sources in the witness.
4. Spatial membership gives known true, known false, or `unknown` with `straddles`.
5. Stratum and alternative witnesses are derived by rules over the published witness graph, and the checker verifies them.
6. The publisher publishes a reading report per reading and role, with exact counts and the offending elements for containment, order and coverage. A broken obligation shows as a warning and does not block publication.
7. A domain bound to `std-part` without channels of its own gets the Flow of parts as its default reading.

## Rejected

- **An anchor field per consumer.** It would give a second truth beside the domain, without states, time, witness or access.
- **Geometry only as an offload library.** Topology and membership on an integer grid are exact, and they belong in the rules. Only what cannot be exact goes to a tool.
- **Measuring fidelity in the viewer.** The viewer computes nothing, so the checker measures.
- **Blocking on a preservation measure.** The owner chose warnings. A measure says what a picture keeps; it does not prove that the picture is understood.

## Where this stops

- **What the report covers.** It measures declared structure. It does not prove that a picture is understandable (J. Goguen, *An Introduction to Algebraic Semiotics*, 1999), and review by a person remains.
- **What the morphism tests cover.** They cover the supported fragment, not every possible view.
