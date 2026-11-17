# Admission

`rezono_admission` is the one step every fact passes before an engine sees it (ticket LS0, item E4; ruling 2 of 11-11-2026). The compiler's batch loading and the [live service](../docs/live-service.md#two-planes) both call it, so both refuse the same rows for the same reasons. **It imports nothing of the compiler** (a test asserts it): a fact never needs the compiler.

```python
from rezono_admission import Admission, Schema, rows

schema = Schema(bundle)                 # the pack's archived schema bundle (contracts/bundle.yaml)
found, refusals = rows(schema, data)    # part (a): records per kind -> rows per engine table, every refusal
step = Admission(schema, seen)          # part (b): a source is required, one delivery is admitted once
result = step.admit(data, source="feed", event="e-17")
```

## Two parts, kept apart

| Part | What | Replaced later by |
|---|---|---|
| (a) `rows.py` | the rows of a fact document against a schema: kinds, identifiers, slots, types, inlined elements and LinkML's dictionary form, as the compiler's loader reads them | the publication's L0 reader, behind the same interface; the parity test then runs against both once |
| (b) `step.py` | the step around it: a batch needs a source; a delivery is keyed by its event id (or by its rows) and admitted once; a batch with a record of a control kind needs the reviewed proposal it comes from (`reviewed=`, DV1); a batch is all or nothing | stays |

**The schema is a parameter, addressed by its hash.** `Schema(bundle)` reads the bundle as the gate reads it (C3), never the pack's sources; `schema.sha256` is the bundle's canonical hash, and every refusal names it.

**A refusal is a code** in L0's form (`^[a-z][a-z0-9_]*$`), where it was found (`kind[record].slot`), and the schema's hash. Every refusal is reported, not only the first: a record with a refusal gives no rows and the records beside it are still judged. The codes (`CODES`): `document_null`, `document_not_mapping`, `section_null`, `section_not_list`, `unknown_kind`, `kind_without_identifier`, `kind_abstract`, `record_not_mapping`, `record_without_identifier`, `unknown_slot`, `dictionary_value_not_record`, `wrong_type`, `decision_missing`, `source_missing`, `control_unreviewed`. A refusal never holds the value it refused.

**Decided values (DV1).** A kind whose bundle entry says `plane: control` (with its `owner`) holds values a reviewed proposal set (O13). Each record of it, or of a subkind, names its `decision` (`decision_missing` otherwise, in part (a), so the compiler's batch loading refuses it too), and a batch with such a record is refused as `control_unreviewed` unless the caller names the reviewed proposal it comes from (`admit(..., reviewed=...)`; for a pack's own facts, the commit of the reviewed pack). A data-plane delta needs no review.

## Parity with the compiler's loader

`tests/test_parity.py` holds admission equal to `rezono_compiler.facts` (the oracle) over every pack with facts in `examples/`, `packs/` and `compiler/tests/fixtures/`: the same rows byte for byte for every fact file, and the same refusal (the loader's first, admission's first) for the loader's refused documents and for broken copies of the first record of every section (no identifier, a wrong identifier, an unknown slot, each slot with a wrong value).

**Not covered yet, and why:**
- The generated tables of sealed kinds (`<kind>__row_sha256`): the bundle does not say which kinds are sealed, so admission does not make them and the parity test leaves them out. The bundle gains that in a pull request of COMPILER (ruling 2: admission never reaches into the `Pack` model).
- A fact file's source sidecar (`.sources.yaml`): the compiler still reads it.

**Next (ruling 2, order):** COMPILER's next pull request calls admission from `facts.py` and removes what it replaces, keeping the error codes its callers know.

```bash
cd admission && python -m pytest -q   # test_parity.py needs the compiler as the oracle; the rest needs only rezono-canon
```
