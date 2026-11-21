"""The epoch statement of one role (docs/ring2/signing.md, "What is signed").

  python -m rezono_publication.statement verify DIR [--policy profile.yaml | --key seal.pub]

One small document per published epoch and filtered role, the one thing a signature covers: an
in-toto Statement (v1) whose subjects are the objects of the role's publication form by their sha256, and whose
predicate binds what the role reads and nothing more:

- the role's manifest as its form carries it (`rezono_publication.publication.role_manifest`: id, epoch, knowledge time,
  definition hash and compiled files), by its canonical hash, with the names a reader looks for spelled out;
- the role's own snapshots, by relation and sha256 (the files the form was made from);
- the schema id, the dataset hash `d-…` and the annotation hash of §6.2, unchanged;
- the row tree (Y2.8): per table, side tables too, the RFC 9162 Merkle root over the table's hash rows in hash
  order (a leaf is `SHA-256(0x00 ‖ CJ(row))`, a node `SHA-256(0x01 ‖ left ‖ right)`, an empty table `SHA-256()`),
  and the inclusion hash `H({"dataset", "roots"})` over them. The dataset hash does not change.

Every value is text, so the canonical bytes of Rezono's canon (which writes an integer as text) are RFC 8785's
bytes too, and a verifier of another implementation reads the same document. Nothing in it is computed from a row
the role may not read, and `pack_sha256` (which hashes hidden facts) is never in it: two worlds that differ only
in such rows give the role the same statement. The statement of the complete role is never made.

The predicate type carries its version (`/v1`); its names are exactly `PREDICATE_KEYS`, with no empty place for
what a later version adds (`previous` with the deltas, `compiler` and `source` with the sealed artifact; `checks`
stays out of a filtered role's statement, O7). The knowledge time is the manifest's, as its form carries it: an
RFC 3339 time with `Z` or an offset (`git log --format=%cI` writes an offset).

`verify` is the reader's check, from the published bytes alone (the index, the statement and the objects): the
statement is canonical and has exactly the contract's names at every level (contracts/statement.yaml is closed,
and so is the reader), names exactly the index's objects with their sha256, agrees with the index on every name,
and its dataset pin, roots and inclusion hash are recomputed from the subjects' own bytes (the schema and rows
read back with the L0 reader). A difference is named; an empty list is a statement that says what its files say.

`verify_signature` is the reader's check of the signature: `statement.sigstore.json`, the Sigstore bundle
cosign writes over the statement's bytes, beside it. It is the shared verification (`rezono_publication.seal`: its
trust policy, its cosign, its key and its loop, `seal.Cosign.accepted`), on a file instead of a registry digest:
one verifier of the policy that accepts is enough, and it reads only the statement, the signature and the public
key. Without a policy the CLI says "signature not checked", never "verified". The signing itself is an effect
(edge/plugins/sign-statement).

Beside a sealed role form, the statement and that same signature are one referrer of the seal's digest
(`ARTIFACT`, the two files as its layers): `attach` pushes it once the sealed index names the statement's sha256,
signing nothing; `verify_sealed` is the reader of the seal and its statement together, see there.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

from rezono_canon import CanonError, canonical_bytes

from . import l0
try:
    from . import seal
except ImportError:
    seal = None  # type: ignore[assignment]
from .hash import H, CJ, HashError, hash_rows, hashes

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://rezono.org/epoch-statement/v1"
FORMAT = "rezono.epoch-statement/1"
PREDICATE_TYPE_V2 = "https://rezono.org/epoch-statement/v2"
FORMAT_V2 = "rezono.epoch-statement/2"
PREDICATE_TYPE_V3 = "https://rezono.org/epoch-statement/v3"
FORMAT_V3 = "rezono.epoch-statement/3"
LEGACY_STATEMENT_TYPES = (("https://rede.dev/epoch-statement/v1", "rede.epoch-statement/1"),)
ACCEPTED_STATEMENT_TYPES = (
    (PREDICATE_TYPE, FORMAT),
    (PREDICATE_TYPE_V2, FORMAT_V2),
    (PREDICATE_TYPE_V3, FORMAT_V3),
    *LEGACY_STATEMENT_TYPES,
)
NAME = "statement.json"  # its name under the role's prefix, beside the form's objects
DIFF_NAME = "diff.json"  # the role-scoped epoch diff beside statement.json on chained epochs
DIFF_FORMAT = "rezono.role-diff/1"
ALLOWED = "allowed.json"  # the role's proof of publish_allowed beside statement.json in v3
ALLOWED_FORMAT = "rezono.epoch-allowed/1"
ALLOWED_RELATION = "publish_allowed"
ALLOWED_DOC_KEYS = ("format", "relation", "row", "proof", "rows", "definition", "rules", "engine")
ENGINE_PIN_KEYS = ("version", "wheel_sha256", "commit")
SIGNATURE = "statement.sigstore.json"  # cosign's Sigstore bundle over the statement's bytes, beside it
ARTIFACT = "application/vnd.rezono.epoch-statement.v1"  # the two as a referrer of the role's seal
LEGACY_ARTIFACTS = ("application/vnd.rede.epoch-statement.v1",)
LAYERS = ((NAME, "application/vnd.in-toto+json"), (SIGNATURE, "application/vnd.dev.sigstore.bundle.v0.3+json"))
MANIFEST_NAMES = ("id", "epoch", "knowledge_time", "definition_sha256")
# The names of the contract (contracts/statement.yaml), at each level; the reader refuses any other.
STATEMENT_KEYS = ("_type", "subject", "predicateType", "predicate")
SUBJECT_KEYS = ("name", "digest")
DIGEST_KEYS = ("sha256",)
PREDICATE_KEYS = ("format", "pack", "role", "manifest", "epoch", "knowledge_time", "definition", "role_manifest",
                  "snapshots", "schema", "dataset", "annotation", "roots", "inclusion")
CHAIN_KEYS = ("previous", "diff")
ALLOWED_KEYS = ("allowed",)
SNAPSHOT_KEYS = ("relation", "sha256")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

__all__ = ["NAME", "DIFF_NAME", "DIFF_FORMAT", "ALLOWED", "ALLOWED_FORMAT", "SIGNATURE", "PREDICATE_TYPE_V2",
           "FORMAT_V2", "PREDICATE_TYPE_V3", "FORMAT_V3", "PREDICATE_KEYS", "CHAIN_KEYS", "ALLOWED_KEYS",
           "tree_root", "roots", "inclusion_hash", "compute_role_diff", "apply_role_diff", "make", "dumps",
           "verify", "verify_signature", "trust_of", "referrer", "attach", "verify_sealed"]


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _mth(leaves: list[bytes], lo: int, hi: int) -> bytes:
    """RFC 9162 §2.1.1, MTH(D[lo:hi]) over the leaf hashes: split at the largest power of two below n."""
    n = hi - lo
    if n == 1:
        return leaves[lo]
    k = 1 << ((n - 1).bit_length() - 1)
    return _sha256(b"\x01" + _mth(leaves, lo, lo + k) + _mth(leaves, lo + k, hi))


def tree_root(entries: list[bytes]) -> str:
    """The Merkle tree hash of RFC 9162 over the entries, in their order, as hex. The empty tree is SHA-256()."""
    if not entries:
        return hashlib.sha256(b"").hexdigest()
    return _mth([_sha256(b"\x00" + e) for e in entries], 0, len(entries)).hex()


def roots(schema: dict, rows: list) -> dict[str, str]:
    """Per table of §6.2, the kind and relation tables and `$why` and `$src`, the root of its row tree: the leaves
    are the canonical JSON of its hash rows in hash order (step 3), the same rows its table hash is over."""
    return {t: tree_root([CJ(r).encode("utf-8") for r in rs]) for t, rs in hash_rows(schema, rows).items()}


def inclusion_hash(dataset: str, table_roots: dict[str, str]) -> str:
    """`H({"dataset", "roots"})`: listed beside the annotation hash (signing.md, the row tree)."""
    return H({"dataset": dataset, "roots": table_roots})


def _text(value) -> str:
    """A name of the manifest as text: the epoch is a number in the manifest and text in the statement."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f"not a name: {value!r}")
    return str(value)


