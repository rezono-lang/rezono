---
decider: [language]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: in_force
subject: language-safe-steps
---

# Write safe steps in Rezono

> **Scope across language versions:** These three building blocks continue to be built in `rezono 0` (`rezono.module/4`). Platform steps convert once with platform rules to `rezono 1` (`rezono.module/5`), where [`decisions/language-rezono-1.md`](language-rezono-1.md#3-effect-on-prior-decisions) specifies how `step` clauses and `invariant intermediate within` read functional derivations.

A pack can write a whole-record assumption, declare a step with its typed effect and confirmation, and mark a publication invariant for intermediate states. These three language additions use the modeled operational rows, observation cut and safety rules of [safe transition rounds](safe-step-rounds.md). The declaration supplies inputs to those rules. The round checker still decides whether an effect is safe, whether it is selected, and whether a later readback confirms it.

## 1. Insert a complete record with suppose

A whole-record assumption applies only to the current session or question.

```rezono
+ Policy policy-a {mode = "enforce", zone = Zone:`zone-a`}
```

The kind and identifier use the same `Type` and `rowId` grammar as `- Policy policy-a`. Braces contain a comma-separated list of named slot assignments. Empty braces are allowed when the kind has no required slot other than its identifier. Each value uses the ordinary expression grammar. Print one space around each `=`, one space after each comma, and the fields in authored order. The question tree stores the key as text and the slot values as expression nodes.

```json
{
  "insert_row": {
    "kind": "Policy",
    "key": "policy-a",
    "slots": [
      {"name": "mode", "value": {"lit": "\"enforce\""}},
      {"name": "zone", "value": {"lit": "Zone:`zone-a`"}}
    ]
  }
}
```

Check the identifier's type, the kind, and the slots against the resolved schema. Require every required field, including inherited fields. Reject duplicate, unresolved and read-only slots, assignments to the identifier, and incompatible types or cardinalities. A field's explicit value state follows its slot's existing rules. A missing required field remains a diagnostic. Check freshness against the whole relevant keyed relation before exposing the new record. An existing key is a diagnostic even when its values agree. If freshness cannot be established, the assumption needs that ground before it can apply.

Lower to the existing `insert` change with kind, key and slot values, then expand it to the kind row and its slot rows. The speculative path does not choose a fact file. A persisted proposal still needs the fact target required by the [delta contract](../contracts/delta.yaml). Check the complete change before applying it to the question's variant. The existing `+ path = value`, `- path` and `- Kind id` forms keep their trees and behavior. See [question expressions](../docs/rezono/expressions.md).

## 2. Declare a step

```rezono
step install_policy(change: PolicyChange)
  when approved(change)
  forbid active_policy(change.target) within policy_inventory(change.zone)
  effect ruleset_install
    + ActivePolicy change.target {mode = change.mode, zone = change.zone}
  confirm policy_readback(change.zone) token change.confirmation
```

The header uses a local name and the existing typed rule column syntax, with one or more ordered columns. One indented `when` clause takes an ordinary `Expr`. Zero or more `forbid` clauses follow. One `effect` names a resolved operation and contains one or more indented changes. One `confirm` names a reader call and a token expression. The printer writes this order and indents each level by two spaces.

The module tree stores the new declaration and the existing expression nodes.

```json
{
  "step": "install_policy",
  "columns": [{"name": "change", "type": "PolicyChange"}],
  "when": {"call": ["approved", [{"path": ["change"]}]]},
  "forbid": [
    {
      "pattern": {"call": ["active_policy", [{"path": ["change", "target"]}]]},
      "within": {"call": ["policy_inventory", [{"path": ["change", "zone"]}]]}
    }
  ],
  "effect": {
    "operation": "ruleset_install",
    "changes": [
      {
        "insert_row": {
          "kind": "ActivePolicy",
          "key": {"path": ["change", "target"]},
          "slots": [
            {"name": "mode", "value": {"path": ["change", "mode"]}},
            {"name": "zone", "value": {"path": ["change", "zone"]}}
          ]
        }
      }
    ]
  },
  "confirm": {
    "reader": {"call": ["policy_readback", [{"path": ["change", "zone"]}]]},
    "token": {"path": ["change", "confirmation"]}
  }
}
```

Omit `forbid` when the declaration has none. Both calls on a `forbid` line are direct relation calls. The left call is the forbidden pattern and can use the existing rule wildcard in a column. The right call uses bound values to identify the inventory and its exact scope for each pattern. A closed modeled domain can discharge that obligation. Observed or open input requires a matching completeness receipt for the reader, scope, observation window and cut. Write row-pattern negation in the scoped `forbid` clause. Refuse a scope call unrelated to the forbidden keys and any unbound identifier. Ordinary `when` comparisons and confirmable prerequisite tokens use the existing rule type and evidence checks.

The match uses the existing finite, safe rule binding discipline. The step key is the owning pack and module's declaration identity followed by the ordered typed bindings in `columns`. Every key needed by the effect, including a fresh record key, must be a deterministic expression of those bindings and pinned constants. Keep distinct witnesses for one match and schedule its key once. The exact effect plan and attempt retain their own identities across rounds.

The effect changes are a closed union. In the table, `key` and `value` are expression trees, `kind` and `slot` are resolved names, and `slots` uses the same entries as the question form.

| Spelling | Tree |
| --- | --- |
| `+ Kind key {slot = value}` | `{"insert_row": {"kind": kind, "key": key, "slots": slots}}` |
| `- Kind key` | `{"retract_row": {"kind": kind, "key": key}}` |
| `+ Kind.slot(key) = value` | `{"set_slot": {"kind": kind, "slot": slot, "key": key, "value": value}}` |
| `- Kind.slot(key)` | `{"retract_slot": {"kind": kind, "slot": slot, "key": key}}` |

Lower each matched change to typed insert, delete, set or unset with the exact expected old rows and signed changes. A replacement retracts the old value and adds the new one. A fresh insertion must supply the complete record. Refuse conflicting and repeated writes before applying or combining changes. Only modeled operational rows may change in the variant. A step has one independently observable effect. Several writes in one declaration need one typed operation binding to a documented adapter boundary that guarantees their indivisibility and has a failure test. Separately observable writes belong in separate steps. The existing [effect contract](../contracts/effect.yaml) binds the exact plan and attempt.

The compiler derives confirmation expectations from the declared writes. It binds the resolved reader and token to the exact effect and expands the same writes into subject, attribute and typed post-state expectations. For a record insertion, this includes the record's identity and every promised cell. For delete and unset it includes the corresponding absence under complete coverage. A single readback must cover the entire promise, including every touched key of an indivisible multi-row effect. The reader must support all declared target scopes. Actual confirmation requires independent matching evidence in the same run, with an event time and admissible observation cut that can confirm this attempt. A later cut must establish its relationship to the attempt. Foreign, stale, incomplete and contradictory evidence leave the obligation open. The effect response and the speculative result supply no readback. See the [observation contract](../contracts/observation.yaml).

## 3. Mark an invariant for intermediate states

```rezono
rule missing_policy(endpoint: Endpoint) invariant intermediate within policy_coverage when exposed(endpoint) and lacks_policy(endpoint)
```

`invariant intermediate within` takes a resolved coverage relation name and appears only on the owning typed derived rule head. Its option node is `{"invariant": "intermediate", "within": {"relation": "policy_coverage"}}`. Bare `invariant` keeps its publication-only behavior and the existing `{"invariant": true}` form. Reject repeated invariant options, missing or ill-typed coverage, and a positional or extension clause that tries to declare the option.

Lower to the existing publication violation relation with `invariant: true` and an intermediate obligation referencing that same relation and its resolved coverage binding. The coverage supplies the finite applicability inventory, the scopes and the readings needed to decide it. An empty violation relation is decisive only after the applicable scopes and required evidence are established. A violation reports the offending bindings. Missing grounds yield a waiting obligation for each affected step or batch variant. Publication still runs its usual invariant check. Speculative violations stay with the variant.

## 4. Formats, lowering and acceptance

Use the existing unversioned question JSON tree for the new `insert_row` alternative. Use `rezono.module/4` for a module containing `step` or `invariant intermediate`. A module that uses neither keeps the format it already requires. Formats `/1`, `/2` and `/3` retain their closed shapes and bytes. In `/4` include the same module envelope and canonical JSON as earlier forms. Anchor the declaration, column and field nodes at their names. Anchor forbids and confirmation at their keywords, the effect node at the operation name, and each change at its operator. Record each nested expression at its usual source span. Anchor the intermediate option at its `invariant` keyword and its `within` node at the referenced relation name. Place entries retain the existing ordering and offsets. The ordinary reader, printer and typed [module contract](../contracts/rezono-module.yaml) must agree on the closed shape.

### Compiled handoff

Ordinary `pack.read` returns two typed tuples on the resolved `Pack`, empty when the forms are unused. Both reference the same checked relation names in `Pack.rules` that `emit.compile_pack` writes to [`ir/rules.json`](../contracts/rules.yaml). Match, pattern, coverage and reader bindings require signatures with resolved schema types from native rule heads or modeled kind and slot relations. A consumer loads the pinned pack through that entry point alongside its rule IR. The handoff uses the compiled pack in memory and leaves the existing rule IR and publication formats intact.

| Pack field | Resolved entry |
| --- | --- |
| `steps` | A `CompiledStep` has an `id` (the ordered triple of owning pack, module and local name), a derived `match_relation` for the positive match, and its identifying `columns` in authored order. Use the native linker's column triples: name, resolved schema type and engine type. Each of its `blockers` binds a forbidden `pattern` and a `coverage` call to checked relations with typed operands. Keep different witnesses for the same ordered match key. |
| `intermediate_invariants` | An `IntermediateInvariant` has a violation `relation`, a `coverage_relation`, and its `key_binding`. The binding is an ordered tuple of column pairs, each with the violation column first and the corresponding coverage key column second. Require the same name and resolved schema type. Extra coverage columns distinguish scopes and readings. Reject a missing or incompatible binding. Emit the violation once in the ordinary IR, with `invariant: true`. |

A resolved call has a `relation` and ordered `operands`. A typed operand carries its `expr` with resolved names and its schema `type`. Only a forbidden pattern may also have a wildcard operand. A compiled step's `operation` identifies the `port` and its `apply` operation and retains any declared `boundary` and `evidence`.

The `changes` use the existing [delta operation](../contracts/delta.yaml) meanings, with `op`, `kind`, `key` and the applicable `slot`, `value` or `values`. Type the operands over the match columns and pinned constants. Instantiating these templates against the pinned base computes the expected old rows and signed row changes. The [effect plan and attempt](../contracts/effect.yaml) bind the instantiated effect.

The `confirmation` has a resolved `reader` (its `port`, resolved `call` and `scope` columns), a typed `token` and `postconditions` derived from the same writes. Each postcondition has a typed `subject` identifier and an `attribute` naming the resolved kind and optional slot. The kind alone denotes record identity. A `present` postcondition carries the expected typed value and an `absent` postcondition requires evidence of absence. Unknown or invalid observation states cannot satisfy either.

### Pack bindings

Include `ports/<name>.yaml` in the shared pack definition inventory so their bytes are copied and hashed alongside `pack.yaml` when verifying the dependency closure. Read each file with `rezono_ports.load` under the existing [`Port` contract](../contracts/port.yaml) and require the declaration name to match the file. Resolve an authored effect name to a unique visible effect port's `apply` operation. An optional `safe_steps` block in `pack.yaml` binds the port declarations to typed pack relations. Refuse unknown members, duplicate bindings, ambiguous names and incompatible types.

- `readers` entries have `relation`, `port`, `scope` and `targets`. The relation is the checked signature named by `confirm`, the port is a visible input port producing the typed observations for this reading, and the scope is a nonempty ordered list of named key columns of that signature. A target names a resolved `kind` and optional `slot`. The kind alone denotes record identity. Check that every expected postcondition has its target, including identity and all promised cells on an insertion. Bind each call to the declared scope. The declaration specifies where to seek readback. An independently observed receipt still has to cover the bound reader, scope, event window and cut.
- `atomic_effects` entries have `operation`, `boundary` and `evidence`. The operation resolves as above. The boundary names the adapter's indivisible visibility boundary and the evidence is a typed [row reference](../contracts/proof.yaml) to its independent failure-test result. Refuse a multi-write step with no binding or incomplete declared readback targets. Before dispatch, verify the referenced result against the pinned adapter, its boundary and the failure test's observations. Refuse dispatch when that verification fails or the evidence is unavailable.

### Evaluation and acceptance

The [safe-round consumer](safe-step-rounds.md#1-pack-interface-and-round-identity) establishes the finite applicable inventory and scoped coverage before evaluating forbidden absence or a zero violation count. Apply the key binding against the same pinned rules and observation cut for each base and variant. A witnessed violation gives offending bindings. A decisive clear result requires complete applicable coverage. Missing applicability or evidence gives a waiting obligation naming the missing ground. Dispatch requires independent verification for the exact base and cut. Completion requires independent matching [observations](../contracts/observation.yaml) for all postconditions in the same run, under an admissible cut causally linked to the same attempt. A partial readback leaves the obligation waiting. Dispatch, observed confirmation, batch choice and certificates belong to safe-round evaluation.

| Building block | Read and lower acceptance |
| --- | --- |
| Whole-record assumption | Round-trip an authored record and its source positions. Lower the keyed row and each typed slot row. Apply to a fresh key and keep the original input unchanged. Reject an existing key, missing required field, duplicate field and a value of the wrong type. |
| Step declaration | Round-trip the exact typed declaration and its nested source positions. Compile matching and blockers, a complete typed effect, and the reader's post-state expectations through the ordinary module entry point. Refuse unscoped absence, unbound write keys, conflicting writes, unresolved bindings and an indivisible effect with incomplete declared observation coverage. A partial readback leaves the match waiting. |
| Intermediate invariant | Round-trip the explicit coverage option. Lower to one violation relation and both applicability checks. Reject duplicate options and invalid coverage bindings. An admissible base and variant with complete coverage can pass. An intermediate violation and an undecidable scope produce different obligations. An ordinary publication invariant retains its original applicability. |

Register these as three separate language building blocks. Freeze authored examples and separate reader and lowerer tests for each before implementation. The whole-record assumption depends on the question reader and existing delta shapes. The other forms depend on the typed native module reader and linker. The safe-round implementation consumes the lowered results at the pinned pack boundary. Until the three blocks are available, packs continue to use typed LinkML records and ordinary Datalog alongside the explicit effect and coverage bindings in [safe transition rounds](safe-step-rounds.md#1-pack-interface-and-round-identity). Transition and live platform acceptance use the recorded safe-round scenarios independently of how those inputs were authored.
