"""Cross-language parity between publication.schema_document (Python) and roleSchema (TypeScript).

Discovers every example pack dynamically, compiles its schema bundle, and verifies that Python
`rezono_publication.publication.schema_document` and the gate's TypeScript `roleSchema` produce
identical `schema_id` and canonical JSON bytes (or agree on refusal) for both complete and
partial role views.
"""

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest

from rezono_canon import canonical_bytes
from rezono_compiler import emit, pack as packs
from rezono_publication import l0, publication

EXAMPLES = Path(__file__).resolve().parent
ROOT = EXAMPLES.parent
PACKS = sorted(
    p.parent
    for p in EXAMPLES.rglob("pack.yaml")
    if "expected" not in p.parts and "fixtures" not in p.parts
)

NODE_SCRIPT = """
import { readFileSync } from 'node:fs';
import { ask, roleSchema } from '__EXPR__';
import { AskError } from '__ASK__';
import { dataSchema, schemaId } from '__ANSWER_SCHEMA__';
import { canonicalJson } from '__CANON__';

const { bundle, snapshots, query } = JSON.parse(readFileSync(0, 'utf8'));
try {
\tconst view = roleSchema(bundle, snapshots);
\tconst doc = dataSchema(view.schema);
\tconst canonical = canonicalJson(doc);
\tconst sid = await schemaId(doc);
\tlet answered;
\tif (query) {
\t\tconst tables = query.rows ?? {};
\t\tanswered = await ask({
\t\t\ttext: query.text,
\t\t\tmanifest: 'm-1',
\t\t\tview,
\t\t\tread: async (relation) => ({ rows: (tables[relation] ?? []).map((key) => ({ key })) }),
\t\t\tbudget: { rows: 1000, steps: 50000 },
\t\t\tlimit: 50,
\t\t});
\t}
\tprocess.stdout.write(JSON.stringify({ ok: true, schema_id: sid, canonical, answered }));
} catch (err) {
\tif (err instanceof AskError) {
\t\tprocess.stdout.write(JSON.stringify({ ok: false, status: err.status, message: err.message }));
\t} else {
\t\tthrow err;
\t}
}
"""


def _bundle_relations(bundle: dict) -> list[str]:
    rels: list[str] = []
    seen: set[str] = set()
    for rel in (
        *(k["id"] for k in bundle.get("kinds", [])),
        *(a["table"] for a in bundle.get("attributes", [])),
        *(a["table"] for a in bundle.get("arrows", [])),
        *(r["id"] for r in bundle.get("relations", [])),
        *(e["id"] for e in bundle.get("enums", [])),
    ):
        if rel not in seen:
            seen.add(rel)
            rels.append(rel)
    return rels


def _run_ts_role_schema(bundle: dict, snapshots: list[dict], *, query: dict | None = None) -> dict:
    script = (
        NODE_SCRIPT
        .replace("__EXPR__", (ROOT / "edge/gate/src/expr.ts").as_uri())
        .replace("__ASK__", (ROOT / "edge/gate/src/ask.ts").as_uri())
        .replace("__ANSWER_SCHEMA__", (ROOT / "rezono/src/answer-schema.ts").as_uri())
        .replace("__CANON__", (ROOT / "viewer/src/lib/canon.ts").as_uri())
    )
    with tempfile.TemporaryDirectory() as tmp:
        driver = Path(tmp) / "driver.mjs"
        driver.write_text(script, encoding="utf-8")
        payload = {"bundle": bundle, "snapshots": snapshots}
        if query is not None:
            payload["query"] = query
        run = subprocess.run(
            [os.environ.get("REZONO_NODE", "node"), str(driver)],
            cwd=ROOT,
            input=json.dumps(payload),
            capture_output=True,
            encoding="utf-8",
            timeout=30,
        )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _publishable_subset(bundle: dict) -> dict:
    """Drop only attributes with colliding inline patterns on plain `string` (which L0 forms
    refuse with FormError), keeping every other kind, boolean slot, boolean derived column,
    control kind, open relation, integer bound, named pattern, and derived relation intact."""
    sub = copy.deepcopy(bundle)
    seen_patterns: dict[str, str] = {}
    kept_attrs = []
    for attr in sorted(sub.get("attributes", []), key=lambda a: a["id"]):
        if attr["type"] == "text" and attr.get("patterns"):
            if len(attr["patterns"]) != 1:
                continue
            name = publication.pascal(attr["schema_type"])
            pat = attr["patterns"][0]
            if name in seen_patterns and seen_patterns[name] != pat:
                continue
            seen_patterns[name] = pat
        kept_attrs.append(attr)
    sub["attributes"] = kept_attrs
    return sub


def _assert_parity(bundle: dict, *, full: set[str] | None, label: str) -> bool:
    """Assert Python schema_document and TS roleSchema agree on schema_id and canonical bytes.
    When Python refuses solely because of colliding inline patterns on plain `string`, verify TS
    still builds a valid role schema for gate queries and return False so the caller also checks
    exact parity on the publishable subset."""
    rels = _bundle_relations(bundle)
    if full is None:
        snapshots = [{"relation": rel, "complete": True, "full": True} for rel in rels]
    else:
        snapshots = [{"relation": rel, "complete": False, "full": rel in full} for rel in rels]

    ts = _run_ts_role_schema(bundle, snapshots)
    try:
        py_doc, _ = publication.schema_document(bundle, full)
    except publication.FormError as err:
        if "a second type named String" in str(err):
            assert ts["ok"], f"{label}: TS should serve packs with colliding plain-string inline patterns: {ts}"
            return "string_pattern_collision"
        assert not ts["ok"], f"{label}: Python refused ({err}) but TS succeeded with {ts['schema_id']}"
        assert ts["status"] == 501, f"{label}: expected TS AskError(501), got {ts}"
        return "agreed_refusal"

    assert ts["ok"], f"{label}: Python succeeded but TS refused: {ts}"
    py_sid = l0.check_schema(py_doc)
    assert ts["schema_id"] == py_sid, f"{label}: schema_id mismatch: ts={ts['schema_id']} py={py_sid}"
    py_bytes = canonical_bytes(py_doc)
    ts_bytes = ts["canonical"].encode("utf-8")
    assert ts_bytes == py_bytes, f"{label}: canonical JSON bytes differ"
    return "ok"


