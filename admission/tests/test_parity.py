"""Parity with the oracle (ruling 2 of 11-11-2026): admission against a pack's schema bundle gives what the
compiler's loader (rezono_compiler.facts) gives from the pack itself. The same rows, byte for byte, for every fact
file of every example pack and compiler fixture; the same refusal, for every refused fixture of the loader's own
tests and for a broken copy of the first record of every section (no identifier, a wrong identifier, an unknown
slot, each slot with a value of the wrong type).

The compiler is only the oracle here, and the bundle comes from it as the publisher archives it. Admission gives
every refusal; the loader stops at the first, so its refusal is compared with admission's first.
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

import pytest
import yaml

pytest.importorskip("rezono_compiler")

from rezono_compiler import emit, facts, pack  # noqa: E402

from rezono_admission import CODES, Schema, rows  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
PACKS = sorted({p.parent for pattern in ("examples/**/pack.yaml", "packs/*/pack.yaml", "compiler/tests/fixtures/*/pack.yaml")
                for p in ROOT.glob(pattern) if "node_modules" not in p.parts})
SEALED = re.compile(r"__row_sha256$")  # generated tables: not in the bundle yet (see rows.rows)

# The loader's messages, and the code admission gives for each.
MESSAGES = [
    ("null document", "document_null"),
    ("mapping of kind to records", "document_not_mapping"),
    (r"section '.*' is null", "section_null"),
    ("is not a list of records", "section_not_list"),
    ("unknown kind", "unknown_kind"),
    ("is abstract", "kind_abstract"),
    ("has no identifier; give its elements inlined", "kind_without_identifier"),
    ("record without", "record_without_identifier"),
    ("unknown slot", "unknown_slot"),
    ("dictionary form", "dictionary_value_not_record"),
    (r"is not a (VARCHAR|BIGINT|BOOLEAN|DATE)$", "wrong_type"),
]
WRONG = [[]]  # a value no slot takes: a list whose one item is a list


def code_of(message: str) -> str:
    found = [code for pattern, code in MESSAGES if re.search(pattern, message)]
    assert len(found) == 1, f"the loader's message has no code: {message}"
    return found[0]


@cache
def compiled(directory: Path):
    model = pack.read(directory)
    bundle = emit.compile_pack(model)["bundle/schema-bundle.json"]
    return model, Schema(json.loads(bundle))


def oracle(model, data):
    """The loader's rows without the sealed kinds' generated tables, or the code of its refusal."""
    try:
        got = facts.rows_of(model, data)
    except facts.LoadError as err:
        return None, code_of(str(err))
    return {t: r for t, r in got.items() if not SEALED.search(t)}, None


def judge(schema, data):
    got, refusals = rows(schema, data)
    assert all(r.code in CODES and re.fullmatch(r"[a-z][a-z0-9_]*", r.code) for r in refusals)
    assert all(r.schema == schema.sha256 for r in refusals), "a refusal names the schema it was judged against"
    return (None, refusals[0].code) if refusals else (got, None)


def documents():
    for directory in PACKS:
        for path in facts.files(directory):
            yield pytest.param(directory, path, id=path.relative_to(ROOT).as_posix())


@pytest.mark.parametrize("directory, path", list(documents()))
def test_every_fact_file_gives_the_rows_the_loader_gives(directory, path):
    model, schema = compiled(directory)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    want, refused = oracle(model, data)
    assert refused is None, f"the loader refuses a fact file of an example: {refused}"
    got, code = judge(schema, data)
    assert code is None and got == want


REFUSED_DOCUMENTS = {  # compiler/tests/test_fact_documents.py
    "empty-file": "", "null-document": "~\n", "list-document": "- {id: a, title: t}\n", "null-section": "alpha:\n",
    "explicit-null-section": "alpha: null\n", "mapping-section": "alpha: {id: a, title: t}\n",
    "unknown-kind": "nothing_here: []\n",
}


@pytest.mark.parametrize("text", REFUSED_DOCUMENTS.values(), ids=REFUSED_DOCUMENTS.keys())
def test_a_refused_document_is_refused_with_the_loader_s_reason(text):
    model, schema = compiled(ROOT / "compiler" / "tests" / "fixtures" / "minimal")
    data = yaml.safe_load(text)
    want = oracle(model, data)
    assert want[1] is not None
    assert judge(schema, data) == want


def broken(model, kind: str, record: dict):
    """Copies of one record, each with one thing wrong."""
    ident = model.kinds[model.root(kind)].identifier
    yield "without its identifier", {k: v for k, v in record.items() if k != ident}
    yield "a wrong identifier", record | {ident: WRONG}
    yield "an unknown slot", record | {"zz_not_a_slot": 1}
    for name in sorted(set(record) - {ident}):
        yield f"{name} of a wrong type", record | {name: WRONG}


def sections():
    for directory in PACKS:
        for path in facts.files(directory):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for kind, records in data.items():
                if records and isinstance(records[0], dict):
                    yield pytest.param(directory, kind, records[0], id=f"{path.relative_to(ROOT).as_posix()}:{kind}")


@pytest.mark.parametrize("directory, kind, record", list(sections()))
def test_a_broken_record_is_refused_with_the_loader_s_reason(directory, kind, record):
    model, schema = compiled(directory)
    for what, bad in broken(model, kind, record):
        want = oracle(model, {kind: [bad]})
        assert judge(schema, {kind: [bad]}) == want, what
