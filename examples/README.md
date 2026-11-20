# Rezono examples

The example packs form a learning ladder from minimal schemas to multi-source statutory regulations and a full operational system:

1. [`library`](library/) — Minimal schema, constraints, and valid/invalid fact sets.
2. [`projects`](projects/) — Multi-file schema relations and cross-record references.
3. [`subsidy`](subsidy/) (with [`subsidy-scheme`](subsidy-scheme/)) — Single-source regulation scheme with Datalog rules, exact minor-unit calculations, proofs, and independent oracle verification.
4. [`zorgtoeslag-slice`](zorgtoeslag-slice/README.md) — Three-source healthcare allowance slice composing independent civil, tax, and insurer packs along shared synthetic `Persoon` keys, proving that identically named `civil.Partner` and `tax.Partner` kinds never silently merge while deriving `toeslagpartner`, `insured`, `joint_income`, and monthly `allowance` with dated facts and ordered exceptions.
5. [`platform`](platform/) — Full multi-role operational system with access scopes, incremental rules, sweeps, and cluster proofs.

Additional reference material:

- [`zorgtoeslag`](zorgtoeslag/) — Full healthcare allowance language design (not yet a compiled pack).
- [`amount`](amount/) and [`network`](network/) — Focused schema and unit examples.
