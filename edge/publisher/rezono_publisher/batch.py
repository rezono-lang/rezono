"""One epoch on the batch backend (DuckDB): a pack's facts in, relations, checks and witnesses out.

The facts are the pack's `facts/` (the main state; scenarios are What-ifs, not main), every file loaded
as it is: a record that two files (or one file twice) give with the same id stays twice, so the
identification check sees it. The checks are the violation views of the compiled pack, one result per
view, and every invariant relation of the rules (`// @invariant`), checked after the rules ran. A pack
whose schema declares invariants that nothing checks yet is refused: a required check may not be missing.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import platform
import re
import sys
import sysconfig
from importlib import metadata
from pathlib import Path

import yaml
from rezono_canon import canonical_sha256, sha256_hex

from . import timing
from .publish import Blocked, Epoch

EMPTY_RULES = '{"format":"rezono.rules/1","relations":[],"rules":[]}\n'  # the rule IR of a pack without rules
SKIP = {"expected", "__pycache__"}
INSTALL = ("admission/pyproject.toml", "canon/pyproject.toml", "checker/pyproject.toml", "compiler/pyproject.toml", "edge/publisher/pyproject.toml")


ASSET_ENTRY = {"file", "sha256", "media_type", "source", "licence"}


def asset_files(pack_dir: Path) -> dict[str, dict]:
    """The pack's images: assets/sources.yaml lists each file under assets/ with its hash, media
    type, source and licence. A listing that does not hold blocks; what an image may contain is the checker's."""
    path = pack_dir / "assets" / "sources.yaml"
    if not path.exists():
        return {}
    out = {}
    for e in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        if not isinstance(e, dict) or set(e) != ASSET_ENTRY:
            raise Blocked(f"rezono:assets: assets/sources.yaml: entry {e} needs exactly {sorted(ASSET_ENTRY)}")
        file = str(e["file"])
        target = (pack_dir / "assets" / file).resolve()
        if ".." in Path(file).parts or not target.is_relative_to((pack_dir / "assets").resolve()) or not target.is_file():
            raise Blocked(f"rezono:assets: assets/{file} is not a file under assets/")
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != str(e["sha256"]):
            raise Blocked(f"rezono:assets: assets/{file} does not have the sha256 assets/sources.yaml lists")
        if file in out:
            raise Blocked(f"rezono:assets: assets/sources.yaml lists {file} twice")
        out[file] = {k: str(e[k]) for k in ("sha256", "media_type", "source", "licence")} | {"bytes": data}
    return out


