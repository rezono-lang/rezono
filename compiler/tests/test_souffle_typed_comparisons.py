"""Typed scalar comparisons (`utc_instant` and `binary_text`) in the Soufflé test oracle helper."""

import re
import shutil

import pytest

import souffle
from rezono_compiler import batch, rules, rules_dl
from test_ordered_rule_scalars import program
from test_ordered_rule_scalars_engines import datalog, expected, inputs


def _lower_decls(text: str) -> list[str]:
    return re.findall(r"^\s*\.decl\s+([a-z0-9_]+)", text, flags=re.M)


REQUEST_ORDINAL_DL = """\
.decl request_order_fields(request: symbol, submission: symbol, tenant: symbol, service: symbol)
.decl request_predecessor(request: symbol, prior: symbol)
.decl request_ordinal(request: symbol, ordinal: number)

request_order_fields(r, submission, tenant, service) :-
    tenant_service_request(r),
    tenant_service_request__submitted_at(r, submission),
    tenant_service_request__tenant(r, tenant),
    tenant_service_request__service(r, service),
    utc_instant(submission) = utc_instant(submission).

request_predecessor(r, prior) :-
    request_order_fields(r, submission, _, _),
    request_order_fields(prior, earlier, _, _),
    utc_instant(earlier) < utc_instant(submission).

request_predecessor(r, prior) :-
    request_order_fields(r, submission, tenant, _),
    request_order_fields(prior, prior_submission, earlier, _),
    utc_instant(prior_submission) = utc_instant(submission),
    binary_text(earlier) < binary_text(tenant).

request_predecessor(r, prior) :-
    request_order_fields(r, submission, tenant, service),
    request_order_fields(prior, prior_submission, tenant, earlier),
    utc_instant(prior_submission) = utc_instant(submission),
    binary_text(earlier) < binary_text(service).

request_ordinal(r, ordinal) :-
    request_order_fields(r, _, _, _),
    predecessors = count : { request_predecessor(r, _) },
    ordinal = predecessors + 1.

.output request_ordinal
"""

REQUEST_TABLES = {
    "tenant_service_request": [("id", "string")],
    "tenant_service_request__submitted_at": [("id", "string"), ("value", "string")],
    "tenant_service_request__tenant": [("id", "string"), ("value", "string")],
    "tenant_service_request__service": [("id", "string"), ("value", "string")],
}


def test_program_lowers_utc_instant_and_binary_text():
    prog = rules.load(program())
    text = souffle.program(prog)
    assert "UtcKey(V_left, UtcLeft_0_), UtcKey(V_right, UtcRight_0_), UtcLeft_0_ < UtcRight_0_" in text
    assert "UtcKey(V_left, UtcLeft_0_), UtcKey(V_right, UtcRight_0_), UtcLeft_0_ = UtcRight_0_" in text
    assert "UtcKey(V_left, UtcLeft_0_), UtcKey(V_right, UtcRight_0_), UtcLeft_0_ != UtcRight_0_" in text
    assert "UtcIn(x) :- left_value(_, _, x)." in text
    assert "UtcIn(x) :- right_value(_, _, x)." in text
    assert ".decl SymbolOrderProbe(x: symbol, y: symbol)" in text
    assert "utc_instant(" not in text and "binary_text(" not in text
    assert sorted(_lower_decls(text)) == sorted(prog.relations)


def test_source_rewrites_typed_comparisons_for_all_ops_literals_and_self_guard():
    prog = rules.load(program())
    dl = datalog()
    text = souffle.source(prog, [dl])
    assert "utc_instant(" not in text and "binary_text(" not in text
    for op in ("=", "!=", "<", "<=", ">", ">="):
        assert f"l {op} r" in text
        assert re.search(rf"UtcKey\(l, UtcL_\d+_\), UtcKey\(r, UtcR_\d+_\), UtcL_\d+_ {re.escape(op)} UtcR_\d+_", text)
    assert sorted(_lower_decls(text)) == sorted(prog.relations)

    # Self-equality validity guard, multi-line spacing, string literal operands, and preserved comments.
    literal_dl = """\
// comment keeping utc_instant(a) < utc_instant(b) and binary_text(a) < binary_text(b) untouched
.decl ok(c: symbol)
ok(c) :-
    left_value("utc_instant", c, s),
    utc_instant( s )
        = utc_instant( s ),
    utc_instant(s) >= utc_instant("2024-01-01T00:00:00Z"),
    binary_text(c) < binary_text("z-limit").
"""
    rewritten = souffle.source(prog, [literal_dl])
    assert "// comment keeping utc_instant(a) < utc_instant(b) and binary_text(a) < binary_text(b) untouched" in rewritten
    code_only = "\n".join(line for line in rewritten.splitlines() if not line.lstrip().startswith("//"))
    assert "utc_instant(" not in code_only and "binary_text(" not in code_only
    assert "UtcKey(s, UtcL_0_), UtcKey(s, UtcR_0_), UtcL_0_ = UtcR_0_" in code_only
    assert 'UtcKey(s, UtcL_1_), UtcKey("2024-01-01T00:00:00Z", UtcR_1_), UtcL_1_ >= UtcR_1_' in code_only
    assert 'c < "z-limit"' in code_only
    assert 'UtcIn("2024-01-01T00:00:00Z").' in code_only


