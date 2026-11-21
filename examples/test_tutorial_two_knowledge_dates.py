"""Behavioral verification for the two-knowledge-dates step in `docs/tutorial.md` on
`examples/zorgtoeslag-slice` (decisions/ask-place-time-restrictions.md,
decisions/bitemporal-history-publication.md).

Verifies that:
1. `docs/tutorial.md` contains a step on `examples/zorgtoeslag-slice` asking the exact same
   question at two distinct knowledge dates (`as known on YYYY-MM-DD`), with shown commands/queries
   and shown outputs naming who receives a different amount between the two knowledge dates and
   from which version of which parameter that difference follows.
2. Publishing `examples/zorgtoeslag-slice` at those two knowledge dates into one bitemporal store
   and evaluating the tutorial's exact `ask ... as known on ...` questions through the real
   `edge/gate` local evaluator (`POST /zorgtoeslag-slice/m-2/ask`) produces answers and verified
   calculation witnesses that match what `docs/tutorial.md` shows (and agree with the independent
   oracle `examples/zorgtoeslag-slice/reference.py`).

Note for tutorial authors: `examples/subsidy/test_tutorial.py` checks every `yaml`, `rezono`, and
unlabeled code fence in `docs/tutorial.md` against `examples/subsidy`, and every `python ` line in
a `bash` fence against its subsidy command list, plus `blocks(page, "json")[0]` for the subsidy
proof. Place the new two-knowledge-dates section after the subsidy steps and use non-colliding
fence tags (such as `sh`, `text`, `console`, or `json`) so both tutorial tests pass together.
"""

from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import zorgtoeslag_history_support as support

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "tutorial.md"
SLICE = ROOT / "examples" / "zorgtoeslag-slice"
ORACLE = SLICE / "reference.py"

AS_KNOWN_ON = re.compile(r"\bas\s+known\s+on\s+(\d{4}-\d{2}-\d{2})\b")
AS_OF_HINT = re.compile(
    r"""(?:as[ _]of|valid[ _]at|valid\s+on)\s*(?:=|:|\s)\s*["']?(\d{4}-\d{2}-\d{2})["']?""",
    re.IGNORECASE,
)
PARAM_RELATIONS = (
    ("CalcStandardPremium", "standard_premium"),
    ("CalcThresholdIncome", "threshold_income"),
    ("CalcIncomeLimitSingle", "income_limit_single"),
    ("CalcIncomeLimitPartner", "income_limit_partner"),
)


def _split_sections(page: str) -> list[str]:
    """Split a markdown document into `## ` sections (ignoring fenced blocks)."""
    sections: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in page.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            if current:
                sections.append("\n".join(current) + "\n")
            current = [line]
            continue
        current.append(line)
    if current:
        sections.append("\n".join(current) + "\n")
    return sections


def _fenced_blocks(text: str) -> list[tuple[str, str]]:
    """Return `(language, body)` for every fenced code block in `text`."""
    blocks: list[tuple[str, str]] = []
    inside = False
    lang = ""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("```"):
            if inside:
                blocks.append((lang, "\n".join(lines) + "\n"))
            inside = not inside
            lang = line[3:].strip() if inside else ""
            lines = []
        elif inside:
            lines.append(line)
    return blocks


def _normalize_query(raw: str) -> str:
    return " ".join(raw.strip().split())


def _query_template(query: str) -> str:
    return _normalize_query(AS_KNOWN_ON.sub("as known on <DATE>", query))


def _extract_ask_queries(section: str) -> list[tuple[str, str]]:
    """Extract `(query_text, known_date)` pairs for `ask ... as known on YYYY-MM-DD ...` in `section`."""
    candidates: list[str] = []

    for _lang, body in _fenced_blocks(section):
        for raw_line in body.splitlines():
            line = raw_line.strip()
            for prefix in ("$ ", "> "):
                if line.startswith(prefix):
                    line = line[len(prefix):].strip()
            if line.startswith("ask ") and AS_KNOWN_ON.search(line):
                candidates.append(line)
        for match in re.finditer(r'"((?:[^"\\]|\\.)*)"', body):
            try:
                decoded = json.loads('"' + match.group(1) + '"')
            except json.JSONDecodeError:
                continue
            text = decoded.strip()
            if text.startswith("ask ") and AS_KNOWN_ON.search(text):
                candidates.append(text)
        for match in re.finditer(r"'([^'\n]*)'", body):
            text = match.group(1).strip()
            if text.startswith("ask ") and AS_KNOWN_ON.search(text):
                candidates.append(text)

    for match in re.finditer(r"`([^`\n]+)`", section):
        text = match.group(1).strip()
        if text.startswith("ask ") and AS_KNOWN_ON.search(text):
            candidates.append(text)

    seen: set[str] = set()
    extracted: list[tuple[str, str]] = []
    for cand in candidates:
        norm = _normalize_query(cand)
        hit = AS_KNOWN_ON.search(norm)
        if not hit or norm in seen:
            continue
        seen.add(norm)
        extracted.append((norm, hit.group(1)))
    return extracted