def _snapshot_keys(raw: bytes) -> set[tuple[str, ...]]:
    """Parse one role snapshot JSON array (`[{"key": [str, ...]}, ...]`) into its set of row key tuples."""
    doc = json.loads(raw)
    if not isinstance(doc, list):
        raise ValueError("snapshot is not a JSON list")
    out: set[tuple[str, ...]] = set()
    for row in doc:
        if (not isinstance(row, dict) or set(row) != {"key"}
                or not isinstance(row["key"], list)
                or not all(isinstance(part, str) for part in row["key"])):
            raise ValueError("snapshot row does not have a text key list")
        out.add(tuple(row["key"]))
    return out


def _relation_diff(before: set[tuple[str, ...]], after: set[tuple[str, ...]]) -> list[dict]:
    """Deterministic row diff of one relation, matching `rezono_publisher.difference.entries`."""
    removed, added = before - after, after - before
    width_b = Counter(k[:-1] for k in before if len(k) > 1)
    width_a = Counter(k[:-1] for k in after if len(k) > 1)
    was = {k[:-1]: k for k in removed if len(k) > 1 and width_b[k[:-1]] == 1 and width_a[k[:-1]] == 1}
    out = []
    for k in added:
        if len(k) > 1 and k[:-1] in was:
            out.append({"key": list(k), "change": "changed", "was": list(was[k[:-1]])})
        else:
            out.append({"key": list(k), "change": "added"})
    paired = {tuple(e["was"]) for e in out if e["change"] == "changed"}
    out += [{"key": list(k), "change": "removed"} for k in removed if k not in paired]
    return sorted(out, key=lambda e: [p.encode("utf-8") for p in e["key"]])


def compute_role_diff(before: dict[str, bytes], after: dict[str, bytes]) -> dict:
    """Compute canonical `rezono.role-diff/1` directly from one role's previous and current snapshot bytes."""
    relations: dict[str, list[dict]] = {}
    for rel in sorted(set(before) | set(after)):
        b_rows = _snapshot_keys(before[rel]) if rel in before else set()
        a_rows = _snapshot_keys(after[rel]) if rel in after else set()
        entries = _relation_diff(b_rows, a_rows)
        if entries:
            relations[rel] = entries
    return {"format": DIFF_FORMAT, "relations": relations}


