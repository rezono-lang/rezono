"""Read Run acceptance evidence from the checked publication on disk."""

from functools import cached_property
import json
from pathlib import Path

import yaml

from offline_cases import RUN
from rezono_canon import sha256_hex
from rezono_compiler import modules, pack, rules, writer
from rezono_publisher import batch, publish, store


class MissingReaderQuestion(AssertionError):
    """The owning pack has yet to publish this reader question."""


def registered(question, test_file, test_name):
    document = yaml.safe_load((RUN / "questions.yaml").read_text(encoding="utf-8"))
    assert set(document) == {"format", "acceptance"} and document["format"] == "rezono.questions/1"
    assert isinstance(document["acceptance"], list)
    errors = []
    entries = pack.acceptance_questions(document["acceptance"], "run/questions.yaml", errors)
    assert not errors, errors
    entry, = [entry for entry in entries if entry["id"] == question]
    expected = f"{Path(test_file).relative_to(RUN).as_posix()}::{test_name}"
    assert entry["tests"] == [expected]


def key(ref):
    return ref["relation"], tuple(json.loads(ref["key"]))


class Publication:
    def __init__(self, bucket, manifest, role):
        self.bucket, self.manifest, self.role = bucket, manifest, role

    def read(self, entry):
        prefix = self.bucket.uri("")
        assert entry["uri"].startswith(prefix)
        data = self.bucket.get(entry["uri"].removeprefix(prefix))
        assert data is not None and sha256_hex(data) == entry["sha256"]
        return json.loads(data)

    def compiled(self, name):
        entry, = [item for item in self.manifest["compiled"] if item["file"] == name]
        return self.read(entry)

    def question(self, question):
        bundle = self.compiled("bundle/schema-bundle.json")
        matches = [row for row in bundle.get("reader_questions", []) if row["id"] == question]
        if not matches:
            raise MissingReaderQuestion(f"the checked publication does not offer {question}")
        reader, = matches
        assert reader["proof"] == "grounds"
        assert any(row["term"] == "grounds" and row["start"] == "present" for row in bundle["questions"])
        assert reader["title_message"] and reader["about_message"] and reader["columns"]
        assert all(column["message"] for column in reader["columns"])
        return reader["relation"]

    def for_role(self, role):
        return Publication(self.bucket, self.manifest, role)

    def rows(self, relation):
        entries = [item for item in self.manifest["snapshots"]
                   if item["role"] == self.role and item["relation"] == relation]
        if not entries:
            return set()
        entry, = entries
        return {tuple(row["key"]) for row in self.read(entry)}

    @cached_property
    def witnesses(self):
        entry, = [item for item in self.manifest["witnesses"] if item["role"] == self.role]
        document = self.read(entry)
        return {key(w["conclusion"]): w for name in ("witnesses", "calc_witnesses")
                for w in document.get(name, [])}

    @cached_property
    def rules(self):
        return rules.load(self.compiled("ir/rules.json")).rules

    def ground_keys(self, relation, row):
        start = (relation, row)
        assert row in self.rows(relation) and start in self.witnesses
        pending, seen, leaves = [start], set(), set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            witness = self.witnesses.get(current)
            if witness is None:
                leaves.add(current)
                continue
            for premise in witness["premises"]:
                if "row" not in premise or premise["polarity"] == "positive":
                    pending.append(key(premise.get("row", premise)))
            for aggregate in witness.get("aggregates", []):
                atom = self.rules[witness["rule_id"]].aggregates[aggregate["position"]].atom
                positions = [position for position, term in enumerate(atom.terms) if term != "_"]
                group = tuple(json.loads(aggregate["group_key"]))
                members = [values for values in self.rows(atom.relation)
                           if tuple(values[position] for position in positions) == group]
                assert len(members) == aggregate["count"]
                pending.extend((atom.relation, member) for member in members)
        return leaves

    def ground_ids(self, relation, row):
        return {values[0] for _, values in self.ground_keys(relation, row) if values}

    def ground_files(self, relation, row):
        entry, = [item for item in self.manifest["fact_sources"] if item["role"] == self.role]
        grounds = self.ground_keys(relation, row)
        return {source["name"] for item in self.read(entry) if key(item["row"]) in grounds
                for source in item["sources"] if source["kind"] == "pack"}


def checked(name, directory, files=None, roles=None, *, change=None):
    source = RUN / "packs" / name
    if not (source / "pack.yaml").is_file():
        raise MissingReaderQuestion(f"owning pack {name} is missing")
    target = modules.copy_closure(source, directory / "input")
    for filename, records in (files or {}).items():
        path = target / "facts" / filename
        path.parent.mkdir(exist_ok=True)
        path.write_text(yaml.safe_dump(records, sort_keys=False), encoding="utf-8")
    if change is not None:
        changed, _ = writer.apply_delta(target, {"format": writer.FORMAT, "changes": [change]})
        writer.write_files(target, changed)
    epoch = batch.epoch(target, epoch=1, knowledge_time="2026-01-15T00:00:00Z",
                        sources=[("rules", "run-acceptance-design")])
    bucket = store.FileStore(directory / "published")
    manifest = publish.publish(epoch, bucket, roles or {"checker": "complete"})
    saved = bucket.get(f"{epoch.pack}/manifests/{manifest['id']}.json")
    manifest = json.loads(saved)
    assert {"name": "rezono:proofs", "status": "green", "violations": 0} in manifest["checks"]
    return Publication(bucket, manifest, "checker")
