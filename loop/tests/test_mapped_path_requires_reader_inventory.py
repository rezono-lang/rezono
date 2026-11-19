"""A pinned Git reader inventory distinguishes an omitted reader from readerlessness."""

from copy import deepcopy
import json
import shutil
import tomllib

import pytest
import yaml

from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_publisher import batch, publish, store
from round_visibility_publication import pinned_evidence
from scripts import components
from test_build_selection import OBSERVED_AT, ROOT, SUITES, capture, git, repository


AUTHORITY = "observer/build-readers.json"
INSTANT = "2027-01-15T08:00:00Z"
SOURCE = "alpha/engine.py"
DOCUMENT = "decisions/note.md"


def archived_json(key, value):
    return {"file": key, "uri": f"s3://rezono/{key}", "sha256": canonical_sha256(value)}


def pin_reader_map(source, base, head):
    git(source, "checkout", "--detach", base)
    authority = source / AUTHORITY
    authority.parent.mkdir()
    authority.write_bytes(canonical_bytes({
        "paths": {SOURCE: {"direct": [], "transitive": ["alpha"]}, DOCUMENT: {"direct": [], "transitive": []}},
        "file_dependencies": [],
    }))
    git(source, "add", AUTHORITY)
    git(source, "commit", "-qm", "Pin the independent reader map")
    engine = git(source, "rev-parse", "HEAD")
    git(source, "update-ref", "refs/remotes/origin/main", engine)
    git(source, "cherry-pick", head)
    return engine


def observed_receipt(source, base, head, engine):
    def tree(revision):
        files = {}
        for entry in git(source, "ls-tree", "-r", revision).splitlines():
            description, path = entry.split("\t", 1)
            mode, kind, oid = description.split()
            assert kind == "blob" and mode in {"100644", "100755"}
            files[path] = {"mode": mode, "blob": oid}
        return files

    paths = git(source, "diff", "--no-renames", "--name-only", base, head, "--").splitlines()
    declaration = git(source, "show", f"{engine}:{AUTHORITY}")
    registry = json.loads(declaration)
    contents = []

    def record(key, origin, rows):
        terminal = {"kind": "git", "name": "build-fixture", "revision": origin.get("revision", head),
                    "position": origin.get("path", f"{base}..{head}")}
        contents.append({"key": key, "terminal": terminal, "rows": [
            {"key": [*key, index], "values": {"value": value, **origin}, "source": terminal}
            for index, value in enumerate(rows)
        ]})

    for path in paths:
        record(["changed-path", path], {"base": base, "head": head}, [path])
        # An empty mapping has a terminal read, even though it has no reader rows. Each reader edge is its own
        # member, so the rules see it in the trusted inventory (decisions/admission-transport.md section 6).
        for kind, readers in registry["paths"][path].items():
            record(["path-readers", path, kind], {"revision": engine, "path": AUTHORITY}, readers)
            for reader in readers:
                record(["path-reader", path, kind, reader], {"revision": engine, "path": AUTHORITY}, [reader])
    record(["file-dependencies"], {"revision": engine, "path": AUTHORITY}, registry["file_dependencies"])
    for revision in (base, head):
        for path, entry in tree(revision).items():
            if path.endswith("/pyproject.toml"):
                origin = {"revision": revision, "path": path, **entry}
                project = tomllib.loads(git(source, "show", f"{revision}:{path}"))["project"]
                record(["manifest", revision, path], origin, [project])
                record(["manifest-dependencies", revision, path], origin, project.get("dependencies", []))
            if revision == head and path.endswith("/test_unit.py"):
                record(["test-file", path], {"revision": head, "path": path, **entry}, [path])
    # The CI universe comes from ordinary discovery on the exact candidate checkout,
    # independently of the suite rows submitted to publication.
    for suite in components.discover_components(source):
        record(["suite", suite.folder], {"revision": head, "path": suite.folder}, [suite.kind])
    contents.sort(key=lambda member: canonical_bytes(member["key"]))
    inventory = [member["key"] for member in contents]
    authorization = {"issuer": "protected-build-observer", "source": "build-fixture", "query": "build-selection",
                     "engine_sha": engine, "path": AUTHORITY, "blob": git(source, "rev-parse", f"{engine}:{AUTHORITY}")}
    bindings = [{"name": name, "type": "Integer" if isinstance(value, int) else "Text", "value": value}
                for name, value in (("attempt", 1), ("base_sha", base), ("engine_sha", engine),
                                    ("event", "pull_request"), ("head_sha", head),
                                    ("observed_at", OBSERVED_AT), ("run", "current"))]
    receipt = {
        "source": {"kind": "git", "name": "build-fixture", "revision": head, "position": f"{base}..{head}"},
        "issuer": {"id": "protected-build-observer",
                   "authorization": archived_json("observations/retained/authorization.json", authorization)},
        "scope": {"definition": archived_json("observations/retained/definition.json", registry),
                  "query": "build-selection", "bindings": bindings},
        "cut": {"frontier": {"source_id": "build-fixture", "position": head}},
        "inventory": archived_json("observations/submitted/inventory.json", inventory),
        "content": archived_json("observations/submitted/content.json", contents),
    }
    receipt["id"] = canonical_sha256(["rezono.completeness-receipt/1", receipt])
    return receipt, {
        "observations/retained/authorization.json": authorization,
        "observations/retained/definition.json": registry,
        "observations/retained/inventory.json": inventory,
        "observations/retained/content.json": contents,
        "observations/submitted/inventory.json": inventory,
        "observations/submitted/content.json": contents,
        "observations/submitted/receipt.json": receipt,
    }


