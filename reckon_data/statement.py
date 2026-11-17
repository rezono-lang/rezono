"""The epoch statement of one role (RV-X41; docs/ring2/signing.md, "What is signed"; decisions Y2.7, Y2.8).

  python -m reckon_data.statement verify DIR [--policy profile.yaml | --key seal.pub]

One small document per published epoch and filtered role, the one thing a signature covers (RV-X42): an
in-toto Statement (v1) whose subjects are the objects of the role's Reckon Data form by their sha256, and whose
predicate binds what the role reads and nothing more:

- the role's manifest as its form carries it (`reckon_data.publication.role_manifest`: id, epoch, knowledge time,
  definition hash and compiled files), by its canonical hash, with the names a reader looks for spelled out;
- the role's own snapshots, by relation and sha256 (the files the form was made from);
- the schema id, the dataset hash `d-…` and the annotation hash of §6.2, unchanged;
- the row tree (Y2.8): per table, side tables too, the RFC 9162 Merkle root over the table's hash rows in hash
  order (a leaf is `SHA-256(0x00 ‖ CJ(row))`, a node `SHA-256(0x01 ‖ left ‖ right)`, an empty table `SHA-256()`),
  and the inclusion hash `H({"dataset", "roots"})` over them. The dataset hash does not change.

Every value is text, so the canonical bytes of Rede's canon (which writes an integer as text) are RFC 8785's
bytes too, and a verifier of another implementation reads the same document. Nothing in it is computed from a row
the role may not read, and `pack_sha256` (which hashes hidden facts) is never in it: two worlds that differ only
in such rows give the role the same statement (O8). The statement of the complete role is never made.

The predicate type carries its version (`/v1`); its names are exactly `PREDICATE_KEYS`, with no empty place for
what a later version adds (`previous` with the deltas, `compiler` and `source` with the sealed artifact; `checks`
stays out of a filtered role's statement, O7). The knowledge time is the manifest's, as its form carries it: an
RFC 3339 time with `Z` or an offset (`git log --format=%cI` writes an offset).

`verify` is the reader's check, from the published bytes alone (the index, the statement and the objects): the
statement is canonical and has exactly the contract's names at every level (contracts/statement.yaml is closed,
and so is the reader), names exactly the index's objects with their sha256, agrees with the index on every name,
and its dataset pin, roots and inclusion hash are recomputed from the subjects' own bytes (the schema and rows
read back with the L0 reader). A difference is named; an empty list is a statement that says what its files say.

`verify_signature` is the reader's check of the signature (RV-X42): `statement.sigstore.json`, the Sigstore bundle
cosign writes over the statement's bytes, beside it. It is RV-K23's one verification (`reckon_data.seal`: its
trust policy, its cosign, its key and its loop, `seal.Cosign.accepted`), on a file instead of a registry digest:
one verifier of the policy that accepts is enough, and it reads only the statement, the signature and the public
key. Without a policy the CLI says "signature not checked", never "verified". The signing itself is an effect
(edge/plugins/sign-statement).

Beside a sealed role form (RV-X43), the statement and that same signature are one referrer of the seal's digest
(`ARTIFACT`, the two files as its layers): `attach` pushes it once the sealed index names the statement's sha256,
signing nothing; `verify_sealed` is the reader of the seal and its statement together, see there.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from rede_canon import CanonError, canonical_bytes

from . import l0
try:
    from . import seal
except ImportError:
    seal = None  # type: ignore[assignment]
from .hash import H, CJ, HashError, hash_rows, hashes

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://rede.dev/epoch-statement/v1"
FORMAT = "rede.epoch-statement/1"
NAME = "statement.json"  # its name under the role's prefix, beside the form's objects
SIGNATURE = "statement.sigstore.json"  # cosign's Sigstore bundle over the statement's bytes, beside it (RV-X42)
ARTIFACT = "application/vnd.rede.epoch-statement.v1"  # the two as a referrer of the role's seal (RV-X43)
LAYERS = ((NAME, "application/vnd.in-toto+json"), (SIGNATURE, "application/vnd.dev.sigstore.bundle.v0.3+json"))
MANIFEST_NAMES = ("id", "epoch", "knowledge_time", "definition_sha256")
# The names of the contract (contracts/statement.yaml), at each level; the reader refuses any other.
STATEMENT_KEYS = ("_type", "subject", "predicateType", "predicate")
SUBJECT_KEYS = ("name", "digest")
DIGEST_KEYS = ("sha256",)
PREDICATE_KEYS = ("format", "pack", "role", "manifest", "epoch", "knowledge_time", "definition", "role_manifest",
                  "snapshots", "schema", "dataset", "annotation", "roots", "inclusion")
SNAPSHOT_KEYS = ("relation", "sha256")

__all__ = ["NAME", "SIGNATURE", "PREDICATE_KEYS", "tree_root", "roots", "inclusion_hash", "make", "dumps", "verify",
           "verify_signature", "trust_of", "referrer", "attach", "verify_sealed"]


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


def make(index: dict, objects: dict[str, bytes], schema: dict, rows: list) -> dict:
    """The statement of the role whose form index and objects these are. `objects` are every object the index
    names except the statement; `schema` and `rows` are the form's own, as `reckon_data.publication.form` made
    them (or as the L0 reader reads them back from those objects)."""
    m = index["manifest"]
    h = hashes(schema, rows)
    if h["schema"] != index["schema"] or h["dataset"] != index["dataset"]:
        raise ValueError("the index does not name the dataset of these rows")
    table_roots = roots(schema, rows)
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": n, "digest": {"sha256": hashlib.sha256(objects[n]).hexdigest()}} for n in sorted(objects)],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "format": FORMAT,
            "pack": index["pack"],
            "role": index["role"],
            "manifest": _text(m["id"]),
            "epoch": _text(m["epoch"]),
            "knowledge_time": _text(m["knowledge_time"]),
            "definition": _text(m["definition_sha256"]),
            "role_manifest": H(m),
            "snapshots": [{"relation": s["relation"], "sha256": s["sha256"]} for s in index["sources"]],
            "schema": h["schema"],
            "dataset": h["dataset"],
            "annotation": h["annotation"],
            "roots": table_roots,
            "inclusion": inclusion_hash(h["dataset"], table_roots),
        },
    }


def dumps(statement: dict) -> bytes:
    """The statement's bytes: canonical JSON (RFC 8785; every value is text, so Rede's canon is RFC 8785 here)."""
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


def verify(statement_bytes: bytes, index: dict, objects: dict[str, bytes], absent=()) -> list[str]:
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
    if not isinstance(st, dict) or st.get("_type") != STATEMENT_TYPE or st.get("predicateType") != PREDICATE_TYPE:
        return ["not an epoch statement (in-toto Statement v1 with Rede's predicate type)"]
    shape = _shape(st)
    if shape:
        return problems + shape
    p = st["predicate"]
    if p["format"] != FORMAT:
        return [f"predicate format is not {FORMAT}"]

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
    held = {n: files[n] for n in subjects if n in files and hashlib.sha256(files[n]).hexdigest() == subjects[n]}
    try:
        schema = json.loads(held["schema.json"])
        sid = l0.check_schema(schema)
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
    """The role's statement and its signature (the bundle as RV-X42 stored it) as a referrer of the seal whose
    manifest bytes these are (RV-X43): the same two files beside the same seal give the same digest."""
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
    """The reader of a sealed role form and its statement (RV-X43): the seal as `seal.verify` checks it (against
    `index`, the one the gate serves, when given); then a referrer of its digest that holds the statement the
    sealed index names by sha256 and its signature; the statement against the sealed index and the carried
    files (`verify`, the objects the seal does not carry named with the index's sha256); and, with a trust
    policy, the signature by `verify_signature`, RV-K23's one loop. The first referrer that passes is enough.
    Returns the seal's pin and digest, and the statement's sha256, referrer and what was checked of its
    signature (`not checked` without a policy). The seal's own signature is `seal.verify`'s and not asked here."""
    repository, body, pin, files = _sealed(oras, ref, index)
    sealed, want = _named(files["index.json"])
    carried = {n: files[n] for n in seal.CORE}
    absent = set(pin["not_carried"]) - {NAME}
    why = []
    for digest in oras.referrers(f"{repository}@{pin['digest']}", ARTIFACT):
        try:
            got = seal.read_referrer(oras, repository, digest, (pin["digest"], len(body)), ARTIFACT, LAYERS)
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
            with tempfile.TemporaryDirectory(prefix="rede-statement-") as d:
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
    """The trust policy a reader names: one public key file, a deploy profile's `seal.trust` (RV-K23's one policy;
    its paths relative to the current directory), or None: nothing to check a signature against."""
    if key:
        return (seal.Key(Path(key).as_posix()),)
    if policy:
        import yaml  # only a profile needs it

        with open(policy, encoding="utf-8") as f:
            return seal.policy(((yaml.safe_load(f) or {}).get("seal") or {}).get("trust"))
    return None


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="reckon_data.statement")
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
