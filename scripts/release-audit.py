"""Audit the bytes delivered by each registry, including generated metadata."""
import json
import re
import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

from leak_check import BUDGET, counts, read_budget

GPL = re.compile(rb"\b(?:[AL]?GPL(?:[- ]?v?\d+(?:\.\d+)*)?|GNU (?:Affero |Lesser )?General Public Licen[cs]e)\b", re.I)


def members(path):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                yield name, archive.read(name)
    else:
        with tarfile.open(path, "r:gz") as archive:
            for member in archive:
                if not member.isfile():
                    raise ValueError(f"Unexpected archive member type in {path.name}")
                yield member.name, archive.extractfile(member).read()


def main(directory):
    budget = read_budget(Path(BUDGET).read_bytes())
    for path in sorted(directory.iterdir()):
        seen = set()
        total = Counter()
        for name, data in members(path):
            if name in seen or name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("Invalid archive path")
            seen.add(name)
            observed = counts(name.encode() + b"\n" + data)
            source = name.removeprefix("rezono_runtime/")
            allowed = {}
            if source != name and source in budget and data == Path(source).read_bytes():
                allowed = budget[source]
            if observed != allowed:
                raise ValueError(f"Unexpected disclosure counts in {path.name}: {observed}")
            if GPL.search(name.encode() + b"\n" + data):
                raise ValueError(f"GPL indicator in {path.name}: {name}")
            total.update(observed)
        print(f"{path.name}: {path.stat().st_size} bytes; {len(seen)} members; "
              f"disclosure counts {json.dumps(dict(total), sort_keys=True)}; GPL indicators 0")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
