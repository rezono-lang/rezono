import os
import sys
from pathlib import Path

from hypothesis import HealthCheck, settings

sys.path.insert(0, str(Path(__file__).parent))
# Bounded per pull request (docs/ci.md); the nightly run sets REDE_HYPOTHESIS_PROFILE=nightly.
settings.register_profile("pr", max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("nightly", max_examples=5000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile(os.environ.get("REDE_HYPOTHESIS_PROFILE", "pr"))
