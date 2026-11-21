---
decider: [language, core, platform]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: personal-data-handling
---

# Mark personal slots, forbid rules from reading them, and block personal data from public roles

Rezono's reasoning layer derives verifiable conclusions with complete witnesses and immutable, content-addressed publications ([vision](../docs/vision.md)). Once real personal data enters a deployment, two obligations collide unless separated at the schema and compiler boundary:

1. **Auditability and immutability:** published facts, witnesses, and Merkle trees remain verifiable over time.
2. **Data minimization and erasure:** personal attributes (names, contact details, addresses, national identifiers) must never leak into public publications, logs, commits, or proofs, and must be erasable per person when required.

This decision defines the opaque identifier discipline, the `personal` slot marker in schemas and `.rezono` modules, the compiler/checker refusal (`R054`) forbidding any rule from reading a `personal` slot, the crypto-erasure storage boundary, and the publication-boundary check (`rezono:personal`) that blocks any person ID or personal row from reaching a public role. The separate per-person encrypted store itself is deferred until a deployment handles real personal data; this decision and its strict red tests fix the language, compiler, checker, and publication contract now.

## 1. Opaque random person identifiers only — never hashes

A person appears in facts, witnesses, sources, commits, or logs **only** as an **opaque random identifier** minted per person (for example, a cryptographically random UUID or token with no deterministic relationship to any personal attribute).

- **Never a hash:** A person identifier MUST NOT be a hash (neither unsalted nor salted/keyed) of a national ID, name, email address, date of birth, or any external register key. Anyone with access to the input space (or a leaked salt/key) could recompute the hash, test membership, or correlate records across publications.
- **Synthetic placeholders in examples and tests:** Real personal records and real national identifiers never enter the repository. Example packs and tests (such as [the three-source healthcare allowance](healthcare-allowance-three-sources.md)) use invented synthetic keys (for example `p-ann`) as stand-ins for opaque random identifiers.

## 2. Marking a slot `personal` in schemas and `.rezono` modules

A scalar attribute whose values are personal data may be marked `personal`:

- **In LinkML schemas (`schema/*.yaml`):** via the boolean annotation `personal: true`:

  ```yaml
  classes:
    Subject:
      attributes:
        id:
          identifier: true
        display_name:
          range: string
          annotations:
            personal: true
  ```

  `"personal"` is added to `ANNOTATIONS` in [the pack loader](../compiler/rezono_compiler/pack.py). Its value must be a YAML boolean (`true` or `false`, default `false`); any non-boolean value is a compile error. Placing `personal` on a schema, a class, an identifier slot, or an arrow (reference to another kind) is refused at compile time.

- **In `.rezono` modules (`rezono/src/module-slot.ts` and `compiler/rezono_compiler/rezono_slot.py`):** via the trailing `personal` modifier on a slot declaration ([slot syntax](language-slots.md)):

  ```rezono
  kind Subject world closed
    display_name: Text personal
  ```

  The module JSON form records `"personal": true` on `SlotDecl`, and `rezono_slot.lower` lowers it to LinkML `annotations: {"personal": True}`. Writing `personal` on an `identifier` slot or an arrow slot is refused.

- **In the compiler IR and schema bundle:**
  - `Slot.personal: bool = False` in [pack.py](../compiler/rezono_compiler/pack.py).
  - `Attribute` in [the schema bundle contract](../contracts/bundle.yaml) gains an optional boolean field `personal` (written as `true` only on personal attributes, omitted otherwise).
  - A `personal` slot may not participate in a `unique_key`, a `path_equation`, a sweep (`explore`), a seal (`seal` / `sealed_with`), or a public `constant` / `rdfs:label` exposure.

## 3. No rule may read a `personal` slot (`R054`) — the crypto-erasure boundary

**No rule or calculation may read a `personal` slot.**

- **Datalog rules (`rules/*.dl`, [rules_dl.py](../compiler/rezono_compiler/rules_dl.py)):** Any rule that references the table `<kind>__<slot>` of a `personal` slot — in a positive body literal, a negative body literal (`!<kind>__<slot>(...)`), or an aggregate (`count : { <kind>__<slot>(...) }`) — is refused at compile time with diagnostic **`R054`**.
- **Native Rezono rules ([native_rule_signatures.py](../compiler/rezono_compiler/native_rule_signatures.py) and [native-rule-check.ts](../rezono/src/native-rule-check.ts)):** Any path expression traversing a `personal` slot (for example `s.display_name`) is refused with **`R054`**.
- **Calculations (`calc/*.yaml` / `rezono_calc.py`):** Any calculation rule referencing a `personal` slot is refused with **`R054`**.
- **Independent checker defense in depth:** The checker also refuses any rule IR whose body or aggregate references a table belonging to an attribute marked `personal: true` in `bundle/schema-bundle.json`.

### Diagnostic code `R054`