def test_request_ordinal_source_and_program_declare_each_relation_once():
    doc = rules_dl.read_program(REQUEST_ORDINAL_DL, "request_ordinal", REQUEST_TABLES, "platform")
    prog = rules.load(doc)
    for text in (souffle.program(prog), souffle.source(prog, [REQUEST_ORDINAL_DL])):
        assert "utc_instant(" not in text and "binary_text(" not in text
        assert sorted(_lower_decls(text)) == sorted(prog.relations)
        assert ".decl UtcKey(x: symbol, k: symbol)" in text
        assert ".decl SymbolOrderProbe(x: symbol, y: symbol)" in text


def test_bound_preserves_typed_comparison_annotations():
    written = 'seen(a, b) :- party__ts(a, s), party__ts(b, t), utc_instant(s) < utc_instant(t), binary_text(a) < binary_text(b).'
    got = souffle.bound(written, {"party": "terms_party", "utc_instant": "renamed", "binary_text": "renamed"})
    assert got == 'seen(a, b) :- terms_party__ts(a, s), terms_party__ts(b, t), utc_instant(s) < utc_instant(t), binary_text(a) < binary_text(b).'


def test_untyped_program_and_source_emit_no_typed_helpers():
    doc = rules_dl.read_program(
        ".decl seen(x: symbol)\nseen(x) :- item(x).\n",
        "plain",
        {"item": [("id", "string")]},
        "plain",
    )
    prog = rules.load(doc)
    for text in (souffle.program(prog), souffle.source(prog, [".decl seen(x: symbol)\nseen(x) :- item(x).\n"])):
        assert "UtcKey" not in text
        assert "SymbolOrderProbe" not in text


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_souffle_program_and_source_order_typed_scalars(tmp_path):
    prog = rules.load(program())
    rows = inputs()
    want = expected()
    assert souffle.run(prog, rows, tmp_path)["comparison"] == want
    src = souffle.source(prog, [datalog()])
    assert souffle.run(prog, rows, tmp_path, program_text=src)["comparison"] == want


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_souffle_request_ordinal_with_self_equality_guard_and_ties(tmp_path):
    doc = rules_dl.read_program(REQUEST_ORDINAL_DL, "request_ordinal", REQUEST_TABLES, "platform")
    prog = rules.load(doc)
    data = {
        "tenant_service_request": [("r1",), ("r2",), ("r3",), ("r4",), ("r_bad_leap",), ("r_bad_offset",)],
        "tenant_service_request__submitted_at": [
            ("r1", "2024-02-29T12:00:00.1Z"),
            ("r2", "2024-02-29T12:00:00.100Z"),
            ("r3", "2024-02-29T12:00:00.09Z"),
            ("r4", "2024-02-29T12:00:00.10Z"),
            ("r_bad_leap", "2023-02-29T12:00:00Z"),
            ("r_bad_offset", "2024-02-29T12:00:00+00:00"),
        ],
        "tenant_service_request__tenant": [
            ("r1", "alpha"),
            ("r2", "alpha"),
            ("r3", "zeta"),
            ("r4", "alpha-next"),
            ("r_bad_leap", "aaa"),
            ("r_bad_offset", "aaa"),
        ],
        "tenant_service_request__service": [
            ("r1", "svc-b"),
            ("r2", "svc-a"),
            ("r3", "svc-z"),
            ("r4", "svc-a"),
            ("r_bad_leap", "svc-a"),
            ("r_bad_offset", "svc-a"),
        ],
    }
    # Expected global order: r3 (.09Z) < r2 (.100Z, alpha, svc-a) < r1 (.1Z, alpha, svc-b) < r4 (.10Z, alpha-next).
    # Malformed timestamps (r_bad_leap, r_bad_offset) fail the self-equality guard and receive no ordinal.
    want_ordinals = {("r3", "1"), ("r2", "2"), ("r1", "3"), ("r4", "4")}
    with batch.connect(prog, data) as con:
        batch.compute(con, prog)
        derived = batch.read(con, prog)
    assert derived["request_ordinal"] == want_ordinals
    assert souffle.run(prog, data, tmp_path) == derived
    src = souffle.source(prog, [REQUEST_ORDINAL_DL])
    assert souffle.run(prog, data, tmp_path, program_text=src) == derived


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_souffle_source_handles_literal_utc_and_binary_text_operands(tmp_path):
    doc = rules_dl.read_program(
        ".decl kept(id: symbol)\nkept(id) :- row(id, ts, tag).\n",
        "lit",
        {"row": [("id", "string"), ("ts", "string"), ("tag", "string")]},
        "lit",
    )
    prog = rules.load(doc)
    raw = """\
.decl kept(id: symbol)
kept(id) :-
    row(id, ts, tag),
    utc_instant(ts) >= utc_instant("2024-02-29T12:00:00.0Z"),
    binary_text(tag) < binary_text("beta").
"""
    data = {
        "row": [
            ("exact_whole", "2024-02-29T12:00:00Z", "alpha"),
            ("after_frac", "2024-02-29T12:00:00.001Z", "alpha-next"),
            ("too_early", "2024-02-29T11:59:59.999Z", "alpha"),
            ("tag_too_high", "2024-02-29T12:00:00Z", "beta"),
            ("bad_leap", "2023-02-29T12:00:00Z", "alpha"),
        ],
    }
    src = souffle.source(prog, [raw])
    assert souffle.run(prog, data, tmp_path, program_text=src)["kept"] == {("exact_whole",), ("after_frac",)}
