"""Shared helpers for Rezono 1 single-pass pack conversion tests and live legacy-archive drift guards.

Used by:
- `examples/test_rezono_1_pack_conversion.py`
- `loop/tests/test_rezono_1_build_epoch_conversion.py`
- `run/tests/test_rezono_1_run_packs_conversion.py`
"""

from __future__ import annotations

from contextlib import ExitStack
import gzip
import io
import json
from pathlib import Path
import shutil
import tarfile

import yaml


REPO = Path(__file__).resolve().parents[3]
LEGACY_ARCHIVE = Path(__file__).resolve().parent / "legacy-packs.tar.gz"
LEGACY_ARCHIVE_REL = "examples/fixtures/rezono-1-legacy/legacy-packs.tar.gz"
TIME = "2026-11-10T00:00:00Z"

ALL_LEGACY_PACKS: tuple[str, ...] = (
    "build",
    "epoch",
    "examples/library",
    "examples/platform",
    "examples/platform/tenant-capacity/interface",
    "examples/projects",
    "examples/subsidy",
    "examples/subsidy-scheme",
    "packs/std-access",
    "packs/std-budget",
    "packs/std-decision",
    "packs/std-explain",
    "packs/std-identity",
    "packs/std-loop",
    "packs/std-order",
    "packs/std-part",
    "packs/std-review",
    "packs/std-time",
    "packs/std-view",
    "run/packs/cleanup",
    "run/packs/cleanup-deadline",
    "run/packs/cluster-shape",
    "run/packs/dispatch",
    "run/packs/exact-quote",
    "run/packs/invoice-drift",
    "run/packs/offer-selection",
    "run/packs/probe-profiles",
    "run/packs/provider-terms",
)

# Packs whose baseline `facts/*.yaml` travel inside the legacy archive for direct `compare_publications`.
PACKS_WITH_ARCHIVED_FACTS = frozenset({"examples/library", "examples/projects"})


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def dl_files_under(directory: Path) -> list[str]:
    return sorted(rel(path) for path in directory.rglob("*.dl"))


def normalize_lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def synthetic_sidecar(source_name: str, position: str) -> str:
    return yaml.safe_dump(
        {
            "default": {
                "kind": "synthetic",
                "name": source_name,
                "position": position,
            }
        },
        sort_keys=False,
    )


def _archived_files_for_pack(pack_rel: str) -> dict[str, Path]:
    """Return `{rel_file: Path}` for every definition file (plus archived baseline facts) of `pack_rel`."""
    from rezono_compiler import modules

    pack_dir = REPO / pack_rel
    files = {p.relative_to(pack_dir).as_posix(): p for p in modules.definition_files(pack_dir)}
    if pack_rel in PACKS_WITH_ARCHIVED_FACTS and (pack_dir / "facts").is_dir():
        for fact_path in sorted((pack_dir / "facts").glob("*.yaml")):
            if fact_path.is_file():
                files[fact_path.relative_to(pack_dir).as_posix()] = fact_path
    return dict(sorted(files.items()))


