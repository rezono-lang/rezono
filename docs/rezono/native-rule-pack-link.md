# Link native rules in pack compilation

Run the assigned test from the repository root.

```text
python scripts/fast_check.py "compiler/tests/rezono/test_native_rule_pack_link.py--test_native_rule_pack_link"
```

Start implementation once the native rule signature linker (`native-rule-signatures`) and the native rule IR entry point (`native-rule-ir-listed`) pass. The hand-authored forms let the test run independently of the source reader.

The test runs ordinary pack compilation with a pinned owner, two native extension clauses and one legacy extension clause. Their module stems put the legacy clause between the two native clauses. The separately authored all-Datalog pack supplies the expected relations, owner module and clause meaning. Rule IDs, clause order and variable names are local choices of each representation and are not compared ([migration equivalence](../../decisions/language-expression-semantics.md#4-migration-equivalence)). Origins must point at each mixed-format clause. Compiling the same pack again must reproduce every artifact byte for byte. [Native relational rules, including imports and witness identity](https://github.com/rezono-lang/rezono/blob/27ff4dc926166484e549e4da0c95d400d067a18b/decisions/language-native-rules.md)

Check the pin before linking any relation. Report an inaccessible import with `R046` and a competing owning signature with `R040`. The signature owner alone declares the native relation. Its extension marker allows consumers to contribute clauses.

Implement the change in `compiler/rezono_compiler/`. Run the assigned test and remove only its expected-failure mark when it passes.
