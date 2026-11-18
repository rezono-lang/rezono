"""The production input adapter joins admitted record columns before rules consume them."""

import shutil

import pytest
import yaml

from pack_records import LOOP, ORDER, evaluate, records


def test_loop_pack_inputs(tmp_path):
    from rezono_compiler import modules, pack

    shell = tmp_path / "std-loop"
    (shell / "rules").mkdir(parents=True)
    # Only the assembly shell is synthetic. All schema and adapter definitions come from production.
    shutil.copytree(LOOP / "schema", shell / "schema")
    # Pack-wide labels can name relations outside this input fragment.
    (shell / "labels").mkdir()
    (shell / "labels" / "en.yaml").write_text("{}\n", encoding="utf-8")
    shutil.copy(LOOP / "channels.yaml", shell / "channels.yaml")
    shutil.copy(LOOP / "rules" / "loop_inputs.dl", shell / "rules")
    shutil.copytree(ORDER, tmp_path / "std-order")
    meta = {"name": "std-loop", "version": "0.1.0", "theory": True, "default_language": "en",
            "imports": [{"name": "std-order", "path": "../std-order", "sha256": modules.pack_hash(ORDER)}]}
    (shell / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    model = pack.read(shell)
    prog, rows, _ = evaluate(model, records())
    assert model.kinds["loop_step"].parent == "ordered"
    assert rows["active"] == {("current",)}
    assert rows["before"] == {("seed", "build"), ("build", "ship"), ("seed", "ship")}
    assert rows["completion"] == {
        ("current", "seed", "seeded", "source-a"), ("current", "build", "built", "source-b"),
        ("prior", "seed", "previous", "old-def"),
    }
    assert rows["expectation"] == {("seeded", "yes"), ("built", "yes")}
    assert [col.type for col in prog.relations["observed"].key] == [
        "string", "string", "integer", "string", "string", "string", "string"]
    assert rows["observed"] == {
        ("prior", "seeded", "20", "event-old", "known", "yes", "old-evidence"),
        ("current", "built", "3", "event-now", "known", "yes", "current-evidence"),
    }
