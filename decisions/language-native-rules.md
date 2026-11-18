# Native relational rules

Use an indented `rules` block of `head if body` clauses. A rule names the same kinds and slots as the rest of the pack. The existing [relational rule block](language-rules.md) with `|` remains available during migration. Both forms feed the same rule IR and run with the same Datalog semantics.

## Source

`Item(?item)` reads the key of a kind. `Item.group(?item, ?group)` reads the key and value of a slot. Resolve both through the pack and its visible imports. A slot read denotes one existing relation and contributes one premise. It does not implicitly add a membership test.

A derived relation has a lower snake case name and named arguments. Its first head gives the ordered field names and every later head must use the same ordered names. Calls supply each field once and may order them differently. Lower calls in the head's field order. The head names fields without declaring their types. The same variables and the relations in the body constrain column types, including recursive calls. Resolve all headers before checking bodies so recursion and forward references work. An imported relation carries its resolved signature. Reject unresolved types, incompatible constraints and attempts to derive a base relation.

`?name` is a variable. Its proof binding uses the name without `?`. `_` denotes a fresh anonymous argument on each occurrence. Text uses double quotes, and whole numbers use decimal digits with an optional leading minus. Resolve each literal against the expected type. Use the language's existing escaped names when needed. `and` joins ordered body parts. Each clause begins on its own logical line. The same head may have multiple clauses. A native block contains only native clauses.

The examples assume closed kinds `Item`, `Group` and `Exclusion`. `Item.group` refers to `Group`, `Item.weight` is a whole number, `Group.parent` refers to `Group`, `Group.state` is text, and `Exclusion.item` refers to `Item`.

### Ordinary rule

```rezono
rules inventory
  listed(item: ?item, group: ?group) if Item.group(?item, ?group) and Group.state(?group, "active")
```

An item and its group are listed when the membership row and the active-state row both exist. Neither row alone suffices.

### Recursion

```rezono
rules ancestry
  reachable(item: ?item, group: ?group) if Item.group(?item, ?group)
  reachable(item: ?item, group: ?group) if reachable(item: ?item, group: ?parent) and Group.parent(?parent, ?group)
```

If `i` belongs to `g1` and `g1` has parent `g2`, the least fixed point contains `(i, g1)` and `(i, g2)`. Removing the parent row removes only the second conclusion.

### Stratified negation

```rezono
rules eligibility
  blocked(item: ?item) if Exclusion.item(?exclusion, ?item)
  eligible(item: ?item) if Item(?item) and not blocked(item: ?item)
```

For an item without an exclusion, `eligible` records the absence of `blocked` in the lower stratum. Adding an exclusion removes eligibility. A dependency cycle through negation is invalid. A missing row in an open base relation remains unknown.

### Counting

```rezono
rules membership
  size(group: ?group, count: ?n) if Group(?group) and ?n = count { Item.group(?item, ?group) }
```

Count matching distinct relation tuples. `?group` is bound outside the count and `?item` is local to it. Two members give `2`, and a known group without members gives `0`. A missing group gives no conclusion.

### Comparison

```rezono
rules capacity
  heavy(item: ?item) if Item.weight(?item, ?weight) and ?weight > 2
```

Whole numbers `3` and `2` distinguish the accepted and rejected boundary cases. A text value cannot be compared to a whole number.

## Module form

A native block uses `rezono.module/2`. It carries `rules` and `clauses`. An interim block carries `rules` and `lines`. Reject mixed fields and unsupported members. A clause carries `head` and an ordered nonempty `body`. An atom has `relation` and `arguments`. An argument carries `value` and optionally `field`. Fields are required on derived atoms and forbidden on schema atoms. A term is a single `var`, `wild` or `lit` member. A literal carries `type` (`text` or `integer` in this slice) and an exact string `value`. The AST carries authored syntax, so inferred types, keys and canonical engine names remain in the resolved IR.

```json
{
  "rules": "capacity",
  "clauses": [
    {
      "head": {
        "relation": "heavy",
        "arguments": [{"field": "item", "value": {"var": "item"}}]
      },
      "body": [
        {
          "atom": {
            "relation": "Item.weight",
            "arguments": [{"value": {"var": "item"}}, {"value": {"var": "weight"}}]
          }
        },
        {"compare": {"left": {"var": "weight"}, "op": ">", "right": {"lit": {"type": "integer", "value": "2"}}}}
      ]
    }
  ]
}
```

Each body part carries exactly one of `atom`, `not`, `count` or `compare`. `not` contains an atom. `count` contains `result` (the variable name without `?`) and `atom`. A `compare` contains `left`, `op` and `right`. Use the existing module `spans` envelope with JSON pointers relative to the module object and code-point offsets. A clause's origin is the head relation token, for example `/decls/0/clauses/0/head/relation`. Keep spans for atom names, fields, terms, `not`, `count` and comparison operators so each refusal points to its authored token. Printing preserves clause order, body order and names.

## Checking and lowering

Collect signatures before solving type constraints from schema columns, literals and uses of the same variable. A repeated variable unifies its type across positions. Ordered comparisons require the scalar types already admitted by the IR. A head, comparison or negated atom may only use variables bound by positive body atoms or by an aggregate result. Aggregate-local variables do not escape. A correlated aggregate variable has a positive binding outside its aggregate. Check stratification with the existing dependency rules and preserve the existing restrictions on open relations and aggregation. Reject ambiguous types and unresolved names before emitting rules.

The reader reports malformed clauses with `R000`. The name and type checker uses the catalog entries in `rezono/messages/` for `R001` (unknown name), `R003` (incompatible types), `R004` (open relation under negation) and `R013` (no type can be inferred). Add catalog entries `R032` (variable has no positive binding, argument: variable), `R033` (non-stratified dependency, arguments: relation and dependency), and `R034` (relation arguments do not match its signature, argument: relation). Return the code, arguments and authored span. Engine errors are never the language's diagnostic interface.

Map schema references through the existing pack name resolver. For example, `Item.weight` denotes exactly the current slot table `item__weight`. Emit the current typed relation columns, rule atoms, comparisons and aggregates. Apply the existing rule identifiers and strata. A named block uses the same module identity as the interim block with that name or the rule file with the same stem. A relation with one clause keeps its relation identifier. Multiple clauses keep the existing source-order numbering. Retain the body order used by the proof, with no extra joins or generated premises. Two spellings of the same relation cannot coexist in one input pack. The comparison oracle uses separate pack inputs.

There is no `.decl` because the schema provides types and the head already names the derived fields. There is no `.output` because derived rows pass through the pack's existing publication and role rules. The spelling cannot grant access or hide a ground. A pack may retain interim blocks for constructs outside this first slice. Moving a pack out of the interim form requires preserving all of its existing semantics, including rule annotations.

## Acceptance

The reader checks the source against the explicit form, including spans. The checker and lowerer can start from the hand-authored form before the reader is available. The type checker checks unknown fields, unsafe variables, open-world negation and a negative cycle. The lowerer and the existing [publication comparison](language-semantic-publication.md) publish equivalent native and interim rules from separate inputs, including the counterexamples above.

Compare both publications' typed relations, conclusions, roles and witnesses. The same rule identifier, stratum, bindings, ordered premise keys and signs, and aggregate members must agree. Each publication verifies the source of its own witness. Only source locations and the hashes that depend on the authored representation may differ. A differing value, missing premise or missing publication fails the comparison.

We considered retaining literal Datalog as the final spelling and adding typed headers to native rules. A literal block keeps schema names outside language checking. Typed headers make authors repeat information that follows from the schema. Named fields preserve tuple keys while schema-based checking gives the language a single source for types.
