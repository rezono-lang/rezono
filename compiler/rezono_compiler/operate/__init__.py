"""Schema operations (docs/compiler.md#schema-operations, decision S13).

`operate` applies an operation set (contracts/operation.yaml, rezono.operations/1) to a pack in a work dir. Each
operation edits the text of the schema, fact, label, channel and rule files (only the lines it concerns), then
checks that the new files load to exactly M(X) for every fact state X, and that the inverse gives X back. It
writes per operation a migration in the format of linkml-map, its inverse when lossless, and one impact
(rezono.impact/1). Any error restores every file it touched: a blocking check leaves the pack as it was.

Built: rename (a kind, a slot or identifier, an enum, an enum value), drop (a kind or a slot), move (a slot up
or down is_a, or across a single-valued arrow), split_by (one subkind per value), combine (a kind absorbs
another across a single-valued arrow), and select (an explicit, simultaneous submodel with omission reasons).

The modules, each importing only from those above it:

- `spec`: the operation file (`load`), the constants and `OperationError`;
- `model`: the model of a pack, its modules, engine names and fact states, and its fact and rule files through the
  source-format boundary (`source_format`, B13);
- `text`: text edits, and deleting YAML text;
- `rename`: rename, and the schema helpers the other operations share;
- `maps`: engine maps, old engine name to new;
- `records`: facts;
- `labels`: labels and channels;
- `state`: the migration on states;
- `datalog`: rules;
- `migration`: the linkml-map migration;
- `drop`, `move`, `split_by`, `combine`: one operation each;
- `checks`: no new violations;
- `execution`: sources through an operation, the steps every operation takes, and the whole (apply in place,
  check, restore on error).

This module is the surface: what the rest of the compiler and the tests read off `operate`.
"""
from ..pack import ACCESS
from .checks import guarded, violations
from .datalog import rule_edits
from .drop import Drop, drop_fact_edits, drop_schema_edits, owned, plan_drop, validate_drop
from .execution import SOURCE_LOSS, WORD, DropOp, Operation, operate, row_text
from .model import Model, model, resolve, states
from .spec import (BUILT, CLASS_NAME, CONDITIONS, FACT_DIRS, FIELDS, FORMAT, IMPACT, OPS, OUTCOME, PARAMETERS,
                   PLAIN, REF, OperationError, load)
from .split_by import case_text
from .state import bag, embedded, migrate, text_of
from .text import Edits, read_text

__all__ = [
    "ACCESS", "BUILT", "CLASS_NAME", "CONDITIONS", "FACT_DIRS", "FIELDS", "FORMAT", "IMPACT", "OPS", "OUTCOME",
    "PARAMETERS", "PLAIN", "REF", "SOURCE_LOSS", "WORD",
    "Drop", "DropOp", "Edits", "Model", "Operation", "OperationError",
    "bag", "case_text", "drop_fact_edits", "drop_schema_edits", "embedded", "guarded", "load", "migrate", "model",
    "operate", "owned", "plan_drop", "read_text", "resolve", "row_text", "rule_edits", "states", "text_of",
    "validate_drop", "violations",
]
