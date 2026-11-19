"""Read module sources with the native reader, for tests that compare its form or refusal with a decision."""

import json
from pathlib import Path
import subprocess


def read_modules(*sources):
    """Return, per source, the module the reader produced (or None) and its diagnostics as code and span."""
    probe = Path(__file__).with_name("read-modules.mts")
    result = subprocess.run(["node", str(probe), json.dumps(list(sources))],
                            capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    read = json.loads(result.stdout)
    assert isinstance(read, list) and len(read) == len(sources)
    return read


def at(source, text, after=""):
    """The reader's span of the first `text` that follows `after` in `source`."""
    start = source.index(after) + len(after) if after else 0
    start = source.index(text, start)
    return {"text": text, "start": start, "end": start + len(text)}