def _pick_identical_question_pair(
    queries: list[tuple[str, str]],
) -> tuple[tuple[str, str], tuple[str, str], list[tuple[tuple[str, str], tuple[str, str]]]]:
    """Pick the primary `(q1, d1), (q2, d2)` pair asking the exact same question at two distinct dates,
    plus any additional identical-question pairs (such as a parameter query)."""
    by_template: dict[str, dict[str, str]] = {}
    for query, known_date in queries:
        datetime.date.fromisoformat(known_date)
        by_template.setdefault(_query_template(query), {})[known_date] = query

    pairs: list[tuple[tuple[str, str], tuple[str, str]]] = []
    for by_date in by_template.values():
        if len(by_date) >= 2:
            dates = sorted(by_date)
            pairs.append(((by_date[dates[0]], dates[0]), (by_date[dates[-1]], dates[-1])))

    assert pairs, (
        "docs/tutorial.md zorgtoeslag-slice section must ask the exact same `ask ... as known on YYYY-MM-DD ...` "
        f"question at two distinct knowledge dates; found queries: {queries}"
    )

    allowance_pairs = [p for p in pairs if "allowance" in p[0][0].lower()]
    primary = allowance_pairs[0] if allowance_pairs else pairs[0]
    others = [p for p in pairs if p is not primary]
    return primary[0], primary[1], others


def _extract_as_of_date(section: str) -> str:
    hit = AS_OF_HINT.search(section)
    if hit:
        datetime.date.fromisoformat(hit.group(1))
        return hit.group(1)
    return "2026-01-01"


