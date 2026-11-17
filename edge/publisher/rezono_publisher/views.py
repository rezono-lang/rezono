"""The published views of a main manifest (docs/gui.md, Work per request: O(page)).

  python -m rezono_publisher.views PACK MANIFEST [--profile p | --store url] [--relayout]

Per role of the manifest: the viewer's own layout code makes the views from the role's snapshots
(viewer/scripts/views.ts, plain Node, never in the Worker): the island levels, the Map of each island and each
Flow the pack binds (the sheet `flow.<id>`), starting from the role's layout in the newest earlier main
manifest that has one, unless --relayout. The checker checks each sheet against the role's rows the same way
(rezono_checker.views); a sheet whose binding does not hold on the role's rows fails that role's views. Only when every role's views are checked is anything written: the pieces, then per
role the view index `<pack>/<manifest>/<role>/views/index.json`, last. The manifest stays as it is.

Exit 0: written (or already there, the same bytes). Exit 2: a view shows more than its role reads, nothing
written. Exit 1: an error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from rezono_canon import canonical_bytes
from rezono_checker.proof import check_indexes, check_proof, check_rows, check_sources
from rezono_checker.views import Role, check_islands, check_page, check_view
from rezono_compiler import gap
from rezono_compiler import rules as ir

from . import proof, timing, view_build
from . import store as stores

ROOT = Path(__file__).resolve().parents[3]
ENTRY = ROOT / "viewer" / "scripts" / "views.ts"
FORMAT = "rezono.views/1"
ROWS = "rezono.rows-index/1"
GAP = "rezono.gap-index/1"
SOURCES = "rezono.sources-index/1"  # the role's source entries by row, for a page of an answer
MAIN = re.compile(r"^m-(\d+)$")


class Blocked(Exception):
    """A view shows something its role may not read, or is not what it says: nothing is written."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dumps(obj) -> bytes:
    """Sorted keys, no spaces: the same index gives the same bytes. Plain JSON, as the tiles (geometry)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def key_of(uri: str) -> str:
    return re.sub(r"^s3://[^/]+/", "", uri)


def index_key(pack: str, manifest: str, role: str) -> str:
    return f"{pack}/{manifest}/{role}/views/index.json"


def previous(st, pack: str, manifest: str, role: str):
    """The newest earlier main manifest with a view index for the role: (id, index bytes), or None."""
    n = int(MAIN.match(manifest).group(1))
    earlier = []
    for key in st.list(f"{pack}/manifests/"):
        m = MAIN.match(key.rsplit("/", 1)[-1].removesuffix(".json"))
        if m and int(m.group(1)) < n:
            earlier.append(int(m.group(1)))
    for k in sorted(earlier, reverse=True):
        data = st.get(index_key(pack, f"m-{k}", role))
        if data is not None:
            return f"m-{k}", data
    return None


def capture(st, pack: str, manifest: str, role: str, relayout: bool = False) -> view_build.CapturedRole:
    """Freeze one role's previous inputs once, or reuse the exact choice of an existing new index."""
    existing = st.get(index_key(pack, manifest, role))
    before = None
    recorded = json.loads(existing) if existing is not None else None
    if recorded is not None:
        if (recorded.get("pack"), recorded.get("manifest"), recorded.get("role")) != (pack, manifest, role):
            raise ValueError("view build: view index belongs to another role or manifest")
        if "capture_sha256" not in recorded or recorded.get("relayout") != relayout:
            raise ValueError("view build: existing view index has no matching captured-input mode")
        if recorded.get("previous"):
            p = recorded["previous"]
            mid = p["manifest"]
            if not MAIN.fullmatch(mid) or int(mid[2:]) >= int(manifest[2:]):
                raise ValueError("view build: previous view must precede this main manifest")
            before = (mid, _get(st, index_key(pack, mid, role), p["sha256"]))
    elif not relayout:
        before = previous(st, pack, manifest, role)
    layouts = []
    if before:
        old = json.loads(before[1])
        if (old.get("pack"), old.get("manifest"), old.get("role")) != (pack, before[0], role):
            raise ValueError("view build: previous view index belongs to another role or manifest")
        for sheet, s in sorted(old.get("sheets", {}).items()):
            if "/" not in sheet and "\\" not in sheet and not sheet.startswith("."):
                key = key_of(s["layout"]["uri"])
                if not key.startswith(f"{pack}/{before[0]}/{role}/views/") or ".." in key.split("/"):
                    raise ValueError("view build: previous layout belongs to another role or manifest")
                layouts.append((sheet, _get(st, key, s["layout"]["sha256"])))
    frozen = view_build.CapturedRole(pack, manifest, role, relayout, before[0] if before else "",
                                     before[1] if before else b"", tuple(layouts))
    if recorded is not None and frozen.sha256 != recorded["capture_sha256"]:
        raise ValueError("view build: existing index's captured inputs differ")
    return frozen


