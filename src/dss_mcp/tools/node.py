from concurrent.futures import ThreadPoolExecutor, as_completed

from dss_mcp.client import borrow_client, get_nodes
from dss_mcp.logging_config import get_logger

log = get_logger("tools.node")


def get_node_info() -> list[dict] | dict:
    """Return basic metadata about all configured DSS nodes.

    Queries each node in parallel. Each entry includes the node_name,
    DSS version, node type, and host URL. Useful for verifying connectivity
    and which nodes are reachable before running heavier queries.
    """
    nodes = get_nodes()

    def _info_for_node(node_name: str) -> dict:
        try:
            with borrow_client(node_name) as client:
                raw = client.get_general_settings().get_raw()
                return {
                    "node_name": node_name,
                    "node_type": "design",
                    "dss_version": raw.get("version"),
                    "node_id": raw.get("nodeId"),
                    "host": raw.get("publicURL"),
                    "status": "ok",
                }
        except Exception as e:
            log.warning("get_node_info failed", extra={"node": node_name, "error": str(e)})
            return {
                "node_name": node_name,
                "status": "error",
                "detail": str(e),
            }

    if len(nodes) == 1:
        return [_info_for_node(nodes[0].name)]

    results: list[dict] = [{}] * len(nodes)
    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        futures = {ex.submit(_info_for_node, n.name): i for i, n in enumerate(nodes)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
    return results
