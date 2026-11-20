"""The public-surface compatibility check at publication (docs/rezono/v0.md, section 4c;
decisions/language-surface-compatibility.md), on the minimal, domain-free fixture pack: the class of each change of
a pack's public surface, read from its compiled schema bundle, against its newest main publication, and, once the
earlier publication promised a stable surface (pack version 1.0.0 or later), R033 for an unaccepted major change and
a refusal of a pack version that moves less far than the class.

Every class is a row of the table in v0 section 4c: an added slot, an added value of an open enum and a widened
refinement are minor; a removed, renamed or retyped slot, a changed cardinality and a closed enum are major; doc
comments, messages and labels are patch."""

import copy
import importlib
import json
import shutil
from pathlib import Path

import pytest
from rezono_compiler import emit, pack
from rezono_publisher import batch, publish, store

FIXTURE = Path(__file__).resolve().parents[3] / "compiler/tests/fixtures/minimal"
PACK, SCHEMA, LABELS, MESSAGES = "pack.yaml", "schema/minimal.yaml", "labels/nl.yaml", "messages/nl.mf2"
ROLES = {"reader": "complete"}

SIZE = "      size:\n        range: Count\n        minimum_value: 0\n        maximum_value: 9\n"
TITLE = "      title:\n        required: true\n"
ADD_COLOUR = [(SCHEMA, SIZE, SIZE + "      colour:\n        range: string\n"),
              (LABELS, "alpha.size: grootte\n", "alpha.size: grootte\nalpha.colour: kleur\n")]
REMOVE_SIZE = [(SCHEMA, SIZE, ""), (LABELS, "alpha.size: grootte\n", "")]
RENAME_SIZE = [(SCHEMA, SIZE, SIZE.replace("size:", "amount:")
                + "        annotations:\n          renamed_from: size\n"),
               (LABELS, "alpha.size:", "alpha.amount:")]
# Text for people only: a doc comment, a message and a label. No element of the surface changes.
TEXT_ONLY = [(SCHEMA, "  Alpha:\n", "  Alpha:\n    description: A neutral element of the first kind.\n"),
             (MESSAGES, "attribute.total = {{Elke {$kind} heeft precies één {$attribute}.}}",
              "attribute.total = {{Bij elke {$kind} hoort één {$attribute}.}}"),
             (LABELS, "alpha.title: titel\n", "alpha.title: opschrift\n")]

# One change of the minimal pack per row of v0 section 4c: its edits, its class, and the change of one element that
# sets that class, named by the element's id in the earlier bundle (an added element by its new id).
CHANGES = {
    "add an optional slot": (ADD_COLOUR, "minor", ("alpha.colour", "added")),
    "widen a refinement": ([(SCHEMA, "        maximum_value: 9\n", "        maximum_value: 99\n")],
                           "minor", ("alpha.size", "widened")),
    "remove a slot": (REMOVE_SIZE, "major", ("alpha.size", "removed")),
    "rename a slot": ([(SCHEMA, TITLE, "      heading:\n        required: true\n        annotations:\n"
                                       "          renamed_from: title\n"),
                       (LABELS, "alpha.title:", "alpha.heading:")], "major", ("alpha.title", "renamed")),
    "retype a slot": ([(SCHEMA, SIZE, "      size:\n        range: string\n")], "major", ("alpha.size", "retyped")),
    "change a cardinality": ([(SCHEMA, TITLE, "      title:\n        required: false\n")],
                             "major", ("alpha.title", "cardinality")),
}


class MissingSurfaceCheck(AssertionError):
    """rezono_publisher.surface.compare or rezono_publisher.publish.compatibility is not there."""


def surface_compare():
    try:
        return importlib.import_module("rezono_publisher.surface").compare
    except (ImportError, AttributeError) as error:
        raise MissingSurfaceCheck(str(error)) from error


def compatibility():
    try:
        return publish.compatibility
    except AttributeError as error:
        raise MissingSurfaceCheck(str(error)) from error