def checkpoint_key(pack: str, manifest: str, role: str) -> str:
    """Private namespace: no manifest, compiled file or gate route exposes these role inputs."""
    return f"{pack}/private/view-inputs/{manifest}/{quote(role, safe='')}.json"


def restored_capture(st, build, pack, manifest, role, relayout):
    body = st.get(checkpoint_key(pack, manifest, role))
    if body is None:
        return None
    result = view_build.restore(body, build, pack, manifest, role, relayout)
    if result.previous:
        if not MAIN.fullmatch(result.previous) or int(result.previous[2:]) >= int(manifest[2:]):
            raise ValueError("view build: invalid previous manifest in private input checkpoint")
        old = json.loads(result.index)
        if (old.get("pack"), old.get("manifest"), old.get("role")) != (pack, result.previous, role):
            raise ValueError("view build: private input checkpoint contains another role's index")
        named = {k: v["layout"] for k, v in old.get("sheets", {}).items()
                 if k and "/" not in k and "\\" not in k and not k.startswith(".")}
        if set(named) != {k for k, _ in result.layouts}:
            raise ValueError("view build: private input checkpoint omits a named layout")
        for sheet, data in result.layouts:
            key = key_of(named[sheet]["uri"])
            if (not key.startswith(f"{pack}/{result.previous}/{role}/views/") or ".." in key.split("/")
                    or sha256(data) != named[sheet]["sha256"]):
                raise ValueError("view build: private input checkpoint layout differs or belongs to another role")
    return result


def prepare(st, pack: str, manifest: str, roles, relayout: bool = False,
            node: str | None = None) -> view_build.PreparedViews:
    """Before main is published: static identity plus private captures, never a cross-role data hash."""
    if not MAIN.fullmatch(manifest):
        raise ValueError("view build: only main manifests have views")
    binary = view_build.executable(node)
    fixed = st.get(f"{pack}/manifests/{manifest}.json")
    expected = None
    if fixed is not None:
        m = json.loads(fixed)
        record = json.loads(_get(st, key_of(m["build"]["uri"]), m["build"]["sha256"])) if m.get("build") else {}
        expected = record.get("views")
        if not isinstance(expected, dict):
            raise ValueError("view build: existing main manifest names another or no view build")
    component = view_build.component(binary, expected=expected)
    captures = []
    for role in sorted(set(roles)):
        frozen = restored_capture(st, component, pack, manifest, role, relayout)
        if frozen is None:
            if fixed is not None:
                raise ValueError(f"view build: fixed main manifest is missing its private input checkpoint for {role}")
            candidate = capture(st, pack, manifest, role, relayout)
            try:
                st.put_new(checkpoint_key(pack, manifest, role), candidate.checkpoint(component))
            except stores.Conflict:
                pass  # Another preparer may have committed a different valid first choice. Never overwrite it.
            frozen = restored_capture(st, component, pack, manifest, role, relayout)
            if frozen is None:
                raise ValueError("view build: private input checkpoint was not stored")
        captures.append(frozen)
    return view_build.PreparedViews(canonical_bytes(component), binary, pack, manifest, tuple(captures))


def _named(key: str, data: bytes | None, digest: str | None) -> bytes:
    if data is None:
        raise ValueError(f"{key} is not in the store")
    if digest is not None and sha256(data) != digest:
        raise ValueError(f"{key} does not have the sha256 that names it")
    return data


