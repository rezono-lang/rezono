import pytest

from case_support import engine, imported, verified


def test_standard_order():
    imported("std-order")
    expected = {("request", "review"), ("review", "apply"), ("request", "apply")}
    actual = {row for row in engine()[1].derived.get("before", ()) if set(row) <= {"review", "request", "apply"}}
    assert actual == expected
    leaves = verified("before", ("request", "apply"))
    assert {("ordered__precedes", ("request", "review")), ("ordered__precedes", ("review", "apply"))} <= leaves
