"""
Set fake env vars before any dss_mcp module is imported.
client.py populates its connection pool at import time using these vars;
without them os.environ["DSS_HOST"] raises a KeyError before any test runs.
dataikuapi.DSSClient construction is lazy (no network calls), so fake values
are sufficient to get a valid (but unusable) pool for unit tests.
"""
import os

os.environ.setdefault("DSS_HOST", "http://test-dss-host")
os.environ.setdefault("DSS_API_KEY", "test-api-key-unit-tests")
