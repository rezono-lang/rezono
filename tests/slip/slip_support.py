"""Shared helpers for the tests of the slip (decisions/viewer-slip.md).

They publish the fixture `tests/fixtures/slip` with the publisher, ask the local reader of `edge/gate` in
process through `reader.mjs`, and draw the page through `viewer/slip/bin/render.ts`. Nothing here names an
example pack.
"""

from __future__ import annotations

import json
import os
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "slip"
PACK = "slip"
ROLES = {"checker": "complete", "reader": "may_read", "summary": "may_read"}
READER = Path(__file__).with_name("reader.mjs")
PAGE = ROOT / "viewer" / "slip"
RENDER = PAGE / "bin" / "render.ts"
FILL = ROOT / "viewer" / "messages" / "src" / "fill.ts"
KNOWLEDGE_TIME = "2026-01-01T00:00:00Z"


class MissingSlipPage(FileNotFoundError):
    """viewer/slip/bin/render.ts, the test entry of the page (decisions/viewer-slip.md), is not there."""


class MissingMessageFiller(FileNotFoundError):
    """viewer/messages/src/fill.ts (decisions/viewer-slip.md, "Filling a message") is not there."""


def node() -> str:
    return os.environ.get("REZONO_NODE", "node")


def key_text(*parts: str) -> str:
    return json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)


def row_query(relation: str, *key: str) -> str:
    return f"relation={quote(relation)}&key={quote(key_text(*key))}"


# Publishing


def publish_main(directory: Path, change=None) -> tuple[Path, dict]:
    """Publish the fixture, after `change(pack_dir)` if given, as epoch 1 into `directory/store`."""
    from rezono_compiler import modules
    from rezono_publisher import batch, publish, store

    pack = modules.copy_closure(FIXTURE, directory / "closure")
    if change:
        change(pack)
    epoch = batch.epoch(pack, epoch=1, knowledge_time=KNOWLEDGE_TIME, sources=[("rules", "test")])
    target = directory / "store"
    manifest = publish.publish(epoch, store.FileStore(target), ROLES)
    return target, manifest


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", "-c", "core.autocrlf=false", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(repo: Path, message: str) -> None:
    (repo / "log.txt").write_text(message, encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("-c", "user.name=Seed", "-c", "user.email=seed@example.org", "commit", "-q", "-m", message, cwd=repo)


def publish_sweeps(directory: Path, change=None) -> tuple[Path, dict, list[tuple[str, str]]]:
    """Publish the fixture as main from a two-commit repository, then every variant of its sweeps.

    Returns the store directory, the main manifest and what `sweep.run` did per variant."""
    from rezono_compiler import modules
    from rezono_publisher import batch, publish, store, sweep

    repo = directory / "repo"
    pack = modules.copy_closure(FIXTURE, repo)
    if change:
        change(pack)
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "core.autocrlf", "false", cwd=repo)
    _commit(repo, "seed")
    _commit(repo, "base")
    base = _git("rev-parse", "HEAD", cwd=repo)
    n, time = sweep.base_of(repo, base)
    target = directory / "store"
    st = store.FileStore(target)
    epoch = batch.epoch(pack, epoch=n, knowledge_time=time, sources=[("rules", base)])
    manifest = publish.publish(epoch, st, ROLES)
    done = sweep.run(repo, pack.relative_to(repo).as_posix(), base, st, ROLES)
    return target, manifest, done


def add_sweep(pack: Path, name: str, key: str, slot: str = "amount") -> None:
    path = pack / "sweeps.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["sweeps"].append({"name": name, "kind": "item", "key": key, "slot": slot})
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8", newline="\n")


# The local reader


def ask(store_dir: Path, role: str, *requests: str) -> list[dict]:
    """[{status, body}] of the local reader for `role`, one per request path."""
    run = subprocess.run([node(), str(READER)], input=json.dumps({"store": store_dir.as_posix(), "role": role,
                                                                   "requests": list(requests)}),
                         capture_output=True, encoding="utf-8", timeout=120, cwd=ROOT)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# The message filler