def _get(st, key: str, digest: str | None = None) -> bytes:
    return _named(key, st.get(key), digest)


def _snapshots(st, snaps: list[dict]) -> dict[str, bytes]:
    """The bytes of a role's snapshots by relation, each the object its manifest names (uri and sha256), read
    side by side (store.get_all): one after another, a role of the lab cost a round trip per relation."""
    got = stores.get_all(st, [key_of(s["uri"]) for s in snaps])
    return {s["relation"]: _named(key_of(s["uri"]), data, s["sha256"]) for s, data in zip(snaps, got)}


def plan(st, pack: str, manifest: str, relayout: bool = False, node: str | None = None, *,
         prepared: view_build.PreparedViews | None = None) -> list[tuple[str, bytes]]:
    """Every object to write, the view indexes last: all made and checked before anything is written. A role
    whose views fail its check raises Blocked; `roles` makes and checks each role on its own."""
    made = roles(st, pack, manifest, relayout, node, prepared=prepared)
    failed = {role: err for role, err in made.items() if isinstance(err, Blocked)}
    if failed:
        raise Blocked("; ".join(f"{err}" for err in failed.values()))
    pieces = [f for files in made.values() for f in files[:-1]]
    return pieces + [files[-1] for files in made.values()]


def roles(st, pack: str, manifest: str, relayout: bool = False, node: str | None = None, *,
          prepared: view_build.PreparedViews | None = None, manifest_bytes: bytes | None = None) -> dict:
    """Per role the gate serves: its objects, the view index last, or the Blocked that stops that role
    alone. A role's views depend only on its own rows, so another role's failure never withholds them."""
    if not MAIN.match(manifest):
        raise ValueError(f"{manifest}: views are made for main manifests (m-<epoch>) only")
    raw = manifest_bytes if manifest_bytes is not None else _get(st, f"{pack}/manifests/{manifest}.json")
    m = json.loads(raw)
    if m.get("id") != manifest or m.get("proposal") or m.get("variant"):
        raise ValueError(f"{manifest}: not a main manifest")
    bundle = next((c for c in m.get("compiled", []) if c.get("file") == "bundle/schema-bundle.json"), None)
    if not bundle:
        raise ValueError(f"{manifest}: names no compiled bundle")
    mine = sorted({s["role"] for s in m.get("snapshots", []) if s.get("complete") is False})
    build = json.loads(_get(st, key_of(m["build"]["uri"]), m["build"]["sha256"])) if m.get("build") else {}
    if "views" in build:
        prepared = prepared or prepare(st, pack, manifest, mine, relayout, node)
        if (prepared.pack, prepared.manifest) != (pack, manifest):
            raise ValueError("view build: prepared inputs belong to another main manifest")
        prepared.verify(build["views"])
        for role in mine:
            saved = restored_capture(st, build["views"], pack, manifest, role, relayout)
            if saved is None or saved != prepared.capture(role):
                raise ValueError(f"view build: missing or changed private input checkpoint for {role}")
        node = prepared.node
    elif prepared is not None:
        raise ValueError("view build: manifest does not name the prepared component")
    out: dict = {}
    laid: dict = {}  # (summary, pieces, first role) the Node entry made, by _layout_key: shared by roles
    # The roles the gate serves: a complete role (server side) gets nothing there, so it gets no view.
    for role in mine:
        try:
            out[role] = _role(st, pack, manifest, raw, m, bundle, role, relayout, node, laid, prepared)
        except Blocked as err:
            out[role] = err
    return out


def _layout_key(bundle: dict, mine: list[dict], layouts: dict[str, bytes]) -> str:
    """The digest of everything the Node entry reads for a role: the compiled bundle, the role's snapshots
    (relation and sha256) and the previous layout of each sheet. The entry is deterministic and reads nothing
    else of the role (AGENTS.md rule 3), so two roles with the same digest get the same bytes."""
    return sha256(dumps({"bundle": bundle["sha256"], "snapshots": [[s["relation"], s["sha256"]] for s in mine],
                         "previous": {sheet: sha256(data) for sheet, data in sorted(layouts.items())}}))


