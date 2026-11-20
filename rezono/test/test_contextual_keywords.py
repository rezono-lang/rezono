"""Contextual keywords, unrestricted member names after '.', and context-aware syntax highlighting
(decisions/language-contextual-keywords.md)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from reader_probe import read_modules

ROOT = Path(__file__).resolve().parents[2]
SYNTAX_GENERATOR = ROOT / "rezono" / "src" / "syntax-grammar.ts"

EXPECTED_HARD_KEYWORDS = frozenset(
    {
        "when",
        "then",
        "else",
        "unless",
        "where",
        "show",
        "not",
        "and",
        "or",
        "in",
        "is",
        "at",
        "as",
        "true",
        "false",
    }
)

SCHEMA = {
    "rezono": "1.0",
    "pack": "sample",
    "base": "urn:example:sample",
    "kinds": {
        "Shelf": {
            "world": "closed",
            "id": {"type": "Text"},
            "slots": {
                "open": {"type": "Bool", "card": "?", "states": ["known", "not_applicable", "unknown"]},
                "closed": {"type": "Bool", "card": "1", "states": ["known"]},
                "version": {"type": "Integer", "card": "1", "states": ["known"]},
                "valid": {"type": "Date", "card": "?", "states": ["known", "not_applicable", "unknown"]},
                "known": {"type": "Bool", "card": "1", "states": ["known"]},
                "world": {"type": "Text", "card": "1", "states": ["known"]},
                "view": {"type": "Text", "card": "1", "states": ["known"]},
                "sources": {"type": "Text", "card": "*", "states": ["known"]},
                "param": {"type": "Text", "card": "1", "states": ["known"]},
                "unit": {"type": "Text", "card": "1", "states": ["known"]},
                "enum": {"type": "Text", "card": "1", "states": ["known"]},
                "kind": {"type": "Text", "card": "1", "states": ["known"]},
            },
        },
        "Item": {
            "world": "closed",
            "id": {"type": "Text"},
            "slots": {
                "version": {"type": "Integer", "card": "1", "states": ["known"]},
            },
        },
        "Entry": {
            "world": "closed",
            "id": {"type": "Text"},
            "slots": {
                "known": {"type": "Date", "card": "?", "states": ["known", "not_applicable", "unknown"]},
            },
        },
        "Claim": {
            "world": "closed",
            "id": {"type": "Text"},
            "slots": {
                "valid": {"type": "Date", "card": "?", "states": ["known", "not_applicable", "unknown"]},
            },
        },
        "Record": {
            "world": "closed",
            "id": {"type": "Text"},
            "slots": {
                "open": {"type": "Bool", "card": "1", "states": ["known"]},
                "value": {"type": "Integer", "card": "1", "states": ["known"]},
                "type": {"type": "Text", "card": "1", "states": ["known"]},
                "range": {"type": "Integer", "card": "1", "states": ["known"]},
                "where": {"type": "Text", "card": "1", "states": ["known"]},
                "at": {"type": "Date", "card": "1", "states": ["known"]},
            },
        },
    },
}

CHECK_PROBE = """\
import { check, fromJson, isError, parse, print, toJson } from './rezono/src/index.ts';
import { keywords } from './rezono/src/rule-names.ts';

const payload = JSON.parse(process.argv[1]);
const schema = payload.schema;
const results = payload.questions.map((text) => {
  const parsed = parse(text);
  const checked = check(text, schema);
  let printed = null;
  let roundTripOk = false;
  if (parsed.tree) {
    printed = print(parsed.tree);
    try {
      const json = toJson(parsed.tree);
      roundTripOk = toJson(fromJson(JSON.parse(json))) === json;
    } catch {
      roundTripOk = false;
    }
  }
  return {
    text,
    tree: parsed.tree ?? null,
    printed,
    roundTripOk,
    parseDiagnostics: parsed.diagnostics.map((d) => ({ code: d.code, span: d.span })),
    checkErrors: checked.diagnostics.filter(isError).map((d) => ({ code: d.code, span: d.span })),
    publication: checked.publication ?? null,
  };
});
process.stdout.write(JSON.stringify({ keywords: [...keywords], results }));
"""

TOKENIZE_PROBE = """\
import { generateSyntaxGrammar } from './rezono/src/syntax-grammar.ts';

