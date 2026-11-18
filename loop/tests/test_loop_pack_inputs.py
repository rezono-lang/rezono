"""The production input adapter joins admitted record columns before rules consume them."""

import shutil

import pytest
import yaml

from pack_records import LOOP, ORDER, evaluate, records


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement packs/std-loop/schema, its labels/channels and packs/std-loop/rules/loop_inputs.dl. Adapt typed fact rows to the existing fragment signatures. This isolated loading test can start before the other fragments land.")
def test_loop_pack_inputs(tmp_path):
    from rezono_compiler import modules, pack

    shell = tmp_path / "std-loop"
    (shell / "rules").mkdir(parents=True)
    # Only the assembly shell is synthetic. All schema and adapter definitions come from production.
    shutil.copytree(LOOP / "schema", shell / "schema")
    for item in ("labels", "channels.yaml", "messages"):
        src = LOOP / item
        if src.is_dir():
            shutil.copytree(src, shell / item)
        elif src.is_file():
            shutil.copy(src, shell / item)
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
