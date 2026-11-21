"""Slip model status-sign mapping for `invalid` values (decisions/std-view-invalid-sign.md).

`viewer/slip/src/model.ts` must map `ValueState` `'invalid'` to the `std-view` `'invalid'` sign (`!`)
rather than `'violated'` (`✕`), keeping `'unknown'` on `'unknown'` (`▨`).
"""

from __future__ import annotations

import json
import subprocess

import pytest
import yaml
from slip_support import ROOT, node

STD_VIEW = ROOT / "packs" / "std-view"
MODEL = ROOT / "viewer" / "slip" / "src" / "model.ts"

PROBE = """\
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const { modelPath, statuses, viewMessages } = JSON.parse(readFileSync(0, 'utf8'));
const { buildRuleSlipView } = await import(pathToFileURL(modelPath).href);

const stdPacks = {
  verbs: [],
  signs: [],
  statuses,
  viewMessages,
  explainMessages: [],
};
const head = { pack: 'sample', epoch: '1', manifest_sha256: '0'.repeat(64) };
const bundle = {
  pack: { id: 'sample', version: '1', default_language: 'en' },
  kinds: [],
  attributes: [],
  arrows: [],
  relations: [],
  rules: [],
  labels: [],
  messages: [{ lang: 'en', resource: '@locale en\\n---\\nreason.multiple_values = multiple values\\nreason.no_value = no value\\n' }],
  questions: [],
};

function lineSign(state, reason) {
  const key = ['item-a', '', state, reason];
  const keyJson = JSON.stringify(key);
  const answer = {
    start: { relation: 'calc__metric', key: keyJson },
    nodes: [],
    calc_witnesses: [{
      conclusion: { relation: 'calc__metric', key: keyJson },
      rule: 'metric',
      steps: [{ path: '/0', op: 'rule', state, reason }],
    }],
  };
  const view = buildRuleSlipView('sample', 'en', head, bundle, { relation: 'calc__metric', key }, answer, stdPacks);
  return view.lines[0]?.valueSign ?? null;
}

console.log(JSON.stringify({
  invalid: lineSign('invalid', 'multiple_values'),
  unknown: lineSign('unknown', 'no_value'),
}));
"""


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/std-view-invalid-sign.md: viewer/slip/src/model.ts must map ValueState "
        "'invalid' to the std-view 'invalid' sign ('!') rather than 'violated' ('✕')."
    ),
)
def test_slip_model_maps_invalid_state_to_invalid_sign():
    key = yaml.safe_load((STD_VIEW / "key.yaml").read_text(encoding="utf-8"))
    en_mf2 = (STD_VIEW / "messages" / "en.mf2").read_text(encoding="utf-8")
    payload = {
        "modelPath": str(MODEL),
        "statuses": key["statuses"],
        "viewMessages": [{"lang": "en", "resource": en_mf2}],
    }
    result = subprocess.run(
        [node(), "--input-type=module", "-e", PROBE],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    signs = json.loads(result.stdout)

    assert signs["unknown"] is not None
    assert signs["unknown"]["name"] == "unknown"
    assert signs["unknown"]["glyph"] == "▨"

    assert signs["invalid"] is not None
    assert signs["invalid"]["name"] == "invalid", signs["invalid"]
    assert signs["invalid"]["glyph"] == "!", signs["invalid"]
