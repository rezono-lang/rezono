"""Command line: check a pack, compile it, turn a fact file into engine rows, or apply schema operations."""

import argparse
import datetime
import json
import sys
from pathlib import Path

from . import emit, facts, modules, pack


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rezono_compiler")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compile", help="compile a pack into an output directory")
    c.add_argument("pack")
    c.add_argument("out")
    c.add_argument("--profile", type=Path, help="deploy profile (deploy/profiles/<profile>.yaml) whose engine budget "
                                               "(build_memory_mb or view_budget) bounds each Feldera pipeline (decision E6)")
    c.add_argument("--max-views", type=int, help=f"view budget per pipeline, instead of a profile's (default {emit.MAX_VIEWS})")
    c.add_argument("--previous", type=Path, help="engine/pipelines.json of an earlier compile: keep its cut where it "
                                                "still fits, so a small change moves few views")
    x = sub.add_parser("explain", help="run the rules on the batch backend (DuckDB) per fact state, and write "
                                       "one proof per derived relation with the snapshots it needs")
    x.add_argument("pack")
    x.add_argument("out")
    k = sub.add_parser("check", help="read a pack and load its fact files, without compiling: a quick check")
    k.add_argument("pack")
    f = sub.add_parser("facts", help="print a fact file as Feldera JSON updates per table")
    f.add_argument("pack")
    f.add_argument("facts")
    h = sub.add_parser("hash", help="print the hash that pins a pack in another pack's imports")
    h.add_argument("pack")
    h.add_argument("--rules", action="store_true", help="print instead the semantic hash of the pack's rule program "
                                                        "(normalise.py): equal when only variable names, body order "
                                                        "or where a rule is written differ")
    o = sub.add_parser("operate", help="apply schema operations (rezono.operations/1) to a pack in a rezono-work-* "
                                       "directory; write the migrations and impact.json to <out>")
    o.add_argument("pack")
    o.add_argument("operations")
    o.add_argument("out")
    s = sub.add_parser("close", help="print the delta (rezono.delta/1) of a seal's close: every period before --until is "
                                     "closed, every accepted row of it covered with its hash; the writer applies it")
    s.add_argument("pack")
    s.add_argument("--close", required=True, help="the identifier of the new PeriodClose")
    s.add_argument("--until", required=True, type=datetime.date.fromisoformat, help="the boundary, an ISO date")
    s.add_argument("--file", required=True, help="the fact file it goes in, as facts/<name>.yaml")
    args = p.parse_args(argv)
    if args.cmd == "hash" and not args.rules:
        print(modules.pack_hash(args.pack))
        return 0
    if args.cmd == "operate":
        from . import operate, writer
        try:
            impact = operate.operate(args.pack, args.operations, args.out)
        except (operate.OperationError, writer.WriteError, pack.CompileError, facts.LoadError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"ok {args.pack}: " + ", ".join(f"{o['index']}-{o['op']} " + ("lossless" if o["lossless"] else "lossy")
                                              for o in impact["operations"]))
        return 0
    try:
        model = pack.read(args.pack)
        if args.cmd == "hash":
            from . import normalise, rules
            print(normalise.program_sha256(rules.load(model.rules) if model.rules else None))
        elif args.cmd == "check":
            files = facts.files(args.pack)
            rows = {}
            for f in files:
                try:
                    rows[f.name] = sum(len(r) for r in facts.load(model, f).values())
                except facts.LoadError as e:
                    raise facts.LoadError(f"facts/{f.name}: {e}", e.diagnostics) from e
            print(f"ok {args.pack}: {len(model.kinds)} kinds; " + ", ".join(f"{n} {c} rows" for n, c in rows.items()))
        elif args.cmd in ("compile", "explain"):
            files = compile_files(model, args) if args.cmd == "compile" else explained(model, args.pack)
            for rel, text in files.items():
                target = Path(args.out) / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(text.encode("utf-8"))
        elif args.cmd == "close":
            from . import scenarios, seal
            states = scenarios.states(model, args.pack)
            delta = seal.close(model, states[0][1] if states else {}, args.close, args.until, args.file)
            print(json.dumps(delta | {"pack": model.meta["name"]}, ensure_ascii=False, indent=1))
        else:
            print(json.dumps(facts.ingress(model, facts.load(model, args.facts)), indent=2))
    except (pack.CompileError, facts.LoadError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def compile_files(model, args) -> dict[str, str]:
    import yaml

    budget, profile, previous = emit.MAX_VIEWS, None, None
    if args.profile:
        doc = yaml.safe_load(args.profile.read_text(encoding="utf-8")) or {}
        budget, profile = emit.view_budget(doc), str(doc.get("profile") or args.profile.stem)
    if args.max_views:
        budget = args.max_views
    if args.previous:
        previous = emit.previous_parts(json.loads(args.previous.read_text(encoding="utf-8")))
    files = emit.compile_pack(model, budget, previous, profile)
    from . import sources
    files["generated/sources.json"] = sources.compile_sources(model, args.pack)
    # Decision E6: going over the budget warns. Only a recursive core above it blocks (in the partition);
    # integrity and the calculation rules are not split yet.
    plan = json.loads(files.get("engine/pipelines.json", "{}"))
    for p in plan.get("pipelines", []):
        if "build_mb" in p and int(p["build_mb"]) > int(plan["build_memory_mb"]):
            print(f"warning: pipeline {p['name']}: an estimated {p['build_mb']} MB to build, more than the profile's "
                  f"{plan['build_memory_mb']} MB", file=sys.stderr)
    return files


def explained(model, pack_dir) -> dict[str, str]:
    """Per fact state: the first row (in key order) of every derived relation, with its proof, and
    complete snapshots of every relation those proofs refer to. A rule that reads a calculation selection runs
    after the calculation (`batch.phases`); its proof holds the calculation witnesses it reaches (decision
    W12), and the selection is a snapshot as a publication holds it (`batch.calculate`). Needs the batch extra
    (DuckDB)."""
    from . import batch, calc, explain, scenarios
    from . import rules as ir

    if not model.rules:
        return {}
    prog = ir.load(model.rules)
    calculation = calc.build(model, model.calc) if prog.calc_inputs() else None
    out = {}
    for state, rows in scenarios.states(model, pack_dir):
        con, calc_witnesses, calculated = batch.run(model, prog, rows, calculation)
        derived = batch.read(con, prog)
        data = batch.read(con, prog, prog.base_used() + prog.calc_inputs()) | derived
        ex = explain.Explainer(prog, data, batch.witnesses(con, prog))
        proofs = [explain.with_calculation(ex.proof(n, min(derived[n]), state), calc_witnesses)
                  for n in sorted(derived) if derived[n]]
        out[f"{state}/proofs.json"] = json.dumps(proofs, ensure_ascii=False, indent=1) + "\n"
        for rel in sorted({r for p in proofs for r in explain.relations_of(p)}):
            out[f"{state}/snapshots/{rel}.json"] = ex.snapshot(rel, calculated.get(rel))
    return out


if __name__ == "__main__":
    sys.exit(main())
