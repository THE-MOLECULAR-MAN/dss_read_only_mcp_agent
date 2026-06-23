from dss_mcp.client import borrow_client
from dss_mcp.logging_config import get_logger

log = get_logger("tools.node")


def get_node_info() -> dict:
    """Return basic metadata about this DSS node.

    Always a Design node per deployment assumption. Returns DSS version,
    node type, and node ID. Useful for verifying connectivity and version
    before making heavier API calls.
    """
    try:
        with borrow_client() as client:
            raw = client.get_general_settings().get_raw()
            return {
                "node_type": "design",  # deployment assumption; verify via raw if needed
                "dss_version": raw.get("version", None),
                "node_id": raw.get("nodeId", None),
                "host": raw.get("publicURL", None),
            }
    except Exception as e:
        log.warning("get_node_info failed", extra={"error": str(e)})
        return {"error": "unavailable", "detail": str(e)}
