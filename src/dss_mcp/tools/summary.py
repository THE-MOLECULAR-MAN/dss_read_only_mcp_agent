"""get_project_summary tool and all its sub-fetchers.

Each _fetch_* function is submitted to the shared ThreadPoolExecutor and must
borrow its own client from the pool. Phase 1 fetches are independent; Phase 2
fetches depend on Phase 1 results.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from dss_mcp.client import borrow_client, executor, get_nodes, project_url as make_project_url
from dss_mcp.logging_config import get_logger
from dss_mcp.security import redact

log = get_logger("tools.summary")

# Recipe type strings by category. Update if DSS 14.x introduces new types.
_VISUAL_TYPES: frozenset[str] = frozenset({
    "shaker", "join", "sync", "split", "sampling", "grouping", "distinct",
    "pivot", "top_n", "filter", "sort", "window", "merge_fuzzy", "vstack",
    "download", "export", "uploadedfiles",
})
_CODE_TYPES: frozenset[str] = frozenset({
    "python", "r", "sql", "hive", "spark_scala", "pyspark", "spark_r",
    "shell", "impala",
})
_LLM_TYPES: frozenset[str] = frozenset({
    "llm",  # verify exact string for DSS 14.6
})

# Jobs considered "completed" (not still running)
_TERMINAL_JOB_STATES: frozenset[str] = frozenset({
    "DONE", "FAILED", "ABORTED",
})

# Origin inference tag patterns
_SOLUTIONS_TAGS: frozenset[str] = frozenset({"solutions", "solutions-hub", "solutions_hub"})
_TUTORIAL_TAGS: frozenset[str] = frozenset({"tutorial", "getting-started", "training", "onboarding"})

# Max datasets to check for DQ rules (caps per-project API calls)
_DQ_CHECK_LIMIT = 50


# ---------------------------------------------------------------------------
# Public tool function
# ---------------------------------------------------------------------------

def get_project_summary(project_key: str, node_name: str | None = None) -> dict:
    """Return comprehensive detail for a single project by project_key.

    node_name identifies which DSS node to query. It must match a value returned
    in the node_name field from list_projects(). When only one node is configured
    this parameter can be omitted.

    Makes multiple parallel API calls. Call this only after list_projects()
    has identified specific candidates — do not call in a loop over all projects.
    """
    try:
        # Default to first node when not specified (single-node backward compat)
        if node_name is None:
            node_name = get_nodes()[0].name

        log.info("get_project_summary started", extra={
            "project_key": project_key, "node": node_name})
        start = time.monotonic()

        # --- Phase 1: independent fetches ---
        p1_futures: dict[str, Future] = {
            "core":        executor.submit(_fetch_core, project_key, node_name),
            "recipes":     executor.submit(_fetch_recipes, project_key, node_name),
            "datasets":    executor.submit(_fetch_datasets, project_key, node_name),
            "ml_tasks":    executor.submit(_fetch_ml_tasks, project_key, node_name),
            "dashboards":  executor.submit(_fetch_dashboards, project_key, node_name),
            "webapps":     executor.submit(_fetch_webapps, project_key, node_name),
            "scenarios":   executor.submit(_fetch_scenarios, project_key, node_name),
            "jobs":        executor.submit(_fetch_jobs, project_key, node_name),
            "eval_stores": executor.submit(_fetch_eval_stores, project_key, node_name),
            "bundles":     executor.submit(_fetch_bundles, project_key, node_name),
            "llm_agents":  executor.submit(_fetch_llm_agents, project_key, node_name),
        }
        p1 = _collect(p1_futures, phase=1, project_key=project_key)

        # --- Phase 2: depend on Phase 1 datasets / recipes ---
        datasets_raw: list[dict] = p1.get("datasets", {}).get("_raw", [])
        recipes_raw: list[dict] = p1.get("recipes", {}).get("_raw", [])

        p2_futures: dict[str, Future] = {
            "dq_rules": executor.submit(_fetch_dq_rules, project_key, datasets_raw, node_name),
            "plugins":  executor.submit(_fetch_plugins, project_key, recipes_raw, datasets_raw, node_name),
        }
        p2 = _collect(p2_futures, phase=2, project_key=project_key)

        elapsed = round(time.monotonic() - start, 2)
        log.info("get_project_summary completed", extra={
            "project_key": project_key, "node": node_name, "elapsed_s": elapsed,
        })

        return _assemble(project_key, node_name, p1, p2)

    except Exception as e:
        log.error("get_project_summary failed", extra={"project_key": project_key, "error": str(e)})
        return {"error": "get_project_summary_failed", "project_key": project_key, "detail": str(e)}


# ---------------------------------------------------------------------------
# Phase 1 sub-fetchers
# ---------------------------------------------------------------------------

def _fetch_core(project_key: str, node_name: str | None = None) -> dict:
    """Fetch project settings (standards, zones, origin) and timeline (contributors)."""
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)

        # --- Settings ---
        try:
            settings_raw = project.get_settings().get_raw()
        except Exception as e:
            log.warning("get_settings failed", extra={"project_key": project_key, "error": str(e)})
            settings_raw = {}

        # Project standards / status checks
        status_checks = (
            settings_raw.get("projectStatus", {}).get("statusChecks", [])
        )
        standards_count = sum(1 for s in status_checks if s.get("enabled", False))

        # Flow zone count — may be in "flowZones" or "zones" depending on version
        flow_zones = settings_raw.get("flowZones", settings_raw.get("zones", []))
        flow_zone_count = len(flow_zones) if isinstance(flow_zones, list) else 0

        # Project app type for origin inference
        app_type = settings_raw.get("projectAppType", "")
        tags_raw = settings_raw.get("tags", [])
        tags = [t.get("name", t) if isinstance(t, dict) else t for t in tags_raw]

        # Identity fields — DSS settings use "label" for the display name and "owner" for login
        name = settings_raw.get("label") or settings_raw.get("name")
        short_desc = settings_raw.get("shortDesc")
        owner_login = settings_raw.get("owner") or settings_raw.get("ownerLogin")

        # --- Timeline ---
        contributor_count: int | None = None
        last_modified_on: int | None = None
        try:
            timeline = project.get_timeline()
            contributors = timeline.get("allContributors", [])
            contributor_count = len(contributors) if isinstance(contributors, list) else None
            last_modified_on = timeline.get("lastModifiedOn")
        except Exception as e:
            log.warning("get_timeline failed", extra={"project_key": project_key, "error": str(e)})

        return {
            "name": name,
            "short_desc": short_desc,
            "tags": [t for t in tags if t],
            "owner_login": owner_login,
            "project_standards_enforced": standards_count,
            "flow_zone_count": flow_zone_count,
            "contributor_count": contributor_count,
            "last_modified_on": last_modified_on,
            **_infer_origin(tags, app_type, settings_raw),
        }


def _fetch_recipes(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            recipes = project.list_recipes()
        except Exception as e:
            log.warning("list_recipes failed", extra={"project_key": project_key, "error": str(e)})
            return {"recipe_count": 0, "recipe_counts_by_category": _empty_recipe_counts(),
                    "recipe_types_present": [], "_raw": []}

    counts = _empty_recipe_counts()
    types_seen: set[str] = set()
    for r in recipes:
        rtype = r.get("type", "") if isinstance(r, dict) else ""
        if not rtype:
            continue
        types_seen.add(rtype)
        if rtype in _VISUAL_TYPES:
            counts["visual"] += 1
        elif rtype in _CODE_TYPES:
            counts["code"] += 1
        elif rtype in _LLM_TYPES:
            counts["prompt_llm"] += 1
        elif "." in rtype or rtype not in (_VISUAL_TYPES | _CODE_TYPES | _LLM_TYPES):
            counts["plugin"] += 1

    return {
        "recipe_count": len(recipes),
        "recipe_counts_by_category": counts,
        "recipe_types_present": sorted(types_seen),
        "_raw": recipes,  # passed to Phase 2
    }


def _fetch_datasets(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            datasets = project.list_datasets()
        except Exception as e:
            log.warning("list_datasets failed", extra={"project_key": project_key, "error": str(e)})
            return {"dataset_count": 0, "connection_types_used": [],
                    "connection_names_used": [], "_raw": []}

    conn_types: set[str] = set()
    conn_names: set[str] = set()
    for d in datasets:
        if not isinstance(d, dict):
            continue
        ctype = d.get("type")
        if ctype:
            conn_types.add(ctype)
        # Connection name lives in params.connection
        params = d.get("params", {})
        if isinstance(params, dict):
            cname = params.get("connection")
            if cname:
                conn_names.add(cname)

    return {
        "dataset_count": len(datasets),
        "connection_types_used": sorted(conn_types),
        "connection_names_used": sorted(conn_names),
        "_raw": datasets,  # passed to Phase 2
    }


def _fetch_ml_tasks(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        ml_tasks: list[dict] = []
        try:
            analyses = project.list_analyses()
        except Exception as e:
            log.warning("list_analyses failed", extra={"project_key": project_key, "error": str(e)})
            return {"ml_task_count": 0, "ml_tasks": []}

        for analysis in analyses:
            try:
                analysis_key = analysis.get("analysisId") if isinstance(analysis, dict) else None
                if not analysis_key:
                    continue
                a_handle = project.get_analysis(analysis_key)
                for mlt in _retry_read(a_handle.list_ml_tasks):
                    mlt_raw = mlt if isinstance(mlt, dict) else {}
                    ml_tasks.append({
                        "name": mlt_raw.get("taskType", mlt_raw.get("name")),
                        "task_type": mlt_raw.get("taskType"),
                        "algorithm": mlt_raw.get("modeling", {}).get("algorithm") if isinstance(
                            mlt_raw.get("modeling"), dict) else None,
                    })
            except Exception as e:
                log.warning("ml_task fetch failed", extra={"project_key": project_key, "error": str(e)})

    return {"ml_task_count": len(ml_tasks), "ml_tasks": ml_tasks}


def _fetch_dashboards(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            dashboards = project.list_dashboards()
        except Exception as e:
            log.warning("list_dashboards failed", extra={"project_key": project_key, "error": str(e)})
            return {"dashboard_count": 0, "total_tile_count": 0}

        total_tiles = 0
        for d in dashboards:
            try:
                dash_id = d.get("id") if isinstance(d, dict) else None
                if not dash_id:
                    continue
                raw = project.get_dashboard(dash_id).get_raw()
                for page in raw.get("pages", []):
                    total_tiles += len(page.get("tiles", []))
            except Exception as e:
                log.warning("dashboard tile count failed", extra={
                    "project_key": project_key, "error": str(e)})

    return {"dashboard_count": len(dashboards), "total_tile_count": total_tiles}


def _fetch_webapps(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            webapps = project.list_webapps()
        except Exception as e:
            log.warning("list_webapps failed", extra={"project_key": project_key, "error": str(e)})
            return {"webapp_count": 0, "webapp_types": [], "autostarter_webapp_count": 0}

        types_seen: set[str] = set()
        autostart_count = 0
        for wa in webapps:
            try:
                wa_dict = wa if isinstance(wa, dict) else {}
                wa_type = wa_dict.get("type")
                if wa_type:
                    types_seen.add(wa_type)
                wa_id = wa_dict.get("id")
                if wa_id:
                    raw = project.get_webapp(wa_id).get_settings().get_raw()
                    # Field name verified for DSS 14.x; may also be "autostart"
                    if raw.get("autoStart", raw.get("autostart", False)):
                        autostart_count += 1
            except Exception as e:
                log.warning("webapp detail failed", extra={"project_key": project_key, "error": str(e)})

    return {
        "webapp_count": len(webapps),
        "webapp_types": sorted(types_seen),
        "autostarter_webapp_count": autostart_count,
    }


def _fetch_scenarios(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            scenarios = project.list_scenarios()
            return {"scenario_count": len(scenarios)}
        except Exception as e:
            log.warning("list_scenarios failed", extra={"project_key": project_key, "error": str(e)})
            return {"scenario_count": 0}


def _fetch_jobs(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            jobs = project.list_jobs(active=False, limit=10)
        except Exception as e:
            log.warning("list_jobs failed", extra={"project_key": project_key, "error": str(e)})
            return {"last_built_on": None, "recent_job_success_rate": None, "recent_jobs_evaluated": 0}

    completed = [j for j in jobs if j.get("state") in _TERMINAL_JOB_STATES]
    recent = completed[:5]
    last_built_on: int | None = None
    if completed:
        last_built_on = completed[0].get("endTime") or completed[0].get("startTime")

    success_rate: float | None = None
    if recent:
        success_count = sum(1 for j in recent if j.get("state") == "DONE")
        success_rate = round(success_count / len(recent), 3)

    return {
        "last_built_on": last_built_on,
        "recent_job_success_rate": success_rate,
        "recent_jobs_evaluated": len(recent),
    }


def _fetch_eval_stores(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            stores = project.list_model_evaluation_stores()
            return {"model_evaluation_store_count": len(stores)}
        except Exception as e:
            log.warning("list_model_evaluation_stores unavailable", extra={
                "project_key": project_key, "error": str(e)})
            return {"model_evaluation_store_count": 0}


def _fetch_bundles(project_key: str, node_name: str | None = None) -> dict:
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        try:
            # Method may also be project.list_bundles() — verify for DSS 14.x
            bundles = project.list_project_bundles()
        except AttributeError:
            try:
                bundles = project.list_bundles()
            except Exception as e:
                log.warning("list_bundles unavailable", extra={"project_key": project_key, "error": str(e)})
                return {"bundle_count": 0, "has_bundle_on_deployer": False}
        except Exception as e:
            log.warning("list_project_bundles failed", extra={"project_key": project_key, "error": str(e)})
            return {"bundle_count": 0, "has_bundle_on_deployer": False}

        # A bundle has been sent to a deployer if it has a "released" or
        # "activatedOn" field. Exact field name requires verification.
        has_deployer = any(
            b.get("released") or b.get("activatedOn") or b.get("deployedOn")
            for b in bundles if isinstance(b, dict)
        )
        return {"bundle_count": len(bundles), "has_bundle_on_deployer": has_deployer}


def _fetch_llm_agents(project_key: str, node_name: str | None = None) -> dict:
    """Fetch LLM connection usage and agent presence.

    The agent API surface in DSS 14.x is still evolving. Approach:
    - Check project settings for LLM configuration blocks
    - Look for agent-type flow objects or dedicated list methods if available
    """
    with borrow_client(node_name) as client:
        project = client.get_project(project_key)

        llm_connections: list[str] = []
        has_agents = False
        agent_count = 0

        # Attempt 1: dedicated LLM config listing
        try:
            llm_confs = project.list_llm_confs()
            for conf in llm_confs:
                if isinstance(conf, dict):
                    name = conf.get("name") or conf.get("id")
                    if name:
                        llm_connections.append(name)
        except AttributeError:
            pass  # method not available in this version
        except Exception as e:
            log.warning("list_llm_confs failed", extra={"project_key": project_key, "error": str(e)})

        # Attempt 2: check project settings raw dict for LLM / agent blocks
        try:
            settings_raw = project.get_settings().get_raw()
            # LLM mesh settings may be under "llmMeshSettings" or "aiSettings"
            llm_block = settings_raw.get("llmMeshSettings", settings_raw.get("aiSettings", {}))
            if isinstance(llm_block, dict) and llm_block:
                # Extract connection references if present
                conns = llm_block.get("llmConnections", [])
                for c in conns:
                    name = c.get("name") or c.get("id") if isinstance(c, dict) else None
                    if name and name not in llm_connections:
                        llm_connections.append(name)
        except Exception as e:
            log.warning("agent/LLM settings check failed", extra={"project_key": project_key, "error": str(e)})

        # Attempt 3: dedicated agent listing (may not exist in 14.6)
        try:
            agents = project.list_agents()
            agent_count = len(agents)
            has_agents = agent_count > 0
        except AttributeError:
            pass  # not available
        except Exception as e:
            log.warning("list_agents failed", extra={"project_key": project_key, "error": str(e)})

    return {
        "llm_connection_names": llm_connections,
        "has_agents": has_agents,
        "agent_count": agent_count,
    }


# ---------------------------------------------------------------------------
# Phase 2 sub-fetchers (depend on Phase 1 results)
# ---------------------------------------------------------------------------

def _fetch_dq_rules(project_key: str, datasets_raw: list[dict], node_name: str | None = None) -> dict:
    """Count fraction of datasets that have ≥1 data quality rule.

    Capped at _DQ_CHECK_LIMIT datasets to bound API calls.
    """
    if not datasets_raw:
        return {"pct_datasets_with_dq_rules": None}

    to_check = datasets_raw[:_DQ_CHECK_LIMIT]
    has_rules_count = 0

    with borrow_client(node_name) as client:
        project = client.get_project(project_key)
        for d in to_check:
            name = d.get("name") if isinstance(d, dict) else None
            if not name:
                continue
            try:
                raw = _retry_read(lambda: project.get_dataset(name).get_settings().get_raw())
                # Field may be "checks", "dataQualityRules", or "monitoring.checks"
                checks = raw.get("checks", raw.get("dataQualityRules", []))
                if not checks and isinstance(raw.get("monitoring"), dict):
                    checks = raw["monitoring"].get("checks", [])
                if checks:
                    has_rules_count += 1
            except Exception as e:
                log.warning("DQ rule check failed", extra={
                    "project_key": project_key, "dataset": name, "error": str(e)})

    pct = round(has_rules_count / len(to_check), 3) if to_check else None
    return {
        "pct_datasets_with_dq_rules": pct,
        "_dq_capped": len(datasets_raw) > _DQ_CHECK_LIMIT,
    }


def _fetch_plugins(project_key: str, recipes_raw: list[dict], datasets_raw: list[dict], node_name: str | None = None) -> dict:
    """Collect plugin IDs referenced by recipes or dataset types in this project."""
    plugin_ids: set[str] = set()

    # Plugin recipes: type contains "." (e.g. "com.dataiku.myplugin.myrecipe")
    for r in recipes_raw:
        rtype = r.get("type", "") if isinstance(r, dict) else ""
        if rtype and "." in rtype:
            # Extract plugin prefix (before last segment)
            parts = rtype.rsplit(".", 1)
            if len(parts) == 2:
                plugin_ids.add(parts[0])

    # Plugin datasets: cross-reference dataset types with installed plugins
    with borrow_client(node_name) as client:
        try:
            installed = {p.get("id") for p in client.list_plugins() if isinstance(p, dict)}
        except Exception as e:
            log.warning("list_plugins failed", extra={"project_key": project_key, "error": str(e)})
            installed = set()

        for d in datasets_raw:
            dtype = d.get("type", "") if isinstance(d, dict) else ""
            # Plugin dataset types often match a plugin ID or contain "."
            if dtype and "." in dtype:
                parts = dtype.rsplit(".", 1)
                candidate = parts[0]
                if candidate in installed:
                    plugin_ids.add(candidate)
            elif dtype in installed:
                plugin_ids.add(dtype)

    return {"plugins_used": sorted(plugin_ids)}


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _assemble(project_key: str, node_name: str | None, p1: dict[str, dict], p2: dict[str, dict]) -> dict:
    """Merge phase results into the final get_project_summary response dict."""
    core = p1.get("core", {})
    recipes = p1.get("recipes", {})
    datasets = p1.get("datasets", {})
    jobs = p1.get("jobs", {})
    llm_agents = p1.get("llm_agents", {})
    webapps = p1.get("webapps", {})
    bundles = p1.get("bundles", {})
    ml_tasks = p1.get("ml_tasks", {})

    result = {
        "project_key": project_key,
        "node_name": node_name,
        "project_url": make_project_url(node_name, project_key) if node_name else None,
        # Identity
        "name": core.get("name"),
        "short_desc": core.get("short_desc"),
        "tags": core.get("tags", []),
        # Timestamps
        "last_modified_on": core.get("last_modified_on"),
        "last_built_on": jobs.get("last_built_on"),
        # Origin
        "inferred_origin": core.get("inferred_origin", "unknown"),
        # Recipes
        "recipe_count": recipes.get("recipe_count", 0),
        "recipe_counts_by_category": recipes.get("recipe_counts_by_category", _empty_recipe_counts()),
        # Datasets & connections
        "dataset_count": datasets.get("dataset_count", 0),
        "connection_types_used": datasets.get("connection_types_used", []),
        "pct_datasets_with_dq_rules": p2.get("dq_rules", {}).get("pct_datasets_with_dq_rules"),
        # AI / LLM / Agents
        "llm_connection_names": llm_agents.get("llm_connection_names", []),
        "has_agents": llm_agents.get("has_agents", False),
        "agent_count": llm_agents.get("agent_count", 0),
        # Dashboards
        **p1.get("dashboards", {}),
        # Web apps (webapp_types omitted — counts are sufficient)
        "webapp_count": webapps.get("webapp_count", 0),
        "autostarter_webapp_count": webapps.get("autostarter_webapp_count", 0),
        # Plugins
        "plugins_used": p2.get("plugins", {}).get("plugins_used", []),
        # Automation
        **p1.get("scenarios", {}),
        # ML
        "ml_task_count": ml_tasks.get("ml_task_count", 0),
        # Jobs
        "recent_job_success_rate": jobs.get("recent_job_success_rate"),
        "recent_jobs_evaluated": jobs.get("recent_jobs_evaluated", 0),
        # Model evaluation stores
        **p1.get("eval_stores", {}),
        # Bundles (bundle_count omitted — has_bundle_on_deployer is the meaningful signal)
        "has_bundle_on_deployer": bundles.get("has_bundle_on_deployer", False),
        # Collaboration
        "contributor_count": core.get("contributor_count"),
    }

    # Strip internal keys, then redact any credential values before returning
    clean = {k: v for k, v in result.items() if not k.startswith("_")}
    return redact(clean)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _retry_read(fn: Callable[[], Any], max_attempts: int = 3, base_delay: float = 0.5) -> Any:
    """Retry a no-argument callable with exponential backoff. Raises on final failure.

    Only use for safe, idempotent read operations.
    """
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception:
            if attempt == max_attempts - 1:
                raise
            time.sleep(base_delay * (2 ** attempt))


def _collect(futures: dict[str, Future], phase: int, project_key: str) -> dict[str, dict]:
    """Resolve all futures; on timeout or error, return empty dict for that key."""
    results: dict[str, dict] = {}
    for key, future in futures.items():
        try:
            results[key] = future.result(timeout=30)
        except Exception as e:
            log.warning("fetch failed", extra={
                "phase": phase, "fetch": key,
                "project_key": project_key, "error": str(e),
            })
            results[key] = {}
    return results


def _empty_recipe_counts() -> dict[str, int]:
    return {"visual": 0, "code": 0, "prompt_llm": 0, "plugin": 0}


def _infer_origin(tags: list[str], app_type: str, settings_raw: dict) -> dict:
    """Best-effort inference of project origin from available metadata."""
    tag_set = {t.lower() for t in tags if isinstance(t, str)}
    evidence: list[str] = []

    if tag_set & _SOLUTIONS_TAGS or "SOLUTION" in app_type.upper():
        evidence.append(f"tags={sorted(tag_set & _SOLUTIONS_TAGS)}" if tag_set & _SOLUTIONS_TAGS
                        else f"projectAppType={app_type}")
        return {"inferred_origin": "solutions_hub", "origin_evidence": evidence}

    if tag_set & _TUTORIAL_TAGS:
        evidence.append(f"tags={sorted(tag_set & _TUTORIAL_TAGS)}")
        return {"inferred_origin": "tutorial", "origin_evidence": evidence}

    # Imported projects may have an "importedFrom" or "sourceBundleId" field
    for key in ("importedFrom", "sourceBundleId", "importSource"):
        if settings_raw.get(key):
            evidence.append(f"{key}={settings_raw[key]}")
            return {"inferred_origin": "imported", "origin_evidence": evidence}

    return {"inferred_origin": "original", "origin_evidence": []}
