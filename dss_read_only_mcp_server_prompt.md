# Role
You are an expert Python developer specializing in the Dataiku DSS Python API (`dataikuapi`). Build a production-ready MCP server that gives an LLM **read-only** access to a remote Dataiku DSS v14.0+ instance.

# Objective
The LLM using this MCP server is a Dataiku sales engineer assistant. It finds and describes DSS projects suitable for customer demos by matching projects to a business problem, industry vertical, or technical use case that a prospect has described.

**Primary workflow**: Sales engineer describes a prospect → LLM uses these tools to browse projects on a live DSS instance → LLM recommends the best-fit demo projects with supporting detail.

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

Initialize a **single shared `DSSClient`** at module load time and reuse it across all tool calls.

```python
import os
import dataikuapi

_client = dataikuapi.DSSClient(
    host=os.environ["DSS_HOST"],
    api_key=os.environ["DSS_API_KEY"],
    no_check_certificate=True,  # DSS instances commonly use self-signed certs
)
```

> **Package choice**: Use `dataiku` for code running **inside** DSS (notebooks, recipes, webapps). Use `dataikuapi` for code running **outside** DSS (MCP server, local scripts, CI/CD). This MCP server always runs outside DSS — use `dataikuapi` throughout.

---

# Tools to Implement
Each tool must return a JSON-serializable `dict` or `list[dict]`. Never return raw DSS handle objects to the MCP client.

## `list_projects`
Return lightweight metadata for all projects. Do **not** fetch full details upfront (see [Performance](#performance--lazy-loading)).

**Returns a list, one entry per project:**
- `project_key` — unique identifier (e.g., `"CHURN_PREDICTION"`)
- `name` — display name
- `short_desc` — short description
- `tags` — list of string tags
- `owner_login` — owner's login name

## `get_project_summary`
Return richer detail for a single project identified by `project_key`. Designed for the LLM to call after `list_projects` narrows candidates.

**Parameters:** `project_key: str`

**Returns:**
- All fields from `list_projects`
- `datasets` — list of `{name, type}` dicts where `type` is the storage connection type (SQL, S3, filesystem, etc.)
- `ml_tasks` — list of `{name, task_type, algorithm}` dicts (task_type: binary classification, regression, clustering, etc.)
- `scenario_names` — list of scenario names (indicates automation workflows present)
- `flow_zone_count` — number of flow zones (proxy for project complexity)

## `list_all_tags`
Return a deduplicated, sorted list of all tags used across all projects. Lets the LLM understand the available taxonomy before searching.

**Returns:** `list[str]`

## `get_node_info`
Return basic metadata about the DSS node itself.

**Returns:** `{dss_version, node_type, node_id}`

---

# Error Handling
**All tools must catch all exceptions and return structured error dicts.** Never let an unhandled exception propagate and crash the MCP server process.

## Connection and Authentication Errors
Wrap the client initialization and each tool body:

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

Common failure modes to handle:
- **Wrong host / network timeout**: `ConnectionError`, `requests.exceptions.ConnectTimeout`
- **Invalid API key**: DSS returns HTTP 401; `dataikuapi` raises an exception
- **SSL errors** (if `no_check_certificate` is ever removed): `ssl.SSLError`

## Per-Object Errors During List Operations
When iterating over projects or their children, some objects may be in a broken state and raise on access. Skip or annotate broken objects rather than aborting the entire list:

```python
results = []
for proj_key in project_keys:
    try:
        results.append(_fetch_project_details(proj_key))
    except Exception as e:
        results.append({"project_key": proj_key, "error": str(e)})
return results
```

## Missing Fields
Use `.get(key, default)` — never direct key access — on all dicts returned by the DSS API. Return `None` or `[]` for absent fields; do not omit them from the response.

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

### Safe method prefixes (read operations)
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
This instance may have up to 5,000 projects, 350 code environments, and 280 plugins. **Never fetch full details for every object upfront.** Use lightweight list calls to enumerate, then fetch details only for specific objects the caller requests.

```python
# Fast: returns a list of summary dicts directly
project_summaries = _client.list_projects()

# Only fetch full handles/details when a specific project_key is requested
project_handle = _client.get_project("MY_PROJECT_KEY")
```

For resource types where `list_*` returns full dicts by default, pass `as_objects=True` to get handles only:

```python
# Handles only — fast on large instances
code_env_handles = _client.list_code_envs(as_objects=True)
```

## 4. Wrap Per-Object Accessors in try/except
Projects and their child objects (datasets, recipes, analyses) can be in broken states. Always wrap per-object detail fetching, especially inside loops.

---

# Reference Documentation
- **Dataiku API Reference**: https://developer.dataiku.com/latest/api-reference/python/client.html#dataikuapi.DSSClient
- **FastMCP**: https://github.com/jlowin/fastmcp
