"""Verify companion propagation against the public five-operation example."""

from operation_source_support import companion, library, per_record  # noqa: F401
from rezono_compiler import operate, sources
from rezono_compiler import pack as packs
from support import REPO


def test_the_worked_example_carries_its_sources_through_every_step(library, tmp_path):
    companion(library, of=per_record)
    fixture = REPO / "contracts" / "fixtures" / "operation" / "OperationSet" / "valid" / "library.yaml"
    impact = operate.operate(library, fixture, tmp_path / "out")
    assert [o["sources"]["companions"] for o in impact["operations"]] == [["facts/valid.sources.yaml"]] * 5
    assert {x["relation"] for x in impact["operations"][4]["sources"]["lost"]} == {"item__reference_only"}
    assert sources.read(packs.read(library), library)  # loads against the facts after every step
