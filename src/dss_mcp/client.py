import os
import queue
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import dataikuapi

from dss_mcp.logging_config import get_logger

log = get_logger("client")

_POOL_SIZE = 6  # conservative for read-mostly metadata against one Design node


def _make_client() -> dataikuapi.DSSClient:
    client = dataikuapi.DSSClient(
        host=os.environ["DSS_HOST"],
        api_key=os.environ["DSS_API_KEY"],
        no_check_certificate=True,
    )
    # Set explicit timeouts on the underlying requests.Session.
    # DSSClient is not thread-safe (shared Session), so each pool slot
    # gets its own instance. Verify "_session" attribute name for your
    # dataikuapi version.
    if hasattr(client, "_session"):
        client._session.timeout = (10, 60)  # (connect_s, read_s)
    return client


_pool: queue.Queue[dataikuapi.DSSClient] = queue.Queue()
for _ in range(_POOL_SIZE):
    _pool.put(_make_client())

# Shared executor for parallel sub-calls within get_project_summary.
# max_workers matches pool size so no worker ever blocks waiting for a client.
executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=_POOL_SIZE)


@contextmanager
def borrow_client() -> Generator[dataikuapi.DSSClient, None, None]:
    """Borrow a DSSClient from the pool; return it automatically on exit."""
    client = _pool.get()
    try:
        yield client
    finally:
        _pool.put(client)