def edited(source: Path, target: Path, edits) -> Path:
    """A copy of the pack at `source` under `target`, with each (file, old, new) edit made once. An edit that does
    not apply exactly once is a broken test, not the expected failure, so it raises ValueError."""
    folder = Path(shutil.copytree(source, target / "minimal"))
    for path, old, new in edits:
        file = folder / path
        text = file.read_text("utf-8")
        if text.count(old) != 1:
            raise ValueError(f"{path}: {old!r} is not there exactly once")
        file.write_text(text.replace(old, new), "utf-8")
    return folder


def bundle_of(folder: Path) -> dict:
    """The compiled schema bundle of a pack, without an engine."""
    return json.loads(emit.compile_pack(pack.read(folder))["bundle/schema-bundle.json"])


def with_facts(target: Path, version: str) -> Path:
    """The fixture pack at a pack version, with one row of alpha that names no slot the tests change."""
    folder = edited(FIXTURE, target, [(PACK, 'version: "0"', f'version: "{version}"')])
    (folder / "facts").mkdir()
    (folder / "facts" / "rows.yaml").write_text("alpha:\n  - {id: a1, title: first}\n", encoding="utf-8")
    return folder


def bumped(old: str, new: str) -> list:
    """The edit that moves the pack version, so a publication at 1.0.0 or later moves as far as its class."""
    return [(PACK, f'version: "{old}"', f'version: "{new}"')]


def epoch_of(folder: Path, number: int):
    return batch.epoch(folder, epoch=number, knowledge_time=f"2026-{number:02d}-01T00:00:00Z",
                       sources=[("facts", "fixture")])


def opened(bundle: dict) -> dict:
    """The bundle as it would be with State declared `world open`: the bundle says so on each slot that takes the
    enum (contracts/bundle.yaml, SemanticType.open). No reader declares an open enum yet, so it is written here."""
    out = copy.deepcopy(bundle)
    [slot] = [a for a in out["attributes"] if a["id"] == "beta.state"]
    slot["semantic"]["open"] = True
    return out


def with_value(bundle: dict, value: str) -> dict:
    out = copy.deepcopy(bundle)
    [enum] = out["enums"]
    enum["values"].append(value)
    return out


def triples(result: dict) -> set:
    return {(c["element"], c["change"], c["class"]) for c in result["changes"]}


def refusal(epoch, archive) -> str | None:
    """Why the publisher refuses the epoch, or None when it publishes it."""
    try:
        publish.publish(epoch, archive, ROLES)
    except publish.Blocked as err:
        return str(err)
    return None


def test_compare_classifies_each_change_as_section_4c_does(tmp_path):
    compare = surface_compare()
    before = bundle_of(edited(FIXTURE, tmp_path / "before", []))
    got, want, results = {}, {}, []
    for number, (name, (edits, expected, (element, change))) in enumerate(sorted(CHANGES.items())):
        result = compare(before, bundle_of(edited(FIXTURE, tmp_path / str(number), edits)))
        results.append(result)
        got[name] = (result["class"], (element, change, expected) in triples(result))
        want[name] = (expected, True)
    text = bundle_of(edited(FIXTURE, tmp_path / "text", TEXT_ONLY))
    got["edit doc comments, messages and labels"] = compare(before, text)
    want["edit doc comments, messages and labels"] = {"class": "patch", "changes": []}
    got["change nothing"] = compare(before, before)
    want["change nothing"] = {"class": "patch", "changes": []}
    open_enum = opened(before)
    [enum] = before["enums"]
    value = f"{enum['id']}.middle"
    result = compare(open_enum, with_value(open_enum, value))
    results.append(result)
    got["add a value to an open enum"] = (result["class"], (value, "added", "minor") in triples(result))
    want["add a value to an open enum"] = ("minor", True)
    result = compare(open_enum, before)
    results.append(result)
    got["close an open enum"] = (result["class"], ("beta.state", "closed", "major") in triples(result))
    want["close an open enum"] = ("major", True)
    assert got == want
    assert all(r["changes"] == sorted(r["changes"], key=lambda c: (c["element"], c["change"])) for r in results)