def published_selection(directory, source, submitted, evidence):
    receipt, objects = evidence
    build = directory / "build"
    shutil.copytree(ROOT / "build", build)
    for name in ("std-decision", "std-loop", "std-order"):
        shutil.copytree(ROOT / "packs" / name, directory / "packs" / name)
    (build / "facts").mkdir()
    (build / "facts/input.yaml").write_text(yaml.safe_dump(submitted), encoding="utf-8")
    # The protected job derives the trusted inventory and content from the pinned repository bundle
    # (decisions/admission-transport.md section 4); it retains the bundle beside them.
    bundle = directory / "build-fixture.bundle"
    git(source, "bundle", "create", str(bundle), "HEAD", "refs/remotes/origin/main")
    bundle_bytes = bundle.read_bytes()
    archive = store.FileStore(directory / "archive")
    bundle_key = "observations/retained/build-fixture.bundle"
    archive.put_new(bundle_key, bundle_bytes)
    for name, value in objects.items():
        archive.put_new(name, canonical_bytes(value))
    protected_context = {field: receipt[field] for field in ("source", "issuer", "scope", "cut")}
    for name in ("inventory", "content"):
        retained = f"observations/retained/{name}.json"
        protected_context[name] = archived_json(retained, objects[retained])
    # The protected caller pins its trusted context in context.json and the candidate in index.json, and hands
    # both to the batch boundary as one Evidence (decisions/admission-transport.md sections 2 to 4).
    evidence = pinned_evidence(
        archive, {"completeness": [protected_context]},
        {"completeness_receipts": [archived_json("observations/submitted/receipt.json", receipt)]},
    )
    epoch = batch.epoch(build, epoch=1, knowledge_time=INSTANT, sources=[("build-observation", receipt["id"])],
                        evidence=evidence)
    manifest = publish.publish(epoch, archive, {"reader": "complete"})
    assert any(check["name"] == "rezono:proofs" and check["status"] == "green" for check in manifest["checks"])
    assert {"source_id": "build-observation", "position": receipt["id"]} in manifest["sources"]

    def read(entry):
        data = archive.get(entry["uri"].removeprefix(archive.uri("")))
        assert sha256_hex(data) == entry["sha256"]
        return json.loads(data)

    rows = {entry["relation"]: {tuple(row["key"]) for row in read(entry)}
            for entry in manifest["snapshots"] if entry["role"] == "reader"}
    [witness] = [read(entry) for entry in manifest["witnesses"] if entry["role"] == "reader"]
    return rows, witness["witnesses"]


def submission(source, base, head, engine, path, evidence):
    records = capture(source, base, head, [path])
    receipt = evidence[0]["id"]
    records["build_run"][0].update(engine_sha=engine, receipt=receipt)
    records["loop_sweep_receipt"][0]["id"] = receipt
    return records