def _role(st, pack, manifest, raw, m, bundle, role, relayout, node, laid=None, prepared=None) -> list[tuple[str, bytes]]:
    """One role's views: made by the Node entry, checked, and its view index; Blocked if the check fails.
    `laid`: what the entry made for earlier roles, by _layout_key. A role whose layout inputs are those of an
    earlier role takes its pieces instead of laying out again, and checks them against its own rows."""
    mine = sorted((s for s in m["snapshots"] if s["role"] == role), key=lambda s: s["relation"])
    snapshots = _snapshots(st, mine)
    captured = prepared.capture(role) if prepared else None
    if captured and captured.relayout != relayout:
        raise ValueError("view build: prepared layout mode differs")
    before = ((captured.previous, captured.index) if captured.previous else None) if captured else (None if relayout else previous(st, pack, manifest, role))
    layouts: dict[str, bytes] = {}
    start = None
    if captured:
        layouts = dict(captured.layouts)
        if before:
            start = {"manifest": before[0], "sha256": sha256(before[1])}
    elif before:
        # Every sheet's layout of the previous manifest, by sheet: each Map starts from its own.
        old = json.loads(before[1])
        for sheet, s in sorted(old.get("sheets", {}).items()):
            if "/" not in sheet and not sheet.startswith("."):
                layouts[sheet] = _get(st, key_of(s["layout"]["uri"]), s["layout"]["sha256"])
        start = {"manifest": before[0], "sha256": sha256(before[1])}
    laid = {} if laid is None else laid
    key = _layout_key(bundle, mine, layouts)
    if key in laid:
        summary, made, first = laid[key]
        print(f"views: role {role} has the layout inputs of role {first}: its pieces, checked again", file=sys.stderr)
    else:
        if prepared:
            prepared.verify()
        summary, made = _lay_out(st, pack, manifest, raw, bundle, role, mine, snapshots, layouts, node)
        laid[key] = summary, made, role
    files = _checked(st, pack, manifest, m, role, relayout, mine, snapshots, start, summary, made)
    if captured:
        key, body = files[-1]
        files[-1] = (key, dumps(json.loads(body) | {"capture_sha256": captured.sha256}))
    return files


def _lay_out(st, pack, manifest, raw, bundle, role, mine, snapshots, layouts, node):
    """The Node entry's pieces for one role: (summary, {path: bytes}), each piece the bytes its summary names."""
    with tempfile.TemporaryDirectory() as tmp:
        given, out = Path(tmp, "store"), Path(tmp, "out")
        # The objects the Node entry reads, by their keys, as a file store.
        objects = {f"{pack}/manifests/{manifest}.json": raw, key_of(bundle["uri"]): _get(st, key_of(bundle["uri"]), bundle["sha256"])}
        objects |= {key_of(s["uri"]): snapshots[s["relation"]] for s in mine}
        for key, data in objects.items():
            Path(given, key).parent.mkdir(parents=True, exist_ok=True)
            Path(given, key).write_bytes(data)
        args = [node or os.environ.get("REZONO_NODE", "node"), str(ENTRY), str(given), pack, manifest, role, str(out)]
        if layouts:
            Path(tmp, "previous").mkdir()
            for sheet, data in layouts.items():
                Path(tmp, "previous", f"{sheet}.json").write_bytes(data)
            args.append(str(Path(tmp, "previous")))
        with timing.phase("tiles"):  # the layout and its tiles, by the viewer's own code
            subprocess.run(args, check=True, cwd=ROOT / "viewer", env=view_build.node_env())
        summary = json.loads(Path(out, "summary.json").read_bytes())
        made = {}
        for p in summary["pieces"]:
            data = Path(out, p["path"]).read_bytes()
            if sha256(data) != p["sha256"]:
                raise Blocked(f"role {role}: {p['path']} is not the piece its summary names")
            made[p["path"]] = data
    return summary, made


