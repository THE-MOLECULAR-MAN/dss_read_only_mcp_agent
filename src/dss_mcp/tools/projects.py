from dss_mcp.client import borrow_client
from dss_mcp.logging_config import get_logger

log = get_logger("tools.projects")


def list_projects() -> list[dict] | dict:
    """Return lightweight metadata for every project visible to this API key.

    list_projects() returns all projects in a single call (no pagination).
    The caller may have admin-level or project-member access; results reflect
    whatever the configured API key can see.

    Each entry contains: project_key, name, short_desc, tags, owner_login,
    last_modified_on. Call get_project_summary(project_key) for deeper detail
    on specific candidates.
    """
    try:
        with borrow_client() as client:
            projects = client.list_projects()
        return [_slim(p) for p in projects]
    except Exception as e:
        log.error("list_projects failed", extra={"error": str(e)})
        return {"error": "list_projects_failed", "detail": str(e)}


def list_all_tags() -> list[str] | dict:
    """Return a deduplicated, sorted list of all tags used across all projects.

    Useful for understanding the available taxonomy before searching. Tags are
    a neutral signal — tag count does not indicate demo quality.
    """
    try:
        with borrow_client() as client:
            projects = client.list_projects()
        tags: set[str] = set()
        for p in projects:
            for tag in p.get("tags", []):
                if isinstance(tag, str):
                    tags.add(tag)
                elif isinstance(tag, dict):
                    # Some DSS versions return tag objects with a "name" key
                    name = tag.get("name")
                    if name:
                        tags.add(name)
        return sorted(tags)
    except Exception as e:
        log.error("list_all_tags failed", extra={"error": str(e)})
        return {"error": "list_all_tags_failed", "detail": str(e)}


def _slim(p: dict) -> dict:
    """Extract the lightweight fields returned by list_projects()."""
    # DSS returns camelCase keys from list_projects(); normalize to snake_case.
    tags_raw = p.get("tags", [])
    tags = [
        t.get("name", "") if isinstance(t, dict) else t
        for t in tags_raw
    ]
    return {
        "project_key": p.get("projectKey"),
        "name": p.get("name"),
        "short_desc": p.get("shortDesc"),
        "tags": [t for t in tags if t],
        "owner_login": p.get("ownerLogin"),
        "last_modified_on": p.get("versionTag", {}).get("lastModifiedOn")
            if isinstance(p.get("versionTag"), dict)
            else p.get("lastModifiedOn"),
    }
