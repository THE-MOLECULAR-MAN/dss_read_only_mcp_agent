# Role
You are an expert Python developer specializing in the Dataiku DSS Python API (`dataikuapi`). Build a production-ready MCP server that gives an LLM **read-only** access to a remote Dataiku DSS v14.0+ instance.

---

# Objective
The LLM using this MCP server is a Dataiku sales engineer assistant. It finds and describes DSS projects suitable for customer demos by matching projects to a business problem, industry vertical, or technical use case that a prospect has described.

**Primary workflow**: Sales engineer describes a prospect → LLM uses these tools to browse a live DSS instance → LLM recommends the best-fit demo projects with supporting evidence.

## What Makes an Ideal Demo Project
A good demo project matches the prospect on:

| Signal | Examples |
|---|---|
| Use case | Fraud detection, churn prediction, demand forecasting |
| Industry / vertical | Financial services, retail, healthcare, manufacturing |
| Infrastructure | Snowflake + S3, Azure + SQL Server, on-prem Hadoop |
| AI approach | Classical ML, LLMs, agents, computer vision |

A good demo project also demonstrates **production quality**:
- Working outputs (dashboards, agents, webapps)
- Data quality rules in place on datasets
- Project standards enforced
- Descriptions filled in on the project and its datasets
- Recently built and mostly green jobs

---

# MCP Framework
Use **FastMCP** (`fastmcp` package). Declare each tool with `@mcp.tool()` and use Python type hints on all parameters and return values.

```python
from fastmcp import FastMCP

mcp = FastMCP("dss-demo-finder")

@mcp.tool()
def list_projects() -> list[dict]:
    """Return lightweight metadata for all DSS projects."""
    ...
```

---

# Connection Configuration
Credentials are read from **environment variables at startup** — do not accept `host` or `api_key` as parameters on individual tool calls. This prevents API keys from appearing in tool call logs.

| Variable | Description | Example |
|---|---|---|
| `DSS_HOST` | Full URL of the DSS instance | `https://my-dss.example.com` |
| `DSS_API_KEY` | Personal or service account API key | `abc123xyz` |

Initialize a **small, bounded pool of `DSSClient` instances** at module load time. `DSSClient` wraps `requests.Session`, which is not thread-safe — use one client per worker rather than sharing a single instance across threads.

```python
import os
import queue
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import dataikuapi

_POOL_SIZE = 6  # conservative for read-mostly metadata queries against one DSS node

def _make_client() -> dataikuapi.DSSClient:
    return dataikuapi.DSSClient(
        host=os.environ["DSS_HOST"],
        api_key=os.environ["DSS_API_KEY"],
        no_check_certificate=True,
    )

_client_pool: queue.Queue[dataikuapi.DSSClient] = queue.Queue()
for _ in range(_POOL_SIZE):
    _client_pool.put(_make_client())

_executor = ThreadPoolExecutor(max_workers=_POOL_SIZE)

@contextmanager
def _borrow_client():
    """Borrow a DSSClient from the pool; return it automatically when the block exits."""
    client = _client_pool.get()
    try:
        yield client
    finally:
        _client_pool.put(client)
```

> **Package choice**: Use `dataiku` for code running **inside** DSS (notebooks, recipes, webapps). Use `dataikuapi` for code running **outside** DSS (MCP server, local scripts, CI/CD). This MCP server always runs outside DSS — use `dataikuapi` throughout.

---

# Concurrency & Connection Model

## Design Principles
- Connect to **one DSS node at a time**.
- Workload is **read-only metadata** (listing, reading settings, checking status) — not file transfers, bulk SQL, or job execution.
- Be **polite by default**: treat DSS capacity as finite; avoid aggressive polling or bursty fan-out.
- Optimize for **correctness, clarity, and low operational risk** — not maximum throughput.

## Using the Client Pool
All tool handlers must borrow a client from the pool rather than creating a new one per call:

```python
@mcp.tool()
def list_projects() -> list[dict]:
    with _borrow_client() as client:
        return [_serialize(p) for p in client.list_projects()]
```

