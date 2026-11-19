"""Count red tests per milestone mark from inert test sources, without running them."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import red_list

SOURCE = '''import pytest

REASON = "M1: computed elsewhere"


@pytest.mark.xfail(strict=True, reason="pending without a mark")
def test_unmarked():
    pass


@pytest.mark.xfail(strict=True, reason="M2: closes the loop")
def test_m2():
    pass


@pytest.mark.xfail(strict=True, reason="M2:missing space")
def test_mark_without_space():
    pass


@pytest.mark.xfail(strict=True, reason="m3: lower case")
def test_lower_case_mark():
    pass


@pytest.mark.xfail(strict=True, reason=REASON)
def test_reason_not_literal():
    pass


class TestLater:
    @pytest.mark.xfail(strict=True, reason="later: drawn views")
    def test_drawing(self):
        pass


@pytest.mark.parametrize("value", [
    pytest.param(1, id="extra", marks=pytest.mark.xfail(strict=True, reason="extra: nice to have")),
    pytest.param(2, id="unmarked", marks=pytest.mark.xfail(strict=True, reason="no mark here")),
])
def test_param(value):
    pass
'''


def collect(relpath, source=SOURCE):
    return red_list.extract_red_tests_from_source(source, relpath, ["demo", "other"])


class MilestoneCounts(unittest.TestCase):
    def test_mark_of_each_reason(self):
        marks = {item.id.split("--", 1)[1]: red_list.milestone_of(item.reason)
                 for item in collect("demo/tests/test_marks.py")}
        self.assertEqual(marks, {
            "test_unmarked": "none",
            "test_m2": "M2",
            "test_mark_without_space": "none",
            "test_lower_case_mark": "none",
            "test_reason_not_literal": "none",
            "TestLater--test_drawing": "later",
            "test_param--extra": "extra",
            "test_param--unmarked": "none",
        })

    def test_every_mark(self):
        for mark in ("M1", "M2", "M3", "M4", "extra", "later"):
            self.assertEqual(red_list.milestone_of(f"{mark}: reason"), mark)
        self.assertEqual(red_list.milestone_of(""), "none")

    def test_unmarked_test_counts_under_none(self):
        counts = red_list.milestone_counts(collect("demo/tests/test_marks.py"))
        self.assertEqual(counts, {"demo": {
            "M1": 0, "M2": 1, "M3": 0, "M4": 0, "extra": 1, "later": 1, "none": 5,
        }})

    def test_table_per_folder_with_totals(self):
        lone = '''import pytest

@pytest.mark.xfail(strict=True, reason="added without a mark")
def test_new():
    pass
'''
        items = collect("other/test_new.py", lone) + collect("demo/tests/test_marks.py")
        table = red_list.format_milestones(red_list.milestone_counts(items))
        self.assertEqual(table.splitlines(), [
            "| folder | M1 | M2 | M3 | M4 | extra | later | none | total |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            "| demo | 0 | 1 | 0 | 0 | 1 | 1 | 5 | 8 |",
            "| other | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |",
            "| total | 0 | 1 | 0 | 0 | 1 | 1 | 6 | 9 |",
        ])


if __name__ == "__main__":
    unittest.main()
