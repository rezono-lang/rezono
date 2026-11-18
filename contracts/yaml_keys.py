"""Keys that YAML made out of text: the contracts' lint before LinkML's (contracts/check.py runs it).

An unquoted value in a flow map ends at its first comma, and what follows becomes a key of its own:
`fanout: {range: integer, description: Children per page, at most.}` loads as the key `description` with the value
`Children per page` and a key `at most.` with no value. LinkML refused the schema only in `ci` / `contracts`, and
the error escaped earlier checks. Two rules, on the composed YAML, so on what the file means rather
than how it is written:
  - a key that holds whitespace and a period is a sentence, never a slot, class or enum name;
  - an entry of a flow map with no value at all (`{a: b, rest of a sentence}`) is text cut at a comma;
  - a key that is a list or a map (`{description: see, [x]}`) is never a name either.
Quote such a value: `description: "Children per page, at most."`.

  python contracts/yaml_keys.py [<file>...]   (default: every contracts/**/*.yaml); exit 1 on a finding.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

NULL = "tag:yaml.org,2002:null"


def findings(text: str, name: str = "<text>") -> list[str]:
    """`<name>:<line>: <what>` for every key in <text> that YAML made out of text."""
    out: list[str] = []

    def walk(node: yaml.Node) -> None:
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if not isinstance(key, yaml.ScalarNode):
                    out.append(f"{name}:{key.start_mark.line + 1}: a key that is a list or a map; quote the value it "
                               "came from")
                else:
                    at = f"{name}:{key.start_mark.line + 1}"
                    if "." in key.value and any(c.isspace() for c in key.value):
                        out.append(f"{at}: the key {key.value!r} is text, not a name; quote the value it came from")
                    elif node.flow_style and isinstance(value, yaml.ScalarNode) and value.tag == NULL and not value.value:
                        out.append(f"{at}: the flow map entry {key.value!r} has no value; quote the text before it if "
                                   "it holds a comma")
                walk(key)
                walk(value)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                walk(item)

    try:
        for doc in yaml.compose_all(text, Loader=yaml.SafeLoader):
            if doc is not None:
                walk(doc)
    except yaml.YAMLError as e:
        out.append(f"{name}: not YAML ({str(e).splitlines()[0]})")
    return out


def main(argv: list[str]) -> int:
    files = [Path(a) for a in argv] or sorted(Path(__file__).resolve().parent.rglob("*.yaml"))
    found = [f for p in files for f in findings(p.read_text(encoding="utf-8"), p.as_posix())]
    for f in found:
        print(f"FAIL  {f}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
