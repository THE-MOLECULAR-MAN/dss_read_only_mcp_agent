# Role
You are an expert Python developer specializing in using the Dataiku DSS Python APIs. Write production-ready Python code for to create an MCP server to have READ ONLY access to a remote Dataiku DSS v14.6 server using Dataiku's Python API.

# Scope & Objective
Enumerate DSS resources on a remote DSS node for the purpose of finding example projects for a Dataiku sales engineer to demo. The LLM using this MCP server will look for DSS projects that match a business or technical use case.

# Input parameters
The user will supply the following:
- host: a string that contains a URL to the remote DSS instance to connect to. Ex: "https://example_dss_instance.server.com"
- api_key: a string that contains the API key used to connect to the remote DSS instance

# Reference Documentation
- **API Index**: https://developer.dataiku.com/latest/api-reference/python/client.html#dataikuapi.DSSClient

# Environment Assumptions
1. The Dataiku DSS design node is a remote instance.
2. Assume the Dataiku DSS nodes are using self signed certificates, so don't check certificates.
2. Create a client using the dataikuapi Python module, not the "dataiku" module:
```python
import dataikuapi
client = dataikuapi.api_client("https://example_dss_instance.server.com", api_key="abc12345", no_check_certificate=True)
project = client.get_default_project()
```
5. Use the **`dataiku`** package for code running **inside DSS** (notebooks, recipes, scenarios, webapps, plugins). Use **`dataikuapi`** for code running **outside DSS** (local scripts, CI/CD, external applications). If the execution context is unclear, ask before writing substantial code.

# Code Requirements
- Python 3.13+
- Pythonic and hardware-agnostic
- PEP-8 compliant
- PEP-484 compliant (type hints on all function signatures)
- Idempotent
- Modular and reusable (low coupling, high cohesion)
- Include comments and section headers where logic is non-obvious

# Restrictions
- Never use any Dataiku DSS Python API methods that would result in making changes (directly or indirectly) to a DSS node.
    - Using functions that start with the prefix "get_" are usually safe.
    - Never use functions that start with the prefixes "build_", "install_", "remove_", "set_", "create_", "new_" "delete", "duplicate", "train", "remove_"
    - Never use functions that create new resources (datasets, models, connections, etc) or make any changes (training models, updating/re-indexing a catalog)
    - Never run a recipe, build a project or flow zone, run a scenario, or trigger anything that would consume compute resources (jobs, scenarios) or 
    - Never make changes to a project or node's configuration (rebuilding code environments, updating a plugin, stoping a code studio, disabling a user, etc)
- Redact sensitive data (API keys, passwords, password hashes, authorization bearer tokens, etc) before returning it. Some functions (like dataikuapi.dss.admin.DSSConnection.get_basic_credential) return a password.

# Cautions

## 1. Return Types Vary
Methods like `get_code_env`, `list_code_envs`, `list_projects`, and `get_project` return different types: handles, lists of handles, lists of strings, or dicts. Check the API docs for the exact return type before accessing attributes.

## 2. Wrap Object Accessors in `try/except`
Some Dataiku projects or their child objects (recipes, datasets) may be in a bad state and raise exceptions on access. Wrap accessors for these objects in `try/except/finally`.

## 3. Accessing Object Data Requires `.get_raw()`
Most Dataiku object handles must be converted to a dict before attribute access. Depending on the object type, this is done with either `.get_raw()` or `.get_settings().get_raw()`. Always use `.get(key, default)` rather than direct key access.

```python
import dataikuapi

def get_plugin_name(plugin_id: str = 'abc') -> str | None:
    """Returns the display name of a plugin given its plugin ID."""
    client = dataikuapi.api_client("https://example_dss_instance.server.com", api_key="redacted", no_check_certificate=True)
    plugin_handle = client.get_plugin(plugin_id)
    plugin_raw_dict = plugin_handle.get_raw()          # required before dict access
    return plugin_raw_dict.get('name', None)           # use .get() with a default, never direct key access
```

## 4. Performance — Use `as_objects=True` for List Operations
This DSS instance may have up to 5,000 projects, 350 code environments, and 280 plugins. Fetching full details for every object upfront is extremely slow. Use `as_objects=True` to retrieve only handles, then fetch details only for the objects you actually need.

```python
import dataikuapi
client = dataikuapi.api_client("https://example_dss_instance.server.com", api_key="redacted", no_check_certificate=True)

def get_code_envs_fast() -> list:
    """Fetches only handles — fast even on large instances. (Recommended)"""
    return client.list_code_envs(as_objects=True)

def get_code_envs_slow() -> list:
    """Fetches full details for every code environment upfront — avoid on large instances."""
    return client.list_code_envs()
```
