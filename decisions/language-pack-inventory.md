# Writing a pack in Rezono

A module starts with the existing rezono and pack headers. Each language decision gives a source fragment and the corresponding object at its location in the module tree. Preserve the current module/1 contract and bytes for existing constructs. A module requiring any new tree member uses rezono.module/2. Its envelope retains module and spans. The new contract must enumerate the new fields, reject unknown fields, and preserve source spans as JSON pointers. A compiler that cannot read the declared version must reject the whole form.

| Pack | Already readable | Needed for publication parity |
| --- | --- | --- |
| library | Kinds, slots, enums, fact rows | Embedded addresses, integer keys, subtypes, bounded lists, patterns, composite keys, path equality, conditional requirements and separate valid/error datasets |
| projects | Kinds, references, enums, facts | Scalar aliases, numeric bounds, named uniqueness and paths, separate datasets |
| subsidy-scheme | Versioned parameters, derived expressions, units, exception groups | Schema metadata, row-backed parameters, named outputs and definitions, relational rules and findings |
| subsidy | Fact tables, calculations, time qualifiers | Typed and sparse facts with provenance, evaluation date, relations and diagnostics. Credential fixtures, views and scenarios continue to use their existing contracts |
| std-access, std-decision, std-identity, std-order, std-part, std-time | Kinds, slots, enums | Publish shared definitions once per pack. Preserve schema and member descriptions, mappings, annotations, relational rules and outputs |
| std-view, std-explain | No schema or rule migration | Their messages and presentation assets retain their existing formats |
| zorgtoeslag | Module and facts already use Rezono | Compile the existing modules and verify case results after the preceding packs |
| platform | Depends on completed example | Inventory and compare the finished example after the platform work lands |

For each construct, compare the reader to the explicit tree and the lowering to the public example's existing schema, fact, rule or calculation file. For each pack, publish the same dataset and imports through both paths. Compare the facts, conclusions, proof meaning and presentation data under the semantic publication decision. Validate the source references within each publication against its own inputs. Keep both source forms until these checks pass. A lowerer change under compiler/rezono_compiler belongs to the compiler track. A contract version belongs to the contracts track. Coordinate those dependencies before assigning an implementation task.

The alternative of switching every pack to the new form at once would remove the independent publication oracle. Separate conversions preserve it for each example.