def _check_diff_doc(diff_bytes: bytes) -> tuple[dict | None, list[str]]:
    """Validate `diff.json` bytes against canonical `rezono.role-diff/1` shape."""
    problems: list[str] = []
    try:
        doc = json.loads(diff_bytes)
        if canonical_bytes(doc) != diff_bytes:
            problems.append(f"{DIFF_NAME} is not in canonical form")
    except (ValueError, CanonError) as err:
        return None, [f"{DIFF_NAME} is not canonical JSON: {err}"]
    if not isinstance(doc, dict) or set(doc) != {"format", "relations"}:
        return None, [f"{DIFF_NAME} does not have exact keys format and relations"]
    if doc["format"] != DIFF_FORMAT:
        problems.append(f"{DIFF_NAME} format is not {DIFF_FORMAT}")
    rels = doc["relations"]
    if not isinstance(rels, dict):
        return None, problems + [f"{DIFF_NAME} relations is not an object"]
    for rel, entries in rels.items():
        if not isinstance(rel, str) or not isinstance(entries, list) or not entries:
            problems.append(f"{DIFF_NAME} relation {rel!r} must map to a non-empty list")
            continue
        prev_key: list[bytes] | None = None
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict):
                problems.append(f"{DIFF_NAME} {rel}[{i}] is not an object")
                continue
            ch = entry.get("change")
            if ch in ("added", "removed"):
                want_keys = {"change", "key"}
            elif ch == "changed":
                want_keys = {"change", "key", "was"}
            else:
                problems.append(f"{DIFF_NAME} {rel}[{i}] has unknown change {ch!r}")
                continue
            if set(entry) != want_keys:
                problems.append(f"{DIFF_NAME} {rel}[{i}] keys are not {sorted(want_keys)}")
                continue
            key = entry["key"]
            if not isinstance(key, list) or not key or not all(isinstance(p, str) for p in key):
                problems.append(f"{DIFF_NAME} {rel}[{i}] key must be a non-empty list of text")
                continue
            if ch == "changed":
                was = entry["was"]
                if (not isinstance(was, list) or len(was) != len(key) or len(key) < 2
                        or not all(isinstance(p, str) for p in was) or was[:-1] != key[:-1] or was == key):
                    problems.append(f"{DIFF_NAME} {rel}[{i}] was is not a changed cell with the same prefix")
                    continue
            enc = [p.encode("utf-8") for p in key]
            if prev_key is not None and enc <= prev_key:
                problems.append(f"{DIFF_NAME} {rel} entries are not strictly sorted by key")
                break
            prev_key = enc
    return doc, problems


def apply_role_diff(before: dict[str, bytes], diff_doc: dict) -> dict[str, set[tuple[str, ...]]]:
    """Apply a verified `rezono.role-diff/1` document to a role's previous snapshots."""
    rels = diff_doc["relations"]
    out: dict[str, set[tuple[str, ...]]] = {}
    for rel in sorted(set(before) | set(rels)):
        base = _snapshot_keys(before[rel]) if rel in before else set()
        current = set(base)
        for entry in rels.get(rel, ()):
            ch = entry["change"]
            key = tuple(entry["key"])
            if ch == "added":
                if key in current:
                    raise ValueError(f"{rel}: added key {key!r} already present")
                current.add(key)
            elif ch == "removed":
                if key not in current:
                    raise ValueError(f"{rel}: removed key {key!r} not present")
                current.remove(key)
            elif ch == "changed":
                was = tuple(entry["was"])
                if was not in current:
                    raise ValueError(f"{rel}: changed previous key {was!r} not present")
                if key in current:
                    raise ValueError(f"{rel}: changed new key {key!r} already present")
                current.remove(was)
                current.add(key)
            else:
                raise ValueError(f"{rel}: unknown change {ch!r}")
        out[rel] = current
    return out


def _check_allowed_doc(allowed_bytes: bytes, *, role: str, epoch: str) -> list[str]:
    """Validate `allowed.json` bytes against canonical `rezono.epoch-allowed/1` shape and statement role/epoch."""
    problems: list[str] = []
    try:
        doc = json.loads(allowed_bytes)
        if canonical_bytes(doc) != allowed_bytes:
            problems.append(f"{ALLOWED} is not in canonical form")
    except (ValueError, CanonError) as err:
        return [f"{ALLOWED} is not canonical JSON: {err}"]
    if not isinstance(doc, dict) or set(doc) != set(ALLOWED_DOC_KEYS):
        return problems + [f"{ALLOWED} does not have exact keys {list(ALLOWED_DOC_KEYS)}"]
    if doc["format"] != ALLOWED_FORMAT:
        problems.append(f"{ALLOWED} format is not {ALLOWED_FORMAT}")
    if doc["relation"] != ALLOWED_RELATION:
        problems.append(f"{ALLOWED} relation is not {ALLOWED_RELATION}")

    row = doc["row"]
    row_ok = isinstance(row, list) and len(row) == 4 and all(isinstance(part, str) for part in row)
    if not row_ok:
        problems.append(f"{ALLOWED} row must be a 4-element list of text")
    else:
        if row[1] != epoch:
            problems.append(f"{ALLOWED} row epoch {row[1]!r} does not match statement epoch {epoch!r}")
        if row[2] != role:
            problems.append(f"{ALLOWED} row role {row[2]!r} does not match statement role {role!r}")

    proof = doc["proof"]
    if not isinstance(proof, dict):
        problems.append(f"{ALLOWED} proof is not an object")
    else:
        root = proof.get("root")
        if not isinstance(root, dict) or root.get("relation") != ALLOWED_RELATION or not isinstance(root.get("key"), str):
            problems.append(f"{ALLOWED} proof root must name relation {ALLOWED_RELATION} and a text key")
        elif row_ok:
            try:
                key_parts = json.loads(root["key"])
            except ValueError:
                problems.append(f"{ALLOWED} proof root key is not JSON")
            else:
                if key_parts != row:
                    problems.append(f"{ALLOWED} proof root key does not match row")
        if not isinstance(proof.get("manifest_id"), str) or not proof["manifest_id"]:
            problems.append(f"{ALLOWED} proof manifest_id must be non-empty text")
        if "witnesses" in proof and not isinstance(proof["witnesses"], list):
            problems.append(f"{ALLOWED} proof witnesses must be a list")

    if not isinstance(doc["rows"], dict):
        problems.append(f"{ALLOWED} rows is not an object")
    for field in ("definition", "rules"):
        val = doc[field]
        if not isinstance(val, str) or not _SHA256_RE.match(val):
            problems.append(f"{ALLOWED} {field} is not a sha256")
    engine = doc["engine"]
    if not isinstance(engine, dict) or set(engine) != set(ENGINE_PIN_KEYS):
        problems.append(f"{ALLOWED} engine must have exact keys {list(ENGINE_PIN_KEYS)}")
    else:
        if not isinstance(engine["version"], str) or not engine["version"]:
            problems.append(f"{ALLOWED} engine version must be non-empty text")
        if not isinstance(engine["wheel_sha256"], str) or not _SHA256_RE.match(engine["wheel_sha256"]):
            problems.append(f"{ALLOWED} engine wheel_sha256 is not a sha256")
        if not isinstance(engine["commit"], str) or not _COMMIT_RE.match(engine["commit"]):
            problems.append(f"{ALLOWED} engine commit is not a 40-hex commit id")
    return problems


