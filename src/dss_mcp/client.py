import os
import queue
import re
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field

import dataikuapi

from dss_mcp.logging_config import get_logger

log = get_logger("client")

_POOL_SIZE = 6


@dataclass
class DSSNode:
    name: str
    host: str
    pool: queue.Queue = field(default_factory=queue.Queue)


def _make_client(host: str, api_key: str) -> dataikuapi.DSSClient:
    client = dataikuapi.DSSClient(host=host, api_key=api_key, no_check_certificate=True)
    if hasattr(client, "_session"):
        client._session.timeout = (10, 60)
    return client


def _name_from_host(host: str) -> str:
    """Derive a short readable name from a host URL, e.g. 'acme-design' from https://acme-design.io."""
    name = re.sub(r"^https?://", "", host)
    return name.split("/")[0].split(":")[0]


def _load_nodes() -> list[DSSNode]:
    """Load DSS node configurations from environment variables.

    Multi-node format (numbered, up to 19 nodes):
        DSS_NODE_1_HOST, DSS_NODE_1_KEY, DSS_NODE_1_NAME (optional)
        DSS_NODE_2_HOST, DSS_NODE_2_KEY, DSS_NODE_2_NAME (optional)
        ...

    Single-node fallback (backward-compatible):
        DSS_HOST, DSS_API_KEY, DSS_NODE_NAME (optional)
    """
    nodes: list[DSSNode] = []

    for i in range(1, 20):
        host = os.environ.get(f"DSS_NODE_{i}_HOST")
        key = os.environ.get(f"DSS_NODE_{i}_KEY")
        if not host or not key:
            break
        name = os.environ.get(f"DSS_NODE_{i}_NAME", _name_from_host(host))
        node_pool: queue.Queue = queue.Queue()
        for _ in range(_POOL_SIZE):
            node_pool.put(_make_client(host, key))
        nodes.append(DSSNode(name=name, host=host, pool=node_pool))

    if not nodes:
        host = os.environ["DSS_HOST"]
        key = os.environ["DSS_API_KEY"]
        name = os.environ.get("DSS_NODE_NAME", _name_from_host(host))
        node_pool = queue.Queue()
        for _ in range(_POOL_SIZE):
            node_pool.put(_make_client(host, key))
        nodes.append(DSSNode(name=name, host=host, pool=node_pool))

    log.info("DSS nodes loaded", extra={"nodes": [n.name for n in nodes]})
    return nodes


_nodes: list[DSSNode] = _load_nodes()
_node_index: dict[str, DSSNode] = {n.name: n for n in _nodes}

# Shared executor — max_workers matches pool size so no worker ever blocks on a client.
executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=_POOL_SIZE)


def get_nodes() -> list[DSSNode]:
    return _nodes


def node_names() -> list[str]:
    return [n.name for n in _nodes]


def project_url(node_name: str, project_key: str) -> str | None:
    """Return the DSS Flow URL for a project on a given node."""
    node = _node_index.get(node_name)
    if not node or not project_key:
        return None
    return f"{node.host.rstrip('/')}/projects/{project_key}/flow/"


@contextmanager
def borrow_client(node_name: str | None = None) -> Generator[dataikuapi.DSSClient, None, None]:
    """Borrow a DSSClient from the named node's pool; defaults to the first configured node."""
    if node_name is None:
        node = _nodes[0]
    else:
        node = _node_index.get(node_name)
        if node is None:
            raise ValueError(
                f"Unknown DSS node: {node_name!r}. "
                f"Configured nodes: {node_names()}"
            )
    client = node.pool.get()
    try:
        yield client
    finally:
        node.pool.put(client)