def test_mapped_path_requires_reader_inventory(tmp_path):
    source = tmp_path / "source"
    base, head, _ = repository(source, SOURCE)
    engine = pin_reader_map(source, base, head)
    base, head, paths = components.pull_request_range(source, "main")
    evidence = observed_receipt(source, base, head, engine)
    records = submission(source, base, head, engine, SOURCE, evidence)
    universe = components.discover_components(source)
    assert paths == [SOURCE] and {suite.folder for suite in universe} == set(SUITES)
    native = {suite.folder for suite in components.pull_request_components(universe, source, "main")}
    intact, _ = published_selection(tmp_path / "intact", source, records, evidence)
    assert {component for _, component, _ in intact["build_selected_job"]} == native == {"alpha", "beta", "gamma"}
    assert not intact["build_full_selection"]

    for removed in ("reader", "path", "manifest", "test-file", "suite"):
        submitted = deepcopy(records)
        if removed == "reader":
            submitted["build_path_reader"].clear()
        elif removed == "path":
            submitted["build_path"].clear()
            submitted["build_path_reader"].clear()
        elif removed == "manifest":
            submitted["build_manifest"] = [row for row in submitted["build_manifest"] if row["component"] != "gamma"]
            submitted["build_dependency"] = [row for row in submitted["build_dependency"] if row["consumer"] != "gamma"]
        elif removed == "test-file":
            submitted["build_test_file"] = [row for row in submitted["build_test_file"] if row["component"] != "beta"]
        else:
            submitted["build_component"] = [row for row in submitted["build_component"] if row["id"] != "spare"]
            for kind in ("build_test_file", "build_manifest"):
                submitted[kind] = [row for row in submitted[kind] if row["component"] != "spare"]
        rows, _ = published_selection(tmp_path / f"omit-{removed}", source, submitted, evidence)
        assert {component for _, component, _ in rows["build_selected_job"]} == set(SUITES), removed
        assert rows["build_full_selection"], removed
        assert not rows.get("build_readerless_path"), removed

    git(source, "checkout", "--detach", base)
    document = source / DOCUMENT
    document.parent.mkdir()
    document.write_text("# An independently readerless decision\n", encoding="utf-8")
    git(source, "add", DOCUMENT)
    git(source, "commit", "-qm", "Change the known readerless document")
    doc_head = git(source, "rev-parse", "HEAD")
    evidence = observed_receipt(source, base, doc_head, engine)
    records = submission(source, base, doc_head, engine, DOCUMENT, evidence)
    rows, witnesses = published_selection(tmp_path / "readerless", source, records, evidence)
    assert not rows["build_full_selection"] and not rows["build_selected_job"]
    key = ("current", DOCUMENT, evidence[0]["id"])
    assert rows["build_readerless_path"] == {key}
    proof = {(witness["conclusion"]["relation"], witness["conclusion"]["key"]): witness for witness in witnesses}
    target = ("build_readerless_path", canonical_json(key))
    assert target in proof
    reached = set()
    pending = [target]
    while pending:
        ref = pending.pop()
        if ref not in reached:
            reached.add(ref)
            pending.extend((premise["row"]["relation"], premise["row"]["key"])
                           for premise in proof.get(ref, {}).get("premises", []) if premise["polarity"] == "positive")
    assert any(relation == "complete" and evidence[0]["id"] in json.loads(row)
               for relation, row in reached)


def resealed_without_reader(evidence):
    """Drop the mapped reader from the submitted receipt and recompute its digests over that subset."""
    receipt, objects = evidence
    objects = dict(objects)
    content = [member for member in deepcopy(objects["observations/submitted/content.json"])
               if member["key"][:2] != ["path-reader", SOURCE]]
    for member in content:
        if member["key"][:2] == ["path-readers", SOURCE]:
            member["rows"] = []
    inventory = [member["key"] for member in content]
    objects["observations/submitted/content.json"] = content
    objects["observations/submitted/inventory.json"] = inventory
    body = {field: value for field, value in receipt.items() if field != "id"}
    body["content"] = archived_json("observations/submitted/content.json", content)
    body["inventory"] = archived_json("observations/submitted/inventory.json", inventory)
    resealed = {**body, "id": canonical_sha256(["rezono.completeness-receipt/1", body])}
    objects["observations/submitted/receipt.json"] = resealed
    return resealed, objects


def test_resealed_receipt_cannot_drop_mapped_reader(tmp_path):
    source = tmp_path / "source"
    base, head, _ = repository(source, SOURCE)
    engine = pin_reader_map(source, base, head)
    base, head, _ = components.pull_request_range(source, "main")
    evidence = resealed_without_reader(observed_receipt(source, base, head, engine))
    records = submission(source, base, head, engine, SOURCE, evidence)
    records["build_path_reader"].clear()
    rows, _ = published_selection(tmp_path / "resealed", source, records, evidence)
    assert {component for _, component, _ in rows["build_selected_job"]} == set(SUITES)
    assert rows["build_full_selection"]
    assert not rows.get("build_readerless_path")
