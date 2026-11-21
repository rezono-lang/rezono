"""The production input adapter joins admitted record columns before rules consume them."""

from pack_records import LOOP, evaluate, records


def test_loop_pack_inputs():
    from rezono_compiler import pack

    model = pack.read(LOOP)
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
