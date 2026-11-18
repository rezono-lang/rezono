"""Shared test-side access to the offline run fixtures and rule evaluator."""

import json
from pathlib import Path
from runpy import run_path

RUN = Path(__file__).resolve().parents[1]
FIXTURE = RUN / "fixtures" / "offline"
SOURCE = "4e592b33e7855de0ef463d447254686044edb00b2f770c0104a179a88331343e"
PLAN_HASH = "8402bbc2ea3d0e92acee572c54d1256d82de52089052c57dda68a75d56614112"


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
