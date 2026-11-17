# Example: library

A second pack with a different shape from `projects`. It works without any compiler change and tests what `projects` lacks:

| Construct | Where |
|---|---|
| inheritance and an abstract kind | `member` and `staff` are a `person` |
| embedded kind without an identifier | an `address` exists only within a `branch`; its ID becomes `<vestiging>/branch.address` |
| self-reference | a `category` has a parent `category` |
| unique key with an arrow | name within the parent category |
| integer identifier | a `copy` has a `barcode` |
| boolean and date | `reference_only`, `lent_on` |
| multiple layers | catalogue as `facts`, loans as `observation` |
| path equation with two steps on each side | the copy and the lending staff member belong to the same branch |
| reference to a subkind | a loan points to a `member`; a `staff` there is a violation |
| multivalued slot with cardinality | a `work` has one to three `authors` |
| pattern | an address's `postcode`: four digits (first non-zero), an optional space and two uppercase letters |
| LinkML rule | an adult `member` has a `home_branch` |

Layout and expected output: as in [projects](../projects/README.md).
