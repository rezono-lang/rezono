from hypothesis import settings

# Fixed seed and no example database: a test run gives the same result everywhere.
settings.register_profile("rezono", derandomize=True, database=None, max_examples=200, deadline=None)
settings.load_profile("rezono")
