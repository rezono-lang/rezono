"""Deterministic `round` (no alphabetical type choice in evaluate.ts or answer-schema.ts), explicit target type
`round(x as TargetType[, mode])`, optional `default_units`, all four rounding modes (`down`, `up`, `half_up`,
`half_even`) alongside distinct `floor` and `ceil`, and the shared symmetric 64-bit exact-number bound
`BOUND = 2^63 - 1` (decisions/language-rezono-1-refinements.md, section 3.4)."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]

DETERMINISTIC_ROUND_PROBE = """\
import { answer, check, isError, load, outputSchema } from './rezono/src/index.ts';

function makeSchema({ withMicro = false, withDefault = false } = {}) {
  const types = {
    Euro: { of: 'Money', currency: 'EUR', scale: '2' },
    Hour: { of: 'Quantity', dimension: 'time', unit: 'h', storage_unit: 's', factor: '3600' },
    GiB: { of: 'Quantity', dimension: 'data', unit: 'GiB', storage_unit: 'B', factor: '1073741824' },
    EurPerHour: { of: 'Money', currency: 'EUR', per: 'h', scale: '4' },
  };
  if (withMicro) {
    types.AaaMicroEur = { of: 'Money', currency: 'EUR', scale: '6' };
  }
  return {
    rezono: '1.0',
    pack: 'sample',
    base: 'https://example.org/sample/',
    types,
    symbols: { '€': 'EUR' },
    rounding: { money: 'half_even' },
    ...(withDefault ? { default_units: { 'money EUR': 'Euro' } } : {}),
    kinds: {
      Rate: {
        world: 'closed',
        id: { type: 'Text' },
        slots: {
          hourly: { type: 'EurPerHour', card: '1', states: ['known'] },
        },
      },
    },
  };
}

const rows = [{ $kind: 'Rate', $id: 'r1', hourly: '€ 0.1234/h' }];

async function askOne(query, schema) {
  const checked = check(query, schema);
  if (checked.diagnostics.some(isError)) {
    return { codes: checked.diagnostics.map((d) => d.code) };
  }
  const data = load(schema, rows);
  const ans = await answer(checked, schema, data);
  const outSchema = await outputSchema(checked.tree, checked, schema);
  const slotType = outSchema?.kinds.Answer.slots.c1.type ?? null;
  return {
    codes: checked.diagnostics.map((d) => d.code),
    c1: ans.rows[0]?.c1 ?? null,
    slot_type: slotType,
    slot_type_def: slotType ? (outSchema?.types[slotType] ?? null) : null,
  };
}

const baseSchema = makeSchema();
const microSchema = makeSchema({ withMicro: true });
const defaultMicroSchema = makeSchema({ withMicro: true, withDefault: true });

const explicitBase = await askOne('ask Rate where true show round(hourly * 1 h as Euro, half_even)', baseSchema);
const explicitMicro = await askOne('ask Rate where true show round(hourly * 1 h as Euro, half_even)', microSchema);
const computedBase = await askOne('ask Rate where true show hourly * 1 h', baseSchema);
const computedMicro = await askOne('ask Rate where true show hourly * 1 h', microSchema);
const ambiguousRound = await askOne('ask Rate where true show round(hourly * 1 h, half_even)', microSchema);
const declaredDefault = await askOne('ask Rate where true show round(hourly * 1 h, half_even)', defaultMicroSchema);
const wrongDim = await askOne('ask Rate where true show round(hourly * 1 h as GiB, half_even)', baseSchema);

process.stdout.write(JSON.stringify({
  explicitBase,
  explicitMicro,
  computedBase,
  computedMicro,
  ambiguousRound,
  declaredDefault,
  wrongDim,
}));
"""

MODES_AND_BOUNDS_PROBE = """\
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
        num: { type: 'Integer', card: '1', states: ['known'] },
        den: { type: 'Integer', card: '1', states: ['known'] },
      },
    },
  },
};

const samples = [
  ['p3_2', 3, 2],
  ['p5_2', 5, 2],
  ['p1_4', 1, 4],
  ['m1_4', -1, 4],
  ['m1_2', -1, 2],
  ['m3_2', -3, 2],
  ['m5_2', -5, 2],
];

const data = load(schema, samples.map(([$id, num, den]) => ({ $kind: 'Probe', $id, num, den })));

async function evalAll(expr) {
  const checked = check(`ask Probe where true show ${expr}`, schema);
  if (checked.diagnostics.some(isError)) return { error: checked.diagnostics.map((d) => d.code) };
  const ans = await answer(checked, schema, data);
  return Object.fromEntries(ans.rows.map((r) => [r.$id, r.c1]));
}

const modes = {
  down: await evalAll('round(num / den, down)'),
  up: await evalAll('round(num / den, up)'),
  half_up: await evalAll('round(num / den, half_up)'),
  half_even: await evalAll('round(num / den, half_even)'),
  floor: await evalAll('floor(num / den)'),
  ceil: await evalAll('ceil(num / den)'),
};

const boundData = load(schema, [{ $kind: 'Probe', $id: 'b1', num: 1, den: 1 }]);
async function evalBound(expr) {
  const checked = check(`ask Probe where true show ${expr}`, schema);
  if (checked.diagnostics.some(isError)) return { error: checked.diagnostics.map((d) => d.code) };
  const ans = await answer(checked, schema, boundData);
  return ans.rows[0]?.c1 ?? null;
}

