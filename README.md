# DSS Demo Finder — MCP Server for Claude

This tool connects an AI assistant directly to your Dataiku DSS instances. Once installed, you can ask Claude (or a DSS agent) to find the best demo projects for a prospect, and it will search across all connected DSS nodes in parallel, evaluate each project's demo-readiness, and return ranked recommendations with direct links.

**Example prompt:**
> *"I have a meeting tomorrow with a retail company interested in demand forecasting and LLM-powered applications. Find me the three best demo projects on our DSS instances."*

---

## Choose your setup track

- **[Track A — Claude Desktop](#track-a--claude-desktop)** — Run the server locally on your Mac; Claude Desktop talks to it
- **[Track B — DSS Agent Tool](#track-b--dss-agent-tool)** — Deploy inside DSS as a local MCP tool so any DSS agent can use it

Both tracks use the same server code and the same environment variable configuration. The only difference is where the package is installed and how credentials are supplied.

---

## Track A — Claude Desktop

### Prerequisites

Open **Terminal** (`Cmd + Space` → type Terminal → Enter) and verify each of the following.

**Python 3.11+**
```bash
python3 --version
```
You need `Python 3.11` or higher. If not installed, download from [python.org/downloads](https://www.python.org/downloads/).

**Git**
```bash
git --version
```
If not found, macOS will prompt you to install it.

**Claude Desktop** — download from [claude.ai/download](https://claude.ai/download) if needed.

---

### Step 1 — Download the server

```bash
cd ~
```
```bash
git clone https://github.com/THE-MOLECULAR-MAN/dss_read_only_mcp_agent.git
```
```bash
cd dss_read_only_mcp_agent
```

---

### Step 2 — Install the server

```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
pip install -e ".[claude]"
```

> **Note:** The `[claude]` extra installs the `dataiku-api-client` package. DSS Agent Tool installations omit this because DSS bundles the equivalent library automatically.

Save the paths printed by this command — you'll need them in Step 4:

```bash
echo "Python path: $(pwd)/.venv/bin/python" && echo "Install dir:  $(pwd)"
```

---

### Step 3 — Get your DSS API key

1. Open your DSS instance in a browser and log in.
2. Click your **profile icon** (top-right) → **Profile & Settings** → **API Keys**.
3. Click **+ New Key** (name it anything, e.g. "Claude MCP").
4. Copy the key — it looks like `dkuaps-aBcDeFgHiJkLmNoPqRsTuVwXyZ`.

> **Keep this key private.** It provides read access to everything visible to your DSS user account.

---

### Step 4 — Configure Claude Desktop

**4a. Quit Claude Desktop completely** before editing the config file (right-click Dock icon → Quit).

**4b. Open the config file:**
```bash
open -a TextEdit "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
```

**4c.** Find the `"mcpServers"` block and add the entry below. Replace the three placeholders with your actual values from Steps 2 and 3:

```json
"mcpServers": {
  "dss-demo-finder": {
    "command": "PASTE_PYTHON_PATH_HERE",
    "args": ["-m", "dss_mcp"],
    "cwd": "PASTE_INSTALL_DIR_HERE",
    "env": {
      "DSS_HOST": "https://your-dss-instance.example.com",
      "DSS_API_KEY": "PASTE_YOUR_API_KEY_HERE"
    }
  }
},
```

**Filled-in example:**
```json
"mcpServers": {
  "dss-demo-finder": {
    "command": "/Users/jsmith/dss_read_only_mcp_agent/.venv/bin/python",
    "args": ["-m", "dss_mcp"],
    "cwd": "/Users/jsmith/dss_read_only_mcp_agent",
    "env": {
      "DSS_HOST": "https://acme.dataiku-sandbox.io",
      "DSS_API_KEY": "dkuaps-aBcDeFgHiJkLmNoPqRsTuVwXyZ"
    }
  }
},
```

Save (`Cmd + S`) and close TextEdit.

> **Tip:** Use the base URL only — no trailing slash, no `/projects/` path.

---

### Step 5 — Start Claude Desktop and verify

Open Claude Desktop. Click the tools icon in the chat input bar — you should see `dss-demo-finder` with four tools: `list_projects`, `get_project_summary`, `list_all_tags`, `get_node_info`.

---

### Step 6 — Try it out

**Find demos for a prospect:**
> *"I'm meeting with a retail bank interested in fraud detection. Find me the top 3 demo projects."*

**Explore by industry or capability:**
> *"Which projects use LLM connections or AI agents and have dashboards ready to show?"*

**Check what tags exist:**
> *"What tags and industry categories do our demo projects cover?"*

---

## (Optional) Connecting to multiple DSS nodes — Claude Desktop

To search multiple DSS design nodes simultaneously, use numbered env vars instead of `DSS_HOST`/`DSS_API_KEY`:

```json
"env": {
  "DSS_NODE_1_HOST": "https://acme-design.dataiku-sandbox.io",
  "DSS_NODE_1_KEY":  "dkuaps-aBcDeFgHiJkLmNoPqRsTuVwXyZ",
  "DSS_NODE_1_NAME": "acme-design",
  "DSS_NODE_2_HOST": "https://solutions.dataiku-sandbox.io",
  "DSS_NODE_2_KEY":  "dkuaps-ZyXwVuTsRqPoNmLkJiHgFeDcBaZy",
  "DSS_NODE_2_NAME": "solutions-hub"
}
```

`DSS_NODE_N_NAME` is optional — the name is derived from the hostname if omitted. Up to 19 nodes are supported. Do not mix the `DSS_HOST` / `DSS_NODE_N_HOST` formats in the same config block.

---

## Track B — DSS Agent Tool

This track deploys the server inside DSS as a **local MCP tool**, so any DSS agent can use it without anyone installing anything locally. The agent can search across other DSS nodes (or its own) and return direct project links.

### Prerequisites

- DSS 14.x or later with the **Agents** feature enabled
- Admin or operator access to create code environments and configure agent tools
- API keys for each DSS node you want to search (same Step 3 process as Track A, once per node)

---

### Step 1 — Create a DSS code environment

In DSS: **Administration → Code envs → New Python env**

- Python version: **3.11** or higher
- Add the following packages:

```
fastmcp>=2.0
git+https://github.com/THE-MOLECULAR-MAN/dss_read_only_mcp_agent.git
```

> **Do not add `dataiku-api-client`** — DSS already bundles the equivalent `dataikuapi` library in every code environment. Installing it separately may cause a version conflict.

Build the environment.

---

### Step 2 — Create the agent tool definition

In DSS: navigate to the agent that should use this tool, go to **Tools → Add tool → Local MCP**.

Fill in the fields:

| Field | Value |
|-------|-------|
| Command | `python` |
| Arguments | `-m dss_mcp` |
| Code environment | *(the env you created in Step 1)* |

Then add environment variables (one row per variable):

**Single-node:**

| Variable | Value |
|----------|-------|
| `DSS_HOST` | `https://your-dss-instance.example.com` |
| `DSS_API_KEY` | `dkuaps-aBcDeFgHiJkLmNoPqRsTuVwXyZ` |

**Multi-node:**

| Variable | Value |
|----------|-------|
| `DSS_NODE_1_HOST` | `https://first-node.example.com` |
| `DSS_NODE_1_KEY` | `dkuaps-...` |
| `DSS_NODE_1_NAME` | `first-node` *(optional)* |
| `DSS_NODE_2_HOST` | `https://second-node.example.com` |
| `DSS_NODE_2_KEY` | `dkuaps-...` |
| `DSS_NODE_2_NAME` | `second-node` *(optional)* |

---

### Step 3 — Load tools and verify

Click **Load tools** in the tool definition. You should see four tools appear:

- `list_projects`
- `get_project_summary`
- `list_all_tags`
- `get_node_info`

Enable the tools you want the agent to use, then save.

---

### Step 4 — Test the agent

Run the agent with a prompt like:

> *"List all projects visible across the connected DSS nodes and tell me how many are on each node."*

---

### Updating the DSS deployment

To pull a new version, rebuild the code environment — DSS will re-clone the repository from GitHub. Pin to a specific git tag or commit hash in the package URL to control when updates take effect:

```
git+https://github.com/THE-MOLECULAR-MAN/dss_read_only_mcp_agent.git@v1.2.3
```

---

## Optional environment variables (both tracks)

| Variable | Default | Description |
|----------|---------|-------------|
| `DSS_NO_CHECK_CERTIFICATE` | `true` | Set to `false` to enable TLS certificate verification. Useful for production nodes with valid certs. |
| `DSS_MCP_LOG_DIR` | `~/.dss-mcp` | Directory for the structured JSON log file (`server.log`). |

---

## Troubleshooting

### The server doesn't appear in Claude Desktop
1. The `"command"` path must point to Python inside `.venv`, not system Python.
2. Validate your JSON at [jsonlint.com](https://jsonlint.com) — a stray comma breaks the whole file.
3. Fully quit Claude Desktop before editing (right-click Dock icon → Quit).

### Tools don't load in DSS
1. Confirm the code environment built without errors and is attached to the tool.
2. Check that `DSS_HOST` and `DSS_API_KEY` (or `DSS_NODE_N_*` equivalents) are set in the tool's env vars.
3. Try running `python -m dss_mcp --help` in a DSS terminal with the code environment activated to confirm the package is installed.

### Claude says it can't connect to DSS / "UnauthorizedException"
- Confirm `DSS_HOST` is reachable from the machine running the server.
- Verify the API key is valid: Profile → API Keys in DSS.
- `get_node_info` requires an admin-level key. `list_projects` and `get_project_summary` work with any project-member key.

### Log file
The server writes structured JSON logs to `~/.dss-mcp/server.log` (or `$DSS_MCP_LOG_DIR/server.log`).

---

## What the server can see

- **Admin API key** — sees all projects and node-level settings.
- **Project-member key** — sees only projects you're a member of; some fields will be empty.

The server is **strictly read-only** — it only calls `get_*` and `list_*` API methods. Credentials and secrets found in DSS project settings are automatically redacted before being returned.

---

## Updating — Claude Desktop

```bash
cd ~/dss_read_only_mcp_agent
git pull
source .venv/bin/activate
pip install -e ".[claude]"
```

Then restart Claude Desktop.

---

## For developers — running the tests

```bash
pip install -e ".[dev]"
pytest
pytest -v
pytest tests/test_security.py
pytest tests/test_error_handling.py
```

The `[dev]` extra includes both `pytest` and `dataiku-api-client` so tests run without a live DSS environment. The test suite covers credential redaction, project metadata normalization, recipe categorization, retry behavior, and error handling for every DSS API call.
