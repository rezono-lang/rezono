"""Exercise the public cleanup relation with independently recorded events and pages."""

import pytest

from offline_cases import PLAN_HASH, relation


def observations():
    return {
        "sweep": [("scan",)],
        "sweep__coverage": [("scan", "complete")],
        "sweep__run": [("scan", "run-one")],
        "sweep__scope": [("scan", "account-one")],
        "sweep__attempt": [("scan", "receipt")],
        "sweep__plan_hash": [("scan", PLAN_HASH)],
        "sweep__started_us": [("scan", 101)],
        "sweep__root_token": [("scan", "first")],
        "attempt": [("receipt",)],
        "attempt__operation": [("receipt", "delete_resources")],
        "attempt__run": [("receipt", "run-one")],
        "attempt__scope": [("receipt", "account-one")],
        "attempt__plan_hash": [("receipt", PLAN_HASH)],
        "attempt__dispatched_us": [("receipt", 100)],
        "page": [("reply-b",), ("reply-a",)],
        "page__sweep": [("reply-b", "scan"), ("reply-a", "scan")],
        "page__token": [("reply-b", "last"), ("reply-a", "first")],
        "page__next_token": [("reply-b", ""), ("reply-a", "last")],
        "page__item_count": [("reply-b", 0), ("reply-a", 0)],
    }


@pytest.mark.parametrize(("field", "values"), [
    pytest.param("sweep__started_us", [("scan", 99)], id="pre-delete"),
    pytest.param("sweep__started_us", [("scan", 100)], id="simultaneous"),
    pytest.param("sweep__started_us", [("scan", 99), ("scan", 101)], id="ambiguous-time"),
    pytest.param("attempt", [], id="missing-dispatch"),
    pytest.param("attempt__dispatched_us", [], id="undispatched"),
    pytest.param("attempt__operation", [("receipt", "submit_order")], id="wrong-action"),
    pytest.param("attempt__run", [("receipt", "other")], id="other-run"),
    pytest.param("attempt__scope", [("receipt", "other")], id="other-scope"),
    pytest.param("attempt__plan_hash", [("receipt", "b" * 64)], id="other-plan"),
    pytest.param("sweep__attempt", [("scan", "other")], id="other-attempt"),
    pytest.param("page__sweep", [], id="declaration-without-pages"),
    pytest.param("page__sweep", [("reply-a", "scan"), ("reply-b", "other")], id="foreign-tail"),
    pytest.param("page__next_token", [("reply-a", "missing"), ("reply-b", "")], id="gap"),
    pytest.param("page__next_token", [("reply-a", ""), ("reply-b", "")], id="orphan"),
    pytest.param("page__next_token", [("reply-a", "last"), ("reply-b", "first")], id="cycle"),
    pytest.param("page__next_token", [("reply-a", "last")], id="missing-terminal"),
    pytest.param("page__next_token", [("reply-a", "last"), ("reply-a", ""), ("reply-b", "")],
                 id="conflicting-terminal"),
    pytest.param("page__token", [("reply-a", "first"), ("reply-b", "first")], id="repeated-page"),
    pytest.param("page__item_count", [("reply-a", 1), ("reply-b", 0)], id="missing-resource"),
])
def test_unproven_cleanup(field, values):
    facts = observations()
    facts[field] = values
    assert relation("cleanup", facts, "cleaned") == set()


def test_complete_cleanup_witness():
    facts = observations()
    del facts["sweep__coverage"]
    assert relation("cleanup", facts, "cleaned") == {("scan",)}
    assert relation("cleanup", facts, "cleanup_page_evidence") == {
        ("scan", "receipt", "reply-a"), ("scan", "receipt", "reply-b"),
    }


def test_matching_resource_on_last_page():
    facts = observations()
    facts.update({
        "page__item_count": [("reply-a", 0), ("reply-b", 1)],
        "resource": [("item",)],
        "resource__sweep": [("item", "scan")],
        "resource__page": [("item", "reply-b")],
        "resource__plan_hash": [("item", PLAN_HASH)],
    })
    assert relation("cleanup", facts, "cleaned") == set()
    facts["resource__plan_hash"] = [("item", "b" * 64)]
    assert relation("cleanup", facts, "cleaned") == {("scan",)}
