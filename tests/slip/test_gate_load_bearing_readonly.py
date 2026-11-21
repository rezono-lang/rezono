"""Planner red test verifying the gate only reads published load_bearing flags (decisions/publish-founded-witnesses.md, #1445).

Runs `edge/gate/src/ask.ts` directly via Node:
1. When a checked proof step carries a published `load_bearing` flag, `ask()` projects it verbatim onto
   `AnswerStep.load_bearing`.
2. When a proof step omits `load_bearing`, `ask()` leaves `load_bearing` absent — it never derives or
   guesses `load_bearing` in the gate, even when a conclusion has two distinct witnesses.
"""

import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
ASK_TS = (ROOT / "edge" / "gate" / "src" / "ask.ts").as_uri()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/publish-founded-witnesses.md (#1445): edge/gate/src/ask.ts must project "
        "published load_bearing flags verbatim onto AnswerStep and never derive load_bearing itself"
    ),
)
def test_gate_ask_only_reads_published_load_bearing_flags():
    script = f"""
import {{ ask, memoryGraph }} from {json.dumps(ASK_TS)};

const c = {{ relation: 'near', key: '["a","b"]' }};
const p1 = {{ relation: 'edge', key: '["b","a"]' }};
const p2 = {{ relation: 'edge', key: '["a","b"]' }};
const w1 = {{
  conclusion: c,
  rule_id: 'near_in',
  bindings: [{{ variable: '?a', value: 'a' }}, {{ variable: '?b', value: 'b' }}],
  premises: [{{ row: p1, polarity: 'positive', stratum: 0 }}],
}};
const w2 = {{
  conclusion: c,
  rule_id: 'near_out',
  bindings: [{{ variable: '?a', value: 'a' }}, {{ variable: '?b', value: 'b' }}],
  premises: [{{ row: p2, polarity: 'positive', stratum: 0 }}],
}};
const question = {{
  term: 'grounds',
  start: 'present',
  answer: 'route',
  limit: 20,
  steps: [{{ trace: {{ direction: 'back', depth: 'all' }} }}],
}};

// Step 1 carries published load_bearing=false; Step 2 omits load_bearing completely.
const g = memoryGraph(
  [w1, w2],
  [
    {{ c, p: p1, how: 'positive', position: 0, load_bearing: false }},
    {{ c, p: p2, how: 'positive', position: 0 }},
  ],
);
const ans = await ask(g, question, 'm-1', c, {{ limit: 20 }});
console.log(JSON.stringify(ans?.steps ?? []));
"""
    node_bin = os.environ.get("REZONO_NODE", "node")
    proc = subprocess.run(
        [node_bin, "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    steps = json.loads(proc.stdout)
    by_premise = {s["premise"]["key"]: s for s in steps}
    assert '["b","a"]' in by_premise and '["a","b"]' in by_premise
    # 1. Published flag must be projected verbatim onto AnswerStep.load_bearing.
    assert by_premise['["b","a"]'].get("load_bearing") is False, (
        f"gate must project published load_bearing=false verbatim, got {by_premise['[\"b\",\"a\"]']}"
    )
    # 2. Omitted flag must stay absent (gate must never compute/derive load_bearing itself).
    assert "load_bearing" not in by_premise['["a","b"]'], (
        f"gate must not invent load_bearing when omitted from proof step, got {by_premise['[\"a\",\"b\"]']}"
    )
