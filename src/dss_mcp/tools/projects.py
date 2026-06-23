from concurrent.futures import ThreadPoolExecutor, as_completed

from dss_mcp.client import borrow_client, get_nodes, project_url as make_project_url
from dss_mcp.logging_config import get_logger

log = get_logger("tools.projects")


def list_projects() -> list[dict] | dict:
    """Return lightweight metadata for every project visible across all configured DSS nodes.

    Queries all nodes in parallel. Each entry includes project_key, name, short_desc,
    tags, owner_login, last_modified_on, node_name, and project_url (a direct link to
    the project's Flow in DSS). Call get_project_summary(project_key, node_name) for
    deeper detail on specific candidates.
    """
    nodes = get_nodes()
    if len(nodes) == 1:
        return _list_for_node(nodes[0].name)

    all_projects: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
        futures = {ex.submit(_list_for_node, n.name): n.name for n in nodes}
        for future in as_completed(futures):
            result = future.result()
            if isinstance(result, list):
                all_projects.extend(result)
            else:
                log.warning("list_projects partial failure", extra={"result": str(result)})
    return all_projects


def list_all_tags() -> list[str] | dict:
    """Return a deduplicated, sorted list of all tags used across all projects on all nodes.

    Useful for understanding the available taxonomy before searching. Tags are
    a neutral signal — tag count does not indicate demo quality.
    """
    nodes = get_nodes()

    def _collect_tags(node_name: str) -> set[str]:
        found: set[str] = set()
        try:
            with borrow_client(node_name) as client:
                projects = client.list_projects()
            for p in projects:
                for tag in p.get("tags", []):
                    if isinstance(tag, str):
                        found.add(tag)
                    elif isinstance(tag, dict):
                        name = tag.get("name")
                        if name:
                            found.add(name)
        except Exception as e:
            log.error("list_all_tags failed", extra={"node": node_name, "error": str(e)})
        return found

    try:
        tags: set[str] = set()
        if len(nodes) == 1:
            tags = _collect_tags(nodes[0].name)
        else:
            with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
                for result in ex.map(_collect_tags, [n.name for n in nodes]):
                    tags |= result
        return sorted(tags)
    except Exception as e:
        log.error("list_all_tags failed", extra={"error": str(e)})
        return {"error": "list_all_tags_failed", "detail": str(e)}


def _list_for_node(node_name: str) -> list[dict] | dict:
    try:
        with borrow_client(node_name) as client:
            projects = client.list_projects()
        return [_slim(p, node_name) for p in projects]
    except Exception as e:
        log.error("list_projects failed", extra={"node": node_name, "error": str(e)})
        return {"error": "list_projects_failed", "node": node_name, "detail": str(e)}


def _slim(p: dict, node_name: str) -> dict:
    """Extract lightweight fields and attach node identity and a direct URL."""
    project_key = p.get("projectKey")
    tags_raw = p.get("tags", [])
    tags = [
        t.get("name", "") if isinstance(t, dict) else t
        for t in tags_raw
    ]
    return {
        "project_key": project_key,
        "node_name": node_name,
        "project_url": make_project_url(node_name, project_key),
        "name": p.get("name"),
        "short_desc": p.get("shortDesc"),
        "tags": [t for t in tags if t],
        "owner_login": p.get("ownerLogin"),
        "last_modified_on": p.get("versionTag", {}).get("lastModifiedOn")
            if isinstance(p.get("versionTag"), dict)
            else p.get("lastModifiedOn"),
    }