def make(index: dict, objects: dict[str, bytes], schema: dict, rows: list, *,
         version: int = 1, previous: str | None = None, diff: str | None = None) -> dict:
    """The statement of the role whose form index and objects these are. `objects` are every object the index
    names except the statement; `schema` and `rows` are the form's own, as `rezono_publication.publication.form` made
    them (or as the L0 reader reads them back from those objects). Version 1 is preserved untouched for existing
    callers and fixtures; version 2 adds optional paired `previous` and `diff` for chained epochs; a form holding
    `allowed.json` gets version 3, which keeps version 2's chain fields and adds `allowed`."""
    if version not in (1, 2, 3):
        raise ValueError(f"unsupported epoch statement version: {version!r}")
    has_allowed = ALLOWED in objects
    effective_version = 3 if has_allowed else version
    if effective_version == 1:
        if previous is not None or diff is not None:
            raise ValueError("epoch statement v1 does not carry previous or diff")
        pred_type, fmt = PREDICATE_TYPE, FORMAT
    else:
        if effective_version == 3 and not has_allowed:
            raise ValueError(f"epoch statement v3 requires {ALLOWED} in objects")
        if (previous is None) != (diff is None):
            raise ValueError(f"epoch statement v{effective_version} requires both previous and diff, or neither")
        if previous is not None:
            if not isinstance(previous, str) or not _SHA256_RE.match(previous):
                raise ValueError(f"previous is not a sha256: {previous!r}")
            if not isinstance(diff, str) or not _SHA256_RE.match(diff):
                raise ValueError(f"diff is not a sha256: {diff!r}")
            if DIFF_NAME not in objects:
                raise ValueError(f"chained epoch statement v{effective_version} requires {DIFF_NAME} in objects")
            if hashlib.sha256(objects[DIFF_NAME]).hexdigest() != diff:
                raise ValueError(f"diff sha256 does not match {DIFF_NAME} bytes")
        elif DIFF_NAME in objects:
            raise ValueError(f"initial epoch statement v{effective_version} must not include {DIFF_NAME}")
        pred_type, fmt = (PREDICATE_TYPE_V3, FORMAT_V3) if effective_version == 3 else (PREDICATE_TYPE_V2, FORMAT_V2)
    m = index["manifest"]
    epoch_text = _text(m["epoch"])
    role_text = index["role"]
    allowed_hash = None
    if effective_version == 3:
        allowed_problems = _check_allowed_doc(objects[ALLOWED], role=role_text, epoch=epoch_text)
        if allowed_problems:
            raise ValueError("; ".join(allowed_problems))
        allowed_hash = hashlib.sha256(objects[ALLOWED]).hexdigest()
    h = hashes(schema, rows)
    if h["schema"] != index["schema"] or h["dataset"] != index["dataset"]:
        raise ValueError("the index does not name the dataset of these rows")
    table_roots = roots(schema, rows)
    predicate = {
        "format": fmt,
        "pack": index["pack"],
        "role": role_text,
        "manifest": _text(m["id"]),
        "epoch": epoch_text,
        "knowledge_time": _text(m["knowledge_time"]),
        "definition": _text(m["definition_sha256"]),
        "role_manifest": H(m),
        "snapshots": [{"relation": s["relation"], "sha256": s["sha256"]} for s in index["sources"]],
        "schema": h["schema"],
        "dataset": h["dataset"],
        "annotation": h["annotation"],
        "roots": table_roots,
        "inclusion": inclusion_hash(h["dataset"], table_roots),
    }
    if previous is not None and diff is not None:
        predicate["previous"] = previous
        predicate["diff"] = diff
    if allowed_hash is not None:
        predicate["allowed"] = allowed_hash
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": n, "digest": {"sha256": hashlib.sha256(objects[n]).hexdigest()}} for n in sorted(objects)],
        "predicateType": pred_type,
        "predicate": predicate,
    }