def build_legacy_archive(output_path: Path = LEGACY_ARCHIVE, *, compresslevel: int = 6) -> None:
    """Create a deterministic, LF-normalized `legacy-packs.tar.gz` covering `ALL_LEGACY_PACKS`."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for pack_rel in sorted(ALL_LEGACY_PACKS):
            for rel_file, path in _archived_files_for_pack(pack_rel).items():
                data = normalize_lf(path.read_bytes())
                info = tarfile.TarInfo(name=f"{pack_rel}/{rel_file}")
                info.size = len(data)
                info.mtime = 0
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                tf.addfile(info, io.BytesIO(data))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=compresslevel) as gz:
            gz.write(buf.getvalue())


def read_legacy_archive() -> dict[str, dict[str, bytes]]:
    """Read `legacy-packs.tar.gz` into `{pack_rel: {file_rel: bytes}}` with strict archive safety checks."""
    assert LEGACY_ARCHIVE.is_file(), f"missing {rel(LEGACY_ARCHIVE)}"
    raw: dict[str, bytes] = {}
    with tarfile.open(LEGACY_ARCHIVE, "r:gz") as tf:
        for member in tf.getmembers():
            assert (
                member.isfile()
                and not member.issym()
                and not member.islnk()
                and not member.name.startswith("/")
                and "\\" not in member.name
                and ".." not in member.name.split("/")
            ), member.name
            handle = tf.extractfile(member)
            assert handle is not None
            raw[member.name] = handle.read()
    pack_roots = sorted(
        (name[: -len("/pack.yaml")] for name in raw if name.endswith("/pack.yaml")),
        key=len,
        reverse=True,
    )
    by_pack: dict[str, dict[str, bytes]] = {root: {} for root in pack_roots}
    for name, data in raw.items():
        owner = next(root for root in pack_roots if name.startswith(root + "/"))
        by_pack[owner][name[len(owner) + 1 :]] = data
    return by_pack


def materialize_legacy_packs(dest_root: Path, pack_prefixes: tuple[str, ...] | None = None) -> None:
    """Extract legacy packs matching `pack_prefixes` (or all packs when None) from `legacy-packs.tar.gz`."""
    by_pack = read_legacy_archive()
    for pack_rel, files in by_pack.items():
        if pack_prefixes is not None and not any(
            pack_rel == prefix or pack_rel.startswith(prefix + "/") for prefix in pack_prefixes
        ):
            continue
        pack_dir = dest_root / pack_rel
        if pack_dir.exists():
            shutil.rmtree(pack_dir)
        for rel_file, data in files.items():
            target = pack_dir / rel_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def admit_legacy_std_packs(stack: ExitStack, root: Path) -> None:
    """Register every legacy `packs/std-*` materialized under `root` via `standard_packs.trial`."""
    from rezono_compiler import modules, standard_packs

    packs_dir = root / "packs"
    if not packs_dir.is_dir():
        return
    for pack_yaml in sorted(packs_dir.glob("std-*/pack.yaml")):
        std_dir = pack_yaml.parent
        stack.enter_context(standard_packs.trial(std_dir.name, modules.pack_hash(std_dir)))


def form_has_derivation(decls: list[dict]) -> bool:
    for decl in decls:
        if not isinstance(decl, dict):
            continue
        if "derived" in decl and isinstance(decl["derived"], str):
            return True
        if "step" in decl:
            return True
        nested = decl.get("derived")
        if isinstance(nested, list) and nested:
            return True
    return False


def pack_is_rezono_1(pack_dir: Path) -> bool:
    """True once `pack_dir` has zero own `.dl` files and every declared `rezono:` module uses `rezono.module/5` (`rezono 1`)."""
    from rezono_compiler import modules

    if any(p.suffix == ".dl" for p in modules.definition_files(pack_dir)):
        return False
    meta_path = pack_dir / "pack.yaml"
    if not meta_path.is_file():
        return False
    meta = yaml.safe_load(meta_path.read_bytes()) or {}
    entries = meta.get("rezono") or []
    if not entries:
        return False
    for entry in entries:
        form_path = pack_dir / entry["form"]
        if not form_path.is_file():
            return False
        form = json.loads(form_path.read_bytes())
        if form.get("format") != "rezono.module/5" or (form.get("module") or {}).get("rezono") != "1":
            return False
    return True


def _legacy_pack_non_manifest_matches(pack_rel: str, by_pack: dict[str, dict[str, bytes]]) -> bool:
    """True iff every non-`pack.yaml` archived file of `pack_rel` exists and matches live bytes (LF-normalized)."""
    arch_files = by_pack.get(pack_rel)
    if arch_files is None:
        return False
    live_files = _archived_files_for_pack(pack_rel)
    if set(live_files) != set(arch_files):
        return False
    return all(
        normalize_lf(live_files[name].read_bytes()) == normalize_lf(arch_files[name])
        for name in arch_files
        if name != "pack.yaml"
    )


def _pack_yaml_matches_legacy(
    pack_dir: Path,
    live_bytes: bytes,
    arch_bytes: bytes,
    by_pack: dict[str, dict[str, bytes]],
    memo: dict[str, bool],
    visiting: set[str],
) -> bool:
    """Compare a still-legacy pack's `pack.yaml` byte-for-byte (LF-normalized), allowing only `imports[].sha256`
    re-pins for imports that have converted to `rezono 1` — directly or transitively through still-legacy
    packs whose own non-`pack.yaml` files match the archive and whose own `pack.yaml` differs only in such pins."""
    live_lf = normalize_lf(live_bytes)
    arch_lf = normalize_lf(arch_bytes)
    if live_lf == arch_lf:
        return True

    from rezono_compiler import modules

    live_meta = yaml.safe_load(live_lf) or {}
    arch_meta = yaml.safe_load(arch_lf) or {}
    arch_pins = {
        (entry.get("name"), entry.get("path")): entry.get("sha256")
        for entry in (arch_meta.get("imports") or ())
        if isinstance(entry, dict)
    }
    repo_root = REPO.resolve()
    adjusted = live_lf.decode("utf-8")
    for entry in live_meta.get("imports") or ():
        if not isinstance(entry, dict):
            continue
        key = (entry.get("name"), entry.get("path"))
        live_sha = entry.get("sha256")
        arch_sha = arch_pins.get(key)
        if not (isinstance(live_sha, str) and isinstance(arch_sha, str)) or live_sha == arch_sha:
            continue
        target_dir = (pack_dir / str(entry["path"])).resolve()
        if not target_dir.is_dir() or modules.pack_hash(target_dir) != live_sha:
            continue
        allowed = pack_is_rezono_1(target_dir)
        if not allowed and target_dir.is_relative_to(repo_root):
            target_rel = target_dir.relative_to(repo_root).as_posix()
            if target_rel in memo:
                allowed = memo[target_rel]
            elif target_rel not in visiting and target_rel in by_pack:
                visiting.add(target_rel)
                try:
                    allowed = _legacy_pack_non_manifest_matches(target_rel, by_pack) and _pack_yaml_matches_legacy(
                        target_dir,
                        (target_dir / "pack.yaml").read_bytes(),
                        by_pack[target_rel]["pack.yaml"],
                        by_pack,
                        memo,
                        visiting,
                    )
                finally:
                    visiting.discard(target_rel)
                memo[target_rel] = allowed
        if allowed:
            adjusted = adjusted.replace(live_sha, arch_sha, 1)
    return adjusted.encode("utf-8") == arch_lf


def assert_legacy_archive_integrity(
    expected_packs: set[str],
    expected_dl_packs: set[str] = frozenset(),
    expected_files: dict[str, set[str]] | None = None,
) -> dict[str, dict[str, bytes]]:
    """Verify archive safety, expected pack roots, valid `pack.yaml`, legacy `.dl` presence, and required files."""
    by_pack = read_legacy_archive()
    assert expected_packs <= set(by_pack), f"missing packs in archive: {sorted(expected_packs - set(by_pack))}"
    for pack_rel in sorted(expected_packs):
        meta = yaml.safe_load(by_pack[pack_rel]["pack.yaml"])
        assert isinstance(meta, dict) and meta.get("name"), f"invalid pack.yaml in archive for {pack_rel}"

    for pack_rel in sorted(expected_dl_packs):
        dl_files = [name for name in by_pack[pack_rel] if name.endswith(".dl")]
        assert dl_files, f"archive pack {pack_rel} is missing legacy .dl definitions"

    for pack_rel, required in sorted((expected_files or {}).items()):
        missing = sorted(required - set(by_pack[pack_rel]))
        assert not missing, f"archive pack {pack_rel} is missing expected files: {missing}"
    return by_pack


def assert_legacy_packs_match_archive(pack_rels: set[str] | tuple[str, ...]) -> None:
    """Byte-for-byte live drift check (CRLF -> LF normalized) for planner refreshes of `legacy-packs.tar.gz`.

    Intended for explicit planner archive refreshes immediately before converting a pack to `rezono 1`,
    not for green PR integrity tests: `legacy-packs.tar.gz` is protected by `scripts/red_guard.py`, so
    worker PRs must remain able to improve unconverted legacy packs without modifying the archive.

    Once a pack converts to native `rezono 1` (`pack_is_rezono_1`), its archived snapshot stays frozen as the
    equivalence baseline and is skipped here. For still-legacy packs, every definition file (`.dl`, schemas,
    labels, messages, calculations, views, channels, etc.) must match the archive byte-for-byte; `pack.yaml`
    allows only `imports[].sha256` re-pins pointing at imports that have already converted to `rezono 1`.
    """
    by_pack = read_legacy_archive()
    memo: dict[str, bool] = {}
    drifts: list[str] = []
    for pack_rel in sorted(pack_rels):
        pack_dir = REPO / pack_rel
        assert pack_dir.is_dir(), f"missing live pack directory {pack_rel}"
        if pack_is_rezono_1(pack_dir):
            continue
        assert pack_rel in by_pack, f"legacy pack {pack_rel} missing from {LEGACY_ARCHIVE_REL}"
        arch_files = by_pack[pack_rel]
        live_files = _archived_files_for_pack(pack_rel)

        missing_in_archive = sorted(set(live_files) - set(arch_files))
        extra_in_archive = sorted(set(arch_files) - set(live_files))
        if missing_in_archive:
            drifts.append(f"{pack_rel}: files missing from archive: {missing_in_archive}")
        if extra_in_archive:
            drifts.append(f"{pack_rel}: stale files in archive: {extra_in_archive}")

        for rel_file in sorted(set(live_files) & set(arch_files)):
            live_bytes = live_files[rel_file].read_bytes()
            arch_bytes = arch_files[rel_file]
            if rel_file == "pack.yaml":
                ok = _pack_yaml_matches_legacy(pack_dir, live_bytes, arch_bytes, by_pack, memo, {pack_rel})
            else:
                ok = normalize_lf(live_bytes) == normalize_lf(arch_bytes)
            if not ok:
                drifts.append(f"{pack_rel}/{rel_file}: live bytes differ from {LEGACY_ARCHIVE_REL}")

    assert not drifts, (
        "Legacy pack definition files drifted from the frozen legacy archive "
        f"({LEGACY_ARCHIVE_REL}); refresh the archive from live legacy packs before landing:\n"
        + "\n".join(f"  - {item}" for item in drifts)
    )


def assert_pack_is_native_rezono_1(
    pack_dir: Path, *, expect_rules: bool = True, compile_output: bool = True
):
    """Verify a pack has zero `.dl` rules, native `rezono.module/5` (`rezono 1`) forms, and compiles cleanly."""
    dl_files = dl_files_under(pack_dir)
    assert not dl_files, f"{rel(pack_dir)} still contains .dl rule files: {dl_files}"

    meta_path = pack_dir / "pack.yaml"
    assert meta_path.is_file(), f"missing {rel(meta_path)}"
    meta = yaml.safe_load(meta_path.read_bytes()) or {}
    entries = meta.get("rezono") or []
    assert entries, f"{rel(pack_dir)}/pack.yaml must declare native rezono 1 modules under `rezono:`"

    has_derivation = False
    for entry in entries:
        module_path = pack_dir / entry["module"]
        form_path = pack_dir / entry["form"]
        assert module_path.is_file(), f"missing module {rel(module_path)}"
        assert form_path.is_file(), f"missing module form {rel(form_path)}"

        form = json.loads(form_path.read_bytes())
        assert form.get("format") == "rezono.module/5", (
            f"{rel(form_path)} must use format rezono.module/5, got {form.get('format')!r}"
        )
        module = form.get("module") or {}
        assert module.get("rezono") == "1", (
            f"{rel(form_path)} must record module.rezono == '1', got {module.get('rezono')!r}"
        )
        decls = module.get("decls") or []
        for decl in decls:
            if isinstance(decl, dict):
                assert "rules" not in decl, f"{rel(form_path)} still contains a legacy `rules` pipe block"
                assert "rule" not in decl, f"{rel(form_path)} still contains a rezono 0 `rule` declaration"
        if form_has_derivation(decls):
            has_derivation = True

    if expect_rules:
        assert has_derivation, f"{rel(pack_dir)} must define native rezono 1 `derived` (or `step`) declarations"

    from rezono_compiler import emit, pack

    model = pack.read(pack_dir)
    if not compile_output:
        return model

    files = emit.compile_pack(model)
    bundle = json.loads(files["bundle/schema-bundle.json"])
    info = bundle.get("pack") or {}
    assert info.get("language_version") == "1", (
        f"{rel(pack_dir)} bundle/schema-bundle.json must record language_version == '1': {info!r}"
    )

    ir = json.loads(files["ir/rules.json"]) if "ir/rules.json" in files else {}
    if expect_rules:
        non_base = [r for r in ir.get("relations", []) if r.get("role") != "base"]
        assert non_base, f"{rel(pack_dir)} compiled ir/rules.json has no derived or functional relations"
    return model, files, bundle, ir


def assert_epoch_is_rezono_1(pack_label: str, epoch) -> tuple[dict, dict]:
    bundle = json.loads(epoch.bundle)
    info = bundle.get("pack") or {}
    assert info.get("language_version") == "1", (
        f"{pack_label} bundle/schema-bundle.json must record language_version == '1': {info!r}"
    )
    ir = json.loads(epoch.rules)
    assert any(r.get("role") != "base" for r in ir.get("relations", ())), (
        f"{pack_label} compiled ir/rules.json has no derived or functional relations"
    )
    return bundle, ir


def roles_for_pack(pack_dir: Path, model) -> dict[str, str]:
    """Discover declared `Role` ids in a pack for per-role publication."""
    roles: dict[str, str] = {"checker": "complete"}
    from rezono_compiler import facts as fact_files

    for path in fact_files.files(pack_dir):
        loaded = fact_files.load(model, path)
        for row in loaded.get("role", ()):
            roles[str(row[0])] = "may_read"
    return roles