def _checked(st, pack, manifest, m, role, relayout, mine, snapshots, start, summary, made):
    """The role's pieces checked against its own rows, its row, proof, gap and source pieces, and its view index last."""
    bundle = next(c for c in m["compiled"] if c.get("file") == "bundle/schema-bundle.json")
    at = lambda path: {"uri": st.uri(f"{pack}/{manifest}/{role}/views/{path}"), "sha256": sha256(made[path])}
    compiled = json.loads(_get(st, key_of(bundle["uri"]), bundle["sha256"]))
    with timing.phase("checker"):
        # What the role reads, derived once by the checker from its snapshots: every check below uses it. The
        # relations it reads in full are the manifest's flags, which the access check verified at publication.
        role_rows = Role(snapshots, compiled, {s["relation"] for s in mine if s.get("full")})
        problems = check_page(snapshots, compiled, made[summary["page"]["path"]], role_rows)
    if problems:
        raise Blocked(f"role {role}: {len(problems)} (first: {'; '.join(problems[:3])})")
    levels = {key: made[p["path"]] for key, p in summary["islands"].items()}
    # The island levels open Maps; any other sheet (a Flow) is checked as a sheet below.
    maps = {sheet: made[s["layout"]["path"]] for sheet, s in summary["sheets"].items() if sheet == "map" or sheet.startswith("map.")}
    with timing.phase("checker"):
        problems = check_islands(snapshots, compiled, levels, maps, role_rows)
    if problems:
        raise Blocked(f"role {role}: islands: {len(problems)} (first: {'; '.join(problems[:3])})")
    sheets = {}
    stubs = role_rows.plan.stubs
    # Every piece by the sheet it lies under (its first path segment), once: never every piece per sheet.
    under: dict[str, dict[str, bytes]] = {}
    for path, data in made.items():
        under.setdefault(path.split("/", 1)[0], {})[path] = data
    for sheet, s in sorted(summary["sheets"].items()):
        layout = made[s["layout"]["path"]]
        tiles = {path: data for path, data in under.get(sheet, {}).items() if path != s["layout"]["path"]}
        warned: list[str] = []
        with timing.phase("checker"):
            problems = check_view(sheet, snapshots, layout, tiles, s["root"]["path"], s["tile"], s["fanout"], s["levels"], compiled,
                                  stubs.get(sheet, {}), warned, role_rows)
        for w in warned:  # layout warns, never blocks (AGENTS.md, rule 5)
            print(f"warning: role {role}: {w}", file=sys.stderr)
        if problems:
            raise Blocked(f"role {role}: {len(problems)} (first: {'; '.join(problems[:3])})")
        sheets[sheet] = {k: s[k] for k in ("tile", "fanout", "levels", "width", "height")} | {
            "root": at(s["root"]["path"]), "layout": at(s["layout"]["path"])}
    pieces = [(f"{pack}/{manifest}/{role}/views/{path}", data) for path, data in sorted(made.items())]
    index = {
        "format": FORMAT,
        "pack": pack,
        "manifest": manifest,
        "role": role,
        "relayout": relayout,
        "sources": [{"relation": s["relation"], "sha256": s["sha256"]} for s in mine],
        "page": at(summary["page"]["path"]),
        "islands": {key: at(p["path"]) for key, p in sorted(summary["islands"].items())},
        "sheets": sheets,
    }
    if start:
        index["previous"] = start
    made_rows, index["rows"] = _rows(st, pack, manifest, role, snapshots)
    made_proof, index["proof"] = _proof(st, pack, manifest, m, role, snapshots)
    made_gap, part = _gap(st, pack, manifest, m, role, snapshots)
    if part:
        index["gap"] = part
    made_sources, part = _sources(st, pack, manifest, m, role)
    if part:
        index["fact_sources"] = part
    return pieces + made_rows + made_proof + made_gap + made_sources + [(index_key(pack, manifest, role), dumps(index))]


