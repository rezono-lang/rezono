"""pytest plugin: the memory each test takes, so growth shows in the log before a runner dies (`-p memory_report`).

A runner capped at 8 GiB that runs out of memory is killed with its pod: the job says only that the runner lost
communication, and no log or report is kept (nightly `compiler`, 15-11-2026). This plugin samples the resident
memory of the test process while each test runs and ends the session with the tests that took the most: the peak
during the test and what the test left behind. With REZONO_MEMORY_LIMIT_GIB set, a process that crosses the limit
prints an ERROR line naming the running test and that table, and exits with code 3, before the kernel or the
pool kills it.

It reports and stops; it never shrinks a test. Linux reads the resident set from /proc, Windows the working set,
its equal; elsewhere the plugin stays silent. Not Windows's private bytes: they count memory that is committed
but never touched, which a cap on a pod does not count. DuckDB commits gigabytes for a check view over hundreds of
tables and touches a few hundred MiB of it (an example pack, 16-11-2026), so private bytes showed a 7 GiB peak that
Linux does not have.
"""
from __future__ import annotations

import os
import sys
import threading
import time

MIB = 1024 * 1024
SHOWN = 15  # tests in the summary
EXIT = 3  # the exit code of a process stopped at the limit
# The process's own standard error, kept before pytest captures it: `-p` imports this module before capturing
# starts, and what a running test writes to stderr is lost when the process stops.
STDERR = os.dup(2)


def resident() -> int | None:
    """The bytes of this process in memory now: the resident set on Linux, the working set on Windows; None where
    neither is known."""
    if sys.platform.startswith("linux"):
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    if sys.platform == "win32":
        import ctypes
        import ctypes.wintypes as wt

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [
                (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                               "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                               "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

        c = Counters()
        c.cb = ctypes.sizeof(c)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(process), ctypes.byref(c), c.cb):
            return c.WorkingSetSize
    return None


def table(rows: list[tuple[str, int, int, float]], limit: int = SHOWN) -> list[str]:
    """The tests that took the most, highest peak first: (test, peak, left behind, seconds), in MiB."""
    out = [f"{'peak MiB':>9} {'left MiB':>9} {'seconds':>8}  test"]
    for test, peak, left, seconds in sorted(rows, key=lambda r: (-r[1], r[0]))[:limit]:
        out.append(f"{peak // MIB:>9} {left // MIB:>+9} {seconds:>8.1f}  {test}")
    return out


class Watch:
    def __init__(self, limit: int | None, interval: float = 0.25):
        self.limit, self.interval = limit, interval
        self.rows: list[tuple[str, int, int, float]] = []
        self.test, self.start, self.peak, self.t0 = "(collection)", 0, 0, time.monotonic()
        self.lock = threading.Lock()

    def sample(self) -> None:
        now = resident() or 0
        with self.lock:
            self.peak = max(self.peak, now)
            test = self.test
        if self.limit and now > self.limit:
            self.stop(test, now)

    def stop(self, test: str, now: int) -> None:
        with self.lock:
            rows = self.rows + [(test, now, now - self.start, time.monotonic() - self.t0)]
        # pytest's form of an error, so the nightly issue names the test (scripts/ci-tier.py, failing_cases).
        lines = [f"ERROR {test} - memory_report: {now // MIB} MiB is over REZONO_MEMORY_LIMIT_GIB "
                 f"({self.limit // MIB} MiB); the test process stops with exit code {EXIT}", *table(rows)]
        os.write(STDERR, ("\n".join(lines) + "\n").encode("utf-8"))
        os._exit(EXIT)

    def loop(self) -> None:
        while True:
            self.sample()
            time.sleep(self.interval)

    def begin(self, test: str) -> None:
        now = resident() or 0
        with self.lock:
            self.test, self.start, self.peak, self.t0 = test, now, now, time.monotonic()

    def end(self, test: str) -> None:
        now = resident() or 0
        with self.lock:
            self.rows.append((test, max(self.peak, now), now - self.start, time.monotonic() - self.t0))
            self.test = "(between tests)"


_watch: Watch | None = None


def pytest_configure(config) -> None:
    global _watch
    if resident() is None or _watch is not None:
        return
    gib = os.environ.get("REZONO_MEMORY_LIMIT_GIB")
    _watch = Watch(int(float(gib) * 1024 * MIB) if gib else None)
    threading.Thread(target=_watch.loop, daemon=True, name="memory_report").start()


def pytest_runtest_logstart(nodeid, location) -> None:
    if _watch:
        _watch.begin(nodeid)


def pytest_runtest_logfinish(nodeid, location) -> None:
    if _watch:
        _watch.end(nodeid)


def pytest_terminal_summary(terminalreporter) -> None:
    if not _watch or not _watch.rows:
        return
    terminalreporter.section("memory per test")
    peak = max(r[1] for r in _watch.rows)
    terminalreporter.write_line(f"highest peak {peak // MIB} MiB over {len(_watch.rows)} tests")
    for line in table(_watch.rows):
        terminalreporter.write_line(line)