def test_compatibility_names_the_class_against_the_newest_main(tmp_path):
    check = compatibility()
    folder = with_facts(tmp_path / "1", "1.0.0")
    (tmp_path / "archive").mkdir()
    archive = store.FileStore(tmp_path / "archive")
    first = epoch_of(folder, 1)
    assert check(first, archive) is None  # nothing is published yet, so nothing is compared
    assert publish.publish(first, archive, ROLES)["id"] == "m-1"

    added = edited(folder, tmp_path / "2", ADD_COLOUR + bumped("1.0.0", "1.1.0"))
    minor = epoch_of(added, 2)
    report = check(minor, archive)
    assert (report["against"], report["class"]) == ("m-1", "minor")
    assert ("alpha.colour", "added", "minor") in triples(report)
    assert publish.publish(minor, archive, ROLES)["id"] == "m-2"

    patch = epoch_of(edited(added, tmp_path / "3", TEXT_ONLY + bumped("1.1.0", "1.1.1")), 3)
    assert check(patch, archive) == {"against": "m-2", "class": "patch", "changes": []}
    assert publish.publish(patch, archive, ROLES)["id"] == "m-3"
    assert publish.newest_main(archive, "minimal")["id"] == "m-3"


def test_a_removed_or_renamed_public_slot_is_refused_with_r033(tmp_path):
    folder = with_facts(tmp_path / "stable", "1.0.0")
    assert publish.publish(epoch_of(folder, 1), store.FileStore(tmp_path / "archive"), ROLES)["id"] == "m-1"
    got = {}
    for name, edits in (("remove", REMOVE_SIZE), ("rename", RENAME_SIZE)):
        archive = store.FileStore(shutil.copytree(tmp_path / "archive", tmp_path / f"{name}-archive"))
        written = archive.list("minimal/")
        reason = refusal(epoch_of(edited(folder, tmp_path / name, edits), 2), archive)
        got[name] = {"R033": reason is not None and "R033" in reason,
                     "names the slot": reason is not None and "alpha.size" in reason,
                     "nothing written": archive.list("minimal/") == written,
                     "newest main": publish.newest_main(archive, "minimal")["id"]}
    expected = {"R033": True, "names the slot": True, "nothing written": True, "newest main": "m-1"}
    assert got == {"remove": expected, "rename": expected}

    # The same removal on a pack in initial development publishes: its earlier publication promised nothing.
    folder = with_facts(tmp_path / "development", "0.1.0")
    archive = store.FileStore(tmp_path / "development-archive")
    assert publish.publish(epoch_of(folder, 1), archive, ROLES)["id"] == "m-1"
    assert refusal(epoch_of(edited(folder, tmp_path / "development-remove", REMOVE_SIZE), 2), archive) is None
    assert publish.newest_main(archive, "minimal")["id"] == "m-2"


def test_a_pack_version_that_moves_less_than_the_class_is_refused(tmp_path):
    folder = with_facts(tmp_path / "stable", "1.0.0")
    assert publish.publish(epoch_of(folder, 1), store.FileStore(tmp_path / "archive"), ROLES)["id"] == "m-1"
    for name, edits, version in (("minor", ADD_COLOUR, "1.1.0"), ("patch", TEXT_ONLY, "1.0.1")):
        archive = store.FileStore(shutil.copytree(tmp_path / "archive", tmp_path / f"{name}-archive"))
        written = archive.list("minimal/")
        reason = refusal(epoch_of(edited(folder, tmp_path / f"{name}-kept", edits), 2), archive)
        # Held here, before the same change is published with a moved version into this archive.
        assert reason is not None and name in reason and "1.0.0" in reason, (name, reason)
        assert archive.list("minimal/") == written, name
        moved = edited(folder, tmp_path / f"{name}-moved", edits + bumped("1.0.0", version))
        assert publish.publish(epoch_of(moved, 2), archive, ROLES)["id"] == "m-2", name


