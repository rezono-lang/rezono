"""Evaluate one production rule fragment with a closed set of typed fixture inputs."""

from pathlib import Path

RULES = Path(__file__).resolve().parents[2] / "packs" / "std-loop" / "rules"


def evaluate(name, columns, facts):
    source = RULES / f"{name}.dl"
    text = source.read_text(encoding="utf-8")
    from rezono_compiler import batch, rules, rules_dl

    inputs = {
        table: [(column, "string") for column in fields.split()] if isinstance(fields, str) else fields
        for table, fields in columns.items()
    }
    program = rules.load(rules_dl.read_program(text, source.name, inputs, "std-loop"))
    connection = batch.connect(program, facts)
    try:
        batch.compute(connection, program)
        return batch.read(connection, program, [name])[name]
    finally:
        connection.close()
