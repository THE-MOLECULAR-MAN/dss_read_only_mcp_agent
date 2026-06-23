# DSS Demo Finder — MCP Server for Claude

This tool connects Claude Desktop to a live Dataiku DSS instance. Once installed, you can ask Claude to find the best demo projects for a prospect, and it will search your DSS node directly, evaluate each project's demo-readiness, and give you ranked recommendations.

**Example:**
> *"I have a meeting tomorrow with a retail company interested in demand forecasting and LLM-powered applications. Find me the three best demo projects on our DSS instance."*

Claude will scan all projects, read their contents in parallel, and return ranked picks with explanations — without you having to open DSS at all.

---

## Before you start

You need three things installed on your Mac before following these steps:

### 1. Check Python

Open **Terminal** (press `Cmd + Space`, type `Terminal`, press Enter) and run:

```bash
python3 --version
```

You need version **3.11 or higher**. If you see something like `Python 3.11.4` or `Python 3.14.6`, you're good. If you see `command not found` or a version below 3.11, install Python from [python.org/downloads](https://www.python.org/downloads/) before continuing.

### 2. Check Claude Desktop

Make sure Claude Desktop is installed and you can open it. You can download it from [claude.ai/download](https://claude.ai/download) if needed.

### 3. Check Git

In Terminal, run:

```bash
git --version
```

If you see a version number, you have Git. If not, macOS will prompt you to install it — click Install and wait for it to finish.

---

## Step 1 — Download the server

In Terminal, run these commands one at a time. Each line copies and pastes on its own.

```bash
cd ~
```
```bash
git clone https://github.com/THE-MOLECULAR-MAN/dss_read_only_mcp_agent.git
```
```bash
cd dss_read_only_mcp_agent
```

You should now be inside the project folder. Your Terminal prompt will show `dss_read_only_mcp_agent` at the end.

---

## Step 2 — Install the server

Still in Terminal, run these commands in order:

```bash
python3 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
pip install -e .
```

The last command installs all dependencies. It may take a minute. When it finishes you'll see a line like `Successfully installed dss-mcp-server-0.1.0 ...`.

### Save the paths you'll need

Now run this command — it will print the two values you need for the next step:

```bash
echo "Python path: $(pwd)/.venv/bin/python" && echo "Install dir:  $(pwd)"
```

You'll see output like:
```
Python path: /Users/yourname/dss_read_only_mcp_agent/.venv/bin/python
Install dir:  /Users/yourname/dss_read_only_mcp_agent
```

**Copy both lines somewhere** (Notes app, a text file) — you'll paste them into the config file shortly.

---

## Step 3 — Get your DSS API key

You need a personal API key from your DSS instance.

1. Open your DSS instance in a browser and log in.
2. Click your **profile icon** in the top-right corner.
3. Click **Profile & Settings** (or just **Profile**).
4. In the left sidebar, click **API Keys**.
5. Click **+ New Key** (you can give it any name, e.g. "Claude MCP").
6. Copy the key that appears — it starts with `dkuaps-` and looks like `dkuaps-aBcDeFgHiJkLmNoPqRsTuVwXyZ`.

> **Keep this key private.** It provides read access to everything visible to your DSS user account.

---

## Step 4 — Configure Claude Desktop

### 4a. Close Claude Desktop

Quit Claude Desktop completely before editing the config file — it overwrites the file when it exits.

### 4b. Open the config file

In Terminal, run:

```bash
open -a TextEdit "$HOME/Library/Application Support/Claude/claude_desktop_config.json"
```

This opens the Claude Desktop config file in TextEdit.

### 4c. Add the DSS server

Find the line that says:

```json
"mcpServers": {},
```

Replace it with the block below. **Before pasting, substitute your actual values for the three placeholders** (the Python path and install dir you saved in Step 2, and your API key from Step 3):

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

**Filled-in example** (your values will differ):

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

Save the file (`Cmd + S`) and close TextEdit.

> **Note on the DSS_HOST value:** use the base URL of your DSS instance — no trailing slash, no path after the domain. If you open DSS in your browser and the URL looks like `https://acme.dataiku-sandbox.io/projects/`, just use `https://acme.dataiku-sandbox.io`.

---

## Step 5 — Start Claude Desktop and verify

Open Claude Desktop. Look for the **MCP tools icon** (a hammer or plug icon) in the chat input bar. Click it — you should see `dss-demo-finder` listed with four tools: `list_projects`, `get_project_summary`, `list_all_tags`, and `get_node_info`.

If the server doesn't appear, see [Troubleshooting](#troubleshooting) below.

---

## Step 6 — Try it out

Here are some example prompts to get started:

**Find demos for a specific prospect:**
> *"I'm meeting with a retail bank tomorrow interested in fraud detection and explainability. Find me the top 3 demo projects on our DSS instance."*

**Find AI/LLM showcases:**
> *"Which projects use LLM connections or AI agents and have dashboards ready to show?"*

**Check what's available by industry:**
> *"What tags and industry categories do our demo projects cover? Give me a breakdown."*

**Find the most polished projects:**
> *"Show me projects with the highest job success rates that have been updated in the last 6 months."*

**Find tutorial or solutions hub projects:**
> *"Which projects came from the Dataiku solutions hub or are tutorial projects?"*

---

## Troubleshooting

### The server doesn't appear in Claude Desktop

1. Double-check that the `"command"` path in the config points to the Python inside `.venv`, not your system Python. It should end in `.venv/bin/python`.
2. Make sure there are no extra commas or missing quotes in the JSON — JSON is picky. Paste your config into [jsonlint.com](https://jsonlint.com) to check for errors.
3. Make sure you fully quit Claude Desktop before editing the file (right-click the Dock icon → Quit, not just close the window).

### Claude says it can't connect to DSS

- Confirm `DSS_HOST` is the correct URL and you can open it in your browser.
- Confirm the API key is valid: try logging into DSS, go to Profile → API Keys, and verify the key exists.
- If your DSS instance uses a self-signed certificate, the server already disables certificate verification — this should not be an issue.

### "Python not found" or version errors

Make sure the `"command"` value is the full path ending in `.venv/bin/python`, not just `python` or `python3`. Claude Desktop does not use your shell PATH.

### Log file

If something goes wrong, the server writes a diagnostic log to:

```
~/.dss-mcp/server.log
```

Open it in TextEdit or Terminal (`cat ~/.dss-mcp/server.log`) to see error messages.

---

## What the server can see

The server connects using your DSS API key and inherits your access level:

- **Admin API key** — sees all projects and node-level settings.
- **Project-member API key** — sees only projects you're a member of; some fields will be empty or missing.

The server is **strictly read-only**. It only calls `get_*` and `list_*` API methods and cannot modify, build, deploy, or delete anything on your DSS instance.

Credentials and secrets found in DSS project settings are automatically redacted before being sent to Claude — they will appear as `[REDACTED]` in Claude's responses.

---

## Updating the server

To pull the latest version:

```bash
cd ~/dss_read_only_mcp_agent
git pull
source .venv/bin/activate
pip install -e .
```

Then restart Claude Desktop.

---

## For developers — running the tests

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

Run all tests:

```bash
pytest
```

Run with verbose output:

```bash
pytest -v
```

Run a specific file:

```bash
pytest tests/test_security.py
pytest tests/test_error_handling.py
```

The test suite covers credential redaction, project metadata normalization, recipe categorization, retry behavior, and error handling for every DSS API call (including partial failures where individual datasets or dashboards in a project are in a bad state).