def test_example_packs_are_discovered():
    assert PACKS, "expected example packs under examples/"


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda p: p.relative_to(EXAMPLES).as_posix())
def test_role_schema_matches_publication_schema_document(pack_dir):
    bundle = json.loads(emit.compile_pack(packs.read(pack_dir))["bundle/schema-bundle.json"])
    pack_label = pack_dir.relative_to(EXAMPLES).as_posix()

    complete_status = _assert_parity(bundle, full=None, label=f"{pack_label} (complete)")
    partial_status = _assert_parity(bundle, full=set(), label=f"{pack_label} (partial)")
    assert complete_status == partial_status

    if complete_status == "string_pattern_collision":
        subset = _publishable_subset(bundle)
        assert _assert_parity(subset, full=None, label=f"{pack_label} subset (complete)") == "ok"
        assert _assert_parity(subset, full=set(), label=f"{pack_label} subset (partial)") == "ok"

    # For a pack with a partial tenant role reading `request` (like Published role tools),
    # verify an ordinary language `/ask` over the full manifest's partial snapshots succeeds.
    if any(k["id"] == "request" for k in bundle.get("kinds", [])) and any(
        a["table"] == "request__cores" for a in bundle.get("attributes", [])
    ):
        rels = _bundle_relations(bundle)
        partial_snaps = [{"relation": rel, "complete": False, "full": False} for rel in rels]
        res = _run_ts_role_schema(
            bundle,
            partial_snaps,
            query={
                "text": "ask Request where request.cores > 0 show request.cores",
                "rows": {
                    "request": [["r-1"], ["r-2"]],
                    "request__cores": [["r-1", "2"], ["r-2", "3"]],
                },
            },
        )
        assert res["ok"], f"{pack_label} partial tenant ask failed: {res}"
        assert "answer" in res["answered"], f"{pack_label} partial tenant ask refused: {res['answered']}"
        keys = [json.loads(n["key"]) for n in res["answered"]["answer"]["nodes"]]
        assert keys == [["r-1"], ["r-2"]]


def test_role_schema_parity_covers_all_schema_features():
    """Synthetic bundle exercising all six schema-translation rules together."""
    bundle = {
        "pack": {"id": "parity-check", "base": "https://example.org/parity-check/"},
        "kinds": [
            {"id": "policy", "class": "Policy", "world": "closed", "id_type": "text",
             "plane": "control", "owner": "stewards"},
            {"id": "child_policy", "class": "ChildPolicy", "parent": "policy", "id_type": "text"},
            {"id": "entry", "class": "Entry", "world": "closed", "id_type": "text"},
        ],
        "attributes": [
            {"id": "policy.decision", "kind": "policy", "name": "decision", "table": "policy__decision",
             "type": "text", "schema_type": "string", "required": True, "multivalued": False, "world": "closed"},
            {"id": "entry.score", "kind": "entry", "name": "score", "table": "entry__score",
             "type": "integer", "schema_type": "integer", "minimum": "1", "maximum": "100",
             "required": False, "multivalued": False, "world": "closed"},
            {"id": "entry.total", "kind": "entry", "name": "total", "table": "entry__total",
             "type": "integer", "schema_type": "cents", "minimum": "0",
             "required": True, "multivalued": False, "world": "closed"},
            {"id": "entry.active", "kind": "entry", "name": "active", "table": "entry__active",
             "type": "boolean", "schema_type": "boolean", "required": False, "multivalued": False, "world": "closed"},
            {"id": "entry.code", "kind": "entry", "name": "code", "table": "entry__code",
             "type": "text", "schema_type": "entry_code", "patterns": ["^[a-z]{3}$"],
             "required": False, "multivalued": False, "world": "open"},
            {"id": "entry.status", "kind": "entry", "name": "status", "table": "entry__status",
             "type": "enum", "schema_type": "entry_status", "enum": "entry_status",
             "required": False, "multivalued": False, "world": "open"},
        ],
        "arrows": [
            {"id": "entry.policy", "kind": "entry", "name": "policy", "table": "entry__policy",
             "target": "policy", "required": False, "multivalued": False, "world": "open"},
        ],
        "relations": [
            {"id": "ranked_entry", "world": "closed", "columns": [
                {"name": "entry", "type": "string",
                 "semantic": {"case": "ref", "base": "string", "target": "entry"}},
                {"name": "rank", "type": "integer",
                 "semantic": {"case": "scalar", "base": "integer"}},
                {"name": "tag", "type": "string"},
                {"name": "complete", "type": "boolean"},
            ]},
        ],
        "enums": [
            {"id": "entry_status", "values": ["entry_status.open", "entry_status.closed"]},
            {"id": "unused_enum", "values": ["unused_enum.alpha"]},
        ],
    }

    assert _assert_parity(bundle, full=None, label="synthetic (complete)")
    # Partial without policy__decision: control marker must be dropped on Policy and ChildPolicy.
    assert _assert_parity(bundle, full={"policy", "child_policy", "entry"}, label="synthetic (partial decision)")
    assert _assert_parity(bundle, full=set(), label="synthetic (all partial)")