const lines = JSON.parse(process.argv[1]);
const grammar = generateSyntaxGrammar();

function collectRules(entries, seen = new Set()) {
  const out = [];
  for (const entry of entries ?? []) {
    if (entry.include && entry.include.startsWith('#')) {
      const key = entry.include.slice(1);
      if (seen.has(key)) continue;
      const next = new Set(seen);
      next.add(key);
      const target = grammar.repository?.[key];
      if (!target) continue;
      if (target.patterns && !target.begin && !target.match) {
        out.push(...collectRules(target.patterns, next));
      } else {
        out.push(target);
      }
    } else {
      out.push(entry);
    }
  }
  return out;
}

const rules = collectRules(grammar.patterns);

function compile(pattern) {
  return new RegExp(pattern, 'dgu');
}

function tokenizeLine(line) {
  const tokens = [];
  let pos = 0;
  while (pos < line.length) {
    let best = null;
    for (let i = 0; i < rules.length; i++) {
      const rule = rules[i];
      const pat = rule.match ?? rule.begin;
      if (!pat) continue;
      const re = compile(pat);
      re.lastIndex = pos;
      const m = re.exec(line);
      if (!m) continue;
      if (!best || m.index < best.m.index) {
        best = { rule, m };
        if (m.index === pos) break;
      }
    }
    if (!best) break;
    const { rule, m } = best;
    const start = m.index;
    let end = start + m[0].length;
    if (rule.begin && rule.end) {
      const endRe = compile(rule.end);
      endRe.lastIndex = end;
      const close = endRe.exec(line);
      end = close ? close.index + close[0].length : line.length;
      tokens.push({ start, end, text: line.slice(start, end), scopes: rule.name ? [rule.name] : [] });
    } else if (rule.captures && m.indices) {
      let emitted = false;
      for (const [group, spec] of Object.entries(rule.captures)) {
        const idx = Number(group);
        const span = m.indices[idx];
        if (!span || span[0] === span[1]) continue;
        emitted = true;
        const scopes = [...(rule.name ? [rule.name] : []), ...(spec?.name ? [spec.name] : [])];
        tokens.push({ start: span[0], end: span[1], text: line.slice(span[0], span[1]), scopes });
      }
      if (!emitted && rule.name) {
        tokens.push({ start, end, text: line.slice(start, end), scopes: [rule.name] });
      }
    } else if (rule.name) {
      tokens.push({ start, end, text: line.slice(start, end), scopes: [rule.name] });
    }
    pos = Math.max(end, start + 1);
  }
  return tokens;
}

