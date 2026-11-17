"""Lint the contracts and validate every fixture, in one Python process (contracts/check.sh runs it).

Layout: fixtures/<schema>/<Class>/{valid,invalid}/*.yaml. Valid files must pass, invalid files must fail.
First every contracts/**/*.yaml goes through contracts/yaml_keys.py: no key that YAML made out of text.
Each file goes through the same commands as before, `linkml-lint --ignore-warnings SCHEMA` and
`linkml-validate -s SCHEMA.yaml -C CLASS FILE`, called in this process instead of one process per file:
the same code path and options, without paying LinkML's import once per fixture (5 of checker's 9 minutes,
measured 07-11-2026). A file is valid when the command exits 0; a crash counts as invalid, as a non-zero
exit of the command did.
"""

from __future__ import annotations

import contextlib
import io
import os
import sys
from pathlib import Path

from linkml.linter.cli import main as lint
from linkml.validator.cli import cli as validate

import yaml_keys  # contracts/yaml_keys.py, beside this file


def run(command, args: list[str], quiet: bool) -> tuple[int, str]:
    """Exit code and captured output of a click command, as `command args...` on the command line."""
    out = io.StringIO()
    code = 1
    with contextlib.ExitStack() as stack:
        if quiet:
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(out))
        try:
            command.main(args=args, prog_name=command.name, standalone_mode=True)
            code = 0
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        except Exception as e:  # noqa: BLE001 - the command line exits non-zero on any crash
            print(f"{type(e).__name__}: {e}", file=out if quiet else sys.stderr)
    return code, out.getvalue()


def main() -> int:
    os.chdir(Path(__file__).resolve().parent)
    fail = 0
    # Keys YAML made out of text, such as a flow map's value split on its comma (#1020): every file, fixtures too.
    if yaml_keys.main([str(p) for p in sorted(Path(".").rglob("*.yaml"))]):
        fail = 1
    # Lint errors block; warnings (style, such as a missing description) are printed only. See AGENTS.md rule 5.
    for schema in sorted(Path(".").glob("*.yaml")):
        code, _ = run(lint, ["--ignore-warnings", str(schema)], quiet=False)
        if code:
            print(f"FAIL  lint {schema} (exit {code})")
            fail = 1
    for file in sorted(Path("fixtures").glob("*/*/*/*.yaml")):
        _, schema, cls, expect, _ = file.parts
        code, out = run(validate, ["-s", f"{schema}.yaml", "-C", cls, str(file)], quiet=True)
        got = "valid" if code == 0 else "invalid"
        if got == expect:
            print(f"ok    {file}")
        else:
            print(f"FAIL  {file} (expected {expect}, got {got})")
            print("      " + out.strip().replace("\n", "\n      "))
            fail = 1
    return fail


if __name__ == "__main__":
    sys.exit(main())
