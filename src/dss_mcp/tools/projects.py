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


def count_projects() -> dict:
    """Return the total number of projects visible across all configured DSS nodes.

    Calls list_project_keys() on each node — returns only project key strings,
    making this far lighter than list_projects(). Use this to scope the inventory
    size, confirm which nodes are reachable, and see how many projects each holds
    before running heavier queries.

    Returns a dict with:
      - total_project_count  Grand total across all nodes
      - nodes                Per-node list, each with: node_name, host,
                             project_count, and status ("ok" or "error")
    """
    nodes = get_nodes()

    def _count_for_node(node) -> dict:
        try:
            with borrow_client(node.name) as client:
                keys = client.list_project_keys()
            return {
                "node_name": node.name,
                "host": node.host,
                "project_count": len(keys),
                "status": "ok",
            }
        except Exception as e:
            log.error("count_projects failed", extra={"node": node.name, "error": str(e)})
            return {
                "node_name": node.name,
                "host": node.host,
                "project_count": 0,
                "status": "error",
                "detail": str(e),
            }

    if len(nodes) == 1:
        node_results = [_count_for_node(nodes[0])]
    else:
        node_results: list[dict] = [{}] * len(nodes)
        with ThreadPoolExecutor(max_workers=len(nodes)) as ex:
            futures = {ex.submit(_count_for_node, n): i for i, n in enumerate(nodes)}
            for future in as_completed(futures):
                node_results[futures[future]] = future.result()

    return {
        "total_project_count": sum(r.get("project_count", 0) for r in node_results),
        "nodes": node_results,
    }


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
    except Exception as e:
        log.error("list_projects failed", extra={"node": node_name, "error": str(e)})
        return {"error": "list_projects_failed", "node": node_name, "detail": str(e)}

    # Free filter: projects with ≤2 version commits are empty/stub projects
    candidates = [p for p in projects if _sufficient_commits(p)]

    # Parallel filter: at least 2 datasets, 2 recipes, and 1 job ever run
    viable_keys: set[str] = set()
    if candidates:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {
                ex.submit(_is_viable_demo, p.get("projectKey"), node_name): p.get("projectKey")
                for p in candidates
                if p.get("projectKey")
            }
            for future in as_completed(futures):
                key = futures[future]
                try:
                    if future.result():
                        viable_keys.add(key)
                except Exception:
                    viable_keys.add(key)  # fail-open on executor error

    return [_slim(p, node_name) for p in candidates if p.get("projectKey") in viable_keys]


def _sufficient_commits(p: dict) -> bool:
    """Return True if the project has more than 2 version commits (or version info is absent)."""
    vt = p.get("versionTag")
    if not isinstance(vt, dict):
        return True
    version_number = vt.get("versionNumber")
    if version_number is None:
        return True
    return int(version_number) > 2


def _is_viable_demo(project_key: str, node_name: str) -> bool:
    """Return True if the project meets minimum dataset, recipe, and job thresholds.

    Thresholds: ≥2 datasets, ≥2 recipes, at least 1 job ever run.
    Returns True on any API error so a single bad API call never silently drops a project.
    """
    try:
        with borrow_client(node_name) as client:
            project = client.get_project(project_key)
            try:
                if len(project.list_datasets()) < 2:
                    return False
            except Exception:
                pass
            try:
                if len(project.list_recipes()) < 2:
                    return False
            except Exception:
                pass
            try:
                if not project.list_jobs(active=False, limit=1):
                    return False
            except Exception:
                pass
        return True
    except Exception:
        return True  # fail-open: include the project if we can't borrow a client


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