process.stdout.write(JSON.stringify(lines.map((line) => ({ line, tokens: tokenizeLine(line) }))));
"""


class MissingContextualKeywords(AssertionError):
    """Dotted member names, contextual keywords, or TextMate highlighting do not match the decision."""


def _probe_questions(questions: list[str]) -> dict:
    run = subprocess.run(
        ["node", "--input-type=module", "-e", CHECK_PROBE, json.dumps({"schema": SCHEMA, "questions": questions})],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _tokenize_lines(lines: list[str]) -> list[dict]:
    run = subprocess.run(
        ["node", "--input-type=module", "-e", TOKENIZE_PROBE, json.dumps(lines)],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _scopes_at(tokenized: dict, word: str, after: str = "") -> list[str]:
    line = tokenized["line"]
    anchor = line.index(after) + len(after) if after else 0
    start = line.index(word, anchor)
    end = start + len(word)
    scopes: list[str] = []
    for token in tokenized["tokens"]:
        if token["start"] < end and token["end"] > start:
            scopes.extend(token["scopes"])
    return scopes


@pytest.mark.xfail(
    strict=True,
    raises=MissingContextualKeywords,
    reason=(
        "M3: decisions/language-contextual-keywords.md: Allow any identifier word after '.' "
        "(`Dotted \".\" identWord` and `SupposePath`), print member segments bare without backticks, "
        "and ensure `require active: shelf.open is known` and dotted paths (`item.version`, "
        "`entry.known`, `claim.valid`, `record.value`, `record.type`, `record.range`, `record.where`, "
        "`record.at`) parse, round-trip, and typecheck cleanly."
    ),
)
def test_dotted_member_names_parse_and_typecheck_without_backticks():
    questions = [
        "require active: shelf.open is known",
        "require versioned: item.version >= 1",
        "require recorded: entry.known is known",
        "require verified: claim.valid is known",
        'ask Record where record.value > 0 and record.type = "a" and record.range = 1 show record.value, record.type, record.range',
        'ask Record where record.where = "lab" and record.at = 2026-11-20',
        "ask Record where Record.where(it.open = true).count() >= 1",
        "+ shelf-1.open = true",
        "- shelf-1.open",
    ]
    data = _probe_questions(questions)
    by_text = {item["text"]: item for item in data["results"]}
    problems = []

    active = by_text["require active: shelf.open is known"]
    if (
        active["parseDiagnostics"]
        or active["checkErrors"]
        or active["printed"] != "require active: shelf.open is known"
        or not active["roundTripOk"]
        or active["publication"] != {"verb": "require", "name": "active", "binder": "shelf", "kind": "Shelf"}
        or active["tree"] != {"check": "require", "name": "active", "cond": {"is": [{"path": ["shelf", "open"]}, "known"]}}
    ):
        problems.append({"shelf_open": active})

    for exact in (
        "require versioned: item.version >= 1",
        "require recorded: entry.known is known",
        "require verified: claim.valid is known",
        'ask Record where record.value > 0 and record.type = "a" and record.range = 1 show record.value, record.type, record.range',
        'ask Record where record.where = "lab" and record.at = 2026-11-20',
        "+ shelf-1.open = true",
        "- shelf-1.open",
    ):
        entry = by_text[exact]
        if entry["parseDiagnostics"] or entry["checkErrors"] or entry["printed"] != exact or not entry["roundTripOk"]:
            problems.append({"failed_dotted": entry})

    method_call = by_text["ask Record where Record.where(it.open = true).count() >= 1"]
    where_node = (method_call["tree"] or {}).get("where")
    expected_lhs = {
        "agg": [
            "count",
            {
                "filter": [
                    {"kind": "Record"},
                    {"cmp": ["=", {"path": ["it", "open"]}, {"lit": "true"}]},
                ]
            },
        ]
    }
    if (
        method_call["parseDiagnostics"]
        or method_call["checkErrors"]
        or not method_call["roundTripOk"]
        or not isinstance(where_node, dict)
        or where_node.get("cmp", [None, None])[1] != expected_lhs
    ):
        problems.append({"method_where_and_count": method_call})

    if problems:
        raise MissingContextualKeywords(json.dumps(problems, indent=2))


@pytest.mark.xfail(
    strict=True,
    raises=MissingContextualKeywords,
    reason=(
        "M3: decisions/language-contextual-keywords.md: Restrict hard keywords in rezono/src/rule-names.ts "
        "to the 15 expression keywords, make declaration and clause keywords (`kind`, `enum`, `unit`, `param`, "
        "`version`, `valid`, `known`, `world`, `open`, `closed`, `view`, `sources`, `example`, etc.) contextual "
        "outside declaration headers, and keep expression keywords reserved."
    ),
)
def test_contextual_declaration_keywords_work_as_identifiers_while_expression_keywords_stay_reserved():
    contextual_module = """\
rezono 1
pack sample
schema example
  iri "urn:example:sample"
kind Shelf world closed
  open: Bool
  closed: Bool
  version: Int
  valid: Date
  known: Bool
  world: Text
  view: Text
  sources: Text*
  param: Text
  unit: Text
  enum: Text
  kind: Text
