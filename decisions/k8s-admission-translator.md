# Admission translator

Part 1 is green on all three oracles: the hand-written `verified-supply` and `in-zone-flow` policies pass the standalone CEL evaluator, the offline API server harness and the disposable cluster. Part 2 compiles the same rules from the rule IR. This decision fixes its inputs, its building blocks and the exact CEL each block emits, so that every block can be built and checked on its own.

## Inputs

The translator reads three things and nothing else:

1. a checked rule program in `rezono.rules/1`;
2. an admission output: a derived relation whose rows admit request rows with the same key;
3. an admission binding (`rezono.admission-binding/1`, one file per rule) that names how one incoming object is read as rows of request relations, and how model relations become parameter lists.

`partition_rule` splits the program into the model fragment, which Rezono evaluates before the release, and the request fragment, which becomes CEL. The translator never parses rule syntax.

An object is admitted when every request row it yields is an output row with the same values. An object that yields no request rows is admitted; this is how the isolation baseline passes. A required field that is absent, of the wrong JSON type or outside a closed shape is a separate denial, "missing or unsupported input", never a violation and never an admission.

## The binding

The checked-in bindings `k8s-admission/fixtures/translator/verified-supply.binding.yaml` and `in-zone-flow.binding.yaml` are the reference examples. Top-level fields: `format`, `rule` (the policy rule identity), `output`, `match` (Kubernetes `resourceRules`, copied verbatim), `request` and `parameters`. Unknown fields are errors.

### Request sources

`request` is a list of sources. A source names one request relation; several sources of the same relation contribute the union of their rows. A source has:

- `each`: an ordered list of iterators. An iterator has a `name` and a `path`. The first path element is a root: `object`, `request`, or the name of an earlier iterator. The remaining elements are map keys. The value at the path must be a list.
  - `optional: true`: an absent list yields no rows. Without it, an absent list is missing input.
  - `nonempty: true`: an empty list is missing input. Kubernetes reads an empty peer or port list as "everything".
  - `closed: [keys]`: every element may use only these keys. Otherwise it is unsupported input. This rejects, for example, a peer with a `namespaceSelector` or an `ipBlock`.

  Every element must be a map. An element that is not a map or breaks `closed` is unsupported input and is not read further.
- `columns`: one entry per column of the relation, with a `path`. A column may give a `default` for an absent field. A column may name the `port-range` reading, with an `end` path: the value at `path` is the first port, the value at `end` (or the first port when absent) the last, and `1 <= first <= last <= 65535` must hold.

A scalar must have the JSON type of its column: a string for `string`, an integer (never a boolean) for `integer`. Rows are the product of the iterators in document order. The Python reader is `request_rows.read_request_rows(binding, program, request)`, where `request` is the `request` of an `AdmissionReview`. It returns `{"rows": {relation: [row, ...]}, "missing": [place, ...]}` with every request relation of the binding. It expands a port range into one row per port and returns each relation's rows sorted and unique.

A missing path is reported as text: the root, then `.key` for a key matching `[A-Za-z_][A-Za-z0-9_]*`, otherwise `["key"]` in JSON quoting, and `[i]` for the zero-based element index of an iterator. Example: `object.spec.ingress[0].from[1].podSelector.matchLabels["rezono.org/service"]`. The reported place is the list for an absent, non-list or forbidden empty list; the element for an element that is not a map or uses a key outside `closed`; the field for a column; and the `path` field for any failure of a port range. Missing places are reported sorted and once. A column is only read for a row that exists: a list with no elements reads no columns. A reading is all or nothing: when anything is missing, it returns no rows.

### Parameters