def _rows(st, pack, manifest, role, snapshots):
    """The role's snapshots as key-range trees (rezono_publisher.proof.rows_plan), checked by
    rezono_checker.proof.check_rows: (pieces, the `rows` part of the view index). Blocked if the check fails."""
    base = f"{pack}/{manifest}/{role}/views"
    try:
        made, roots, inverse = proof.rows_plan(snapshots, base)
    except proof.TooLarge as err:
        raise Blocked(f"role {role}: rows: {err}") from err
    with timing.phase("checker"):
        problems = check_rows(snapshots, {k.removeprefix(base + "/"): b for k, b in made}, roots, proof.PIECE, proof.FANOUT, inverse)
    if problems:
        raise Blocked(f"role {role}: rows: {len(problems)} (first: {'; '.join(problems[:3])})")
    trees = {rel: r if not r["count"] else {"uri": st.uri(f"{base}/{r['file']}"), "sha256": r["sha256"],
                                            "levels": r["levels"], "count": r["count"]}
             for rel, r in roots.items()}
    named = {rel: {"uri": st.uri(f"{base}/{r['file']}"), "sha256": r["sha256"], "levels": r["levels"]} for rel, r in inverse.items()}
    return made, {"format": ROWS, "piece": proof.PIECE, "fanout": proof.FANOUT, "trees": trees, "inverse": named}


def _proof(st, pack, manifest, m, role, snapshots, base=None):
    """The role's proof graph as key-range pieces (rezono_publisher.proof), checked by rezono_checker.proof:
    (pieces, the `proof` part of the view index). Blocked if the check fails. `base` is the key prefix of
    the pieces: the role's views, or its explain index for a proposal or variant (rezono_publisher.difference)."""
    w = next((x for x in m.get("witnesses", []) if x["role"] == role), None)
    rules = next((c for c in m.get("compiled", []) if c.get("file") == "ir/rules.json"), None)
    sees = json.loads(_get(st, key_of(w["uri"]), w["sha256"])) if w else {"witnesses": []}
    doc = json.loads(_get(st, key_of(rules["uri"]), rules["sha256"])) if rules else None
    if doc is None and sees["witnesses"]:
        raise ValueError(f"{manifest}: witnesses for role {role}, but no rule IR")
    base = base or f"{pack}/{manifest}/{role}/views"
    try:
        made, roots = proof.plan(doc, sees, snapshots, base) if doc or sees.get("calc_witnesses") else ([], {t: {} for t in proof.TREES})
    except proof.TooLarge as err:
        raise Blocked(f"role {role}: proof: {err}") from err
    with timing.phase("checker"):
        problems = check_proof(doc or {"rules": []}, sees, snapshots, {k.removeprefix(base + "/"): b for k, b in made},
                               roots, proof.PIECE, proof.FANOUT)
    if problems:
        raise Blocked(f"role {role}: proof: {len(problems)} (first: {'; '.join(problems[:3])})")
    trees = {t: {rel: {"uri": st.uri(f"{base}/{r['file']}"), "sha256": r["sha256"], "levels": r["levels"]}
                 for rel, r in by.items()} for t, by in roots.items()}
    part = {"format": proof.INDEX, "piece": proof.PIECE, "fanout": proof.FANOUT, "trees": trees,
            "witnesses": w["sha256"] if w else None, "rules": rules["sha256"] if rules else None}
    return made, {k: v for k, v in part.items() if v is not None}


def _sources(st, pack, manifest, m, role):
    """The role's source entries (S25, its `fact_sources` set in the manifest) as key-range trees by row
    (rezono_publisher.proof.sources_plan), checked by rezono_checker.proof.check_sources: (pieces, the
    `fact_sources` part of the view index, or None for a manifest without a source set for the role). The
    part names the set's sha256, so the gate reads the trees only for the set the manifest names."""
    ref = next((x for x in m.get("fact_sources", []) if x["role"] == role), None)
    if ref is None:
        return [], None
    entries = json.loads(_get(st, key_of(ref["uri"]), ref["sha256"]))
    base = f"{pack}/{manifest}/{role}/views"
    try:
        made, roots = proof.sources_plan(entries, base)
    except proof.TooLarge as err:
        raise Blocked(f"role {role}: sources: {err}") from err
    with timing.phase("checker"):
        problems = check_sources(entries, {k.removeprefix(base + "/"): b for k, b in made}, roots, proof.PIECE, proof.FANOUT)
    if problems:
        raise Blocked(f"role {role}: sources: {len(problems)} (first: {'; '.join(problems[:3])})")
    trees = {rel: {"uri": st.uri(f"{base}/{r['file']}"), "sha256": r["sha256"], "levels": r["levels"]} for rel, r in roots.items()}
    return made, {"format": SOURCES, "piece": proof.PIECE, "fanout": proof.FANOUT, "set": ref["sha256"], "trees": trees}