def dumps(statement: dict) -> bytes:
    """The statement's bytes: canonical JSON (RFC 8785; every value is text, so Rezono's canon is RFC 8785 here)."""
    return canonical_bytes(statement)


_NESTED = ("subject", "predicate", "digest", "snapshots", "roots")


def _keys(where: str, value, names: tuple[str, ...]) -> list[str]:
    """`value` is an object with exactly `names` (the contract's names at that level), each but those listed in
    `_NESTED` text."""
    if not isinstance(value, dict):
        return [f"{where} is not an object"]
    problems = []
    if set(value) - set(names):
        problems.append(f"{where} has names the contract does not: {sorted(set(value) - set(names))}")
    if set(names) - set(value):
        problems.append(f"{where} lacks {sorted(set(names) - set(value))}")
    problems += [f"{where} {k} is not text" for k in sorted(set(names) & set(value))
                 if k not in _NESTED and not isinstance(value[k], str)]
    return problems


def _shape(st) -> list[str]:
    """The contract's shape (contracts/statement.yaml, closed at every level): what it refuses, the reader refuses."""
    problems = _keys("the statement", st, STATEMENT_KEYS)
    if problems:
        return problems
    subjects = st["subject"]
    if not isinstance(subjects, list):
        problems.append("the subjects are not a list")
    else:
        for i, s in enumerate(subjects):
            problems += _keys(f"subject {i}", s, SUBJECT_KEYS)
            if isinstance(s, dict) and "digest" in s:
                problems += _keys(f"subject {i}'s digest", s["digest"], DIGEST_KEYS)
        names = [s.get("name") for s in subjects if isinstance(s, dict)]
        if not problems and names != sorted(set(names)):
            problems.append("the subjects are not sorted by name, one each")
    p = st["predicate"]
    ptype = st.get("predicateType")
    if ptype in (PREDICATE_TYPE_V2, PREDICATE_TYPE_V3) and isinstance(p, dict):
        has_prev = "previous" in p
        has_diff = "diff" in p
        if has_prev and has_diff:
            expected_keys = PREDICATE_KEYS + CHAIN_KEYS
        elif not has_prev and not has_diff:
            expected_keys = PREDICATE_KEYS
        else:
            expected_keys = PREDICATE_KEYS + CHAIN_KEYS
            problems.append("the predicate must carry both previous and diff, or neither")
        if ptype == PREDICATE_TYPE_V3:
            expected_keys = expected_keys + ALLOWED_KEYS
        problems += _keys("the predicate", p, expected_keys)
        sha_keys = CHAIN_KEYS + ALLOWED_KEYS if ptype == PREDICATE_TYPE_V3 else CHAIN_KEYS
        for k in sha_keys:
            if k in p and (not isinstance(p[k], str) or not _SHA256_RE.match(p[k])):
                problems.append(f"the predicate {k} is not a sha256")
    else:
        problems += _keys("the predicate", p, PREDICATE_KEYS)
    if isinstance(p, dict) and isinstance(p.get("snapshots"), list):
        for i, s in enumerate(p["snapshots"]):
            problems += _keys(f"snapshot {i}", s, SNAPSHOT_KEYS)
    elif isinstance(p, dict) and "snapshots" in p:
        problems.append("the predicate's snapshots are not a list")
    if isinstance(p, dict) and "roots" in p:
        r = p["roots"]
        if not isinstance(r, dict) or not all(isinstance(v, str) for v in r.values()):
            problems.append("the predicate's roots are not a map of table to text")
    return problems