def text(v) -> str:
    """Canonical text of one value: an integer as decimal text, a boolean as true/false, a date as ISO."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return str(v)


def tree_sha256(root: Path, suffixes=None) -> str:
    """One hash over the files under a directory: sorted relative paths with the hash of their bytes."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if not p.is_file() or SKIP.intersection(rel.parts) or (suffixes and p.suffix not in suffixes):
            continue
        h.update(f"{rel.as_posix()}\0{hashlib.sha256(p.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def definition_sha256(pack_dir: Path) -> str:
    """The hash of the pack's definition, without facts, scenarios or anything else that holds rows: the
    fingerprint a role may see. It is the compiler's `pack_hash`, over the one list of
    definition files (`modules.DEFINITION`), so whatever the compiler reads, a calculation and a sweep
    included, changes it. `pack_sha256` hashes the facts too, so a role never gets it."""
    from rezono_compiler import modules

    return modules.pack_hash(pack_dir)


def columns(model) -> dict[str, tuple]:
    """Per base relation, the kind of each column, or None for a value: a kind table holds an
    element of its kind, a slot table the element and, for an arrow, an element of its target. Enum and
    parameter tables come from the schema and hold no element."""
    from rezono_compiler import emit

    out = {}
    for k, kind in model.kinds.items():
        out[k] = (k,)
        for s in kind.slots.values():
            out[s.table] = (k, s.range if s.arrow else None)
    for e in model.enums:
        out[e] = (None,)
    for table, _, _ in emit.slot_parameters(model):
        out[table] = (None,)
    for s in model.seals:  # refused input names the element and the close that refused it
        out[s.refused] = (s.kind, "period_close")
        out[s.accepted] = (s.kind,)
        out[s.row_sha256] = (s.kind, None)
        for p in s.parts:
            out[p.accepted] = (p.kind,)
    return dict(sorted(out.items()))


def unchecked_invariants(node) -> bool:
    """True if a schema declares the `invariants` annotation anywhere (recognized, not computed yet)."""
    if isinstance(node, dict):
        ann = node.get("annotations")
        if isinstance(ann, dict) and "invariants" in ann:
            return True
        return any(unchecked_invariants(v) for v in node.values())
    if isinstance(node, list):
        return any(unchecked_invariants(v) for v in node)
    return False


def libraries(dist: str) -> dict[str, str]:
    """Every installed library `dist` needs at run time, recursively, with its exact version."""
    found: dict[str, str] = {}
    todo = [dist]
    while todo:
        for req in metadata.requires(todo.pop()) or []:
            if "extra ==" in req:
                continue
            name = re.match(r"[A-Za-z0-9_.-]+", req).group(0)
            key = re.sub(r"[-_.]+", "-", name).lower()
            if key in found:
                continue
            try:
                found[key] = metadata.version(name)
            except metadata.PackageNotFoundError:
                continue  # not installed: its marker excludes it here
            todo.append(name)
    return dict(sorted(found.items()))


def compiler_parts() -> dict:
    """What compiled output depends on besides the pack: the compiler's source, rezono-canon, admission (which
    decides the rows the compiler takes from a fact file), the contracts the compiler reads and the exact
    version of every library they use."""
    import rezono_admission
    import rezono_canon
    import rezono_compiler
    from rezono_compiler import pack as packs

    return {
        "compiler": tree_sha256(Path(rezono_compiler.__file__).parent, {".py", ".yaml"}),
        "canon": tree_sha256(Path(rezono_canon.__file__).parent, {".py"}),
        "admission": tree_sha256(Path(rezono_admission.__file__).parent, {".py"}),
        "contracts": {p.name: sha256_hex(p.read_bytes()) for p in sorted(packs.CONTRACTS.glob("*.yaml"))},
        "libraries": libraries("rezono-compiler") | libraries("rezono-canon"),
    }


def build_record() -> dict:
    """What a publication is made with besides its inputs, to set up the same environment again
    (docs/ci.md#8-pinned-versions): the compiler, the publisher's own source, every library with its exact
    version, the Python runtime and platform, and the hash of the lock that installed them. The
    publisher adds the effective profile. Any change here is another build, so the manifest names it."""
    import rezono_checker
    from rezono_compiler import pack as packs

    root = packs.CONTRACTS.parent
    locks = {p.name: sha256_hex(p.read_bytes()) for p in sorted((root / "requirements").glob("*.txt"))}
    install = {name: sha256_hex((root / name).read_bytes()) for name in INSTALL if (root / name).is_file()}
    return {
        # v3: names the checker too, which the publisher runs before the manifest (R7); v2 named
        # pyproject.toml (`install`; rezono_publisher.kept)
        "format": "rezono.build/3",
        "compiler_sha256": canonical_sha256(compiler_parts()),
        "compiler": compiler_parts(),
        "publisher": tree_sha256(Path(__file__).parent, {".py"}),
        "checker": tree_sha256(Path(rezono_checker.__file__).parent, {".py"}),
        "libraries": libraries("rezono-publisher") | libraries("rezono-checker") | libraries("rezono-compiler")
        | libraries("rezono-canon"),
        "python": {
            "implementation": sys.implementation.name, "version": platform.python_version(),
            "build": list(platform.python_build()), "compiler": platform.python_compiler(),
            # The interpreter itself, so another build of the same version is another build here too.
            "executable_sha256": sha256_hex(Path(sys.executable).resolve().read_bytes()),
        },
        "platform": sysconfig.get_platform(),
        "locks": locks or {"none": "installed without requirements/*.txt"},
        # How the packages were installed from source: their pyproject.toml decides what is installed.
        "install": install or {"none": "installed without the projects' pyproject.toml"},
    }


def engine_component() -> dict:
    import duckdb

    record = metadata.distribution("duckdb").read_text("RECORD") or duckdb.__version__
    return {"name": "duckdb-batch", "version": duckdb.__version__,
            "sha256": hashlib.sha256(record.encode()).hexdigest()}


def compute_rules(con, prog, relations=None) -> None:
    """rezono_compiler.batch.compute, with a counter that reached its bound left to its check view.
    The compiler raises `bound_reached` after every statement of the run has executed; here the run
    goes on, and `rule_checks` reads the rows past the bound from `<relation>__exhausted` as a red check like
    any other, so the publication is blocked (or a variant diagnosed) by one path, without a traceback."""
    from rezono_compiler import batch

    try:
        batch.compute(con, prog, relations=relations)
    except batch.BoundReached:
        pass  # the check view holds the rows; rule_checks makes them a red check


def rule_checks(con, prog) -> list[dict]:
    """The checks of the rules, as manifest checks, per derived relation in name order: a named outcome's
    (`<outcome>__total`, `<outcome>__state`) and a counter's bound (`<relation>__exhausted`, R16),
    the views `rezono_compiler.rules_sql.checks` names. A row in any of them is a red check."""
    from rezono_compiler import emit, rules_sql

    out = []
    for name in sorted(prog.relations):
        for view, _ in rules_sql.checks(prog, name, "duckdb"):
            n = con.execute(f"SELECT COUNT(*) FROM {emit.q(view)}").fetchone()[0]
            out.append({"name": view, "status": "red" if n else "green", "violations": n})
    return out


def admitted_rows(evidence) -> dict[str, list[tuple]]:
    """The rows admission gives the protected relations, by relation (decisions/admission-transport.md,
    section 5): none without evidence. A context or an index that does not hold is the protected caller's
    own broken input and blocks the epoch; a candidate that fails verification just gives no row."""
    if evidence is None:
        return {}
    from rezono_checker import evidence as admission

    try:
        return admission.admit(evidence).rows
    except ValueError as e:
        raise Blocked(f"rezono:evidence: {e}") from e


def epoch(pack_dir, *, epoch: int, knowledge_time: str, sources, proposal: str = "",
          base_manifest: str = "", evidence=None) -> Epoch:
    import duckdb
    from rezono_compiler import batch, calc, emit, explain, rules_dl, scenarios, seal
    from rezono_compiler import checks as check_meta
    from rezono_compiler import facts as fact_files
    from rezono_compiler import pack as packs
    from rezono_compiler import rules as ir
    from rezono_compiler import sources as provenance
    from rezono_compiler.rules_dl import PROTECTED

    timing.switch("compile")
    pack_dir = Path(pack_dir)
    model = packs.read(pack_dir)
    if model.meta["theory"]:
        raise Blocked("a theory pack cannot publish an instance")
    schemas = [yaml.safe_load(f.read_text(encoding="utf-8")) for f in sorted((pack_dir / "schema").glob("*.yaml"))]
    if unchecked_invariants(schemas):
        raise Blocked("the schema declares invariants (annotation `invariants`) that the engine does not check yet")
    files = emit.compile_pack(model)
    timing.switch("batch")  # facts in, relations and checks, then the rules and every witness instance
    facts: dict[str, list] = {}
    for f in fact_files.files(pack_dir):
        for table, rs in fact_files.load(model, f).items():
            facts.setdefault(table, []).extend(rs)
    params = {t: [tuple(r.values()) for r in rs] for t, rs in emit.parameters(model).items()}
    admitted = admitted_rows(evidence)  # after the facts, before the rules

    db = duckdb.connect()
    db.execute(emit.DUCKDB_FUNCTIONS)  # RLIKE for pattern checks, as in Feldera
    db.execute(emit.duckdb(files["engine/tables.sql"]))
    db.execute(emit.duckdb(files["engine/integrity.sql"]))
    for table, rs in sorted((params | facts).items()):
        if rs:
            db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
    # One view per check kind. Each logical check gets its count from validation_result,
    # 0 when it has no rows, under the name it always had.
    logical = json.loads(files["bundle/schema-bundle.json"])["checks"]
    counts = dict(db.execute("SELECT info, COUNT(*) FROM validation_result GROUP BY info").fetchall()) if logical else {}
    checks = [{"name": c["view"], "status": "red" if counts.get(c["view"]) else "green",
               "violations": counts.get(c["view"], 0)} for c in logical]
    # The check metadata (rezono__*) is schema, in the bundle: no snapshot of it, and the checker compares it.
    tables = [r[0] for r in db.execute("SELECT table_name FROM information_schema.tables "
                                       "WHERE table_type = 'BASE TABLE' ORDER BY table_name").fetchall()
              if not r[0].startswith(check_meta.P)]
    # Refused and accepted input of a seal are named rows, not violations: in the snapshot
    # like a table, from the engine's SQL, so the checker holds them against the rows the rules read.
    tables += [n for n, _ in seal.views(model)]
    # The check metadata as the engine loaded it, duplicates kept: the checker compares it with the bundle.
    metadata = [r[0] for r in db.execute("SELECT table_name FROM information_schema.tables WHERE table_type = "
                                         "'BASE TABLE' ORDER BY table_name").fetchall() if r[0].startswith(check_meta.P)]
    check_metadata = {t: [tuple(text(v) for v in r) for r in db.execute(f"SELECT * FROM {emit.q(t)}").fetchall()]
                      for t in metadata}
    rows = {t: sorted({tuple(text(v) for v in r) for r in db.execute(f"SELECT * FROM {emit.q(t)}").fetchall()})
            for t in tables}

    calc_program = calc.build(model, model.calc) if model.calc is not None else None
    calc_witnesses, witnesses, protected = [], [], {}
    if model.rules:  # the calculation in its phase of the rules, on the same tables
        prog = ir.load(model.rules)
        # The protected relations the pack declares take the admitted rows as base rows, and appear in the
        # snapshots like any other base relation; admitted rows for an undeclared one are not inserted.
        protected = {n: admitted.get(n, []) for n in sorted(PROTECTED) if n in prog.relations}
        # Only a `.decl` with the fixed signature makes a protected relation. A table of the schema under that
        # name (the compiler refuses it) would lose its own facts to the admitted rows, without a finding.
        for name in protected:
            key = [(c.name, c.type) for c in prog.relations[name].key]
            if name in rules_dl.base_tables(model) or name in rows or key != PROTECTED[name]:
                raise Blocked(f"rezono:evidence: {name} is a protected admission input, but the pack has it "
                              "as a table of its own; only `.decl` with the fixed signature declares it")
        for name, rs in protected.items():
            rows[name] = sorted({tuple(text(v) for v in r) for r in rs})
        con = batch.connect(prog, scenarios.rule_rows(model, prog, facts | protected))
        calc_witnesses = batch.phases(con, prog, calc_program, lambda: calculate(calc_program, db, con, rows),
                                      compute_rules) or []
        derived = batch.read(con, prog)
        for name in sorted(n for n, r in prog.relations.items() if r.invariant):
            n = len(derived.get(name, ()))
            checks.append({"name": name, "status": "red" if n else "green", "violations": n})
        checks += rule_checks(con, prog)
        # Every instance, not only the chosen proof: the publisher chooses a proof per role among the
        # instances that role can read.
        thetas = batch.witnesses(con, prog)
        ex = explain.Explainer(prog, batch.read(con, prog, prog.base_used()) | derived, thetas)
        witnesses = [ex.instance(prog.rules[rid], dict(zip(prog.rules[rid].variables, theta)))
                     for rid in sorted(thetas) for theta in thetas[rid]]
        for name in sorted(derived):
            rows[name] = sorted(derived[name])
    elif calc_program is not None:
        calc_witnesses = calculate(calc_program, db, duckdb.connect(), rows)

    timing.switch("compile")  # the hashes of what the epoch was made with: the compiler's sources, the pack
    return Epoch(
        pack=model.meta["name"], theory=model.meta["theory"], epoch=epoch, knowledge_time=knowledge_time,
        pack_sha256=tree_sha256(pack_dir), definition_sha256=definition_sha256(pack_dir),
        columns=columns(model) | {n: (None,) * len(PROTECTED[n]) for n in protected},  # values, no element
        compiler_sha256=canonical_sha256(compiler_parts()), build=build_record(),
        schema_version=str(model.meta.get("version", "")), engine=engine_component(),
        sources=list(sources), checks=checks, kinds=frozenset(model.kinds), rows=rows, witnesses=witnesses,
        check_metadata=check_metadata,
        parents={k: v.parent for k, v in sorted(model.kinds.items()) if v.parent},
        proposal=proposal, base_manifest=base_manifest, bundle=files["bundle/schema-bundle.json"],
        rules=files.get("ir/rules.json") or EMPTY_RULES,  # never empty: see publish.verify
        sweeps=files.get("ir/sweeps.json", ""), seals=tuple(s.kind for s in model.seals),
        calc=files.get("ir/calc.json", ""), calc_witnesses=calc_witnesses, assets=asset_files(pack_dir),
        fact_sources=provenance.read(model, pack_dir),  # where each base row comes from, never the engine's
        evidence=evidence)


def calculate(prog, db, con, rows: dict) -> list[dict]:
    """Run the calculation rules (batch/calc.sql) on `con`, which holds the derived relations of the rules,
    after copying in the base tables they read from `db`. Each rule's view, and each version named as
    rule@version, goes into `rows` as (subject, value, state, reason), with the evaluation date; the
    calculation witnesses come back, one per such row (contracts/proof.yaml, CalcWitness)."""
    from rezono_compiler import batch

    return batch.calculate(con, prog, db, rows)
