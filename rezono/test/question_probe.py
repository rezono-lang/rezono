"""Read question sources with the native reader, for tests that compare its tree or refusal with a decision."""

import json
from pathlib import Path
import subprocess


def read_questions(*sources):
    """Return, per source, the question tree the reader produced (or None), the text the printer writes back for
    it, and its diagnostics as code and span."""
    probe = Path(__file__).with_name("read-questions.mts")
    result = subprocess.run(["node", str(probe), json.dumps(list(sources))],
                            capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    read = json.loads(result.stdout)
    assert isinstance(read, list) and len(read) == len(sources)
    return read
