"""The world of a kind without a world line, by language version, and the guard on observed kinds
(decisions/language-rezono-1-defaults.md, sections 1 and 2). The module forms are written by hand from that decision:
a kind without a `world` member is a kind whose text has no world line, because the reader never writes the default.
The expected worlds are read from the lowered LinkML schema, as test_lower_open_world.py reads them."""

import json

import pytest
from rezono_compiler import rezono_module


def kind(name, *slots, **properties):
    return {"kind": name, "slots": list(slots), "derived": [], **properties}


def slot(name, type_name, **properties):
    return {"slot": name, "type": type_name, **properties}


def world(definition):
    return (definition.get("annotations") or {}).get("world", "closed")


def lowered(directory, decls, *, version, layer="facts"):
    """Lower one hand-written module form registered in `layer`; return its classes and the compiler's refusals."""
    form = {
        "format": "rezono.module/5" if version == "1" else "rezono.module/2", "spans": [],
        "module": {"rezono": version, "pack": "sample", "use": [], "decls": list(decls)},
    }
    entry = rezono_module.Declared("rezono/part.rezono", "rezono/part.json", layer)
    errors = []
    result = rezono_module.lower(directory, entry, form, "sample", {}, errors)
    classes = (result.schema.get("classes") or {}) if result is not None else {}
    return classes, errors


def test_rezono_0_kind_without_world_stays_open(tmp_path):
    # Harness check: a rezono 0 kind that writes `world closed` lowers closed, as it does today.
    classes, errors = lowered(tmp_path / "written", [kind("Zone", slot("name", "Text"), world="closed")], version="0")
    assert not errors and world(classes["Zone"]) == "closed", errors
    # Without a world line a rezono 0 kind is open (docs/rezono/v0.md section 5): the compiler refuses it as open
    # or lowers it open, and never lowers it as closed.
    classes, errors = lowered(tmp_path / "left-out", [kind("Zone", slot("name", "Text"))], version="0")
    assert ("Zone" not in classes and errors) or world(classes["Zone"]) == "open", (classes, errors)


class MissingRezono1WorldDefault(AssertionError):
    """A rezono 1 kind without a world line did not lower as closed, or a written default lowered differently."""


def test_rezono_1_kind_without_world_lowers_closed(tmp_path):
    decls = [
        kind("Zone", slot("name", "Text")),
        kind("Team", slot("name", "Text"), world="open"),
        kind("Item", slot("name", "Text"), slot("note", "Text", world="open")),
    ]
    classes, errors = lowered(tmp_path / "left-out", decls, version="1")
    problems = []
    if errors or set(classes) != {"Zone", "Team", "Item"}:
        problems.append({"errors": errors, "classes": sorted(classes)})
    else:
        want = {"Zone": "closed", "Team": "open", "Item": "closed"}
        got = {name: world(classes[name]) for name in want}
        if got != want:
            problems.append({"kind worlds": got, "want": want})
        attributes = classes["Item"].get("attributes") or {}
        slots = {name: world(attributes.get(name) or {}) for name in ("name", "note")}
        if slots != {"name": "closed", "note": "open"}:
            problems.append({"slot worlds of Item": slots, "want": {"name": "closed", "note": "open"}})
        written, written_errors = lowered(
            tmp_path / "written", [kind("Zone", slot("name", "Text"), world="closed")], version="1")
        if written_errors or written.get("Zone") != classes["Zone"]:
            problems.append({"with world closed": written.get("Zone"), "errors": written_errors,
                             "without": classes["Zone"]})
    if problems:
        raise MissingRezono1WorldDefault(json.dumps(problems, indent=2, default=str))


class MissingObservationGuard(AssertionError):
    """An observed rezono 1 kind without `world open` was not refused with R051, or another kind was refused."""


def test_rezono_1_observed_kind_needs_open_world(tmp_path):
    decls = [
        kind("Reading", slot("value", "Text")),
        kind("Export", slot("value", "Text"), world="closed"),
        kind("Probe", slot("value", "Text"), world="open"),
    ]
    _, errors = lowered(tmp_path / "observed", decls, version="1", layer="observation")
    refused = sorted(name for name in ("Reading", "Export", "Probe")
                     if any("R051" in error and name in error for error in errors))
    problems = []
    if refused != ["Export", "Reading"]:
        problems.append({"refused with R051": refused, "want": ["Export", "Reading"], "errors": errors})
    # Counter-case: the same kind in a module of the facts layer is closed by default and is not refused.
    classes, errors = lowered(tmp_path / "facts", decls[:1], version="1", layer="facts")
    if errors or "Reading" not in classes or world(classes["Reading"]) != "closed":
        problems.append({"facts layer": classes.get("Reading"), "errors": errors})
    if problems:
        raise MissingObservationGuard(json.dumps(problems, indent=2, default=str))
