"""No implicit existential variables in rezono 1: relation calls never bind undeclared names, bare names in
typed kind or enum positions resolve unambiguously as element IDs or enum values, and extra-column joins use
the tuple-set method form with an optional explicit binder (`Kind.any(x: ...)`, `rel.any(row: ...)`)
(decisions/language-rezono-1-refinements.md, section 1)."""

import json
from pathlib import Path
import subprocess

import pytest
from reader_probe import at, read_modules

ROOT = Path(__file__).resolve().parents[2]

VALID_MODULE = """\
rezono 1
pack sample
enum Flag
  yes
  no
kind Function
kind Zone
  outside: Flag
  entry_boundary: Flag
  isolated_recovery: Flag
kind Service
kind Edge
  src: Service
  dst: Service
derived asks(s: Service, f: Function): Bool = Service.any(it = s) and Function.any(it = f)
derived provides(s: Service, f: Function, port: Int): Bool = Service.any(it = s) and Function.any(it = f) and port = 443
derived crossing(src: Service, dst: Service, za: Zone, zb: Zone, port: Int): Bool = Edge.any(e: e.src = src and e.dst = dst) and Zone.any(it = za) and Zone.any(it = zb) and port = 443
extend s: Service
  derived authenticates: Bool = asks(s, identity) or provides(s, identity, _)
derived outside_reaches_inside(a: Service, b: Service): Bool = crossing.where(src = a and dst = b).any(za.outside = yes and zb.entry_boundary = no)
derived recovery_reached(a: Service, b: Service): Bool = crossing.where(src = a and dst = b).any(zb.isolated_recovery = yes)
derived two_hop(a: Service, c: Service): Bool = Edge.any(e1: e1.src = a and Edge.any(e2: e1.dst = e2.src and e2.dst = c))
derived explicit_row(a: Service, b: Service): Bool = crossing.any(row: row.src = a and row.dst = b and row.za.outside = yes)
"""

IMPLICIT_EXISTENTIAL_PATH = """\
rezono 1
pack sample
enum Flag
  yes
  no
kind Zone
  outside: Flag
  entry_boundary: Flag
kind Service
derived crossing(src: Service, dst: Service, za: Zone, zb: Zone, port: Int): Bool = Service.any(it = src) and Service.any(it = dst) and Zone.any(it = za) and Zone.any(it = zb) and port = 443
derived outside_reaches_inside(a: Service, b: Service): Bool = crossing(a, b, za, zb, _) and za.outside = yes and zb.entry_boundary = no
"""

UNDECLARED_NON_KIND_ARG = """\
rezono 1
pack sample
kind Zone
kind Service
derived crossing(src: Service, dst: Service, za: Zone, zb: Zone, port: Int): Bool = Service.any(it = src) and Service.any(it = dst) and Zone.any(it = za) and Zone.any(it = zb) and port = 443
derived bad_port(a: Service, b: Service): Bool = crossing(a, b, zone_a, zone_b, port_var)
"""

REZONO_0_NATIVE = """\
rezono 0
pack sample
rule linked(a: Item) when edge(a, b) and b.active
"""

PROBE = """\
import * as rezono from './rezono/src/index.ts';

const sources = JSON.parse(process.argv[1]);
const checkModule = rezono.checkModule;
if (typeof checkModule !== 'function') {
  process.stdout.write(JSON.stringify({ missing_export: 'checkModule' }));
  process.exit(0);
}
const out = sources.map((source) => {
  const checked = checkModule(source);
  const printed = checked.form ? rezono.printModule(checked.form.module) : null;
  const reparsed = printed ? rezono.moduleForm(printed) : null;
  return {
    format: checked.form?.format ?? null,
    module: checked.form?.module ?? null,
    printed,
    roundtrip_ok: Boolean(reparsed && !reparsed.diagnostics.length && JSON.stringify(reparsed.module) === JSON.stringify(checked.form?.module)),
    diagnostics: checked.diagnostics.map((d) => ({
      code: d.code,
      args: d.args ?? [],
      span: d.span,
    })),
  };
});
process.stdout.write(JSON.stringify({ results: out }));
"""


def check_sources(*sources):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROBE, json.dumps(list(sources))],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class MissingNoImplicitExistentials(AssertionError):
    """The rezono 1 reader/checker did not enforce no-implicit-existentials or explicit method binders."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingNoImplicitExistentials,
    reason="M3: decisions/language-rezono-1-refinements.md: Implement no implicit existential variables and optional "
           "explicit method binders (`Kind.any(x: ...)`, `rel.any(row: ...)`, `.where(x: ...)`) in rezono/src/ "
           "(grammar.ts, parse.ts, print-expression.ts, check.ts, and exported `checkModule` in index.ts): resolve "
           "unbound bare names in Kind/Enum call positions as element IDs or enum values (e.g. `asks(s, identity)`), "
           "never bind undeclared variables from relation calls, refuse undeclared names outside kind/enum positions "
           "(such as `za.outside` or `port_var` in an Int slot) with R001, and round-trip explicit binders. Read section 1.",
)
def test_rezono_1_no_implicit_existentials_and_explicit_binder():
    payload = check_sources(VALID_MODULE, IMPLICIT_EXISTENTIAL_PATH, UNDECLARED_NON_KIND_ARG)
    if "missing_export" in payload:
        raise MissingNoImplicitExistentials(json.dumps(payload, indent=2))
    valid, implicit_path, bad_port = payload["results"]
    problems = []

    if valid["diagnostics"] or valid["format"] != "rezono.module/5" or not valid["roundtrip_ok"]:
        problems.append({"valid_module_failed": valid})
    else:
        decls = {d["derived"]: d for d in valid["module"]["decls"] if isinstance(d.get("derived"), str)}
        explicit_row = decls.get("explicit_row", {}).get("value")
        # Explicit binder must be preserved as the 4th element of the `agg` tuple.
        if not (isinstance(explicit_row, dict) and isinstance(explicit_row.get("agg"), list)
                and len(explicit_row["agg"]) == 4 and explicit_row["agg"][3] == "row"):
            problems.append({"explicit_binder_not_preserved": explicit_row})

    path_r001 = [d for d in implicit_path["diagnostics"] if d["code"] == "R001"]
    path_names = {d["span"]["text"] for d in path_r001}
    if not {"za", "zb"}.issubset(path_names):
        problems.append({"implicit_existential_not_refused_with_r001": implicit_path})

    port_r001 = [d for d in bad_port["diagnostics"] if d["code"] == "R001"]
    want_port_span = at(UNDECLARED_NON_KIND_ARG, "port_var", after="bad_port")
    if not any(d["span"] == want_port_span for d in port_r001):
        problems.append({"undeclared_int_arg_not_r001": bad_port, "want_span": want_port_span})

    if problems:
        raise MissingNoImplicitExistentials(json.dumps(problems, indent=2))


def test_rezono_0_keeps_rule_existentials():
    """Counter-case: rezono 0 native rules keep positional existential variables in rezono.module/3."""
    [read_back] = read_modules(REZONO_0_NATIVE)
    assert read_back["diagnostics"] == [] and read_back["format"] == "rezono.module/3", read_back
