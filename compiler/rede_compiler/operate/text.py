# --- Text edits ----------------------------------------------------------------------------------------------

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .spec import PLAIN, OperationError


class Edits:
    """Replacements of character spans, per file; applied from the end so spans stay valid."""

    def __init__(self):
        self.by_file: dict[str, dict[tuple[int, int], tuple[str, bool]]] = {}

    def add(self, rel: str, start: int, end: int, new: str, block: bool = False):
        spans = self.by_file.setdefault(rel, {})
        if start == end and (start, end) in spans and not block:  # insertions at one point keep their order
            spans[(start, end)] = (spans[(start, end)][0] + new, False)
            return
        if spans.get((start, end), (new, block)) != (new, block):
            raise OperationError(f"{rel}: two different edits at {start}")
        spans[(start, end)] = (new, block)

    def node(self, rel: str, node, new: str):
        """Replace a scalar node. A block scalar's span ends after its line breaks; those stay."""
        self.add(rel, node.start_mark.index, node.end_mark.index, new, getattr(node, "style", None) in ("|", ">"))

    def apply(self, rel: str, text: str) -> str:
        """Apply the edits of one file. An edit inside a span that another edit replaces is moot (a renamed key
        in a record that goes); an insertion at either end of such a span stays."""
        spans = sorted(self.by_file.get(rel, {}).items(), key=lambda kv: (kv[0][0], -kv[0][1]))
        kept, outer = [], None
        for (start, end), v in spans:
            if outer and outer[0] <= start and end <= outer[1] and (start, end) != outer \
                    and not (start == end and start in outer):
                continue
            kept.append(((start, end), v))
            if end > start and (outer is None or end > outer[1]):
                outer = (start, end)
        spans = sorted(kept, reverse=True)
        last = len(text) + 1
        for (start, end), (new, block) in spans:
            if end > last:
                raise OperationError(f"{rel}: overlapping edits at {start}")
            if block:
                old = text[start:end]
                new += old[len(old.rstrip("\r\n")):]
            text, last = text[:start] + new + text[end:], start
        return text