For `get_project_summary`, parallelize the multiple sub-calls (recipes, datasets, dashboards, etc.) by submitting each to `_executor` and collecting results with a timeout:

```python
def get_project_summary(project_key: str) -> dict:
    futures = {
        "recipes":    _executor.submit(_fetch_recipes, project_key),
        "datasets":   _executor.submit(_fetch_datasets, project_key),
        "dashboards": _executor.submit(_fetch_dashboards, project_key),
        "jobs":       _executor.submit(_fetch_recent_jobs, project_key),
        # ... other sub-calls
    }
    results = {}
    for key, future in futures.items():
        try:
            results[key] = future.result(timeout=30)
        except Exception as e:
            results[key] = {"error": str(e)}
    return results
```

Each helper (`_fetch_recipes`, etc.) must use `_borrow_client()` internally so it gets its own thread-safe client from the pool.

## Timeouts
Set explicit read timeouts on the underlying `requests.Session` when creating each client. This prevents a slow or hung DSS call from blocking a worker indefinitely:

```python
def _make_client() -> dataikuapi.DSSClient:
    client = dataikuapi.DSSClient(...)
    client._session.timeout = (10, 60)  # (connect_timeout_s, read_timeout_s)
    return client
```

> Verify that `_session` is the correct attribute name for the underlying session in the installed `dataikuapi` version.

## Retry with Exponential Backoff
Apply retry only to **safe, idempotent read operations**. A minimal implementation:

```python
import time

def _retry_read(fn, max_attempts: int = 3, base_delay: float = 1.0):
    """Retry a no-argument callable with exponential backoff. Raises on final failure."""
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))
```

If `tenacity` is already a project dependency, prefer it over a hand-rolled loop.

## What to Avoid
- Creating a new `DSSClient` inside each tool call or sub-call
- Sharing a single `DSSClient` across multiple threads
- `ThreadPoolExecutor` with `max_workers` above ~8 for this workload
- Unbounded `asyncio` fan-out or one-coroutine-per-project patterns
- Tight polling loops without backoff
- Submitting all projects to the executor simultaneously (iterate in bounded batches instead)

---

# Tools to Implement
Each tool must return a JSON-serializable `dict` or `list[dict]`. Never return raw DSS handle objects to the MCP client.

## `list_projects`
Return lightweight metadata for all projects. This is the starting point — the LLM scans this list to identify candidates, then calls `get_project_summary` for specifics.