`parameters` maps each model relation the request fragment reads to its place in the `NamespacePublication`. `scope` names the namespace column; that column selects the publication object and is not written into it. `lists` is ordered; each list has a `field`, the `columns` it writes (named as the relation's columns), optional `fixed` values for the remaining non-scope columns, and `optional: true` when an empty list is omitted. A row goes into the first list whose `fixed` values it matches. A row that matches no list is an error. Entries are sorted by their written columns in order, integers numerically, and are unique. Every managed namespace receives each non-optional list, possibly empty. A row outside the managed namespaces is an error. `parameter_projection.project_parameters(binding, program, rows, namespaces)` returns, per managed namespace, the publication `spec` fields of this binding without the digest.

## CEL building blocks

Each block is one module in `k8s-admission/` and returns CEL text. The text is exact, so that the same input yields the same bytes. Generated CEL uses only the standard cel-go environment, which both offline oracles provide: no Kubernetes library functions.

A **table** describes a parameter relation inside CEL: `{"list": <CEL list>, "columns": {column: <CEL template>}, "types": {column: type}}`, with the columns in relation order. In a template, the literal text `{e}` stands for the element variable. An **environment** maps IR variables (`?image`) to CEL expressions. **Types** map IR variables to `string` or `integer`.

- **Literal** (`cel_literal.literal(value, type)`). An `integer` is canonical decimal text within the signed 64-bit range and is written as is, including a leading minus. A `string` is written in double quotes. Printable ASCII from U+0020 to U+007E is written as itself, except `"` as `\"` and `\` as `\\`. Every other code point is written as `\u` with four lowercase hex digits, or `\U` with eight above U+FFFF. A surrogate code point, a non-canonical integer or an unknown type is a `ValueError`.
- **Condition** (`cel_condition.condition(condition, env, types)`). `(<left> <op> <right>)` with `==`, `!=`, `<`, `<=`, `>`, `>=` for `eq`, `ne`, `lt`, `le`, `gt`, `ge`. A variable is its environment entry; a constant is a literal of the other side's type, or of its own form when both sides are constants. A variable outside the environment is a `ValueError`.
- **Atom** (`cel_atom`). `bind(atom, table, env, types, var)` returns `(conditions, env2)`. For each term in order, with `x` its column template with `{e}` replaced by `var`: a constant gives `(x == <literal of the column type>)`; a variable already in `env` gives `(x == <env entry>)`; a variable first seen in this atom adds `x` to `env2` and gives no condition; a variable seen earlier in this atom gives `(x == <its env2 entry>)`. `exists(table, var, conditions, rest=None)` returns `<list>.exists(<var>, <parts>)`, where the parts are the conditions followed by `rest` when given, joined by ` && `, or `true` when there are none. `negative(atom, table, env, types, var)` returns `!` followed by `exists` without `rest`. Every variable of a negated atom must already be in `env`.
- **Port range** (`cel_port_range.covers(table, var, conditions, column, start, end)`). With `x` the column template for `var`: `(<start> <= <end> && size(<list>.filter(<var>, <parts>)) == <end> - <start> + 1)`, where the parts are the given conditions followed by `(x >= <start>)` and `(x <= <end>)`, joined by ` && `. This is sound only because a table's rows are unique; the publication CRD's list-map keys guarantee that.
- **Parameter table** (`cel_parameter_tables.parameter_tables(binding, program, namespace)`). For each relation under `parameters`: the scope column's template is the given `namespace` expression; every other column's template is `{e}.<column>`; `types` are the relation's column types. The list joins one item per binding list, in order, with ` + `, wrapped in outer parentheses `(...)` when there is more than one binding list so that postfix CEL macros (`.exists`, `.filter`, `.map`) apply to the whole union. An item is `<base>.map(x, {<entries>})`, where `<base>` is `params.spec.<field>`, or `(has(params.spec.<field>) ? params.spec.<field> : [])` for an optional list, and the entries cover the non-scope columns in relation order: `"<column>": x.<column>` for a written column, `"<column>": <literal>` for a fixed one, joined by `, `.
- **Request sources** (`cel_request`). `quantify(binding, program, roots, body)` returns CEL that holds when `body(relation, columns)` holds for every row of every source. `roots` maps `object` and `request` to CEL expressions. `columns` maps each column to CEL for the current row, and a `port-range` column to `{"start": <CEL>, "end": <CEL>}`; `body` returns CEL text. Optional lists are guarded with `has`; nested iterators become nested `all`. `missing(binding, program, roots)` returns CEL that holds when the object has missing or unsupported input under the rules of the binding above. `quantify` is only evaluated when `missing` is false. These tests compare semantics in cel-go, not text, so they need Go.

## Policy shell

`policy_shell.policy_shell(binding, digest, missing=..., violation=...)` requires a lowercase SHA-256 digest and a rule identity matching `[a-z0-9]([-a-z0-9]*[a-z0-9])?`, and returns the `ValidatingAdmissionPolicy` named `<rule>.<digest[:32]>.<digest[32:]>`, with `failurePolicy: Fail`, `paramKind` `admission.rezono.org/v1alpha1` `NamespacePublication`, and `matchConstraints.resourceRules` from the binding. It has one variable, `missing`, and three validations in order, each message starting with `<rule> (<digest>): `:

1. `params.spec.digest == '<digest>'`: "publication digest does not match the policy release";
2. `!variables.missing`: "missing or unsupported input";
3. `variables.missing || (<violation>)`: "request exceeds the published rule".

The `ValidatingAdmissionPolicyBinding` objects still come from `bindings.render_binding`.

## What CEL cannot do

`admission_route.classify(program, output, request_objects)` decides whether a rule becomes a gate or stays an observation. Only the request fragment counts: the model fragment is evaluated by Rezono before the release and may use anything the language has. It returns `{"route": "gate"}`, or `{"route": "observe", "reason": <code>, "rule": <rule id or null>}`. The request fragment is refused, in this order, with the first offending rule in id order; the first two reasons name no rule:

- `no_incoming_object`: the output reads no request relation;
- `multiple_objects`: it reads request relations of more than one object;
- `recursion`: a request-side relation depends on itself; the offending rule reads a relation of its own recursive component;
- `aggregate`: an aggregate;
- `arithmetic`: an assignment, including `days`;
- `open_negation`: a negated relation in the open world, because unknown must never admit.

A refused rule is not lost. Rezono evaluates it on observed objects and reports findings: `observed_findings.observed_findings(program, output, model_rows, observations, rule=..., digest=...)`. An observation is `{"object": {"kind", "namespace", "name"}, "rows": {relation: [row, ...]}, "missing": [place, ...]}`, as the Python reader returns it for one object. The output is evaluated once over the model rows and the rows of all observations together, so a rule over several objects is evaluated on the observed state. There is one `not_admitted` finding, with `relation` and `row`, per request row that is not an output row, and one `missing_input` finding, with `places`, per object with missing input. Each finding also has `rule`, `digest`, `object` and `reason`. A row keeps its observed values. Findings are sorted by object kind, namespace and name, then reason, relation and row. The partition refuses any other number of objects than one with the message `<output>: admission requires one incoming object; it reads <relation> (<kind>), ...`, listing every request relation the output reads with its object kind, sorted by relation, or `none`.

An IPv6 address does not fit one integer of the rule language. Address ranges stay observation-only until the language has a reading for them. No reading for quantities, versions or image name parts is introduced here: both rules compare whole names.

## Order

The blocks are independent. The composition into a complete policy waits for all of them: `admission_translator.translate(program, binding, digest)` treats the binding's request relations as one incoming object, refuses with a `ValueError` naming the reason any rule that `classify` keeps as an observation, and returns the policy. Its expectation comes from part 1: on the same requests, the generated release must give the same outcome as the hand-written release, in the standalone CEL evaluator, in the offline API server harness and later in the disposable cluster. Only then does the generated policy replace the hand-written one in the release, which then remains only as a test expectation.

## Considered

- Reading objects through per-render JSON pointers in the output index. Those pointers describe one rendered object. Admission reads objects that were never rendered, so it needs the pattern behind them. The binding is that pattern; a round trip through the platform renderer checks that it reads back the rows the renderer wrote.
- Materialising request rows as a CEL list. Core CEL has no flatten, and nested iteration would need it. Quantifying with nested `all` needs neither.
- Expanding port ranges in CEL. Core CEL has no range; counting unique matching rows is exact and already proven in part 1.
- Kubernetes CEL library functions. The standalone oracle runs plain cel-go; staying inside it keeps the two offline oracles comparable.