`R054` is the next unused refusal code after `R053` ([fact origins](fact-origin-required.md#4-phasing-and-codes)). Its templates are added to `rezono/messages/en.json` and `rezono/messages/nl.json` with `{0}` naming the personal slot (`<kind>.<slot>` or `<kind>__<slot>`):

| Code | en | nl |
| --- | --- | --- |
| `R054` | rule cannot read personal slot `{0}`; personal slots live outside the reasoning layer so discarding a person's key erases their data | regel mag persoonlijk veld `{0}` niet lezen; persoonlijke velden leven buiten de redeneerlaag zodat het weggooien van een persoonsleutel die gegevens wist |

### Why this establishes crypto-erasure

Because no rule, aggregate, calculation, or witness can ever depend on a `personal` slot, personal slot values never enter derived relations, witnesses, proof trees, or Merkle roots over derivations. Personal slot values live solely in a separate per-person encrypted store keyed by the person's opaque random identifier (to be built when real personal data enters). Discarding a person's cryptographic key irreversibly erases all personal slot values for that person without altering or invalidating any historical reasoning artifact.

## 4. Publication boundary and the `rezono:personal` check

Personal data must never reach a public role:

1. **Person-bearing kind:** A kind that declares (or inherits from an ancestor) at least one `personal` slot.
2. **Public role:** Any filtered (`may_read`) role that does **not** hold the `read_restricted` capability in `std-access` (`role__capability(role, "read_restricted")`). When a pack does not use `role__capability`, every filtered (`may_read`) role is treated as public unless explicitly granted `read_restricted`.
3. **Personal slot exclusion from filtered outputs:**
   - The table `<kind>__<personal_slot>` is **never** written into any filtered role's snapshots, witnesses, fact sources, or publication form (`rows.json`, `schema.json`, `hashes.json`, columnar tables, standards exports).
   - No personal slot values appear in `bundle/schema-bundle.json` (which carries schema structure only, never fact values) or in any public role's published files.
   - A public role's publication `schema.json` omits `personal` slots so the public form contains neither personal rows nor personal slot values.
4. **Blocking check `rezono:personal`:**
   - Every published epoch carries a named check row `rezono:personal` alongside [the epoch checks](../edge/publisher/rezono_publisher/batch.py) (`rezono:origins`, `rezono:proofs`, `rezono:access`, `rezono:sources`).
   - Before writing any objects, manifest, or head, the publisher (and independent checker) inspects every public role's readable snapshots, witnesses, and fact sources:
     - If any personal slot table (`<kind>__<personal_slot>`) appears with any row in a public role's snapshots, **or**
     - If any element ID of a person-bearing kind appears in a public role's readable snapshots, witnesses, or fact sources (whether in the person-bearing kind's own table, one of its slot tables, an arrow column targeting it, or a derived relation column carrying it),
     then `rezono:personal` is **red**, the publisher raises `Blocked` naming `rezono:personal` (without echoing the personal values or person IDs), and nothing is written to the store.
   - When zero personal rows and zero person IDs appear in any public role's readable output, the manifest records `{"name": "rezono:personal", "status": "green", "violations": 0}` and publication succeeds cleanly for the public role.

## 5. Considered alternatives

- **Deterministic hashes (or HMACs) for person IDs.** Rejected: deterministic hashes over low-entropy national numbers or names are vulnerable to offline dictionary recomputation and cross-register correlation. Opaque random identifiers carry zero information about the person.
- **Allowing rules to read `personal` slots and redacting outputs at the gate.** Rejected: derived rows, counts, and witnesses would depend on personal values, breaking crypto-erasure (discarding a person's key would leave personal information embedded in proofs or require rewriting historical epochs).
- **Encrypting personal slot values inside published snapshots.** Rejected: ciphertext in immutable snapshots stays in long-lived public storage and complicates erasure audits; keeping personal slot values out of published snapshots altogether is simpler and fail-closed.
- **Enforcing public-role isolation only at the access gate.** Rejected: the publisher and independent checker already enforce role boundaries before writing any object to storage; checking `rezono:personal` at publication time prevents personal data from ever landing in a public role's stored artifacts.

## 6. Tests

All requirements are recorded as strict `extra:` red tests:

- [compiler/tests/test_personal_slots.py](../compiler/tests/test_personal_slots.py):
  - `test_rule_reading_personal_slot_is_refused`: verifies that a pack with a `personal` slot refuses a rule reading that slot at compile time with diagnostic `R054` (naming the personal slot), while the same pack compiles cleanly and marks `personal: true` in `bundle/schema-bundle.json` when rules read only non-personal slots.
- [edge/publisher/tests/test_personal_data_boundary.py](../edge/publisher/tests/test_personal_data_boundary.py):
  - `test_pack_with_personal_slot_publishes_zero_personal_values_for_public_role`: publishes a pack containing a person-bearing kind with a `personal` slot alongside a public non-personal kind; verifies `rezono:personal` is `green` with `0` violations and zero personal slot values or person IDs appear anywhere in the public role's snapshots, witnesses, fact sources, publication form, or bundle.
  - `test_public_role_reading_person_id_or_personal_row_is_blocked`: counter-case where `may_read` grants the public role access to a person-bearing kind; verifies the publisher blocks with `rezono:personal` and writes nothing to the store.
