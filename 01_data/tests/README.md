# Local tests

Stage 3 generates its SQL from the contracts. `sqlite_dialect.py` runs that same SQL on SQLite so the
validation logic can be tested on a laptop without Databricks. Only a few function names differ from Spark
(see the docstring in `sqlite_dialect.py`).

Results on the original files match the profiling counts exactly (e.g. 72 under-allocated, 78 over-allocated,
607 outdated, 237 Board-date-passed, 324 review-overdue). Deliberately broken rows were quarantined with the
expected reasons, and a systemic failure (every date in the wrong format) stopped the run without replacing
the validated tables.
