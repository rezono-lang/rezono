"""Regression cases for the policy, using inert bytes without executing proposed changes."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from red_guard import allowed


def main():
    reason = b'pytest.mark.xfail(strict=True, reason="pending")'
    updated = reason.replace(b"pending", b"documented")
    function = b"@" + reason + b"\ndef test_count():\n    assert count() == 2\n"
    cases = [
        ("changed test expectation", "tests/test_count.py", function, function.replace(b"== 2", b"== 3"), False),
        ("changed recorded outcome", "examples/demo/expected/rows.json", b"[2]", b"[3]", False),
        ("removed policy workflow", ".github/workflows/red-policy.yml", b"policy", None, False),
        ("changed status publisher", "scripts/red_status.py", b"report", b"other", False),
        ("changed shared fixture", "contracts/fixtures/data.json", b"{}", b"[]", False),
        ("changed test helper", "tests/support.py", b"value = 2\n", b"value = 3\n", False),
        ("changed test setup", "demo/conftest.py", b"value = 2\n", b"value = 3\n", False),
        ("removed function mark", "tests/test_count.py", function, function.split(b"\n", 1)[1], True),
        ("explained function mark", "tests/test_count.py", function, function.replace(reason, updated), True),
    ]
    cls = b"@" + reason + b"\nclass TestCount:\n    pass\n"
    module = b"pytestmark = " + reason + b"\n" + b"def test_count(): pass\n"
    for name, source in (("class", cls), ("module", module)):
        cases.extend([
            (f"explained {name} mark", "demo/test_counts.py", source, source.replace(reason, updated), True),
            (f"removed {name} mark", "demo/test_counts.py", source, source.split(b"\n", 1)[1], True),
            (f"added {name} mark", "demo/test_counts.py", source.split(b"\n", 1)[1], source, False),
        ])
    param = b"values = [pytest.param(True, marks=" + reason + b")]\n"
    cases.append(("removed parameter mark", "demo/test_counts.py", param, b"values = [pytest.param(True)]\n", True))
    for label, path, before, after, expected in cases:
        actual = allowed(path, before, after)
        if actual != expected:
            raise AssertionError(f"{label}: expected {expected}, got {actual}")
        print(f"{'ALLOW' if actual else 'DENY'} without planner: {label}")


if __name__ == "__main__":
    main()
