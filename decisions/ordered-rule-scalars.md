# Exact text and UTC order in rules

Rules can compare two bound scalar values using a declared comparison type. Start with binary text and UTC instants. Reuse the rule IR's conditions and witness bindings. The condition receives the two values from its premises, so a witness can be checked from the values recorded in those premises.

The current engine orders only whole numbers. Numeric axis positions in `std-time` and predecessor edges in `std-order` are useful when the source supplies those grounds. A request source supplies time and names. Its request ordinal needs an order computed from those values.

## Scalar values

- **Text.** Compare the UTF-8 bytes of Unicode scalar text. The first differing byte decides, and a proper prefix sorts first. Equality requires identical bytes. The comparison uses neither locale rules nor Unicode normalization. Request tenant and service names already use lowercase ASCII words or digits joined by hyphens. For that domain the byte order agrees with the documented ascending identifier order.
- **UTC instant.** Accept the request input's existing spelling `YYYY-MM-DDTHH:mm:ss[.digits]Z`. Validate a Gregorian date in years 0001 to 9999 and a time with seconds 00 through 59. An optional fraction has one or more ASCII digits at any precision. Retain the raw value in the witness. For comparison, remove the terminal `Z`, strip trailing zeros from the fraction, and omit the separator if the fraction becomes empty. Compare the resulting bytes. The fixed-width whole-second part sorts first. The fraction compares exactly as decimal digits, including equivalent spellings such as `.0000001Z` and `.000000100Z`.

Neither a SQL timestamp nor a fixed-width numeric fraction is sufficient for this input domain. Canonical JSON continues to encode witness values and row keys. The order of JSON object members does not determine the order of text values in a rule.

## Condition and proof

Add a typed `compare_as` option to the existing condition with values `binary_text` and `utc_instant`. Both need two bound text operands. Apply the existing `eq`, `ne`, `lt`, `le`, `gt` and `ge` operations to the resulting ordering. Conditions without the option retain their current type checks, semantics and bytes.

Source rules opt in at the comparison. For example, `utc_instant(a) < utc_instant(b)` and `binary_text(a) < binary_text(b)` select the comparison type. These are contextual operand annotations with the existing comparison operators. They do not read another relation. The native module form already carries calls within its comparison tree. Datalog and native lowering emit the same condition, and the checker works from that condition independently of their parsers.

Missing or withheld operands supply no positive premise. A malformed UTC value cannot satisfy a typed condition, including inequality. Admission rejects malformed observations with a diagnostic. Independently, the checker recomputes the comparison from the snapshot-bound values and rejects a witness whose typed operands are malformed or whose condition is false. The same comparison semantics apply in closure checks. A field guard using typed self-equality can ensure a malformed record cannot acquire an ordinal from an empty predecessor group.

## Engines and acceptance

| Evaluator | Required proof |
| --- | --- |
| DuckDB | Use explicit byte comparison of text or of the normalized UTC key. `encode` gives bytes on the pinned DuckDB. Validate the generated SQL against the authored values and witness bindings. |
| Soufflé | Keep the independent oracle. Prove the pinned binary's symbol behavior before using it as byte order. The portable alternative is first-difference and prefix rules over an independently encoded byte sequence, including length and the original tuples. Use input values as evidence for the oracle, without importing the SQL implementation's comparison results. |
| Feldera | Run the same cases through the pinned incremental engine, including a late earlier request. Confirm a byte comparison or use a pure typed function returning the comparison sign if the engine's string operation has a different collation. A user-defined function receives source values and has no access to the request set. |
| Checker | Independently validate UTC components, compare arbitrary fractional precision and compare text bytes in both witness and closure checks. Refuse malformed typed conditions and forged witnesses. |

Freeze edge cases before implementation. Include proper prefixes, hyphens, non-ASCII distinguishing pairs, whole seconds, midnight, valid and invalid leap days, hundreds of fractional digits, trailing-zero equality, invalid offsets and absent values. A local probe of 196 UTC pairs compared normalized byte order with an independent exact rational reference. DuckDB 2.0.0 agreed on those and 81 text pairs. The emitted SQL, pinned Soufflé and pinned Feldera still need executable evidence.

## Repair the request rule

Build the ordering fields from request membership and the authenticated submission instant, tenant and service rows. Derive a predecessor if its instant is earlier, or if the instants are equal and its tenant sorts earlier, or if both tie and its service sorts earlier. A complete request's ordinal is one plus the number of its distinct predecessors. Admitted request identities are tenant/service pairs. An absent ordering field excludes the request, and an exact time tie proceeds to the identifiers. Disjoint tenants share the same global sequence.

Global rank attributes may be retained temporarily for compatibility with stored inputs. They contribute no premise or conclusion. The regression must mutate those fields in the actual public pack path without changing source values, then verify the independent proof and the unchanged ordinal. Also remove the fields entirely. Test genuine updates of each authentic ordering field, equal fractions, missing fields, additions and input permutations. Reject a proof that claims a later request precedes an earlier one. Only a publication compiled with the repaired rule and checked against its definition and snapshot pins can establish the new ordering.

## Scope and rollout

Publish the design and a neutral comparison test first. Implement and prove the shared rule condition in `contracts/rules.yaml`, compiler rule loading and SQL generation, the independent checker and the existing Soufflé and Feldera oracle paths. Add the authoring lowering when both use that condition. Then change the platform rule and its scoped regression. Preserve the independent per-tenant delivery number behavior.

Until those checks pass, the existing ordinal lacks sufficient evidence for authorizing an admission or for publishing a verified request order. The temporary option is to withhold that use of the ordinal. Keep the counterexample as a red acceptance case until the rule has independent source-value evidence.
