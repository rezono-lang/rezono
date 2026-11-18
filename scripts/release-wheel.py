"""Build the distribution from the same component metadata used by editable installs."""
import json
import shutil
import sys
import tomllib
from pathlib import Path

from setuptools import Distribution
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.build_py import build_py

ROOT = Path.cwd()
VERSION = json.loads(Path("rezono/package.json").read_text())["version"]
PROJECTS = ("admission", "canon", "checker", "compiler", "edge/publisher", "publication")
metadata = [tomllib.loads((ROOT / name / "pyproject.toml").read_text())["project"] for name in PROJECTS]
local = {project["name"] for project in metadata}
dependencies = sorted({req for project in metadata for req in project["dependencies"] if req not in local}
                      | {"duckdb>=1.1"})


class Build(build_py):
    def run(self):
        target = Path(self.build_lib)
        runtime = target / "rezono_runtime"
        for directory, project in zip(PROJECTS, metadata, strict=True):
            source = ROOT / directory
            dest = runtime / directory
            dest.mkdir(parents=True)
            shutil.copyfile(source / "pyproject.toml", dest / "pyproject.toml")
            module = project["name"].replace("-", "_")
            for item in sorted((source / module).rglob("*")):
                if item.suffix in {".py", ".yaml"} and item.is_file():
                    member = dest / item.relative_to(source)
                    member.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(item, member)
            # The publisher fingerprints each component's installed dependency graph.
            info = dest / f"{module}-{VERSION}.dist-info"
            info.mkdir()
            requirements = "".join(f"Requires-Dist: {req}\n" for req in project["dependencies"])
            (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {project['name']}\nVersion: {VERSION}\n{requirements}")
        for pattern in ("contracts/*.yaml", "requirements/*.txt", "requirements/.python-*"):
            for item in sorted(ROOT.glob(pattern)):
                dest = runtime / item.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, dest)
        (target / "rezono_runtime.pth").write_text("".join(f"rezono_runtime/{name}\n" for name in PROJECTS))


def main():
    out = Path(sys.argv[1]).resolve()
    work = Path(sys.argv[2]).resolve()
    dist = Distribution({
        "name": "rezono", "version": VERSION,
        "description": "Rezono reasoning engine and command-line tools",
        "python_requires": ">=3.11", "install_requires": dependencies,
        "extras_require": {"s3": ["boto3>=1.35.10"]},
        "packages": ["rezono_canon"], "package_dir": {"rezono_canon": "canon/rezono_canon"}, "cmdclass": {"build_py": Build},
        "license_files": ["LICENSE", "NOTICE", *(f.as_posix() for f in sorted(Path("LICENSES").glob("*.txt")))],
        "entry_points": {"console_scripts": [
            "rezono=rezono_compiler.__main__:main", "rezono-checker=rezono_checker.__main__:main",
            "rezono-publish=rezono_publisher.__main__:main",
        ]},
    })
    dist.script_name = "scripts/release-wheel.py"
    dist.get_command_obj("build").build_base = str(work / "build")
    dist.get_command_obj("egg_info").egg_base = str(work)
    wheel = bdist_wheel(dist)
    wheel.dist_dir = str(out)
    wheel.bdist_dir = str(work / "wheel")
    wheel.ensure_finalized()
    wheel.run()


if __name__ == "__main__":
    main()