def test_adding_explicit_enum_openness_when_before_lacks_it_is_not_major(tmp_path):
    compare = surface_compare()
    base = bundle_of(edited(FIXTURE, tmp_path / "base", []))
    open_before = opened(base)
    enum_id = base["enums"][0]["id"]

    # Earlier bundle carries openness only on the slot (no explicit `world`/`open` on the enum).
    # A newer compiler starting to write explicit `world: "open"` or `open: true` must not report a major `opened`.
    for field, value in (("world", "open"), ("open", True)):
        after_same = copy.deepcopy(open_before)
        after_same["enums"][0][field] = value
        assert compare(open_before, after_same) == {"class": "patch", "changes": []}, (field, value)

        new_val = f"{enum_id}.middle"
        after_added = with_value(after_same, new_val)
        result = compare(open_before, after_added)
        assert result["class"] == "minor", (field, result)
        assert (new_val, "added", "minor") in triples(result)
        assert (enum_id, "opened", "major") not in triples(result)

    # Even without any slot referencing the enum, an explicit `world`/`open` absent from `before` is not compared.
    unreferenced = copy.deepcopy(base)
    unreferenced["attributes"] = [a for a in unreferenced["attributes"] if a["id"] != "beta.state"]
    for field, value in (("world", "open"), ("open", True)):
        after_unreferenced = copy.deepcopy(unreferenced)
        after_unreferenced["enums"][0][field] = value
        assert compare(unreferenced, after_unreferenced) == {"class": "patch", "changes": []}, (field, value)

    # When `before` DOES carry explicit openness, real changes and dropped open flags stay major.
    explicit_closed = copy.deepcopy(unreferenced)
    explicit_closed["enums"][0]["world"] = "closed"
    explicit_open = copy.deepcopy(unreferenced)
    explicit_open["enums"][0]["world"] = "open"

    opened_res = compare(explicit_closed, explicit_open)
    assert opened_res["class"] == "major"
    assert (enum_id, "opened", "major") in triples(opened_res)

    closed_res = compare(explicit_open, explicit_closed)
    assert closed_res["class"] == "major"
    assert (enum_id, "closed", "major") in triples(closed_res)

    dropped_res = compare(explicit_open, unreferenced)
    assert dropped_res["class"] == "major"
    assert (enum_id, "closed", "major") in triples(dropped_res)


def test_private_slots_do_not_affect_public_enum_openness(tmp_path):
    compare = surface_compare()
    base = bundle_of(edited(FIXTURE, tmp_path / "base", []))
    enum_id = base["enums"][0]["id"]
    new_val = f"{enum_id}.middle"
    [state_slot] = [a for a in base["attributes"] if a["id"] == "beta.state"]

    # 1. A private closed slot referencing a public open enum must not make the enum appear closed.
    open_with_private_closed = opened(base)
    private_closed = copy.deepcopy(state_slot)
    private_closed["id"] = "beta.internal_state"
    private_closed["stable_id"] = state_slot["stable_id"] + "_private"
    private_closed["name"] = "internal_state"
    private_closed["table"] = "beta__internal_state"
    private_closed["private"] = True
    private_closed["semantic"].pop("open", None)
    open_with_private_closed["attributes"].append(private_closed)

    result_open = compare(open_with_private_closed, with_value(open_with_private_closed, new_val))
    assert result_open["class"] == "minor", result_open
    assert (new_val, "added", "minor") in triples(result_open)

    # 2. A private open slot must not make an enum without public open slots appear open.
    closed_with_private_open = copy.deepcopy(base)
    closed_with_private_open["attributes"] = [
        a for a in closed_with_private_open["attributes"] if a["id"] != "beta.state"
    ]
    private_open = copy.deepcopy(private_closed)
    private_open["semantic"]["open"] = True
    closed_with_private_open["attributes"].append(private_open)

    result_closed = compare(closed_with_private_open, with_value(closed_with_private_open, new_val))
    assert result_closed["class"] == "major", result_closed
    assert (new_val, "added", "major") in triples(result_closed)