param version: Int = 1
require active: shelf.open is known
"""
    refused_schema_module = "rezono 1\npack sample\nschema where\n"
    ok_mod, bad_mod = read_modules(contextual_module, refused_schema_module)

    bare_ok = (
        "ask Shelf where open and not closed and version >= 1 and valid is known and known "
        "show world, view, param, unit, enum, kind"
    )
    tail_guard = "ask Shelf where version > 3 limit 5"
    hard_refusals = [
        "ask Shelf where where > 1",
        "ask Shelf where and = true",
        "ask Shelf where when = true",
        "ask Shelf where else = 1",
        "ask Shelf where show = 1",
        "ask Shelf where unless = true",
    ]
    data = _probe_questions([bare_ok, tail_guard, *hard_refusals])
    by_text = {item["text"]: item for item in data["results"]}

    problems = []
    actual_keywords = frozenset(data["keywords"])
    if actual_keywords != EXPECTED_HARD_KEYWORDS:
        problems.append(
            {
                "unexpected_hard_keywords": sorted(actual_keywords - EXPECTED_HARD_KEYWORDS),
                "missing_hard_keywords": sorted(EXPECTED_HARD_KEYWORDS - actual_keywords),
            }
        )

    if ok_mod["diagnostics"] or ok_mod["module"] is None or ok_mod["printed"] is None:
        problems.append({"contextual_module": ok_mod})
    else:
        mod = ok_mod["module"]
        if mod.get("schema") != "example":
            problems.append({"schema_name": mod.get("schema")})
        kinds = [d for d in mod["decls"] if "kind" in d]
        expected_slots = [
            "open",
            "closed",
            "version",
            "valid",
            "known",
            "world",
            "view",
            "sources",
            "param",
            "unit",
            "enum",
            "kind",
        ]
        if len(kinds) != 1 or [s["slot"] for s in kinds[0]["slots"]] != expected_slots:
            problems.append({"kind_slots": kinds})
        params = [d for d in mod["decls"] if "param" in d]
        if len(params) != 1 or params[0]["param"] != "version":
            problems.append({"param_decl": params})
        if "`" in ok_mod["printed"]:
            problems.append({"unexpected_backticks_in_printed_module": ok_mod["printed"]})
        [reparsed] = read_modules(ok_mod["printed"])
        if reparsed["diagnostics"] or reparsed["module"] != mod:
            problems.append({"module_roundtrip": reparsed})

    if bad_mod["module"] is not None or "R000" not in [d["code"] for d in bad_mod["diagnostics"]]:
        problems.append({"hard_keyword_schema_not_refused": bad_mod})

    bare_entry = by_text[bare_ok]
    if bare_entry["parseDiagnostics"] or bare_entry["checkErrors"] or bare_entry["printed"] != bare_ok:
        problems.append({"bare_contextual_expression": bare_entry})

    tail_entry = by_text[tail_guard]
    if tail_entry["tree"] is None or tail_entry["tree"].get("tail") != [{"limit": "5"}]:
        problems.append({"clause_word_after_number": tail_entry})

    for text in hard_refusals:
        entry = by_text[text]
        if entry["tree"] is not None or "R000" not in [d["code"] for d in entry["parseDiagnostics"]]:
            problems.append({"hard_keyword_not_refused": entry})

    if problems:
        raise MissingContextualKeywords(json.dumps(problems, indent=2))


@pytest.mark.xfail(
    strict=True,
    raises=MissingContextualKeywords,
    reason=(
        "M3: decisions/language-contextual-keywords.md: Update rezono/src/syntax-grammar.ts so slot names "
        "after '.' (`shelf.open`, `item.version`, `entry.known`, `claim.valid`, `x.value`, `x.type`, `x.range`, "
        "`x.where`, `x.and`) and contextual declaration words outside declaration headers are never scoped as "
        "`keyword.control*` (or operator/state scopes after '.')."
    ),
)
def test_syntax_grammar_does_not_color_dotted_slots_or_contextual_words_as_control_keywords():
    if not SYNTAX_GENERATOR.is_file():
        raise MissingContextualKeywords("missing rezono/src/syntax-grammar.ts")

    samples = [
        "require active: shelf.open is known",
        "ask Item where item.version >= 1 and entry.known is known and claim.valid is known",
        'ask Record where x.value > 0 and x.type = "a" and x.range = 1',
        'ask Record where x.where = "lab" and x.and = true',
        "  open: Bool",
        "  version: Int",
        "  value: Int",
        "  type: Text",
        "  range: Int",
        "  valid: Date",
        "  world: Text",
        "  view: Text",
        "  sources: Text*",
        "ask Shelf where open and version > 1 and value = type and range > 0 and valid is known and view = world and param = unit and enum = kind show open",
        "kind Shelf world closed",
        "param rate: Int = 1",
        "when a then b else c",
    ]
    tokenized = {item["line"]: item for item in _tokenize_lines(samples)}
    problems = []

    # 1. Slot names after '.' must never be colored as keyword.control*, keyword.operator.*, or constant.language.*.
    dotted_checks = [
        ("require active: shelf.open is known", "open", "shelf."),
        ("ask Item where item.version >= 1 and entry.known is known and claim.valid is known", "version", "item."),
        ("ask Item where item.version >= 1 and entry.known is known and claim.valid is known", "known", "entry."),
        ("ask Item where item.version >= 1 and entry.known is known and claim.valid is known", "valid", "claim."),
        ('ask Record where x.value > 0 and x.type = "a" and x.range = 1', "value", "x."),
        ('ask Record where x.value > 0 and x.type = "a" and x.range = 1', "type", "x."),
        ('ask Record where x.value > 0 and x.type = "a" and x.range = 1', "range", "x."),
        ('ask Record where x.where = "lab" and x.and = true', "where", "x."),
        ('ask Record where x.where = "lab" and x.and = true', "and", "x."),
    ]
    for line, word, after in dotted_checks:
        scopes = _scopes_at(tokenized[line], word, after)
        bad = [s for s in scopes if s.startswith(("keyword.control", "keyword.operator.", "constant.language."))]
        if bad:
            problems.append({"dotted_slot_miscolored": {"line": line, "word": after + word, "scopes": scopes}})

    # 2. Contextual declaration words in slot declarations or expression positions must never be keyword.control*.
    for slot_word in ("open", "version", "value", "type", "range", "valid", "world", "view", "sources"):
        line = next(s for s in samples if s.startswith(f"  {slot_word}:"))
        scopes = _scopes_at(tokenized[line], slot_word)
        if any(s.startswith("keyword.control") for s in scopes):
            problems.append({"slot_decl_colored_as_control": {"line": line, "word": slot_word, "scopes": scopes}})

    expr_line = (
        "ask Shelf where open and version > 1 and value = type and range > 0 "
        "and valid is known and view = world and param = unit and enum = kind show open"
    )
    for word, after in (
        ("open", "where "),
        ("version", "and "),
        ("value", "and "),
        ("type", "= "),
        ("range", "and "),
        ("valid", "and "),
        ("view", "and "),
        ("world", "= "),
        ("param", "and "),
        ("unit", "= "),
        ("enum", "and "),
        ("kind", "= "),
        ("open", "show "),
    ):
        scopes = _scopes_at(tokenized[expr_line], word, after)
        if any(s.startswith("keyword.control") for s in scopes):
            problems.append({"contextual_expr_colored_as_control": {"word": word, "after": after, "scopes": scopes}})

    # 3. Positive sanity checks: hard expression keywords and declaration headers keep keyword scopes.
    for line, word, after, prefix in (
        ("when a then b else c", "when", "", "keyword.control"),
        ("when a then b else c", "then", "a ", "keyword.control"),
        ("when a then b else c", "else", "b ", "keyword.control"),
        (expr_line, "where", "Shelf ", "keyword.control"),
        (expr_line, "show", "kind ", "keyword.control"),
        (expr_line, "and", "open ", "keyword.operator.logical"),
        (expr_line, "is", "valid ", "keyword.operator.word"),
        ("require active: shelf.open is known", "require", "", "keyword."),
        ("kind Shelf world closed", "kind", "", "keyword."),
        ("param rate: Int = 1", "param", "", "keyword."),
    ):
        scopes = _scopes_at(tokenized[line], word, after)
        if not any(s.startswith(prefix) for s in scopes):
            problems.append({"missing_expected_scope": {"line": line, "word": word, "expected": prefix, "scopes": scopes}})

    if problems:
        raise MissingContextualKeywords(json.dumps(problems, indent=2))
