"""Generate a TextMate syntax-highlighting grammar directly from rezono/src/'s Ohm grammar
(decisions/language-rezono-1.md, sections 1 and 8)."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "rezono" / "src" / "syntax-grammar.ts"

KEYWORDS_PROBE = """\
import { keywords, aggregates } from './rezono/src/rule-names.ts';
process.stdout.write(JSON.stringify({ keywords, aggregates }));
"""


class MissingSyntaxGrammarGenerator(AssertionError):
    """The syntax-highlighting grammar generator is missing, non-deterministic, or out of sync with grammar.ts."""


def test_generated_syntax_highlighting_grammar():
    if not GENERATOR.is_file():
        raise MissingSyntaxGrammarGenerator("missing rezono/src/syntax-grammar.ts")

    first = subprocess.run(["node", str(GENERATOR)], cwd=ROOT, capture_output=True, encoding="utf-8")
    second = subprocess.run(["node", str(GENERATOR)], cwd=ROOT, capture_output=True, encoding="utf-8")
    problems = []
    if first.returncode != 0 or second.returncode != 0:
        problems.append({"exit_codes": [first.returncode, second.returncode], "stderr": first.stderr})
    elif first.stdout != second.stdout:
        problems.append("generator output is not deterministic across two runs")
    else:
        grammar = json.loads(first.stdout)
        if grammar.get("scopeName") != "source.rezono":
            problems.append({"scopeName": grammar.get("scopeName")})
        if not isinstance(grammar.get("patterns"), list) or not grammar["patterns"]:
            problems.append("missing top-level patterns")
        if not isinstance(grammar.get("repository"), dict) or not grammar["repository"]:
            problems.append("missing repository")

        kw_run = subprocess.run(
            ["node", "--input-type=module", "-e", KEYWORDS_PROBE],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )
        vocab = json.loads(kw_run.stdout)
        text = first.stdout
        missing_keywords = [word for word in vocab["keywords"] if word not in text]
        missing_aggregates = [word for word in vocab["aggregates"] if word not in text]
        if missing_keywords:
            problems.append({"missing_keywords": missing_keywords})
        if missing_aggregates:
            problems.append({"missing_aggregates": missing_aggregates})
        for token, label in (("--", "line comment"), ("@", "source citation")):
            if token not in text:
                problems.append(f"grammar text does not mention {label} ({token!r})")

    if problems:
        raise MissingSyntaxGrammarGenerator(json.dumps(problems, indent=2))
