# Check example output against independent records, not against itself

The compiled output of the example packs is generated and is not kept in git. Two example tests compared every compiled file with a stored copy: `examples/test_examples.py::test_examples_are_found` and `test_golden_bytes`. Storing the compiler's current output as that copy would make them pass, but it would only test that the compiler still agrees with itself. A test needs an expectation from an independent source.

## Choice

- **No generated golden.** No compiled output of an example pack is checked in as its own expectation. The two marks are not worker tasks. They are replaced as a whole by independent checks, and no worker makes them green as they stand.
- **Discovery** is checked on a small tree written by hand in the test. It holds two packs, one of them nested, a pack without facts and facts without a pack. The expected discovered set is written out.
- **Recorded output** is checked on the small existing schema fixture. A hand-written record of about thirty lines gives the complete parameter file, and two hand-chosen rows give the exact violation at the inclusive maximum. A person can check both by reading the schema.
- **Full-tree comparison** applies only to a complete example snapshot that was produced and reviewed independently and is stored beside its pack. Without one, the example still counts for repeatability (two compiles give the same bytes) and for its per-fact violation records.

The replacement is ready on the branch `golf1/planner-kern-recorded-output-fixtures-examples`. Any change to `examples/test_examples.py` needs a passing live Feldera comparison under the test evidence rule. That replacement therefore lands once the live comparison passes again. Until then, the two marks stay red and wait for it.

## Alternatives considered

- **Regenerate and commit the goldens.** Rejected: the expectation would be the code's own output.
- **Delete the two tests.** Rejected: discovery and byte stability of recorded output are worth checking, and small independent records can do it.
- **Mark them as later.** Rejected as a lasting state, because the replacement already exists. The marks wait only for the evidence gate.
