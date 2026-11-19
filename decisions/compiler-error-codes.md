# Every compiler error has a code

The diagnostic contract (`contracts/diagnostic.yaml`) says that a code names a diagnostic and that its sentence for a reader comes from the message files. The compiler mostly does not follow it yet. The rule IR has 47 stable codes on `IRError`, but `rules_dl.py` turns them into text and the diagnostic list then carries the single code `compile_error`. The other errors of the compiler carry no code at all. A reader who gets an error sees no explanation in their own language, and a test that matches the English sentence breaks when the sentence is improved.

## An `IRError` keeps its code

Where the compiler catches an `IRError` and raises it again as a pack error (`rules_dl.RuleError`, `view_rules.ViewRuleError`, the calculation's check in `pack.read`), the diagnostic list carries the `IRError`'s own code, such as `not_stratified` or `unsafe_variable`, with the sentence as its message. `RuleError` and `ViewRuleError` become `Diagnosed`, so `pack.read` keeps their diagnostics as it keeps those of view typing. The text of the error stays as it is, so a reader of the sentence sees no change.

A test of a rule error checks the code: `[d.code for d in error.diagnostics]` or `IRError.code`, not a regular expression over the sentence. Once the codes reach the list, the planner rewrites the tests that match the sentence of an `IRError`, in one pull request.

## The errors without a code

A site gives a code with the keyword `code="<code>"` on its error class, or by adding a `Diagnostic` with a code to a list of collected errors. `Diagnosed` takes the keyword and makes the diagnostic of each line of its message with that code. `OperationError` and `WriteError` become `Diagnosed`. A code is snake_case, as the contract's `DiagnosticCode` requires, names what is wrong rather than where (`unknown_kind`, not `facts_error_3`), and means one thing wherever it is raised. An existing code is reused for the same meaning.

**What the budget counts.** Every construction, under `compiler/rezono_compiler/`, of one of these classes without the keyword `code` or `diagnostics` (and, for `CompileError` and `LoadError`, without a second positional argument, which forwards diagnostics): `CompileError`, `LoadError`, `OperationError`, `WriteError`, `RuleError`, `ViewError`, `ViewRuleError`, `PatternError`, `IdentityError` and `Unmatched`. And every `errors.append(...)` whose argument is not a `Diagnostic(...)`: those sentences are joined into one `CompileError` and are error sites of their own.

**What it does not count.** `IRError`, `native_rule_dl.Refusal` and `ViewTypingError` carry a code already. `BoundReached`, `NoProof` and `TooBig` are signals inside the engine path, not a judgement of what an author wrote. `UnitError` builds its diagnostics from its problems.

**The budget.** `compiler/error-code-budget.json` holds the number of such sites per file and per class. `compiler/tests/test_error_codes.py` counts them from the source and requires each file and class at most its budget, and the budget total at most the number it had when the budget was set (869). A new error site without a code is therefore red at once; a pull request that gives sites a code may lower the budget in the same change, but need not, so that changes merged together in one queue group cannot break on an exact count. The budget only goes down.

**The order.** The four largest groups first, in the order an author meets them: `CompileError` (reading a pack), `LoadError` (reading facts), `WriteError` (writing facts), `OperationError` (schema operations). Then `RuleError`, `ViewRuleError`, `ViewError`, `PatternError`, `IdentityError` and `Unmatched`. The collected sentences come last, file by file, because they are the most and each needs its own code.

## Alternatives

- **One code per module.** Cheap, but a code would not name a diagnostic, and a message file could not explain it. Rejected.
- **Codes for every site in one change.** Close to nine hundred sites in one review. Rejected for the budget, which lets each group land on its own and keeps new sites from adding to the debt.
