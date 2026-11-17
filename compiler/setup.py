"""The build of rezono-compiler; its metadata is in pyproject.toml.

The compiler reads some of Rezono's contracts at run time (view.yaml with its imports, source.yaml). They live in the
repository's contracts/, outside this package, and stay there: building copies contracts/*.yaml byte for byte into
the package as rezono_compiler/contracts/, where an installed compiler finds them (pack.contract_dir). So build from a
checkout (`pip install ./compiler`); an sdist does not carry contracts/, and the build refuses without them.
"""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"


class BuildPy(build_py):
    def run(self):
        super().run()
        files = sorted(CONTRACTS.glob("*.yaml"))
        if not (CONTRACTS / "view.yaml").is_file():
            raise SystemExit(f"rezono-compiler: no contracts in {CONTRACTS}; build from a checkout of the repository")
        out = Path(self.build_lib, "rezono_compiler", "contracts")
        out.mkdir(parents=True, exist_ok=True)
        for f in files:
            (out / f.name).write_bytes(f.read_bytes())


setup(cmdclass={"build_py": BuildPy})