def _verify_chain(
    p: dict,
    subjects: dict[str, str],
    held: dict[str, bytes],
    *,
    previous_statement: bytes | None,
    previous_snapshots: dict[str, bytes] | None,
    current_snapshots: dict[str, bytes] | None,
) -> list[str]:
    """Verify v2 epoch-chain invariants: subject agreement, diff.json shape, predecessor link, and diff replay."""
    problems: list[str] = []
    chained = "previous" in p and "diff" in p
    if not chained:
        if DIFF_NAME in subjects:
            problems.append(f"{DIFF_NAME} is a subject without predicate previous and diff")
        if any(x is not None for x in (previous_statement, previous_snapshots, current_snapshots)):
            problems.append("predecessor chain inputs were given for an unchained statement")
        return problems

    if DIFF_NAME not in subjects:
        problems.append(f"{DIFF_NAME} is missing from subjects on a chained statement")
    elif subjects[DIFF_NAME] != p["diff"]:
        problems.append(f"{DIFF_NAME} subject sha256 does not match predicate diff")

    diff_doc = None
    if DIFF_NAME in held:
        diff_doc, diff_problems = _check_diff_doc(held[DIFF_NAME])
        problems.extend(diff_problems)

    prev_p = None
    if previous_statement is not None:
        if hashlib.sha256(previous_statement).hexdigest() != p["previous"]:
            problems.append("previous statement bytes do not match predicate previous")
        try:
            prev_st = json.loads(previous_statement)
            if dumps(prev_st) != previous_statement:
                problems.append("previous statement is not in canonical form")
        except (ValueError, CanonError) as err:
            problems.append(f"previous statement is not canonical JSON: {err}")
            prev_st = None
        if prev_st is not None:
            accepted_types = {t for t, _ in ACCEPTED_STATEMENT_TYPES}
            if (not isinstance(prev_st, dict) or prev_st.get("_type") != STATEMENT_TYPE
                    or prev_st.get("predicateType") not in accepted_types or _shape(prev_st)):
                problems.append("previous statement is not a valid epoch statement")
            else:
                prev_p = prev_st["predicate"]
                if (prev_st["predicateType"], prev_p["format"]) not in ACCEPTED_STATEMENT_TYPES:
                    problems.append("previous statement predicate format does not match its predicateType")
                if prev_p["pack"] != p["pack"]:
                    problems.append("previous statement pack does not match")
                if prev_p["role"] != p["role"]:
                    problems.append("previous statement role does not match")
                try:
                    if not (int(prev_p["epoch"]) < int(p["epoch"])):
                        problems.append("previous statement epoch is not strictly smaller")
                except ValueError:
                    problems.append("epoch is not an integer")

    if previous_snapshots is not None and prev_p is not None:
        want_prev = {s["relation"]: s["sha256"] for s in prev_p["snapshots"]}
        got_prev = {rel: hashlib.sha256(b).hexdigest() for rel, b in previous_snapshots.items()}
        if got_prev != want_prev:
            problems.append("previous snapshots do not match previous statement snapshots")

    if current_snapshots is not None:
        want_curr = {s["relation"]: s["sha256"] for s in p["snapshots"]}
        got_curr = {rel: hashlib.sha256(b).hexdigest() for rel, b in current_snapshots.items()}
        if got_curr != want_curr:
            problems.append("current snapshots do not match predicate snapshots")

    if previous_snapshots is not None and current_snapshots is not None:
        if DIFF_NAME not in held:
            problems.append(f"{DIFF_NAME} is not a subject with its bytes")
        else:
            try:
                recomputed = canonical_bytes(compute_role_diff(previous_snapshots, current_snapshots))
            except (ValueError, CanonError) as err:
                problems.append(f"could not recompute {DIFF_NAME}: {err}")
            else:
                if recomputed != held[DIFF_NAME]:
                    problems.append(f"{DIFF_NAME} does not match recomputed role diff")
            if diff_doc is not None:
                try:
                    applied = apply_role_diff(previous_snapshots, diff_doc)
                    expected = {rel: _snapshot_keys(b) for rel, b in current_snapshots.items()}
                    for rel in sorted(set(applied) | set(expected)):
                        if applied.get(rel, set()) != expected.get(rel, set()):
                            problems.append(f"applying {DIFF_NAME} to previous snapshots does not yield current {rel}")
                except ValueError as err:
                    problems.append(f"applying {DIFF_NAME} failed: {err}")

    return problems


def _verify_allowed(p: dict, subjects: dict[str, str], held: dict[str, bytes]) -> list[str]:
    """Verify v3 `allowed` invariants: subject agreement, canonical `allowed.json` shape, and role/epoch match."""
    problems: list[str] = []
    if ALLOWED not in subjects:
        problems.append(f"{ALLOWED} is missing from subjects on a v3 statement")
    elif subjects[ALLOWED] != p["allowed"]:
        problems.append(f"{ALLOWED} subject sha256 does not match predicate allowed")
    if ALLOWED in held:
        problems.extend(_check_allowed_doc(held[ALLOWED], role=p["role"], epoch=p["epoch"]))
    return problems