def fill(cases: list[dict]) -> list[dict]:
    """Fill each case ({resources, lang, id, args}) with viewer/messages/src/fill.ts: [{text} | {error}]."""
    if not FILL.is_file():
        raise MissingMessageFiller(FILL.relative_to(ROOT).as_posix())
    driver = Path(__file__).with_name("fill.mjs")
    run = subprocess.run([node(), str(driver)], input=json.dumps(cases), capture_output=True, encoding="utf-8",
                         timeout=60, cwd=ROOT)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


# The page

_installed = False


def render(store_dir: Path, role: str, *, lang: str = "en", row: dict | None = None, keys: list[dict] | None = None,
           reader: Path | None = None, pack: str = PACK) -> dict:
    """The page drawn by viewer/slip/bin/render.ts for one request: {html, files, doc} (doc: the parsed body)."""
    global _installed
    if not RENDER.is_file():
        raise MissingSlipPage(RENDER.relative_to(ROOT).as_posix())
    if not _installed:
        npm = "npm.cmd" if os.name == "nt" else "npm"
        installed = subprocess.run([npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=PAGE,
                                   capture_output=True, encoding="utf-8", timeout=600)
        assert installed.returncode == 0, installed.stderr
        _installed = True
    request = {"store": store_dir.as_posix(), "role": role, "pack": pack, "lang": lang}
    if row is not None:
        request["row"] = row
    if keys:
        request["keys"] = keys
    if reader is not None:
        request["reader"] = reader.as_posix()
    run = subprocess.run([node(), str(RENDER)], input=json.dumps(request), capture_output=True, encoding="utf-8",
                         timeout=300, cwd=ROOT)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert set(result) == {"html", "files"}, sorted(result)
    result["doc"] = parse(result["html"])
    return result


class Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: Node | None):
        self.tag, self.attrs, self.parent = tag, attrs, parent
        self.children: list[Node | str] = []

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def all(self, tag: str | None = None, **attrs: str | bool) -> list[Node]:
        """Every descendant with `tag` and each attribute: True asks only that it is there."""
        found = []
        for child in self.children:
            if isinstance(child, str):
                continue
            if (tag is None or child.tag == tag) and all(
                    (name.replace("_", "-") in child.attrs) if value is True
                    else child.attrs.get(name.replace("_", "-")) == value for name, value in attrs.items()):
                found.append(child)
            found.extend(child.all(tag, **attrs))
        return found

    def one(self, tag: str | None = None, **attrs: str | bool) -> Node:
        found = self.all(tag, **attrs)
        assert len(found) == 1, f"{len(found)} of <{tag or '*'} {attrs}>"
        return found[0]

    def ancestor(self, tag: str) -> Node | None:
        at = self.parent
        while at is not None and at.tag != tag:
            at = at.parent
        return at


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#document", {}, None)
        self.at = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v if v is not None else "" for k, v in attrs}, self.at)
        self.at.children.append(node)
        if tag not in VOID:
            self.at = node

    def handle_startendtag(self, tag, attrs):
        self.at.children.append(Node(tag, {k: v if v is not None else "" for k, v in attrs}, self.at))

    def handle_endtag(self, tag):
        at = self.at
        while at is not None and at.tag != tag:
            at = at.parent
        if at is not None and at.parent is not None:
            self.at = at.parent

    def handle_data(self, data):
        self.at.children.append(data)


def parse(html: str) -> Node:
    tree = _Tree()
    tree.feed(html)
    tree.close()
    return tree.root


def lines(table: Node) -> list[Node]:
    return table.all("tr", data_line=True)


def line_ref(line: Node) -> tuple[str, list[str]]:
    return line.attrs["data-relation"], json.loads(line.attrs["data-key"])


def drop_variant(store_dir: Path, variant: str) -> None:
    """Take one published variant out of the store, so its stop is not computed."""
    gone = [p for p in store_dir.rglob(f"{variant}.json") if "manifests" in p.parts]
    assert gone, variant
    for path in gone:
        path.unlink()