**Do not** fetch full details upfront (see [Performance](#3-performance--lazy-loading)).

**Returns a list, one entry per project:**
- `project_key` — unique identifier (e.g., `"CHURN_PREDICTION"`)
- `name` — display name
- `short_desc` — short description
- `tags` — list of string tags
- `owner_login` — owner's login name
- `last_modified_on` — Unix timestamp (ms) of last project modification

---

## `get_project_summary`
Return comprehensive detail for a single project. Designed to be called **after** `list_projects` has narrowed the candidate set. This tool makes multiple API calls and may take several seconds per project.

**Parameters:** `project_key: str`

**Returns the following fields** (use `None` or `[]` for any field that cannot be retrieved — do not omit fields):

```python
{
    # --- Identity ---
    "project_key": str,
    "name": str,
    "short_desc": str,
    "tags": list[str],
    "owner_login": str,

    # --- Timestamps ---
    "last_modified_on": int | None,       # Unix ms; indicates how current the project is
    "last_built_on": int | None,          # Unix ms of the most recent completed job (any status)

    # --- Project Origin (best-effort inference; see Origin Inference section) ---
    "inferred_origin": str,               # "solutions_hub" | "tutorial" | "imported" | "original" | "unknown"
    "origin_evidence": list[str],         # tags or metadata strings that support the inference

    # --- Recipes ---
    "recipe_count": int,
    "recipe_counts_by_category": {
        "visual": int,                    # shaker, join, sync, split, grouping, etc.
        "code": int,                      # python, r, sql, pyspark, spark_scala, etc.
        "prompt_llm": int,                # LLM / prompt recipes (see Recipe Taxonomy)
        "plugin": int,                    # recipes from installed plugins
    },
    "recipe_types_present": list[str],    # raw DSS type strings, e.g. ["python", "shaker", "llm"]

    # --- Datasets & Connections ---
    "dataset_count": int,
    "connection_types_used": list[str],   # storage backend types, e.g. ["Snowflake", "S3", "Filesystem"]
    "connection_names_used": list[str],   # DSS connection names (the named connection objects)
    "pct_datasets_with_dq_rules": float | None,  # 0.0–1.0; fraction of datasets with ≥1 data quality rule

    # --- AI / LLM / Agents (DSS 14.x — see Agent API Caution) ---
    "llm_connection_names": list[str],    # names of LLM connections used in the project
    "has_agents": bool,
    "agent_count": int,
    "has_agent_tools": bool,
    "has_agent_hub": bool,

    # --- Dashboards ---
    "dashboard_count": int,
    "total_tile_count": int,              # sum of all tiles/charts across all dashboards
    "in_workspace": bool,                 # true if any dashboard or content is shared in a Dataiku Workspace
    "workspace_names": list[str],         # names of Dataiku Workspaces referencing this project

    # --- Web Apps ---
    "webapp_count": int,
    "webapp_types": list[str],            # e.g. ["STANDARD", "SHINY", "BOKEH", "DASH"]

    # --- Plugins ---
    "plugins_used": list[str],            # plugin IDs referenced by recipes or datasets in this project

    # --- Automation ---
    "scenario_count": int,

    # --- Flow Complexity ---
    "flow_zone_count": int,               # number of flow zones; proxy for project size and organization

    # --- ML ---
    "ml_task_count": int,
    "ml_tasks": [
        {
            "name": str,
            "task_type": str,             # e.g. "BINARY_CLASSIFICATION", "REGRESSION", "CLUSTERING"
            "algorithm": str | None
        }
    ],

    # --- Job Health (last 3–5 completed jobs) ---
    "recent_job_success_rate": float | None,  # 0.0–1.0; None if no completed jobs found
    "recent_jobs_evaluated": int,             # actual count inspected (may be < 5)

    # --- Project Quality ---
    "project_standards_enforced": int,    # count of enabled project standards / checklists
}
```

---

## `list_all_tags`
Return a deduplicated, sorted list of all tags used across all projects. Lets the LLM understand the available taxonomy before searching.

**Returns:** `list[str]`

---

## `get_node_info`
Return basic metadata about the DSS node itself.

**Returns:** `{dss_version, node_type, node_id}`

---

# Implementation Notes

These notes map each return field to the DSS API calls most likely to provide it. Verify field names against the DSS 14.x API reference before finalizing — exact key names can vary by minor version.

## Timestamps
- `last_modified_on`: available in `_client.list_projects()` summary dicts (look for a timestamp or `versionTag` field).
- `last_built_on`: call `project.list_jobs(active=False, limit=1)` and read the `startTime` or `endTime` of the first result.

## Recipe Categorization
Call `project.list_recipe_names()` or `project.list_recipes()`. Each recipe summary dict contains a `type` field. Categorize using the taxonomy below.

### Recipe Type Taxonomy

| Category | Typical DSS `type` values |
|---|---|
| **Visual** | `shaker`, `join`, `sync`, `split`, `sampling`, `grouping`, `distinct`, `pivot`, `top_n`, `filter`, `sort`, `window`, `merge_fuzzy`, `vstack`, `download`, `export` |
| **Code** | `python`, `r`, `sql`, `hive`, `spark_scala`, `pyspark`, `spark_r`, `shell`, `impala` |
| **Prompt / LLM** | `llm` — verify the exact type string against DSS 14.6 docs; it may differ |
| **Plugin** | Any type string that contains a dot (`.`) or that doesn't appear in the above lists |

## Datasets & Connections
- `project.list_datasets()` returns a list of dataset summary dicts. Each contains a `type` field (the storage backend, e.g. `Snowflake`, `S3`, `Filesystem`) and a `params.connection` field with the DSS connection name.
- Deduplicate connection names and types across all datasets.

## Data Quality Rules (`pct_datasets_with_dq_rules`)
For each dataset, retrieve its settings and check for data quality rules:

```python
ds_handle = project.get_dataset(dataset_name)
raw = ds_handle.get_settings().get_raw()
has_rules = bool(raw.get("checks", []))  # or "dataQualityRules" — verify field name
```

> **Performance**: Checking DQ rules requires one API call per dataset. Cap at 50 datasets per project to bound execution time. If capped, note the cap in the return value.

## Agents & LLM (DSS 14.x)
> **Caution**: The agent API surface is new in DSS 14.x and may not be fully exposed in `dataikuapi` 14.6. Before implementing, search the API reference for agent-related methods. If unavailable, return `has_agents: false` and `agent_count: 0` with a note in the response. Do not guess at method names.

Likely approaches (verify each):
- LLM connections: `project.list_llm_confs()` or inspect `project.get_settings().get_raw()` for LLM configuration blocks.
- Agents: look for flow items or recipes with a type matching `agent` or similar. May also appear in a dedicated `project.list_agents()` method if present.
- Agent Hub: look for agent hub configuration in project settings.

## Dashboards
```python
dashboards = project.list_dashboards()       # list of dashboard summary dicts
dashboard_count = len(dashboards)
total_tiles = sum(
    len(project.get_dashboard(d["id"]).get_raw().get("pages", [{}])[0].get("tiles", []))
    for d in dashboards
)
```
> Verify the exact structure of dashboard pages and tiles in the raw dict.

## Workspaces (`in_workspace`, `workspace_names`)
> **Caution**: Workspace API availability depends on node type and DSS version. Verify `client.list_workspaces()` exists before calling it.

If available, iterate workspaces and check whether any content item references this `project_key`. If the workspace API is unavailable, return `in_workspace: false` and `workspace_names: []` without raising an error.

## Plugins Used
Collect plugin IDs from two sources:
1. **Plugin recipes**: recipes in the **Plugin** category above; extract the plugin ID from the recipe type string.
2. **Plugin datasets**: datasets whose `type` field matches an installed plugin's dataset type. Cross-reference with `_client.list_plugins()`.

## Project Standards (`project_standards_enforced`)
```python
raw = project.get_settings().get_raw()
standards = raw.get("projectStatus", {}).get("statusChecks", [])  # verify field path
project_standards_enforced = sum(1 for s in standards if s.get("enabled", False))
```

## Job Health (`recent_job_success_rate`)
```python
jobs = project.list_jobs(active=False, limit=10)
completed = [j for j in jobs if j.get("state") not in ("RUNNING", "WAITING", "QUEUED")]
recent = completed[:5]
if recent:
    success_rate = sum(1 for j in recent if j.get("state") == "DONE") / len(recent)
```

## Project Origin Inference
Infer `inferred_origin` from tags and available metadata. This is a best-effort heuristic, not a guaranteed fact — always populate `origin_evidence` with the signals used.

| Origin | Signals to look for |
|---|---|
| `solutions_hub` | Tags containing `solutions`, `solutions-hub`, or `solutions_hub`; project key patterns; `projectAppType` in project settings |
| `tutorial` | Tags containing `tutorial`, `getting-started`, `training`, `onboarding` |
| `imported` | Metadata fields indicating an import source (check project settings raw dict for import provenance fields) |
| `original` | No signals match any of the above |
| `unknown` | Metadata could not be retrieved |

---

# Error Handling
**All tools must catch all exceptions and return structured error dicts.** Never let an unhandled exception propagate and crash the MCP server process.

## Connection and Authentication Errors
```python
@mcp.tool()
def list_projects() -> list[dict] | dict:
    try:
        ...
    except dataikuapi.utils.DataikuException as e:
        return {"error": "dss_api_error", "detail": str(e)}
    except Exception as e:
        return {"error": "unexpected_error", "detail": str(e)}
```

Common failure modes:
- **Wrong host / network timeout**: `ConnectionError`, `requests.exceptions.ConnectTimeout`
- **Invalid API key**: DSS returns HTTP 401; `dataikuapi` raises an exception
- **SSL errors**: `ssl.SSLError`

## Per-Object Errors During List Operations
When iterating over projects or their children, skip or annotate broken objects rather than aborting the entire list:

```python
results = []
for proj_key in project_keys:
    try:
        results.append(_fetch_project_details(proj_key))
    except Exception as e:
        results.append({"project_key": proj_key, "error": str(e)})
return results
```

## Missing or Unavailable Features
If an API method does not exist on this DSS version, catch `AttributeError` and return the relevant fields as `None` or `[]` rather than raising. Include a `"_notes"` key in the response to flag which fields were unavailable.

## Missing Fields
Use `.get(key, default)` — never direct key access — on all dicts from the DSS API. Return `None` or `[]` for absent fields; do not omit them.

---

# Security & Data Handling

## Sensitive Data Redaction
Some DSS API methods return credentials (e.g., `get_basic_credential()`). Before returning any data, replace the *values* of these field names with `"[REDACTED]"`:

`password`, `passwd`, `secret`, `apiKey`, `api_key`, `token`, `bearerToken`, `credential`, `privateKey`

Apply redaction recursively to nested dicts and lists.

## API Key Safety
Never log, echo, or include the value of `DSS_API_KEY` in any tool response or error message.

---

# Restrictions — Read-Only Enforcement
**Never call any method that modifies DSS state.**

### Safe method prefixes
`get_`, `list_`

### Forbidden method prefixes — never use
`build_`, `create_`, `delete_`, `duplicate_`, `install_`, `new_`, `remove_`, `set_`, `train_`

### Additional forbidden actions
- Do not trigger jobs, scenarios, or any compute-consuming operation
- Do not modify project or node configuration (plugins, code environments, users, connections)
- Do not call any method that rebuilds, re-indexes, or retrains anything

---

# Code Requirements
- Python 3.11+
- PEP-8 compliant
- PEP-484 compliant (type hints on all function signatures)
- Modular: break logic into focused helper functions; avoid monolithic tool handlers
- Comments only where the logic is non-obvious (no narrative docstrings)

---

# API Pitfalls & Cautions

## 1. Return Types Vary
`list_projects()`, `get_project()`, `list_code_envs()`, and similar methods return different types: handles, lists of handles, lists of dicts, or plain strings. Check the API reference for the exact return type before accessing attributes.

## 2. Object Data Requires `.get_raw()`
Most DSS handle objects are wrappers. Call `.get_raw()` — or `.get_settings().get_raw()` for settings-bearing objects — to get the underlying dict.

```python
plugin_handle = _client.get_plugin("my-plugin")
raw = plugin_handle.get_raw()
name = raw.get("name", None)  # always .get(), never raw["name"]
```

## 3. Performance — Lazy Loading
This instance may have up to 5,000 projects. **Never fetch full details for every object upfront.** The intended call pattern is:

1. `list_projects()` → lightweight scan of all projects
2. `get_project_summary(project_key)` → deep fetch for a handful of candidates only

`get_project_summary` itself is intentionally heavier (multiple API calls per project) and is only called for specific projects of interest, not in a loop over all projects.

For resource types where `list_*` returns full details by default, pass `as_objects=True` to get handles only:

```python
code_env_handles = _client.list_code_envs(as_objects=True)  # fast on large instances
```

## 4. Wrap Per-Object Accessors in try/except
Projects and their child objects (datasets, recipes, analyses) can be in broken states. Always wrap per-object detail fetching, especially inside loops.

---

# Reference Documentation
- **Dataiku Python API Reference**: https://developer.dataiku.com/latest/api-reference/python/client.html#dataikuapi.DSSClient
- **FastMCP**: https://github.com/jlowin/fastmcp
