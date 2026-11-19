"""Entry point for the language usage inventory, which lives in scripts/language_usage.py.

The tests in this folder import it as `language_usage`, and the coverage step of the CI summary runs
this file. Change the inventory in scripts/language_usage.py, not here.
"""

import importlib.util
from pathlib import Path
import sys


def _load():
    name = "rezono_language_usage"
    if name in sys.modules:
        return sys.modules[name]
    source = Path(__file__).resolve().parents[3] / "scripts" / "language_usage.py"
    spec = importlib.util.spec_from_file_location(name, source)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module


_inventory = _load()
globals().update({key: value for key, value in vars(_inventory).items() if not key.startswith("__")})


if __name__ == "__main__":
    print(_inventory.render())