const bounds = {
  max_ok: await evalBound('9223372036854775807'),
  min_ok: await evalBound('-9223372036854775807'),
  neg_min_ok: await evalBound('-(-9223372036854775807)'),
  pos_overflow: await evalBound('9223372036854775807 + 1'),
  neg_overflow: await evalBound('-9223372036854775807 - 1'),
};

process.stdout.write(JSON.stringify({ modes, bounds }));
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


class NonDeterministicRoundError(AssertionError):
    """`round` or `outputSchema` still relies on alphabetical type lookup or lacks `round(x as Type, mode)` / `default_units`."""


class RoundingOrBoundMismatchError(AssertionError):
    """Rounding modes (`down`/`up`/`half_up`/`half_even`), `floor`/`ceil`, or symmetric 64-bit `BOUND = 2^63 - 1` failed."""


def test_round_is_invariant_to_alphabetical_types_and_requires_target():
    res = run_node(DETERMINISTIC_ROUND_PROBE)
    problems = []

    if res["explicitBase"].get("codes") or res["explicitMicro"].get("codes"):
        problems.append({"explicit_as_failed": [res["explicitBase"], res["explicitMicro"]]})
    elif res["explicitBase"]["c1"] != "€ 0.12" or res["explicitMicro"]["c1"] != "€ 0.12":
        problems.append({"explicit_as_wrong_value": [res["explicitBase"], res["explicitMicro"]]})

    if (res["computedBase"].get("slot_type") != res["computedMicro"].get("slot_type")
            or res["computedBase"].get("slot_type_def") != res["computedMicro"].get("slot_type_def")
            or res["computedMicro"].get("slot_type") in ("p.AaaMicroEur", "p.Euro")):
        problems.append({
            "output_schema_not_invariant_to_alphabetical_type": {
                "base": res["computedBase"],
                "with_micro": res["computedMicro"],
            }
        })

    if "R013" not in res["ambiguousRound"].get("codes", []):
        problems.append({"ambiguous_round_not_r013": res["ambiguousRound"]})

    if res["declaredDefault"].get("codes") or res["declaredDefault"].get("c1") != "€ 0.12":
        problems.append({"declared_default_units_failed": res["declaredDefault"]})

    if "R003" not in res["wrongDim"].get("codes", []):
        problems.append({"wrong_dimension_not_r003": res["wrongDim"]})

    if problems:
        raise NonDeterministicRoundError(json.dumps(problems, indent=2))


def test_round_modes_floor_ceil_and_64bit_bound():
    res = run_node(MODES_AND_BOUNDS_PROBE)
    problems = []

    want_modes = {
        "down":      {"p3_2": "1", "p5_2": "2", "p1_4": "0", "m1_4": "0",  "m1_2": "0",  "m3_2": "-1", "m5_2": "-2"},
        "up":        {"p3_2": "2", "p5_2": "3", "p1_4": "1", "m1_4": "-1", "m1_2": "-1", "m3_2": "-2", "m5_2": "-3"},
        "half_up":   {"p3_2": "2", "p5_2": "3", "p1_4": "0", "m1_4": "0",  "m1_2": "-1", "m3_2": "-2", "m5_2": "-3"},
        "half_even": {"p3_2": "2", "p5_2": "2", "p1_4": "0", "m1_4": "0",  "m1_2": "0",  "m3_2": "-2", "m5_2": "-2"},
        "floor":     {"p3_2": "1", "p5_2": "2", "p1_4": "0", "m1_4": "-1", "m1_2": "-1", "m3_2": "-2", "m5_2": "-3"},
        "ceil":      {"p3_2": "2", "p5_2": "3", "p1_4": "1", "m1_4": "0",  "m1_2": "0",  "m3_2": "-1", "m5_2": "-2"},
    }
    for name, want in want_modes.items():
        if res["modes"].get(name) != want:
            problems.append({"mode": name, "got": res["modes"].get(name), "want": want})

    want_bounds = {
        "max_ok": 9223372036854775807,
        "min_ok": -9223372036854775807,
        "neg_min_ok": 9223372036854775807,
        "pos_overflow": {"$unknown": "beyond_exact_bound"},
        "neg_overflow": {"$unknown": "beyond_exact_bound"},
    }
    # Large integers serialize as canonical decimal text or numbers depending on Row JSON; compare via string form
    # for the known extremes while requiring exact `{"$unknown": "beyond_exact_bound"}` on overflow.
    got_bounds = res["bounds"]
    for key in ("max_ok", "min_ok", "neg_min_ok"):
        if str(got_bounds.get(key)) != str(want_bounds[key]):
            problems.append({"bound": key, "got": got_bounds.get(key), "want": want_bounds[key]})
    for key in ("pos_overflow", "neg_overflow"):
        if got_bounds.get(key) != want_bounds[key]:
            problems.append({"bound": key, "got": got_bounds.get(key), "want": want_bounds[key]})

    if problems:
        raise RoundingOrBoundMismatchError(json.dumps(problems, indent=2))
