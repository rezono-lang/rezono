# Check explained example output without a generated golden

`examples/test_rules.py::test_explained_output_is_the_golden` compares the explained output of each ruled example with stored bytes under `expected/explained/`. That output is one `proofs.json` per fact state plus one snapshot per relation the proofs read. No such bytes are stored. The platform example produces about half a megabyte of them and the subsidy example several megabytes. Nobody can write those by hand. Storing what the engine produces today would make the comparison pass without checking anything independently.

## Choice

- **Content is checked without a golden.** The test keeps its structural checks:
  - every fact state has a `proofs.json`;
  - each relation's first proof is for its least row;
  - every relation a proof reads has its snapshot.

  The independent checker validates the emitted proofs and rejects mutated ones in the neighbouring tests of the same file. Determinism of the bytes is checked by compiling twice.
- **A byte reference comes later, per example.** An example gets `expected/explained/` only once a person has checked its proofs against the pack's worked reference, such as the subsidy README and its reference calculation. Only then may the checked output be recorded and compared from then on. Until then the byte comparison is marked `later:` and is not a worker task.
- **Smallest first.** The first candidate is the tenant capacity interface pack: two fact states and about four kilobytes.

## Alternatives considered

- **Commit the current output as the golden.** Rejected: the expectation would be the code's own output.
- **Delete the byte comparison.** Rejected: once the content of a reference has been checked by hand, the comparison guards the serialization against silent change.
- **Hand-write the full bytes for every example.** Not feasible for the platform and subsidy examples.
