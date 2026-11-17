"""The compiler's SchemaView keeps its memo on the instance: the answers are LinkML's, the memory goes with the view.

linkml-runtime memoizes SchemaView methods on the class, keyed on the instance, so every view ever made stayed
alive; the nightly `compiler` run grew some 30 MiB per generated pack and lost its runner (15-11-2026).
"""
from __future__ import annotations

import gc
import os
import pickle
import subprocess
import sys
import weakref
from pathlib import Path

import pytest
from linkml_runtime import SchemaView as LinkMLView
from linkml_runtime.linkml_model import ClassDefinition

import memory_report
from rezono_compiler import pack
from rezono_compiler.schemaview import _MEMOIZED, SchemaView
from support import FIXTURE

SCHEMA = FIXTURE / "schema" / "minimal.yaml"


def class_cache() -> dict[str, int]:
    return {name: getattr(LinkMLView, name).cache_info().currsize for name in _MEMOIZED}


def test_every_memoized_method_of_linkml_is_kept_on_the_instance():
    assert len(_MEMOIZED) > 50, "linkml-runtime memoizes SchemaView's lookups; the subclass must find them"
    sv = SchemaView(str(SCHEMA))
    assert set(_MEMOIZED) <= set(vars(sv))


def test_reading_a_pack_leaves_nothing_in_linkml_s_class_cache():
    before = class_cache()
    pack.read(FIXTURE)
    assert class_cache() == before


def test_a_view_and_its_memo_are_freed_with_it():
    sv = SchemaView(str(SCHEMA))
    for c in sv.all_classes():
        for s in sv.class_induced_slots(c):
            sv.induced_slot(s.name, c)
    gone = weakref.ref(sv)
    del sv
    gc.collect()
    assert gone() is None


def test_the_answers_are_linkml_s():
    ours, theirs = SchemaView(str(SCHEMA)), LinkMLView(str(SCHEMA))
    assert list(ours.all_classes()) == list(theirs.all_classes())
    assert list(ours.all_enums()) == list(theirs.all_enums())
    for c in theirs.all_classes():
        assert [s.name for s in ours.class_induced_slots(c)] == [s.name for s in theirs.class_induced_slots(c)]
        for s in theirs.class_induced_slots(c):
            assert ours.induced_slot(s.name, c) == theirs.induced_slot(s.name, c)


def test_a_change_to_the_schema_is_seen():
    sv = SchemaView(str(SCHEMA))
    assert "Added" not in sv.all_classes()
    sv.add_class(ClassDefinition("Added"))
    assert "Added" in sv.all_classes()


def test_a_view_survives_pickling_with_a_memo_of_its_own():
    sv = SchemaView(str(SCHEMA))
    names = list(sv.all_classes())
    copy = pickle.loads(pickle.dumps(sv))
    assert list(copy.all_classes()) == names
    assert copy.all_classes is not sv.all_classes


@pytest.mark.skipif(memory_report.resident() is None, reason="no memory reading on this platform")
def test_memory_report_stops_a_process_over_the_limit_and_names_the_test(tmp_path):
    """The nightly issue names the test (scripts/ci-tier.py reads pytest's ERROR lines)."""
    # The test lowers the limit to 64 MiB above what the process holds, then takes 128 MiB.
    (tmp_path / "test_grow.py").write_text(
        "import time\nimport memory_report as m\n\n"
        "def test_grow():\n"
        "    m._watch.limit = m.resident() + 64 * m.MIB\n"
        "    held = bytearray(128 * m.MIB)\n"
        "    time.sleep(5)\n")
    env = {**os.environ, "REZONO_MEMORY_LIMIT_GIB": "1000",
           "PYTHONPATH": os.pathsep.join([str(Path(memory_report.__file__).parent), os.environ.get("PYTHONPATH", "")])}
    done = subprocess.run([sys.executable, "-m", "pytest", "-p", "memory_report", "-p", "no:cacheprovider", "-q",
                           "test_grow.py"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    assert done.returncode == memory_report.EXIT, done.stdout + done.stderr
    assert "ERROR test_grow.py::test_grow - memory_report: " in done.stderr


def test_memory_report_lists_the_highest_peaks_first():
    mib = memory_report.MIB
    rows = [("a", 5 * mib, -mib, 1.0), ("b", 9 * mib, 2 * mib, 0.5), ("c", 9 * mib, 0, 0.1)]
    lines = memory_report.table(rows, limit=2)
    assert [line.split()[-1] for line in lines[1:]] == ["b", "c"]
    assert lines[1].split()[:2] == ["9", "+2"]