def verify(
    statement_bytes: bytes,
    index: dict,
    objects: dict[str, bytes],
    absent=(),
    *,
    previous_statement: bytes | None = None,
    previous_snapshots: dict[str, bytes] | None = None,
    current_snapshots: dict[str, bytes] | None = None,
) -> list[str]:
    """What is wrong with a role's statement, read from the published bytes alone: `index` is the role's form
    index, `objects` every object it names (the statement may be among them and is then left out; an object the
    index does not name, such as the index itself, is never read). An object named in `absent` may be missing
    (a seal's `not_carried`); the statement must then name it with the sha256 the index names. Empty: the
    statement says exactly what its files say."""
    problems: list[str] = []
    try:
        st = json.loads(statement_bytes)
        if dumps(st) != statement_bytes:
            problems.append("the statement is not in canonical form")
    except (ValueError, CanonError) as err:
        return [f"the statement is not canonical JSON: {err}"]
    accepted_types = {t for t, _ in ACCEPTED_STATEMENT_TYPES}
    if not isinstance(st, dict) or st.get("_type") != STATEMENT_TYPE or st.get("predicateType") not in accepted_types:
        return ["not an epoch statement (in-toto Statement v1 with Rezono's predicate type)"]
    shape = _shape(st)
    if shape:
        return problems + shape
    p = st["predicate"]
    if (st["predicateType"], p["format"]) not in ACCEPTED_STATEMENT_TYPES:
        want_fmt = dict(ACCEPTED_STATEMENT_TYPES)[st["predicateType"]]
        return [f"predicate format is not {want_fmt}"]

    listed = {o["name"]: o["sha256"] for o in index.get("objects", [])}
    if NAME in listed and listed[NAME] != hashlib.sha256(statement_bytes).hexdigest():
        problems.append(f"the index names {NAME} with another sha256")
    files = {n: b for n, b in objects.items() if n != NAME and n in listed}  # never the index itself
    subjects = {s["name"]: s["digest"]["sha256"] for s in st["subject"]}
    if set(subjects) != set(listed) - {NAME}:
        problems.append("the subjects are not the objects the index names: "
                        f"{sorted(set(subjects) ^ (set(listed) - {NAME}))}")
    for name in sorted(set(subjects) | set(files)):
        data = files.get(name)
        if data is None:
            if name not in absent:
                problems.append(f"{name}: the statement names it and it is not there")
            elif subjects.get(name) != listed.get(name):
                problems.append(f"{name}: the statement and the index name it with another sha256")
            continue
        got = hashlib.sha256(data).hexdigest()
        if subjects.get(name) != got:
            problems.append(f"{name}: its sha256 is not the one the statement names")
        if listed.get(name) != got:
            problems.append(f"{name}: its sha256 is not the one the index names")

    m = index.get("manifest") or {}
    want = {
        "pack": index.get("pack"), "role": index.get("role"),
        "schema": index.get("schema"), "dataset": index.get("dataset"),
        "snapshots": [{"relation": s["relation"], "sha256": s["sha256"]} for s in index.get("sources", [])],
    }
    try:
        want |= {"manifest": _text(m.get("id")), "epoch": _text(m.get("epoch")),
                 "knowledge_time": _text(m.get("knowledge_time")), "definition": _text(m.get("definition_sha256")),
                 "role_manifest": H(m)}
    except (ValueError, HashError) as err:
        problems.append(f"the index's manifest: {err}")
    for k, v in want.items():
        if p.get(k) != v:
            problems.append(f"predicate {k} is not the index's")

    # What the role's rows say, recomputed from the subjects' own bytes (a subject whose bytes are there and have
    # the sha256 the statement names), read back with the L0 reader: never from the file hashes alone.
    is_legacy = (st["predicateType"], p["format"]) in LEGACY_STATEMENT_TYPES
    held = {n: files[n] for n in subjects if n in files and hashlib.sha256(files[n]).hexdigest() == subjects[n]}
    try:
        schema = json.loads(held["schema.json"])
        sid = l0.check_schema(schema, allow_legacy=is_legacy)
        rows = l0.read_collection(schema, json.loads(held["rows.json"]))
        h = hashes(schema, rows)
        table_roots = roots(schema, rows)
    except KeyError as err:
        return problems + [f"{err.args[0]} is not a subject with its bytes"]
    except (ValueError, l0.L0Error, HashError) as err:
        return problems + [f"the form does not read back: {err}"]
    if sid != p.get("schema"):
        problems.append("schema.json is not the schema the statement names")
    for k in ("dataset", "annotation"):
        if p.get(k) != h[k]:
            problems.append(f"predicate {k} is not the hash of the rows")
    if p["roots"] != table_roots:
        bad = sorted(t for t in set(table_roots) | set(p["roots"]) if p["roots"].get(t) != table_roots.get(t))
        problems.append(f"the row-tree roots are not those of the rows: {bad}")
    if p["inclusion"] != inclusion_hash(h["dataset"], table_roots):
        problems.append("the inclusion hash is not the hash of the roots")
    if "hashes.json" in held:
        try:
            if json.loads(held["hashes.json"]) != h:
                problems.append("hashes.json is not the hashes of the rows")
        except ValueError:
            problems.append("hashes.json is not JSON")
    if st["predicateType"] in (PREDICATE_TYPE_V2, PREDICATE_TYPE_V3):
        problems.extend(_verify_chain(
            p, subjects, held,
            previous_statement=previous_statement,
            previous_snapshots=previous_snapshots,
            current_snapshots=current_snapshots,
        ))
    elif any(x is not None for x in (previous_statement, previous_snapshots, current_snapshots)):
        problems.append("predecessor chain inputs were given for a v1 statement")
    if st["predicateType"] == PREDICATE_TYPE_V3:
        problems.extend(_verify_allowed(p, subjects, held))
    elif ALLOWED in subjects:
        problems.append(f"{ALLOWED} is a subject without a v3 predicate allowed")
    return problems


def verify_signature(statement: Path, signature: Path, trust, cosign: seal.Cosign | None = None) -> str:
    """`verified: <verifier>`, the first verifier of the trust policy (`seal.policy`) that accepts `signature`
    (a Sigstore bundle) over the bytes of the file `statement`; else SealError with why each refused. The same
    verifiers as a seal's (`seal.Cosign.accepted`), each running `cosign verify-blob` instead of `cosign verify`:
    a key without a transparency log, a keyless identity with it. Reads the statement, the signature and the
    public key, nothing else."""
    v, why = (cosign or seal.Cosign()).accepted(str(statement), trust, bundle=signature)
    if v is None:
        raise seal.SealError(f"no verifier of the policy accepts the signature on {Path(statement).name}: "
                             f"{'; '.join(why)}")
    return f"verified: {v}"


def referrer(seal_manifest: bytes, statement_bytes: bytes, signature: bytes) -> seal.Artifact:
    """The role's statement and its signature (the stored bundle) as a referrer of the seal whose
    manifest bytes these are: the same two files beside the same seal give the same digest."""
    return seal.referrer((seal.digest_of(seal_manifest), len(seal_manifest)), ARTIFACT,
                         [(n, m, d) for (n, m), d in zip(LAYERS, (statement_bytes, signature))])


def _sealed(oras: seal.Oras, ref: str, index: bytes | None) -> tuple[str, bytes, dict, dict]:
    """The seal at `ref`, verified as `seal.verify` does: its repository, manifest bytes, pin and files."""
    files: dict[str, bytes] = {}
    pin = seal.verify(oras, ref, index, files=files)
    repository, _ = seal.split(ref)
    return repository, oras.manifest(f"{repository}@{pin['digest']}"), pin, files


