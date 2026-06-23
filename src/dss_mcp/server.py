"""DSS Demo Finder MCP server.

Runs over stdio transport for Claude Desktop. Configure in
claude_desktop_config.json:

    {
      "mcpServers": {
        "dss-demo-finder": {
          "command": "python",
          "args": ["-m", "dss_mcp"],
          "env": {
            "DSS_HOST": "https://your-dss-instance.example.com",
            "DSS_API_KEY": "your-api-key-here"
          }
        }
      }
    }

Required environment variables:
    DSS_HOST      Full URL of the DSS Design node
    DSS_API_KEY   API key with read access (admin-level preferred; degrades
                  gracefully to project-member scope if not)

Optional:
    DSS_MCP_LOG_DIR   Directory for structured JSON log file
                      (default: ~/.dss-mcp/server.log)
"""

import sys

from fastmcp import FastMCP

from dss_mcp.logging_config import get_logger, setup_logging
from dss_mcp.tools.node import get_node_info
from dss_mcp.tools.projects import list_all_tags, list_projects
from dss_mcp.tools.summary import get_project_summary

setup_logging()
log = get_logger("server")

mcp = FastMCP(
    name="dss-demo-finder",
    instructions=(
        "You help Dataiku sales engineers find DSS projects suitable for "
        "customer demos. Use list_projects to scan all projects, then call "
        "get_project_summary on specific candidates. Rank by fit to the "
        "prospect's use case, industry, and infrastructure, and by demo "
        "readiness signals (dashboards, agents, recent successful jobs)."
    ),
)

# Register tools by passing plain functions to mcp.tool().
# Tool docstrings become the MCP tool descriptions visible to the LLM.
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