def _post_ask(store_dir: Path, role: str, manifest: str, *queries: str) -> list[dict]:
    """Send `POST /zorgtoeslag-slice/<manifest>/ask` requests through `tests/slip/reader.mjs`."""
    payload = {
        "store": store_dir.as_posix(),
        "role": role,
        "requests": [
            {
                "path": f"/zorgtoeslag-slice/{manifest}/ask",
                "method": "POST",
                "body": {"text": text},
            }
            for text in queries
        ],
    }
    run = subprocess.run(
        [support.node(), str(support.READER)],
        input=json.dumps(payload),
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        cwd=ROOT,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _answer_rows(body: dict) -> list[dict]:
    return [row for row in body.get("dataset", {}).get("rows", []) if row.get("$kind") == "Answer"]


def _known_amounts_by_subject(body: dict) -> dict[str, str]:
    """Extract `{subject: amount_cents}` from `CalcAllowance` `Answer` rows."""
    amounts: dict[str, str] = {}
    for row in _answer_rows(body):
        raw_id = row.get("$id")
        assert isinstance(raw_id, str), row
        parts = json.loads(raw_id)
        assert isinstance(parts, list) and len(parts) >= 3, parts
        subject, value, state = str(parts[0]), str(parts[1]), str(parts[2])
        if state == "known" and value.lstrip("-").isdigit():
            amounts[subject] = value
    return amounts


def _load_oracle():
    spec = importlib.util.spec_from_file_location("tutorial_zorgtoeslag_reference", ORACLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _facts_source() -> Path:
    facts_dir = SLICE / "facts"
    return facts_dir if facts_dir.is_dir() else SLICE / "facts.rezono"


def _mentions_version(text: str, version: str) -> bool:
    pattern = re.compile(
        rf'(?:\bversion\s+{re.escape(version)}\b|\bv{re.escape(version)}\b|"version"\s*:\s*"{re.escape(version)}")',
        re.IGNORECASE,
    )
    return bool(pattern.search(text))


def _mentions_cents(text: str, cents_str: str) -> bool:
    if re.search(rf"\b{re.escape(cents_str)}\b", text):
        return True
    cents = int(cents_str)
    if cents % 100 == 0:
        euros = cents // 100
        for formatted in (f"{euros:,}", str(euros)):
            if re.search(rf"(?:€|EUR\s*){re.escape(formatted)}(?:\.00)?\b", text):
                return True
    return False


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/ask-place-time-restrictions.md: Add a two-knowledge-dates step to "
        "docs/tutorial.md on examples/zorgtoeslag-slice asking the exact same question at two "
        "distinct `as known on <date>` dates, showing who receives a different amount and from "
        "which version of which parameter that difference follows, verified end-to-end against "
        "bitemporal publication (decisions/bitemporal-history-publication.md) and real edge/gate "
        "POST /ask evaluation."
    ),
)
def test_tutorial_two_knowledge_dates_step_matches_real_zorgtoeslag_ask(tmp_path: Path):
    page = PAGE.read_text(encoding="utf-8")
    matching_sections = [
        sec for sec in _split_sections(page)
        if "examples/zorgtoeslag-slice" in sec and AS_KNOWN_ON.search(sec)
    ]
    assert matching_sections, (
        "docs/tutorial.md must include a section on examples/zorgtoeslag-slice that asks the same "
        "question at two distinct knowledge dates (`as known on YYYY-MM-DD`)"
    )
    section = matching_sections[0]
    blocks = _fenced_blocks(section)
    assert len(blocks) >= 2, (
        "docs/tutorial.md two-knowledge-dates section must show both the command/query and its "
        f"output in fenced code blocks; found {len(blocks)} block(s)"
    )

    queries = _extract_ask_queries(section)
    (q1, d1), (q2, d2), extra_pairs = _pick_identical_question_pair(queries)
    assert d1 < d2, f"expected two distinct ordered knowledge dates, got {d1!r} and {d2!r}"
    as_of = _extract_as_of_date(section)

    # Publish the real examples/zorgtoeslag-slice pack at the two extracted knowledge dates.
    store_dir, manifests = support.publish_history(tmp_path, [(as_of, d1), (as_of, d2)])
    assert [m["id"] for m in manifests] == ["m-1", "m-2"]

    # Evaluate the exact two questions extracted from docs/tutorial.md through real edge/gate POST /ask.
    ans1, ans2 = _post_ask(store_dir, "checker", "m-2", q1, q2)
    assert ans1["status"] == 200, (q1, ans1)
    assert ans2["status"] == 200, (q2, ans2)

    body1, body2 = ans1["body"], ans2["body"]
    assert body1.get("restriction") == {
        "default": False,
        "at": None,
        "during": None,
        "as_known": d1,
        "resolved_manifest": "m-1",
        "knowledge_time": f"{d1}T00:00:00Z",
    }, body1.get("restriction")
    assert body2.get("restriction") == {
        "default": False,
        "at": None,
        "during": None,
        "as_known": d2,
        "resolved_manifest": "m-2",
        "knowledge_time": f"{d2}T00:00:00Z",
    }, body2.get("restriction")

    w1 = body1.get("calc_witnesses") or []
    w2 = body2.get("calc_witnesses") or []
    assert w1 and w2, f"expected verified calc_witnesses on both answers: {len(w1)}, {len(w2)}"
    assert w1 != w2, "expected distinct calc_witnesses between the two knowledge dates"

    amounts1 = _known_amounts_by_subject(body1)
    amounts2 = _known_amounts_by_subject(body2)
    diff_subjects = {
        subject: (amounts1[subject], amounts2[subject])
        for subject in sorted(amounts1.keys() & amounts2.keys())
        if amounts1[subject] != amounts2[subject]
    }
    assert diff_subjects, (
        f"the two tutorial queries at {d1} and {d2} produced no differing allowance amounts: "
        f"{amounts1} vs {amounts2}"
    )

    # Cross-check the real gate amounts against the independent stdlib oracle.
    oracle = _load_oracle()
    facts_src = _facts_source()
    for subject, (v1, v2) in diff_subjects.items():
        assert oracle.allowance(facts_src, subject, as_of, d1) == int(v1), (subject, as_of, d1, v1)
        assert oracle.allowance(facts_src, subject, as_of, d2) == int(v2), (subject, as_of, d2, v2)

    # Verify the tutorial names at least one affected applicant/person and both real differing amounts
    # in both the section text and its shown output block(s).
    blocks_text = "\n".join(body for _lang, body in blocks)
    named_diff = [
        subject for subject in diff_subjects
        if re.search(rf"\b{re.escape(subject)}\b", section)
    ]
    assert named_diff, (
        f"docs/tutorial.md must name at least one affected subject from {sorted(diff_subjects)}"
    )
    shown_in_block = False
    for subject in named_diff:
        v1, v2 = diff_subjects[subject]
        assert _mentions_cents(section, v1) and _mentions_cents(section, v2), (
            f"docs/tutorial.md names {subject!r} but does not show both real amounts ({v1} and {v2})"
        )
        if (
            re.search(rf"\b{re.escape(subject)}\b", blocks_text)
            and re.search(rf"\b{re.escape(v1)}\b", blocks_text)
            and re.search(rf"\b{re.escape(v2)}\b", blocks_text)
        ):
            shown_in_block = True
    assert shown_in_block, (
        "docs/tutorial.md must show at least one affected subject and both real differing amounts "
        f"inside a fenced output block; differing subjects: {diff_subjects}"
    )

    # If the tutorial embeds any JSON answer excerpts from the gate, verify they match the real answers.
    answers_by_date = {d1: body1, d2: body2}
    for (eq1, ed1), (eq2, ed2) in extra_pairs:
        extra1, extra2 = _post_ask(store_dir, "checker", "m-2", eq1, eq2)
        assert extra1["status"] == 200, (eq1, extra1)
        assert extra2["status"] == 200, (eq2, extra2)
        assert extra1["body"].get("restriction", {}).get("as_known") == ed1, extra1["body"]
        assert extra2["body"].get("restriction", {}).get("as_known") == ed2, extra2["body"]

    # Determine from the real gate parameter witnesses which parameter and versions changed between d1 and d2.
    probe_subject = named_diff[0]
    param_queries = [
        f'ask {kind} as known on {date} where subject = "{probe_subject}" show subject, value'
        for kind, _name in PARAM_RELATIONS
        for date in (d1, d2)
    ]
    param_replies = _post_ask(store_dir, "checker", "m-2", *param_queries)
    changed_params: list[tuple[str, str, str, str, str]] = []
    for idx, (_kind, param_name) in enumerate(PARAM_RELATIONS):
        r1, r2 = param_replies[2 * idx], param_replies[2 * idx + 1]
        assert r1["status"] == 200 and r2["status"] == 200, (param_name, r1, r2)
        pw1 = r1["body"].get("calc_witnesses") or []
        pw2 = r2["body"].get("calc_witnesses") or []
        assert len(pw1) == 1 and len(pw2) == 1, (param_name, pw1, pw2)
        ver1, val1 = str(pw1[0]["version"]), str(pw1[0]["value"])
        ver2, val2 = str(pw2[0]["version"]), str(pw2[0]["value"])
        if ver1 != ver2 or val1 != val2:
            changed_params.append((param_name, ver1, val1, ver2, val2))

    assert changed_params, (
        f"no parameter version changed between {d1} and {d2} on examples/zorgtoeslag-slice; "
        "the tutorial step must demonstrate a difference that follows from a parameter version change"
    )

    for param_name, ver1, val1, ver2, val2 in changed_params:
        assert re.search(rf"\b{re.escape(param_name)}\b", section), (
            f"docs/tutorial.md must name the parameter {param_name!r} whose version changed"
        )
        assert _mentions_version(section, ver1) and _mentions_version(section, ver2), (
            f"docs/tutorial.md must name both versions ({ver1} and {ver2}) of parameter {param_name!r}"
        )
        assert _mentions_cents(section, val1) and _mentions_cents(section, val2), (
            f"docs/tutorial.md must show both values ({val1} and {val2}) of parameter {param_name!r}"
        )

    # Verify any embedded rezono.answer/1 JSON block in the section matches the real gate output.
    all_real_answers = [body1, body2] + [r["body"] for r in param_replies]
    for lang, body in blocks:
        if lang != "json":
            continue
        parsed = json.loads(body)
        if isinstance(parsed, dict) and parsed.get("format") == "rezono.answer/1":
            restriction = parsed.get("restriction")
            assert isinstance(restriction, dict), parsed
            known_at = restriction.get("as_known")
            assert known_at in answers_by_date, parsed
            matching_real = [
                ans for ans in all_real_answers
                if ans.get("restriction") == restriction
            ]
            assert matching_real, f"shown JSON restriction does not match any real gate answer: {restriction}"
            shown_rows = _answer_rows(parsed)
            if shown_rows:
                real_ids = {
                    row["$id"]
                    for ans in matching_real
                    for row in _answer_rows(ans)
                }
                for row in shown_rows:
                    assert row.get("$id") in real_ids, (
                        f"shown JSON Answer row {row!r} does not match real gate output {sorted(real_ids)}"
                    )