def _gap(st, pack, manifest, m, role, snapshots):
    """What `gap` reads for one role (docs/gui.md, "gap"): the compiler's plan (rezono_compiler.gap, rezono.gap/1)
    as one file, and the indexes its premise tests need (rezono_publisher.proof.index_plan), checked by
    rezono_checker.proof.check_indexes: (pieces, the `gap` part of the view index, or None without rules)."""
    rules = next((c for c in m.get("compiled", []) if c.get("file") == "ir/rules.json"), None)
    if not rules:
        return [], None
    plan = gap.plan(ir.load(json.loads(_get(st, key_of(rules["uri"]), rules["sha256"]))))
    base = f"{pack}/{manifest}/{role}/views"
    data = dumps(plan)
    try:
        made, entries = proof.index_plan(plan, snapshots, base)
    except proof.TooLarge as err:
        raise Blocked(f"role {role}: gap: {err}") from err
    problems = check_indexes(plan, snapshots, {k.removeprefix(base + "/"): b for k, b in made}, entries, proof.PIECE, proof.FANOUT)
    if problems:
        raise Blocked(f"role {role}: gap: {len(problems)} (first: {'; '.join(problems[:3])})")
    trees = [{k: v for k, v in e.items() if k not in ("file",)} | ({"uri": st.uri(f"{base}/{e['file']}")} if "file" in e else {})
             for e in entries]
    part = {"format": GAP, "piece": proof.PIECE, "fanout": proof.FANOUT, "rules": rules["sha256"],
            "plan": {"uri": st.uri(f"{base}/gap.json"), "sha256": sha256(data)}, "trees": trees}
    return made + [(f"{base}/gap.json", data)], part


def publish(st, pack: str, manifest: str, relayout: bool = False, node: str | None = None, *,
            prepared: view_build.PreparedViews | None = None, manifest_bytes: bytes | None = None) -> list[str]:
    """Make, check and write the views of a manifest, role by role: a role whose views pass is written (its
    index last), whatever another role's do. Returns the keys of the view indexes written; raises Blocked
    afterwards if a role failed, which then has no index, so the gate serves it no view."""
    timing.switch("views")  # reading the role's rows, its row and proof pieces; tiles and checks are lent out
    made = roles(st, pack, manifest, relayout, node, prepared=prepared, manifest_bytes=manifest_bytes)
    timing.switch("upload")
    written = []
    for role, files in made.items():
        if isinstance(files, Blocked):
            continue
        stores.put_all(st, files[:-1])  # concurrently; the role's index after them
        st.put_new(*files[-1])
        written.append(files[-1][0])
    failed = [str(err) for err in made.values() if isinstance(err, Blocked)]
    if failed:
        raise Blocked("; ".join(failed))
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_publisher.views")
    p.add_argument("pack")
    p.add_argument("manifest")
    p.add_argument("--profile", help="deploy profile with the section storage")
    p.add_argument("--store", help="file:///path or s3://bucket; overrides the profile")
    p.add_argument("--relayout", action="store_true", help="a full relayout: start from no earlier layout")
    args = p.parse_args(argv)
    from .__main__ import profile_settings

    url, endpoint, _ = profile_settings(args.profile) if args.profile else (None, None, {})
    url = args.store or url
    if not url:
        p.error("no store: give --store or a profile with storage")
    try:
        for key in publish(stores.open_store(url, endpoint), args.pack, args.manifest, args.relayout):
            print(key)
    except Blocked as err:
        print(f"blocked: {err}", file=sys.stderr)
        return 2
    except (stores.Conflict, ValueError, subprocess.CalledProcessError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
