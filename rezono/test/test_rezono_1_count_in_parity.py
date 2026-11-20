"""Cross-engine expression parity in rezono/src/evaluate.ts:
1. `S.count(pred)` is identically equal to `S.where(pred).count()` (`n/a` predicate results excluded, `unknown` and
   `invalid` undecided), while zero-argument `S.count()` remains strict in member states.
2. `x in S` includes `S`'s member states and undecided memberships in `worst` when `x` is not `known`
   (`n/a in [invalid] = invalid`, matching `a in lo..hi` and Appendix A.3).
(decisions/language-rezono-1-refinements.md, sections 3.1 and 3.2)."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]

COUNT_PROBE = """\
import { answer, check, isError, load } from './rezono/src/index.ts';

const schema = {
  rezono: '1.0',
  pack: 'sample',
  base: 'https://example.org/sample/',
  kinds: {
    Probe: { world: 'closed', id: { type: 'Text' }, slots: {} },
    Item: {
      world: 'closed',
      id: { type: 'Text' },
      slots: {
        tag: { type: 'Text', card: '?', states: ['known', 'not_applicable', 'unknown', 'invalid'] },
      },
    },
  },
};

async function runCase(items) {
  const data = load(schema, [{ $kind: 'Probe', $id: 'p1' }, ...items]);
  const run = async (q) => {
    const checked = check(q, schema);
    if (checked.diagnostics.some(isError)) return { error: checked.diagnostics.map((d) => d.code) };
    const ans = await answer(checked, schema, data);
    return {
      rows: ans.rows.map((r) => [r.$id, r.c1]),
      undecided: ans.undecided.map((u) => [u.$id, u.state, u.reason]),
      not_applicable: ans.counts.not_applicable,
    };
  };
  return {
    where_count: await run('ask Probe where true show (Item where tag = "a").count()'),
    count_pred: await run('ask Probe where true show Item.count(tag = "a")'),
    zero_arg_na: await run('ask Probe where true show Item.tag.count()'),
  };
}

const with_na = await runCase([
  { $kind: 'Item', $id: 'i1', tag: 'a' },
  { $kind: 'Item', $id: 'i2', tag: { $na: '' } },
  { $kind: 'Item', $id: 'i3', tag: 'b' },
]);

const with_unknown = await runCase([
  { $kind: 'Item', $id: 'i1', tag: 'a' },
  { $kind: 'Item', $id: 'i2', tag: { $unknown: 'missing_tag' } },
  { $kind: 'Item', $id: 'i3', tag: { $na: '' } },
]);

const with_invalid = await runCase([
  { $kind: 'Item', $id: 'i1', tag: 'a' },
  { $kind: 'Item', $id: 'i2', tag: { $invalid: 'bad_tag' } },
  { $kind: 'Item', $id: 'i3', tag: { $unknown: 'missing_tag' } },
  { $kind: 'Item', $id: 'i4', tag: { $na: '' } },
]);

process.stdout.write(JSON.stringify({ with_na, with_unknown, with_invalid }));
"""

IN_PROBE = """\
import { answer, check, isError, load } from './rezono/src/index.ts';

const schema = {
  rezono: '1.0',
  pack: 'sample',
  base: 'https://example.org/sample/',
  kinds: {
    Probe: {
      world: 'closed',
      id: { type: 'Text' },
      slots: {
        needle: { type: 'Text', card: '?', states: ['known', 'not_applicable', 'unknown', 'invalid'] },
      },
    },
    Bucket: {
      world: 'closed',
      id: { type: 'Text' },
      slots: {
        val: { type: 'Text', card: '?', states: ['known', 'not_applicable', 'unknown', 'invalid'] },
        flag: { type: 'Bool', card: '1', states: ['known', 'unknown', 'invalid'] },
      },
    },
    OpenBag: { world: 'open', id: { type: 'Text' }, slots: {} },
  },
};

async function evalIn(probes, buckets, query) {
  const data = load(schema, [...probes, ...buckets]);
  const checked = check(query, schema);
  if (checked.diagnostics.some(isError)) return { error: checked.diagnostics.map((d) => d.code) };
  const ans = await answer(checked, schema, data);
  return {
    rows: ans.rows.map((r) => r.$id),
    undecided: ans.undecided.map((u) => [u.$id, u.state, u.reason]),
    not_applicable: ans.counts.not_applicable,
  };
}

const na_in_invalid = await evalIn(
  [{ $kind: 'Probe', $id: 'p1', needle: { $na: '' } }],
  [{ $kind: 'Bucket', $id: 'b1', val: 'ok', flag: true }, { $kind: 'Bucket', $id: 'b2', val: { $invalid: 'bad_member' }, flag: true }],
  'ask Probe where needle in Bucket.val',
);

const na_in_unknown = await evalIn(
  [{ $kind: 'Probe', $id: 'p1', needle: { $na: '' } }],
  [{ $kind: 'Bucket', $id: 'b1', val: 'ok', flag: true }, { $kind: 'Bucket', $id: 'b2', val: { $unknown: 'miss_member' }, flag: true }],
  'ask Probe where needle in Bucket.val',
);

