"""Project complete published kind and slot rows into reversible, typed triples."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from rezono_compiler import facts, modules, pack, rules_dl, scenarios
from rezono_publisher import batch, publish, store
from rezono_publisher.views import key_of


KIND = ("kind", "VARCHAR")


def encode(domain, value):
    text = json.dumps([list(domain), value], ensure_ascii=False, separators=(",", ":"))
    return "v_" + text.encode("utf-8").hex()


def decode(token):
    if not token.startswith("v_"):
        raise ValueError(f"unknown triple token {token!r}")
    domain, value = json.loads(bytes.fromhex(token[2:]).decode("utf-8"))
    domain = tuple(domain)
    if not isinstance(value, str) or encode(domain, value) != token:
        raise ValueError("noncanonical triple token")
    return domain, value


def digest(raw):
    return sha256(raw).hexdigest()


def write_json(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def catalog(model):
    names = {kind: ("id", model.kinds[model.root(kind)].id_type, kind) for kind in model.kinds}
    tables = {kind: (domain,) for kind, domain in names.items()}
    for kind in model.kinds.values():
        for slot in kind.slots.values():
            if slot.arrow:
                domain = names[slot.range]
            elif slot.enum:
                domain = ("enum", slot.sql_type, slot.enum)
            else:
                domain = ("value", slot.sql_type, slot.range, slot.currency or "", slot.unit or "")
            tables[slot.table] = (names[slot.kind], domain)
    return tables


def triples(relation, domains, rows):
    for row in sorted(rows):
        values = [encode(domain, value) for domain, value in zip(domains, row, strict=True)]
        if len(domains) == 1:
            yield values[0], "is", encode(KIND, relation)
        else:
            yield values[0], relation, values[1]


def project(pack_dir, destination, commit):
    model = pack.read(pack_dir)
    tables = catalog(model)
    worlds = rules_dl.base_worlds(model)
    authored = scenarios.rows_of(model, [record for path in facts.files(pack_dir)
                                         for record in scenarios.records(model, path)])
    with TemporaryDirectory(prefix="anyburl-publication-") as temp:
        bucket = store.FileStore(Path(temp))
        epoch = batch.epoch(pack_dir, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])
        manifest = publish.publish(epoch, bucket, {"checker": "complete"})
        definition = modules.pack_hash(pack_dir)
        if manifest["definition_sha256"] != definition:
            raise ValueError("publication definition differs from the pinned pack")
        entries = {item["relation"]: item for item in manifest["snapshots"] if item["role"] == "checker"}
        projected, snapshots, targets = [], {}, []
        for relation, domains in sorted(tables.items()):
            entry = entries[relation]
            raw = bucket.get(key_of(entry["uri"]))
            if raw is None or digest(raw) != entry["sha256"] or not entry["complete"]:
                raise ValueError(f"{relation}: expected the complete published snapshot at its digest")
            rows = {tuple(item["key"]) for item in json.loads(raw)}
            if rows != {tuple(batch.text(value) for value in row) for row in authored.get(relation, ())}:
                raise ValueError(f"{relation}: the published and ordinary authored rows differ")
            projected.extend(triples(relation, domains, rows))
            snapshots[relation] = entry["sha256"]
            if rows and len(domains) == 2 and worlds[relation] == "closed":
                targets.append(relation)

    # AnyBURL scores missing predictions for a target. A shared is predicate is usable as
    # a target only if all its contributing kind relations are declared closed.
    if any(predicate == "is" for _, predicate, _ in projected) and all(worlds[rel] == "closed"
                                                                       for rel in model.kinds):
        targets.append("is")
    if not targets:
        raise ValueError("the publication has no nonempty closed candidate target")
    raw = "".join("\t".join(row) + "\n" for row in sorted(projected)).encode("utf-8")
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "facts.tsv").write_bytes(raw)
    write_json(destination / "input.json", {
        "commit": commit, "definition_sha256": definition, "publication": manifest["id"],
        "triples_sha256": digest(raw), "triples": len(projected), "snapshots": snapshots,
        "closed_targets": sorted(targets),
    })
    (destination / "targets.txt").write_text(",".join(sorted(targets)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("pack", type=Path)
    cli.add_argument("destination", type=Path)
    cli.add_argument("commit")
    args = cli.parse_args()
    project(args.pack, args.destination, args.commit)
