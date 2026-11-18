import pytest

from case_support import engine, imported, verified


def test_standard_part():
    imported("std-part")
    verified("within", ("database", "catalog-entry"))
    leaves = verified("outermost", ("database", "catalog-entry"))
    assert {("constituent__part_of", ("database", "delivery")), ("constituent__part_of", ("delivery", "catalog-entry"))} <= leaves
