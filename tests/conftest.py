"""
Set fake env vars before any dss_mcp module is imported.
client.py populates its connection pool at import time using these vars;
without them the missing-env-var guard raises RuntimeError before any test runs.
dataikuapi.DSSClient construction is lazy (no network calls), so fake values
are sufficient to get a valid (but unusable) pool for unit tests.

dataikuapi is provided by the [dev] optional-dependency group
(via dataiku-api-client) — install with: pip install -e ".[dev]"
"""
import os

os.environ.setdefault("DSS_HOST", "http://test-dss-host")
os.environ.setdefault("DSS_API_KEY", "test-api-key-unit-tests")
