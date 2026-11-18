# Literal flags in native Rezono module forms

The native module contract uses the JSON boolean `true` for authored rule flags and wildcards. A flag appears only when asserted. The wire form and source positions remain those of [native relational rules](language-native-rules.md#7-json-form-of-a-rule).

## Decision

Keep `contracts/rezono-module.yaml` as the closed structural LinkML contract. Declare its native flag type as a boolean. Put the literal requirement in `contracts/rezono-module-literals.schema.json`, a JSON Schema Draft 2020-12 supplement. Its single `const: true` definition applies to `extend`, `invariant` and `absence` in native rule options and to `wildcard` anywhere in their argument or guard expressions. The supplement only applies to `rezono.module/3`. The companion schema owns this literal rule.

- `contracts.validate.module_form_errors(document) -> list[str]` is the repository ModuleForm entry point. It reads the ordinary closed LinkML contract, then applies the literal supplement. The native acceptance test calls this entry point. Contract fixture checks retain their LinkML schema lint and validation and also apply the same supplement to ModuleForm.
- `rezono_compiler.native_literals.native_literal_errors(document) -> list[str]` applies the supplement and returns errors with JSON paths. Add the contract resource to the existing file map in `compiler/setup.py`. Resolve it through `pack.contract_dir()`, which finds the installed asset before a checkout. The compiler calls the helper in `rezono_module.read_form` on both submitted and reader-produced forms after the envelope check and before validating spans or lowering. It continues to validate structure and source provenance through its existing input paths.
- Use the installed JSON Schema validator directly. Keep a missing or invalid supplement a validation failure. The compiled runtime has no need to generate JSON Schema with LinkML.

## Alternatives and evidence

LinkML 1.12.1 emits a boolean constant for `equals_number: true`, and its own metamodel correctly rejects that input because `equals_number` expects an integer. A plain boolean passes schema lint and accepts both boolean values. String and numeric constants reject the frozen valid form. The closed LinkML shape plus the supplement passes the existing accepted and rejected forms. It rejects `false`, `"true"`, `1` and `null` at all four marker sites. The same packaged resource works from outside a checkout. Keep the [native acceptance cases](../compiler/tests/rezono/test_native_rule_form_contract.py) as the evidence for the contract.
