# Native rule conversion from Datalog

Can the converter inventory today's authored Datalog and preserve its rule semantics in a native conversion plan, with a precise refusal where the context cannot justify a faithful plan?

Read [the worker card](../../../WORKER.md) and [the public native-rule design, sections 2–7 and 10–11](https://github.com/rezono-lang/rezono/blob/27ff4dc926166484e549e4da0c95d400d067a18b/decisions/language-native-rules.md#10-mechanical-conversion). The test's input sources and expected native declaration trees are authored examples. They can be checked against those sections and the original Datalog conventions in [the existing reader](../../rezono_compiler/rules_dl.py). The test needs no native source reader or native program assembly.

Run the worker check from the repository root.

~~~sh
python scripts/fast_check.py "compiler/tests/rezono/test_native_rule_dl_converter.py--test_native_rule_dl_converter"
~~~

Implement the native planning entry points in `compiler/rezono_compiler/native_rule_dl.py`. Use `rules_dl.parse_file` and its tokenizer to read the source and recover the annotation order, lexical terms and original head location. Feed the plan from resolved schema identities, relation shapes and visible owner modules. Check the legacy input and output directives before omitting them from native declarations.

- `inventory(root)` returns the sorted repo-relative paths from `git ls-files -z -- '*.dl'`, excluding files under a `fixtures` directory. The inventory follows the checked-out Git index.
- `convert_modules(sources, schema, imports)` returns the native declaration trees by authored pack and file stem, the clause order and provenance of the legacy assembly, and structured conversion issues. The fixture supplies the resolved relation columns, kind/slot identity and worlds, and the client import alias. Keep both clauses under the owning module and keep their different source files. Preserve column order, annotation options, the two wildcard occurrences, empty and escaped strings, the signed comparison and the aggregate order and contributor identities.
- When a column lacks nominal type evidence, name the unresolved column and its declaration line. When negating an open register would require scoped completeness, name the input and its clause line. An issue leaves that source in its existing representation and the plan contains no replacement for it.

The standard-pack converter pilot in #440 handles schema and interim blocks. This task produces the native plan independently. A worker may change its implementation and remove this one xfail once the fast check passes.
