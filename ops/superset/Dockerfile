# Extends the official Superset image with DuckDB support -- not present in the base image.
# duckdb-engine is the SQLAlchemy dialect Superset needs to connect to a DuckDB file
# (confirmed via research: this is the documented pattern, no first-party Superset/DuckDB image).
FROM apache/superset:5.0.0

USER root
# The base image's /app/.venv is uv-managed and has no pip installed in it at all (uv doesn't
# need one) -- plain `pip install` hits system Python instead, so packages silently land
# somewhere the app never sees. Use uv directly, targeting the venv explicitly.
RUN uv pip install --python /app/.venv/bin/python \
    duckdb>=1.0 duckdb-engine>=0.13 psycopg2-binary>=2.9
USER superset
