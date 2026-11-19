# Admission binding checks

The admission translator (`k8s-admission-translator.md`) reads an admission binding and trusts it. A binding that names a column its relation lacks, reads from an iterator that does not exist, or writes a list the publication CRD does not declare fails late: during translation, when the release is applied, or never, by reading the wrong field. Three checks run before translation. Each is a pure function in its own module and reports every problem it finds, not only the first.

A problem is a pair `(code, place)`. The place is the path to the offending part, as its keys and zero-based list indices joined by `/`, for example `request/1/each/0/path`. A check returns its problems sorted and unique. An empty list means the input passes.

## Schema

`k8s-admission/resources/admission-binding.schema.json` is a JSON Schema (draft 2020-12) for `rezono.admission-binding/1`. Every object schema with named `properties` sets `additionalProperties: false`; the maps (`columns`, `fixed` and `parameters`) constrain their values instead. `admission_binding.load_binding(text)` parses YAML text, validates it against the schema and returns the binding. A parse or schema error is a `ValueError` whose message names the offending key. The schema requires:

- the top-level fields `format` (exactly `rezono.admission-binding/1`), `rule` (matching `^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`), `output` (a non-empty string), `match`, `request` and `parameters`;
- `match`: at least one resource rule with exactly `apiGroups`, `apiVersions`, `operations`, `resources` (non-empty lists of strings) and `scope`. `operations` contains only `CREATE` and `UPDATE`: a `DELETE` or `CONNECT` request has no object to read. `scope` is `Namespaced`: the publication is found in the request namespace;
- `request`: at least one source with `relation` (a non-empty string), `each` (a list, possibly empty) and `columns` (a map with at least one entry);
- an iterator: `name` matching `^[A-Za-z_][A-Za-z0-9_]*$` and `path` (at least two non-empty strings), with optional booleans `optional` and `nonempty`, and optional `closed` (a non-empty list of unique non-empty strings);
- a column: `path` (at least two non-empty strings), with optional `default` (a string or an integer, never a boolean), `reading` (only `port-range`) and `end` (like `path`, and only together with `reading`);
- `parameters`: a map, possibly empty, from a relation name to `scope` (a non-empty string) and `lists` (at least one). A list has `field`, matching `^[a-z][A-Za-z0-9]*$` and not `digest`, which the publication reserves, and `columns` (a non-empty list of unique non-empty strings). It may have `fixed` (a map to strings or integers, never booleans) and the boolean `optional`.

## Request check

`request_check.check_request(binding, program)` checks `output` and `request` against the rule program. The codes:

- `unknown_relation` at `output` or `request/<i>/relation`: the program has no such relation.
- `output_role` at `output`: the output is not a derived relation.
- `request_role` at `request/<i>/relation`: a request relation is not a base relation. Request rows are facts about the incoming object; no rule derives them.
- `iterator_name` at `request/<i>/each/<j>/name`: the name is `object` or `request`, or an earlier iterator of the same source has it.
- `path_root` at `request/<i>/each/<j>/path`: the first element is not `object`, `request` or the name of an earlier iterator of the same source. At `request/<i>/columns/<c>/path` and `request/<i>/columns/<c>/end`: the first element is not `object`, `request` or the name of an iterator of the same source.
- `column_unknown` at `request/<i>/columns/<c>`: the relation has no column `c`.
- `column_missing` at `request/<i>/columns/<c>`: the relation's column `c` has no entry.
- `reading_type` at `request/<i>/columns/<c>/reading`: `port-range` on a column whose type is not `integer`.
- `default_type` at `request/<i>/columns/<c>/default`: the default's JSON type is not the column's: a string for `string`, an integer and not a boolean for `integer`.

A source whose relation is unknown gets no column, reading or default codes.

## Parameter check

`parameter_check.check_parameters(binding, program)` checks `parameters`. With `<r>` the relation, `<k>` the index of a list and `<n>` the index of a written column:

- `unknown_relation` at `parameters/<r>`: the program has no such relation. Nothing else is checked for it.
- `request_relation` at `parameters/<r>`: a request source of the binding names the same relation. A relation is read from the object or published, never both.
- `scope_column` at `parameters/<r>/scope`: the scope is not a `string` column of the relation.
- `list_column` at `parameters/<r>/lists/<k>/columns/<n>`: the written column is not a column of the relation, or it is the scope.
- `fixed_column` at `parameters/<r>/lists/<k>/fixed/<c>`: the fixed column is not a column of the relation, is the scope, or this list also writes it.
- `fixed_type` at `parameters/<r>/lists/<k>/fixed/<c>`: the column exists and the fixed value's JSON type is not the column's.
- `list_cover` at `parameters/<r>/lists/<k>`: a column of the relation other than the scope is neither written nor fixed by this list.
- `list_shadowed` at `parameters/<r>/lists/<k>`: an earlier list of the same relation has `fixed` values that are all among this list's `fixed` values, with equal values. Every row this list matches then matches the earlier list first, so this list stays empty. No `fixed` counts as an empty set of values.
- `field_repeated` at `parameters/<r>/lists/<k>/field`: an earlier list of the binding, in document order of `parameters` and then `lists`, has the same field.

## CRD check

`crd_check.check_crd(crd, pairs)` checks a `NamespacePublication` CustomResourceDefinition against the bindings that write it. `pairs` is a list of `(binding, program)`. The check reads the version with `storage: true` and its schema at `schema.openAPIV3Schema.properties.spec`, called `S` here. Places are relative to the publication's `spec`: `digest`, `<field>` and `<field>/<column>`. A list's columns and their types come from the program's relation under `parameters`.

- `digest` at `digest`: `digest` is not in `S.required`, or its schema does not have `type: string` and `pattern: ^[0-9a-f]{64}$`.
- `field_missing` at `<field>`: a binding's list writes a field that is not a property of `S`.
- `field_unwritten` at `<field>`: a property of `S` other than `digest` that no binding writes.
- `field_shared` at `<field>`: more than one list, of one binding or of several, writes the field. One publication object serves every rule of a namespace, so a field has one writer. A shared field gets no other codes.
- `list_shape` at `<field>`: the property does not have `type: array`, a `maxItems` and `x-kubernetes-list-type: map`. `maxItems` bounds the cost that Kubernetes estimates for the generated CEL.
- `list_keys` at `<field>`: `x-kubernetes-list-map-keys` is not the list's written columns, in order. These keys make the rows of a list unique, which the port-range block relies on.
- `item_columns` at `<field>`: the set of the item's `properties`, or the set of its `required`, is not the set of written columns.
- `item_type` at `<field>/<column>`: a written column's property does not have the column's `type`: `string` for `string`, `integer` for `integer`.
- `required` at `<field>`: the field is in `S.required` while the list is optional, or it is not in `S.required` while the list is not optional.

A missing field gets no other codes. The checked-in `k8s-admission/resources/publication-crd.yaml`, written by hand in part 1, passes with the two translator bindings and their programs.

## Order

The three checks depend neither on each other nor on the translator's blocks. The translator may call them; this decision does not require it.

## Considered

- One check function for everything. Three modules can be built at once, and each answer stays small enough to read.
- Generating the CRD from the bindings. The CRD carries constraints that a binding does not have: string lengths, the image digest pattern, the protocol enum and the port bounds. A check keeps the reviewed CRD as the source and still catches drift between it and the bindings.
- Stopping at the first problem. Reporting all problems lets one run fix a binding.
