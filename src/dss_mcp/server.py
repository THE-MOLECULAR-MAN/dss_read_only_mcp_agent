"""DSS Demo Finder MCP server.

Runs over stdio transport. Works as both a Claude Desktop MCP server and a
Dataiku DSS Agent Tool (local MCP).

Claude Desktop — configure in claude_desktop_config.json:

    {
      "mcpServers": {
        "dss-demo-finder": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "dss_mcp"],
          "cwd": "/path/to/dss_read_only_mcp_agent",
          "env": {
            "DSS_HOST": "https://your-dss-instance.example.com",
            "DSS_API_KEY": "your-api-key-here"
          }
        }
      }
    }

DSS Agent Tool — configure in the DSS agent tool definition:

    Command : python
    Args    : -m dss_mcp
    Env vars: DSS_HOST, DSS_API_KEY  (or DSS_NODE_1_HOST / DSS_NODE_1_KEY
              for multi-node)

Required environment variables:
    DSS_HOST      Full URL of the DSS Design node
    DSS_API_KEY   API key with read access (admin-level preferred)

Optional:
    DSS_NODE_NAME           Display name for the single-node config
    DSS_NO_CHECK_CERTIFICATE  Set to "false" to enable TLS verification
                              (default: "true" — skip verification)
    DSS_MCP_LOG_DIR         Directory for the structured JSON log file
                            (default: ~/.dss-mcp/server.log)
"""

import sys

from fastmcp import FastMCP

from dss_mcp.logging_config import get_logger, setup_logging
from dss_mcp.tools.node import get_node_info
from dss_mcp.tools.projects import count_projects, list_all_tags, list_projects, search_projects
from dss_mcp.tools.summary import get_project_summary

setup_logging()
log = get_logger("server")

