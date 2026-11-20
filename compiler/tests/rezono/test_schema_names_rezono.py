"""`modules.schema_names` collects declared kinds, enums, scalar aliases and units from Rezono modules as well as
YAML schemas, so a Rezono consumer importing a Rezono-only pack resolves imported names without any `schema/*.yaml`."""

import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler import modules, pack, rezono_module
from support import FIXTURE, compile_dir
from test_rezono_module import add, declare, module


def rezono_v2(
    pack_dir: Path,
    decls: list[dict],
    *,
    pack_name: str,
    name: str,
    use: list[dict] | None = None,
    layer: str = "facts",
) -> None:
    """Write a form-only `rezono.module/2` module and register it in `pack.yaml`."""
    body = {"rezono": "0", "pack": pack_name, "use": use or [], "decls": decls}
    spans = [
        {"at": pointer, "line": str(10 + idx), "start": "0", "end": "1"}
        for idx, pointer in enumerate(rezono_module.place_pointers(body))
    ]
    (pack_dir / "rezono").mkdir(exist_ok=True)
    (pack_dir / "rezono" / f"{name}.json").write_bytes(
        json.dumps({"format": rezono_module.IDENTIFIER_FORMAT, "module": body, "spans": spans}, sort_keys=True).encode("utf-8")
    )
    (pack_dir / "rezono" / f"{name}.rezono").write_bytes(f"rezono 0\npack {pack_name}\n".encode("utf-8"))
    meta = yaml.safe_load((pack_dir / "pack.yaml").read_bytes())
    entry = {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": layer}
    declare(pack_dir, [e for e in meta.get("rezono") or [] if e["module"] != entry["module"]] + [entry])


def rezono_only_lib(root: Path) -> Path:
    """A pack with no `schema/` directory: one Rezono schema module plus one Rezono dataset module."""
    lib = root / "lib"
    (lib / "labels").mkdir(parents=True)
    (lib / "pack.yaml").write_text("name: lib\nversion: '0.1.0'\ndefault_language: nl\nimports: []\n", encoding="utf-8")
    (lib / "labels" / "nl.yaml").write_text(
        "role: rol\nrole.capability: recht\ncapability: recht\ncapability.read: lezen\ncapability.review: beoordelen\n",
        encoding="utf-8",
    )
    rezono_v2(
        lib,
        [
            {"enum": "Capability", "values": ["read", "review"]},
            {"type": "TagCode", "base": "Text"},
            {"unit": "Cents", "is": "money minor EUR"},
            {
                "kind": "Role",
                "world": "closed",
                "slots": [{"slot": "capability", "type": "Capability", "card": "*"}],
                "derived": [],
            },
        ],
        pack_name="lib",
        name="access",
    )
    # A dataset-only Rezono module must not appear as a schema module in `schema_names`.
    dataset_body = {"rezono": "0", "pack": "lib", "use": [], "decls": [{"dataset": "seed", "decls": []}]}
    (lib / "rezono" / "seed.json").write_bytes(
        json.dumps({"format": rezono_module.DATASET_FORMAT, "module": dataset_body, "spans": []}, sort_keys=True).encode("utf-8")
    )
    (lib / "rezono" / "seed.rezono").write_bytes(b"rezono 0\npack lib\ndataset seed\n")
    meta = yaml.safe_load((lib / "pack.yaml").read_bytes())
    declare(lib, meta["rezono"] + [{"module": "rezono/seed.rezono", "form": "rezono/seed.json", "layer": "facts"}])
    assert not (lib / "schema").exists()
    return lib


def consumer_of(root: Path, lib: Path) -> Path:
    consumer = Path(shutil.copytree(FIXTURE, root / "main"))
    meta = yaml.safe_load((consumer / "pack.yaml").read_bytes())
    meta["imports"] = [{"name": "lib", "path": "../lib", "sha256": modules.pack_hash(lib)}]
    (consumer / "pack.yaml").write_bytes(yaml.safe_dump(meta, sort_keys=False).encode("utf-8"))
    add(
        consumer / "labels" / "nl.yaml",
        "grant: toekenning\ngrant.role: rol\ngrant.capability: recht\ngrant.code: code\ngrant.fee: tarief\n"
        "special_role: speciale rol\n",
    )
    return consumer


def test_schema_names_includes_rezono_modules_and_excludes_datasets(tmp_path):
    lib = rezono_only_lib(tmp_path / "rezono_only")
    assert modules.schema_names(lib) == {"access": {"Role", "Capability", "TagCode", "Cents"}}

    # Hybrid pack: both YAML schema files and Rezono modules are reported.
    hybrid = Path(shutil.copytree(FIXTURE, tmp_path / "hybrid"))
    module(
        hybrid,
        [
            {"enum": "Tier", "values": ["basic", "full"]},
            {"kind": "Ticket", "world": "closed", "slots": [{"slot": "tier", "type": "Tier"}], "derived": []},
        ],
        pack="minimal",
        name="extra",
    )
    assert modules.schema_names(hybrid) == {
        "minimal": {"Alpha", "Beta", "State", "Count"},
        "extra": {"Tier", "Ticket"},
    }


@pytest.mark.parametrize("prefixed", [False, True])
def test_rezono_consumer_imports_rezono_only_pack(tmp_path, prefixed):
    root = tmp_path / ("prefixed" if prefixed else "plain")
    lib = rezono_only_lib(root)
    consumer = consumer_of(root, lib)
    prefix = "acc." if prefixed else ""
    use = [{"use": "lib", "as": "acc"}] if prefixed else [{"use": "lib"}]
    rezono_v2(
        consumer,
        [
            {
                "kind": "Grant",
                "world": "closed",
                "slots": [
                    {"slot": "role", "type": f"{prefix}Role"},
                    {"slot": "capability", "type": f"{prefix}Capability"},
                    {"slot": "code", "type": f"{prefix}TagCode"},
                    {"slot": "fee", "type": f"{prefix}Cents"},
                ],
                "derived": [],
            },
            {"kind": "SpecialRole", "parent": f"{prefix}Role", "slots": [], "derived": []},
        ],
        pack_name="minimal",
        name="grants",
        use=use,
    )

    loaded = pack.read(consumer)
    assert "grant" in loaded.kinds
    assert "role" in loaded.kinds
    assert loaded.kinds["special_role"].parent == "role"
    assert "capability" in loaded.enums
    assert loaded.units["Cents"].currency == "EUR"
    grant_slots = loaded.kinds["grant"].slots
    assert grant_slots["role"].arrow and grant_slots["role"].range == "role"
    assert grant_slots["capability"].enum == "capability"
    assert grant_slots["code"].sql_type == "VARCHAR"
    assert grant_slots["fee"].sql_type == "BIGINT" and grant_slots["fee"].currency == "EUR"

    bundle = json.loads(compile_dir(consumer, root / "out")["bundle/schema-bundle.json"])
    assert ("grant.role", "role", True) in {(a["id"], a["target"], a["required"]) for a in bundle["arrows"]}
    assert any(s["module"] == "lib:access" and s["file"] == "rezono/access.rezono" for s in bundle["schemas"])
