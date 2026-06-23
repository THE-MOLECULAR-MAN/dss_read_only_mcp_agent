# DSS Demo Finder — MCP Server

A read-only [Model Context Protocol](https://modelcontextprotocol.io/) server that connects Claude to a live Dataiku DSS Design node. It is designed to help sales engineers quickly find DSS projects that match a prospect's business problem, industry vertical, or technical use case.

## What it does

The server exposes four MCP tools to Claude:

| Tool | Description |
|---|---|
| `list_projects` | Returns lightweight metadata for every project visible to the API key (name, tags, owner, last modified). Use this to scan and shortlist candidates. |
| `get_project_summary` | Returns deep detail for a single project: recipe/dataset counts by type, connections used, dashboards, agents, LLM connections, scenarios, ML tasks, notebooks, job success rate, data quality coverage, workspace membership, and more. |
| `list_all_tags` | Returns a deduplicated, sorted list of every tag used across all projects — useful for understanding the available taxonomy before searching. |
| `get_node_info` | Returns the DSS version, node type, and node ID. |

`get_project_summary` makes up to 16 parallel API calls per project and is designed to be called only on specific candidates, not in a bulk loop.

## Requirements

- Python 3.11 or later
- A running Dataiku DSS Design node (DSS 14.x recommended)
- A DSS API key (personal API key with at least project-member access; admin-level preferred for full coverage)
- Claude Desktop

## Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd dss_read_only_mcp_agent
```

### 2. Create a virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 3. Configure Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) and add the server under `mcpServers`. Replace the placeholder values with your DSS instance URL and API key.

```json
{
  "mcpServers": {
    "dss-demo-finder": {
      "command": "/path/to/.venv/bin/python",
      "args": ["-m", "dss_mcp"],
      "cwd": "/path/to/dss_read_only_mcp_agent",
      "env": {
        "DSS_HOST": "https://your-dss-instance.example.com",
        "DSS_API_KEY": "your-api-key-here",
        "PYTHONPATH": "/path/to/dss_read_only_mcp_agent/src"
      }
    }
  }
}
```

**Finding your API key in DSS:** Profile → API Keys → Personal API Keys → New Key.

**Note:** Claude Desktop is a GUI app and does not inherit shell environment variables. Credentials must be placed directly in the `env` block — `${VAR}` expansion does not work here.

Restart Claude Desktop after saving the config. The `dss-demo-finder` server should appear in the MCP servers list.

## Example conversation

Once connected, you can ask Claude things like:

> *"I'm meeting with a retail company that wants to see how Dataiku handles demand forecasting. Show me the best demo projects on this DSS instance."*

Claude will:
1. Call `list_projects` to get all visible projects and their tags.
2. Identify candidates by name, tags, and description.
3. Call `get_project_summary` on each candidate to evaluate demo readiness (dashboards, recent job success, agents, data quality rules, contributor activity, etc.).
4. Rank and explain the top matches.

---

> *"Find projects that use LLM connections or AI agents and have working dashboards."*

> *"Which projects have been actively maintained in the last 6 months and have a high job success rate?"*

> *"Show me tutorial or solutions hub projects I could use to demonstrate the platform to a new prospect."*

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DSS_HOST` | Yes | Full base URL of the DSS Design node, e.g. `https://my-dss.example.com` (no trailing slash) |
| `DSS_API_KEY` | Yes | DSS personal API key |
| `DSS_MCP_LOG_DIR` | No | Directory for the structured JSON log file. Default: `~/.dss-mcp/` |

## Logging

The server writes a structured JSON-Lines log to `~/.dss-mcp/server.log` (or the directory set by `DSS_MCP_LOG_DIR`). Each line is a JSON object with fields `ts`, `level`, `logger`, `msg`, and any extra context. Credential field values are never written to the log.

## Security

- The server is strictly read-only. All write, build, deploy, and mutation operations are excluded by design — the underlying API calls made are limited to `get_*` and `list_*` methods.
- Credentials and secrets are redacted from all tool output before it is returned to Claude. Redaction covers sensitive field names (e.g. `password`, `apiKey`, `token`) and value patterns that match base64 blobs ≥40 chars, JWTs, or hex strings ≥32 chars.
- Project and global variable names are returned, but their values are never fetched.

## Running the tests

Install the dev dependencies (if you haven't already):

```bash
pip install -e ".[dev]"
```

Run the full test suite:

```bash
pytest
```

Run with verbose output to see each test name:

```bash
pytest -v
```

Run a specific test file:

```bash
pytest tests/test_security.py
pytest tests/test_error_handling.py
```

### What the tests cover

| File | Focus |
|---|---|
| `tests/test_security.py` | All 18 sensitive key names and all credential value patterns (base64, JWT, hex); recursive redaction; `safe_user_fields` |
| `tests/test_projects.py` | `_slim()` normalization; `list_projects` and `list_all_tags` with mocked DSS client |
| `tests/test_summary.py` | Origin inference; recipe categorization; retry-with-backoff; `_assemble()` field mapping and redaction |
| `tests/test_logging.py` | All 11 log-sensitive field names; JSON-Lines format; internal fields excluded |
| `tests/test_error_handling.py` | Every fetcher's response when DSS raises exceptions — both list-level failures (returns safe defaults) and per-item failures inside loops (skips bad item, continues with rest) |

The tests use `unittest.mock` to simulate a remote DSS node without a live connection. The connection pool in `client.py` is initialized with fake credentials at test startup and never contacted.

## Project structure

```
src/dss_mcp/
├── __main__.py          # Entry point: python -m dss_mcp
├── server.py            # FastMCP app and tool registration
├── client.py            # Connection pool (6 DSSClient instances)
├── security.py          # Credential redaction
├── logging_config.py    # Structured JSON-Lines logger
└── tools/
    ├── node.py          # get_node_info
    ├── projects.py      # list_projects, list_all_tags
    └── summary.py       # get_project_summary (16 parallel fetchers)

tests/
├── conftest.py              # Fake env vars before pool initialization
├── test_security.py
├── test_projects.py
├── test_summary.py
├── test_logging.py
└── test_error_handling.py
```
