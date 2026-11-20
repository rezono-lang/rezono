"""Verify that examples/subsidy/messages/en.mf2 aligns with rules/access.dl and drops std-explain duplicates."""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).parent
ACCESS_DL = HERE / "rules" / "access.dl"
EN_MF2 = HERE / "messages" / "en.mf2"

MAY_READ_CLAUSE = re.compile(r'^\s*may_read\(\s*(r|"[^"]+")\s*,\s*"([^"]+)"\s*,\s*x\s*\)\s*:-')
MF2_ENTRY = re.compile(r"^([A-Za-z0-9_.-]+)\s*=\s*(.+)$")
MF2_VAR = re.compile(r"\{\$([A-Za-z0-9_]+)\}")

ROLE_PREFIX = {
    "r": ("Role {$r} may read ", {"r", "x"}),
    '"case_officer"': ("The case officer may read ", {"x"}),
    '"policy_adviser"': ("The policy adviser may read ", {"x"}),
    '"viewer"': ("The reader may read ", {"x"}),
    '"propose"': ("The proposer may read ", {"x"}),
}

KIND_OBJECT = {
    "article": "article {$x}.",
    "decision": "decision {$x}.",
    "purpose": "purpose {$x}.",
    "principle": "principle {$x}.",
    "alternative": "rejected alternative {$x}.",
    "exception": "exception {$x}.",
    "scheme_parameter": "scheme parameter {$x}.",
    "cost_item": "cost item {$x}.",
    "reference_date": "reference date {$x}.",
    "role": "role {$x}.",
    "calendar": "calendar {$x}.",
    "interval": "period of validity {$x}, stated apart from a scheme parameter.",
    "axis": "axis {$x}, stated apart from a calendar.",
    "reference_point": "reference point {$x}, stated apart from an evaluation day.",
    "series": "series {$x} of periods of validity.",
    "household": "household {$x}.",
    "application": "application {$x}.",
    "cost_line": "quote line {$x}.",
    "income_statement": "income statement {$x}.",
    "advice_report": "advice report {$x}.",
    "ledger_payment": "ledger payment {$x}.",
    "period_close": "close {$x} of the ledger.",
    "closed_payment": "closed payment {$x}.",
    "trust_entry": "trust entry {$x}.",
    "credential": "credential {$x}.",
    "credential_claim": "claim {$x}.",
    "status_lookup": "status lookup {$x}.",
    "identity_statement": "identity statement {$x}.",
}


def _access_clauses() -> list[tuple[str, str]]:
    clauses: list[tuple[str, str]] = []
    for raw in ACCESS_DL.read_text(encoding="utf-8").splitlines():
        line = raw.split("//", 1)[0]
        if match := MAY_READ_CLAUSE.match(line):
            clauses.append((match.group(1), match.group(2)))
    return clauses


def _mf2_entries() -> dict[str, str]:
    _, sep, body = EN_MF2.read_text(encoding="utf-8").partition("\n---\n")
    assert sep, "messages/en.mf2 must have a header/body separator"
    entries: dict[str, str] = {}
    current: str | None = None
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            current = None
            continue
        if line[0] in (" ", "\t") and current is not None:
            entries[current] += " " + line.strip()
            continue
        match = MF2_ENTRY.match(line)
        assert match, f"unexpected mf2 line: {line!r}"
        current = match.group(1)
        assert current not in entries, f"duplicate mf2 key: {current}"
        entries[current] = match.group(2).strip()
    return entries


def test_may_read_messages_match_access_dl_clauses():
    clauses = _access_clauses()
    entries = _mf2_entries()
    may_read_keys = sorted(k for k in entries if k.startswith("rule.may_read_"))
    expected_keys = sorted(f"rule.may_read_{i}" for i in range(1, len(clauses) + 1))
    assert may_read_keys == expected_keys

    for idx, (role_term, kind) in enumerate(clauses, start=1):
        key = f"rule.may_read_{idx}"
        text = entries[key]
        prefix, expected_vars = ROLE_PREFIX[role_term]
        expected_text = prefix + KIND_OBJECT[kind]
        assert text == expected_text, f"{key} for ({role_term}, {kind})"
        assert set(MF2_VAR.findall(text)) == expected_vars, key


def test_en_mf2_does_not_duplicate_std_explain_messages():
    entries = _mf2_entries()
    duplicated = sorted(k for k in entries if k.startswith("explain."))
    assert duplicated == [], f"std-explain messages should not be duplicated: {duplicated}"
