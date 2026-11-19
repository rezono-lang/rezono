# Rezono language coverage

Run `python compiler/tests/rezono/language_usage.py` from the repository root for the current inventory.
The check on `main` prints the same output in its run summary.
This page keeps no copy of it, so it cannot fall behind the evidence.

The output has four parts:

- **Features.** How many authored files use each language feature, and whether its reader and lowering tests pass without expected-failure markers. Each file counts once per feature. A higher count gives a feature priority among available tasks.
- **Packs.** For each pack or source directory: the features it uses directly and through transitive local imports, the features still pending, and whether it can take a mixed conversion (legacy rules kept as pipe blocks) or a native conversion (typed rules). A pack is "Ready" when nothing it uses is pending.
- **Native rules.** The rule census: how many rule sources use Datalog or interim pipes and how many use native rules, and whether the reader, form and IR evidence for native rules passes. A mixed file counts once in the total and in each spelling it uses.
- **State evidence.** For each pack with rules, whether an explicit state predicate needs a review of its evidence before conversion.

Native conversion requires reader, form, IR, signature and publication evidence. The expression syntax and the migration are specified in the [Native rules decision](../../decisions/language-native-rules.md).