def read_text(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def compose(text: str, where: str):
    try:
        return yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as e:
        raise OperationError(f"{where}: {e}") from e


def pairs(node):
    return node.value if isinstance(node, yaml.MappingNode) else []


def get(node, key: str):
    return next((v for k, v in pairs(node) if isinstance(k, yaml.ScalarNode) and k.value == key), None)


def scalars(node):
    if isinstance(node, yaml.ScalarNode):
        yield node
    elif isinstance(node, yaml.SequenceNode):
        for n in node.value:
            yield from scalars(n)


def walk(node, skip=("annotations",)):
    """Every (key, value) pair of every mapping below `node`, except under the keys in `skip`."""
    if isinstance(node, yaml.MappingNode):
        for k, v in node.value:
            yield k, v
            if not (isinstance(k, yaml.ScalarNode) and k.value in skip):
                yield from walk(v, skip)
    elif isinstance(node, yaml.SequenceNode):
        for v in node.value:
            yield from walk(v, skip)


def scalar(value, node=None) -> str:
    """A scalar in YAML, in the style of the node it replaces when that still reads back the same."""
    text = str(value)
    style = getattr(node, "style", None)
    if style == '"' or (style is None and "\n" in text):
        return json.dumps(text, ensure_ascii=False)
    if style != "'" and PLAIN.match(text) and yaml.safe_load(text) == value:
        return text
    return "'" + text.replace("'", "''") + "'"


# --- Deleting YAML text: a pair of a mapping, items of a sequence ----------------------------------------------

def line_start(text: str, i: int) -> int:
    return text.rfind("\n", 0, i) + 1


def line_end(text: str, i: int) -> int:
    """The index after the line break of the line that holds index i (or the end of the text)."""
    j = text.find("\n", i)
    return len(text) if j < 0 else j + 1


def empty(node) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.value == "" and node.style is None


def content_end(text: str, node) -> int:
    """Where the text of a node ends: its last character, not the line breaks or the next token after it."""
    if isinstance(node, yaml.ScalarNode):
        end = node.end_mark.index
        if node.style in ("|", ">"):
            while end > node.start_mark.index and text[end - 1] in "\r\n":
                end -= 1
        return end
    if node.flow_style or not node.value:
        return node.end_mark.index
    if isinstance(node, yaml.MappingNode):
        k, v = node.value[-1]
        return content_end(text, k) if empty(v) else content_end(text, v)
    return content_end(text, node.value[-1])


def pair_end(text: str, k, v) -> int:
    return content_end(text, k) if empty(v) else content_end(text, v)


def delete_pair(rel: str, text: str, mapping, key, edits: Edits):
    """Remove one pair from a mapping, with the rest of its last line (a comment). Block style removes its
    whole lines; after a list item's dash it removes up to the next key."""
    i = next(n for n, (k, _) in enumerate(mapping.value) if k is key)
    k, v = mapping.value[i]
    nxt = mapping.value[i + 1][0] if i + 1 < len(mapping.value) else None
    if mapping.flow_style:
        if nxt is not None:
            edits.add(rel, k.start_mark.index, nxt.start_mark.index, "")
        elif i > 0:
            edits.add(rel, pair_end(text, *mapping.value[i - 1]), pair_end(text, k, v), "")
        else:
            edits.add(rel, k.start_mark.index, pair_end(text, k, v), "")
        return
    start = line_start(text, k.start_mark.index)
    if not text[start:k.start_mark.index].strip():
        edits.add(rel, start, line_end(text, pair_end(text, k, v)), "")
    elif nxt is not None:
        edits.add(rel, k.start_mark.index, nxt.start_mark.index, "")
    else:  # the only entry of a list item: the item stays, as an empty record
        edits.add(rel, k.start_mark.index, pair_end(text, k, v), "{}")


def comment_start(text: str, seq, i: int, after: int) -> int:
    """Where item i of a block sequence starts with the comment lines directly above it, which belong to it;
    `after` is where the sequence's own line ends (for the first item)."""
    floor = line_end(text, content_end(text, seq.value[i - 1])) if i > 0 else after
    s = line_start(text, seq.value[i].start_mark.index)
    while s > floor:
        prev = line_start(text, s - 1)
        if prev < floor or not text[prev:s].lstrip().startswith("#"):
            break
        s = prev
    return s


def delete_items(rel: str, text: str, parent, key: str, items: list, edits: Edits, comments: bool = False):
    """Remove items from the sequence under `key` of mapping `parent`; when all go, the value becomes [].
    With `comments`, the comment lines directly above an item go with it."""
    seq = get(parent, key)
    if not items:
        return
    if len(items) == len(seq.value):
        k = next(k for k, v in pairs(parent) if v is seq)
        colon = text.index(":", k.end_mark.index)
        end = seq.end_mark.index
        if not seq.flow_style:  # up to the line break after the last item, which stays
            j = text.find("\n", content_end(text, seq))
            end = len(text) if j < 0 else j
        edits.add(rel, colon + 1, end, " []")
        return
    for item in items:
        i = next(n for n, x in enumerate(seq.value) if x is item)
        if seq.flow_style:
            if i + 1 < len(seq.value):
                edits.add(rel, item.start_mark.index, seq.value[i + 1].start_mark.index, "")
            else:
                edits.add(rel, content_end(text, seq.value[i - 1]), content_end(text, item), "")
            continue
        start = line_start(text, item.start_mark.index)
        if text[start:item.start_mark.index].strip() != "-":
            raise OperationError(f"{rel}:{item.start_mark.line + 1}: a list item that does not start its line")
        if comments:
            k = next(k for k, v in pairs(parent) if v is seq)
            start = comment_start(text, seq, i, line_end(text, k.end_mark.index))
        edits.add(rel, start, line_end(text, content_end(text, item)), "")