mcp = FastMCP(
    name="dss-demo-finder",
    instructions="""
You are connected to one or more live Dataiku DSS design nodes via a read-only
MCP server. Use these tools to find, evaluate, and recommend DSS projects for
customer demonstrations. All operations are read-only — you cannot modify,
build, run, or delete anything on DSS.

## Available tools

### search_projects(query, limit=50)
THE PRIMARY DISCOVERY TOOL. Searches project names, descriptions, tags, and
keys across all nodes for the given query string. Returns up to `limit`
projects sorted by relevance score — no per-project API calls, safe on any
inventory size.

Key design: use BROAD search terms. The query is split into individual tokens
and each is matched independently, so "financial crime fraud banking" will
surface AML projects, credit card fraud demos, anti-money-laundering solutions,
and any financial risk project — even when none contain your exact phrase.
Always prefer broad terms over narrow exact phrases.

### count_projects()
Returns the total number of projects visible across all configured nodes,
plus per-node identity (node_name and host URL) and per-node counts.
Calls list_project_keys() — much lighter than list_projects(). Use to scope
the inventory or confirm which nodes are reachable before heavier queries.

### get_node_info()
Returns connectivity status and DSS version for every configured node. Call
when you are unsure which nodes are reachable, or if a user asks what
instances are connected.

### list_projects()
Returns lightweight metadata for EVERY project visible across ALL nodes.
WARNING: on large instances this may return thousands of projects and consume
significant context. Prefer search_projects() for all discovery tasks.
Only use list_projects() when you genuinely need the full inventory (e.g.,
building a complete tag taxonomy or counting projects by category).

### list_all_tags()
Returns a deduplicated sorted list of every tag used across all nodes. Call
this to understand the available taxonomy, or to map a prospect's keywords
to real tag values before calling search_projects.

### get_project_summary(project_key, node_name)
Returns comprehensive detail for a single project. Always pass node_name
exactly as it appears in the search_projects response. Makes ~13 parallel
API calls per invocation; do not call this in a loop over all projects.

Key fields returned and what they signal:

  DEMO READINESS
  - dashboard_count / total_tile_count   Higher = more visual, presentable output
  - webapp_count / autostarter_webapp_count  Live interactive UI ready to show
  - recent_job_success_rate (0–1.0)      ≥ 0.8 = data pipeline is reliable
  - last_built_on (epoch ms)             Recency — recently built = maintained
  - has_bundle_on_deployer               True = deployment story already exists

  AI / GEN AI CAPABILITY
  - has_agents / agent_count             Project uses DSS Agents
  - llm_connection_names                 List of LLM connections configured
  - recipe_counts_by_category.prompt_llm  Number of LLM prompt recipes

  ORIGIN & QUALITY
  - inferred_origin                      "solutions_hub" = Dataiku-vetted and polished;
                                         "tutorial" = good for learning demos;
                                         "original" = custom-built
  - contributor_count                    Actively maintained if > 1

  TECHNICAL PROFILE
  - connection_types_used                Data sources (S3, Snowflake, etc.)
  - recipe_counts_by_category            visual / code / prompt_llm / plugin
  - ml_task_count                        Number of ML models present
  - pct_datasets_with_dq_rules           Data quality discipline (0–1.0)
  - plugins_used                         Third-party integrations

## Standard workflow

1. CALL search_projects(query) with broad terms covering the prospect's
   industry, use case, and adjacent concepts. Examples:
     "anti money laundering" → use "financial crime fraud banking compliance"
     "supply chain" → use "supply chain logistics inventory procurement"
   This returns up to 50 scored candidates without overloading context.

2. SCAN the returned list. Identify the top 3–6 candidates based on name,
   short_desc, and tags alone. No get_project_summary calls yet.

3. CALL get_project_summary(project_key, node_name) for each candidate.
   Use the node_name field from search_projects exactly as returned.

4. SCORE each candidate on demo readiness:
   - recent_job_success_rate ≥ 0.8  (data works reliably)
   - dashboard_count > 0 or webapp_count > 0  (something to show visually)
   - last_built_on within 6 months  (not stale)
   - inferred_origin = solutions_hub  (bonus: production-quality)
   - has_agents = true or llm_connection_names non-empty  (for AI prospects)

5. RETURN ranked recommendations. For each, include:
   - The project_url (direct link — always include this)
   - Name and short description
   - Why it fits the prospect's use case
   - Demo readiness signals that support your ranking
   - Any caveats (e.g. low job success rate, no dashboards)

## When to use each tool

| Situation | Tool |
|-----------|------|
| Starting a demo search for a prospect | search_projects() → get_project_summary() |
| "How many projects do we have?" | count_projects() |
| Confirming which nodes are up and reachable | count_projects() or get_node_info() |
| User asks what tags/industries are covered | list_all_tags() |
| User asks which nodes are connected | get_node_info() |
| Deep evaluation of a specific project | get_project_summary() |
| Need the full unfiltered project list | list_projects() (use sparingly) |

## Important constraints

- Always pass node_name to get_project_summary — omitting it defaults to the
  first configured node, which may be wrong in a multi-node setup.
- Credentials and secrets found in DSS project settings are automatically
  redacted to [REDACTED] before being returned. Never attempt to access or
  reconstruct them.
- This server is strictly read-only. It cannot trigger builds, run scenarios,
  modify projects, or access user data stored in datasets.
""",
)

# Register tools by passing plain functions to mcp.tool().
# Tool docstrings become the MCP tool descriptions visible to the LLM.
mcp.tool()(search_projects)
mcp.tool()(count_projects)
mcp.tool()(list_projects)
mcp.tool()(get_project_summary)
mcp.tool()(list_all_tags)
mcp.tool()(get_node_info)


def main() -> None:
    log.info("DSS MCP server starting", extra={"transport": "stdio"})
    try:
        mcp.run(transport="stdio")
    except Exception as e:
        log.error("Server crashed", extra={"error": str(e)})
        sys.exit(1)
