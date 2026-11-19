import os

from hypothesis import settings

# Fixed seed and no example database: a pull-request run gives the same result everywhere.
settings.register_profile("rezono", derandomize=True, database=None, max_examples=200, deadline=None)
# The nightly property run (.github/workflows/property-nightly.yml) draws fresh worlds from the seed in its log.
settings.register_profile("nightly", derandomize=False, database=None, max_examples=5000, deadline=None)
settings.load_profile("nightly" if os.environ.get("REZONO_HYPOTHESIS_PROFILE") == "nightly" else "rezono")