const unknown_in_invalid = await evalIn(
  [{ $kind: 'Probe', $id: 'p1', needle: { $unknown: 'lhs_unknown' } }],
  [{ $kind: 'Bucket', $id: 'b1', val: { $invalid: 'bad_member' }, flag: true }],
  'ask Probe where needle in Bucket.val',
);

const na_in_invalid_filter = await evalIn(
  [{ $kind: 'Probe', $id: 'p1', needle: { $na: '' } }],
  [{ $kind: 'Bucket', $id: 'b1', val: 'ok', flag: { $invalid: 'bad_filter' } }],
  'ask Probe where needle in (Bucket where flag).val',
);

const na_in_known = await evalIn(
  [{ $kind: 'Probe', $id: 'p1', needle: { $na: '' } }],
  [{ $kind: 'Bucket', $id: 'b1', val: 'ok', flag: true }],
  'ask Probe where needle in Bucket.val',
);

const known_decisive = await evalIn(
  [{ $kind: 'Probe', $id: 'p1', needle: 'ok' }],
  [{ $kind: 'Bucket', $id: 'b1', val: 'ok', flag: true }, { $kind: 'Bucket', $id: 'b2', val: { $invalid: 'bad_member' }, flag: true }],
  'ask Probe where needle in Bucket.val',
);

process.stdout.write(JSON.stringify({
  na_in_invalid,
  na_in_unknown,
  unknown_in_invalid,
  na_in_invalid_filter,
  na_in_known,
  known_decisive,
}));
"""


def run_node(script):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class CountPredParityError(AssertionError):
    """`S.count(pred)` did not match `S.where(pred).count()` across n/a, unknown, and invalid predicate outcomes."""


class InSetWorstError(AssertionError):
    """`x in S` did not include `S`'s states in `worst` when `x` is not `known`."""


def test_count_pred_matches_where_count_with_na_unknown_invalid():
    res = run_node(COUNT_PROBE)
    problems = []

    if res["with_na"]["where_count"]["rows"] != [["p1", "1"]]:
        problems.append({"where_count_na_baseline": res["with_na"]["where_count"]})
    if res["with_na"]["count_pred"] != res["with_na"]["where_count"]:
        problems.append({
            "count_pred_diverged_on_na": res["with_na"]["count_pred"],
            "where_count": res["with_na"]["where_count"],
        })
    if res["with_na"]["zero_arg_na"]["rows"] != [["p1", {"$na": ""}]]:
        problems.append({"zero_arg_count_not_strict_on_na": res["with_na"]["zero_arg_na"]})

    if res["with_unknown"]["count_pred"] != res["with_unknown"]["where_count"]:
        problems.append({"count_pred_diverged_on_unknown": res["with_unknown"]})
    if res["with_unknown"]["count_pred"]["rows"] != [["p1", {"$unknown": "missing_tag"}]]:
        problems.append({"count_pred_unknown_expected": res["with_unknown"]["count_pred"]})

    if res["with_invalid"]["count_pred"] != res["with_invalid"]["where_count"]:
        problems.append({"count_pred_diverged_on_invalid": res["with_invalid"]})
    if res["with_invalid"]["count_pred"]["rows"] != [["p1", {"$invalid": "bad_tag"}]]:
        problems.append({"count_pred_invalid_expected": res["with_invalid"]["count_pred"]})

    if problems:
        raise CountPredParityError(json.dumps(problems, indent=2))


def test_in_set_takes_worst_over_set_when_lhs_not_known():
    res = run_node(IN_PROBE)
    problems = []

    if res["na_in_invalid"] != {"rows": [], "undecided": [["p1", "invalid", "bad_member"]], "not_applicable": 0}:
        problems.append({"na_in_invalid": res["na_in_invalid"]})
    if res["na_in_unknown"] != {"rows": [], "undecided": [["p1", "unknown", "miss_member"]], "not_applicable": 0}:
        problems.append({"na_in_unknown": res["na_in_unknown"]})
    if res["unknown_in_invalid"] != {"rows": [], "undecided": [["p1", "invalid", "bad_member"]], "not_applicable": 0}:
        problems.append({"unknown_in_invalid": res["unknown_in_invalid"]})
    if res["na_in_invalid_filter"] != {"rows": [], "undecided": [["p1", "invalid", "bad_filter"]], "not_applicable": 0}:
        problems.append({"na_in_invalid_filter": res["na_in_invalid_filter"]})
    if res["na_in_known"] != {"rows": [], "undecided": [], "not_applicable": 1}:
        problems.append({"na_in_known": res["na_in_known"]})
    if res["known_decisive"] != {"rows": ["p1"], "undecided": [], "not_applicable": 0}:
        problems.append({"known_decisive": res["known_decisive"]})

    if problems:
        raise InSetWorstError(json.dumps(problems, indent=2))
