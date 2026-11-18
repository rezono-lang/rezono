"""Shared test-side access to the offline run fixtures and rule evaluator."""

import json
from pathlib import Path
from runpy import run_path

RUN = Path(__file__).resolve().parents[1]
FIXTURE = RUN / "fixtures" / "offline"
PRICE_FACTS_HASH = "7f4cb977a2cc577039ea302c5e2a98b47225943392d01121b0b1bd2093f21f02"
PRICE_SOURCE_HASH = "4e592b33e7855de0ef463d447254686044edb00b2f770c0104a179a88331343e"
PLAN_HASH = "e919be970648421f6374c599bcec647bfc62fe9f1df92e0346e2f40c89b41c0f"


def case():
    return json.loads((FIXTURE / "case.json").read_text(encoding="utf-8"))


def implementation(file, name):
    return run_path(str(RUN / file))[name]


def relation(name, data, output):
    path = RUN / "packs" / name
    assert (path / "pack.yaml").is_file()
    from rezono_compiler import batch, pack, rules

    program = rules.load(pack.read(path).rules)
    connection = batch.connect(program, data)
    try:
        batch.compute(connection, program)
        return batch.read(connection, program, [output])[output]
    finally:
        connection.close()
