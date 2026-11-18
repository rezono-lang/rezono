# Write safe steps in Rezono

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

Pass the compiler's resolved match relation, identifying column order, scoped blockers, typed delta templates, readback expectations and intermediate obligations to the [safe-round interface](safe-step-rounds.md#1-pack-interface-and-round-identity). Resolve operation, reader and coverage names in the pack's verified dependency closure. Use the existing rule checker, schema resolution, typed row delta and observation contracts. Validate the language and compiled contract before speculative evaluation. Dispatch, observed confirmation, width and batch choice, and transition certificates remain part of the safe-round interface.

| Building block | Read and lower acceptance |
| --- | --- |
| Whole-record assumption | Round-trip an authored record and its source positions. Lower the keyed row and each typed slot row. Apply to a fresh key and keep the original input unchanged. Reject an existing key, missing required field, duplicate field and a value of the wrong type. |
| Step declaration | Round-trip the exact typed declaration and its nested source positions. Compile matching and blockers, a complete typed effect, and the reader's post-state expectations through the ordinary module entry point. Refuse unscoped absence, unbound write keys, conflicting writes, unresolved bindings and an indivisible effect with incomplete declared observation coverage. A partial readback leaves the match waiting. |
| Intermediate invariant | Round-trip the explicit coverage option. Lower to one violation relation and both applicability checks. Reject duplicate options and invalid coverage bindings. An admissible base and variant with complete coverage can pass. An intermediate violation and an undecidable scope produce different obligations. An ordinary publication invariant retains its original applicability. |

Register these as three separate language building blocks. Freeze authored examples and separate reader and lowerer tests for each before implementation. The whole-record assumption depends on the question reader and existing delta shapes. The other forms depend on the typed native module reader and linker. The loop consumes the lowering results through its existing safe-round interface. Until the three blocks are available, packs continue to use typed LinkML records and ordinary Datalog alongside the explicit effect and coverage bindings in [safe transition rounds](safe-step-rounds.md#1-pack-interface-and-round-identity). Transition and live platform acceptance use the recorded safe-round scenarios independently of how those inputs were authored.