def _named(index_bytes: bytes) -> tuple[dict, str]:
    index = json.loads(index_bytes)
    want = {o.get("name"): o.get("sha256") for o in index.get("objects") or []}.get(NAME)
    if not want:
        raise seal.SealError(f"the sealed index names no {NAME}")
    return index, want


def attach(oras: seal.Oras, ref: str, statement_bytes: bytes, signature: bytes) -> str:
    """Put the role's statement and its signature beside the seal at `ref` (a tag or a digest), as a referrer of
    the seal's digest: "pushed" or "present". The seal must verify and its index must name these statement bytes
    by their sha256. Nothing is signed here: the signature is the one the sign-statement effect made."""
    repository, body, _, files = _sealed(oras, ref, None)
    _, want = _named(files["index.json"])
    if hashlib.sha256(statement_bytes).hexdigest() != want:
        raise seal.SealError(f"the sealed index names {NAME} with another sha256")
    return seal.attach(oras, repository, referrer(body, statement_bytes, signature))


def verify_sealed(oras: seal.Oras, ref: str, index: bytes | None = None, trust=None,
                  cosign: seal.Cosign | None = None) -> dict:
    """The reader of a sealed role form and its statement: the seal as `seal.verify` checks it (against
    `index`, the one the gate serves, when given); then a referrer of its digest that holds the statement the
    sealed index names by sha256 and its signature; the statement against the sealed index and the carried
    files (`verify`, the objects the seal does not carry named with the index's sha256); and, with a trust
    policy, the signature by `verify_signature`, in a single loop. The first referrer that passes is enough.
    Returns the seal's pin and digest, and the statement's sha256, referrer and what was checked of its
    signature (`not checked` without a policy). The seal's own signature is `seal.verify`'s and not asked here."""
    repository, body, pin, files = _sealed(oras, ref, index)
    sealed, want = _named(files["index.json"])
    carried = {n: files[n] for n in seal.CORE}
    absent = set(pin["not_carried"]) - {NAME}
    why = []
    for artifact_type in (ARTIFACT, *LEGACY_ARTIFACTS):
        for digest in oras.referrers(f"{repository}@{pin['digest']}", artifact_type):
            try:
                got = seal.read_referrer(oras, repository, digest, (pin["digest"], len(body)), artifact_type, LAYERS)
            except seal.SealError as err:
                why.append(str(err))
                continue
            if hashlib.sha256(got[NAME]).hexdigest() != want:
                why.append(f"{digest}: its {NAME} is not the one the sealed index names")
                continue
            problems = verify(got[NAME], sealed, carried, absent)
            if problems:
                why.append(f"{digest}: {'; '.join(problems)}")
                continue
            said = seal.NOT_CHECKED
            if trust is not None:
                with tempfile.TemporaryDirectory(prefix="rezono-statement-") as d:
                    (Path(d) / NAME).write_bytes(got[NAME])
                    (Path(d) / SIGNATURE).write_bytes(got[SIGNATURE])
                    try:
                        said = verify_signature(Path(d) / NAME, Path(d) / SIGNATURE, trust, cosign)
                    except seal.SealError as err:
                        why.append(f"{digest}: {err}")
                        continue
            return pin | {"statement": {"sha256": want, "referrer": digest, "signature": said}}
    raise seal.SealError(f"no statement beside {ref} that verifies: {'; '.join(why) or 'none is there'}")


def _verify_dir(folder: Path) -> list[str]:
    index = json.loads((folder / "index.json").read_bytes())
    objects = {o["name"]: (folder / o["name"]).read_bytes() for o in index["objects"] if (folder / o["name"]).exists()}
    if NAME not in objects:
        return [f"{NAME} is not there"]
    return verify(objects[NAME], index, objects)


def trust_of(policy: str | Path | None = None, key: str | Path | None = None):
    """The trust policy a reader names: one public key file, a deploy profile's `seal.trust` (the shared policy;
    its paths relative to the current directory), or None: nothing to check a signature against."""
    if key:
        return (seal.Key(Path(key).as_posix()),)
    if policy:
        import yaml  # only a profile needs it

        with open(policy, encoding="utf-8") as f:
            return seal.policy(((yaml.safe_load(f) or {}).get("seal") or {}).get("trust"))
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_publication.statement")
    p.add_argument("command", choices=["verify"])
    p.add_argument("folder", type=Path, help="a role's form: index.json and the objects it names, side by side, "
                                             f"and {SIGNATURE} when a signature is checked")
    how = p.add_mutually_exclusive_group()
    how.add_argument("--policy", help="a deploy profile: the signature is checked under its seal.trust (needs "
                                      "`cosign`; paths in it are relative to the current directory)")
    how.add_argument("--key", help="a public key file: the signature is checked with this key alone")
    args = p.parse_args(argv)
    problems, said = _verify_dir(args.folder), "signature not checked"
    try:
        trust = trust_of(args.policy, args.key)
        if trust is not None:
            if not (args.folder / SIGNATURE).is_file():
                raise seal.SealError(f"{SIGNATURE} is not there")
            said = verify_signature(args.folder / NAME, args.folder / SIGNATURE, trust)
    except (seal.SealError, OSError) as err:
        problems.append(str(err))
    for line in problems:
        print(f"refused: {line}", file=sys.stderr)
    if not problems:
        print(f"the statement says what its files say ({said})")
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
