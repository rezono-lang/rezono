"""The package under test is the one beside this directory, installed or not."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
