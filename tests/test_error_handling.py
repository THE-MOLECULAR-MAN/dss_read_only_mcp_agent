"""
Tests for error handling inside each _fetch_* sub-fetcher.

A remote DSS Design node may host old or corrupted projects that raise
exceptions when their datasets, recipes, dashboards, analyses, etc. are
accessed. Every fetcher must:
  - Return safe defaults (zeros / None / empty lists) when the top-level
    list call fails entirely.
  - Skip the bad item and continue processing when only individual items
    inside a loop fail.
  - Fall back to an alternate API method when the primary one is missing
    (AttributeError).

All tests use a shared _make_borrow() helper to mock borrow_client without
touching the real connection pool.
"""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from dss_mcp.tools.summary import (
    _fetch_bundles,
    _fetch_core,
    _fetch_dashboards,
    _fetch_data_collections,
    _fetch_datasets,
    _fetch_dq_rules,
    _fetch_eval_stores,
    _fetch_jobs,
    _fetch_llm_agents,
    _fetch_ml_tasks,
    _fetch_notebooks,
    _fetch_plugins,
    _fetch_scenarios,
    _fetch_webapps,
    _fetch_workspaces,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_borrow(client):
    @contextmanager
    def _borrow(node_name=None):
        yield client
    return _borrow


def _mock_client(project_attrs=None):
    """Return a mock DSSClient whose get_project() returns a configured mock."""
    client = MagicMock()
    project = MagicMock()
    client.get_project.return_value = project
    if project_attrs:
        for attr, value in project_attrs.items():
            setattr(project, attr, value)
    return client, project


# ---------------------------------------------------------------------------
# _fetch_core
# ---------------------------------------------------------------------------

class TestFetchCoreErrors:
    def test_get_settings_failure_returns_safe_defaults(self):
        client, project = _mock_client()
        project.get_settings.side_effect = RuntimeError("metadata corrupt")
        project.get_timeline.return_value = {"allContributors": [], "lastModifiedOn": None}
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_core("BAD_PROJECT")
        assert result["name"] is None
        assert result["tags"] == []
        assert result["flow_zone_count"] == 0
        assert result["project_standards_enforced"] == 0

    def test_get_timeline_failure_returns_none_for_contributor_fields(self):
        client, project = _mock_client()
        project.get_settings.return_value.get_raw.return_value = {}
        project.get_timeline.side_effect = RuntimeError("timeline unavailable")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_core("BAD_PROJECT")
        assert result["contributor_count"] is None
        assert result["last_modified_on"] is None

    def test_both_settings_and_timeline_fail(self):
        client, project = _mock_client()
        project.get_settings.side_effect = RuntimeError("settings gone")
        project.get_timeline.side_effect = RuntimeError("timeline gone")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_core("BAD_PROJECT")
        # Must return a dict with all expected keys, not raise
        assert "name" in result
        assert "contributor_count" in result
        assert result["contributor_count"] is None


# ---------------------------------------------------------------------------
# _fetch_datasets
# ---------------------------------------------------------------------------

class TestFetchDatasetsErrors:
    def test_list_datasets_failure_returns_safe_defaults(self):
        client, project = _mock_client()
        project.list_datasets.side_effect = RuntimeError("project not found")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_datasets("BAD_PROJECT")
        assert result["dataset_count"] == 0
        assert result["connection_types_used"] == []
        assert result["connection_names_used"] == []
        assert result["_raw"] == []


# ---------------------------------------------------------------------------
# _fetch_ml_tasks
# ---------------------------------------------------------------------------

class TestFetchMlTasksErrors:
    def test_list_analyses_failure_returns_safe_defaults(self):
        client, project = _mock_client()
        project.list_analyses.side_effect = RuntimeError("analyses unavailable")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_ml_tasks("BAD_PROJECT")
        assert result["ml_task_count"] == 0
        assert result["ml_tasks"] == []

    def test_individual_analysis_failure_skips_and_continues(self):
        client, project = _mock_client()
        good_analysis = MagicMock()
        good_analysis.list_ml_tasks.return_value = [{"taskType": "PREDICTION"}]
        project.list_analyses.return_value = [
            {"analysisId": "good"},
            {"analysisId": "bad"},
        ]
        project.get_analysis.side_effect = lambda key: (
            good_analysis if key == "good" else (_ for _ in ()).throw(RuntimeError("corrupt"))
        )
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            with patch("dss_mcp.tools.summary.time.sleep"):
                result = _fetch_ml_tasks("MY_PROJECT")
        assert result["ml_task_count"] == 1

    def test_analysis_with_no_analysis_id_skipped(self):
        client, project = _mock_client()
        project.list_analyses.return_value = [{"no_id_field": "val"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_ml_tasks("MY_PROJECT")
        assert result["ml_task_count"] == 0


# ---------------------------------------------------------------------------
# _fetch_dashboards
# ---------------------------------------------------------------------------

class TestFetchDashboardsErrors:
    def test_list_dashboards_failure_returns_safe_defaults(self):
        client, project = _mock_client()
        project.list_dashboards.side_effect = RuntimeError("dashboards inaccessible")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_dashboards("BAD_PROJECT")
        assert result["dashboard_count"] == 0
        assert result["total_tile_count"] == 0

    def test_individual_dashboard_get_raw_failure_skips_tiles(self):
        # 2 dashboards listed; get_raw() fails for one. dashboard_count=2, tiles only from good one.
        client, project = _mock_client()
        project.list_dashboards.return_value = [{"id": "d1"}, {"id": "d2"}]

        good_raw = {"pages": [{"tiles": [1, 2, 3]}]}
        good_dash = MagicMock()
        good_dash.get_raw.return_value = good_raw

        bad_dash = MagicMock()
        bad_dash.get_raw.side_effect = RuntimeError("dashboard corrupt")

        project.get_dashboard.side_effect = lambda did: (
            good_dash if did == "d1" else bad_dash
        )
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_dashboards("MY_PROJECT")
        assert result["dashboard_count"] == 2
        assert result["total_tile_count"] == 3  # only from the good dashboard

    def test_dashboard_with_no_id_skipped(self):
        client, project = _mock_client()
        project.list_dashboards.return_value = [{"no_id": "val"}, {"id": "d1"}]
        good_dash = MagicMock()
        good_dash.get_raw.return_value = {"pages": [{"tiles": [1]}]}
        project.get_dashboard.return_value = good_dash
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_dashboards("MY_PROJECT")
        assert result["dashboard_count"] == 2
        assert result["total_tile_count"] == 1


# ---------------------------------------------------------------------------
# _fetch_webapps
# ---------------------------------------------------------------------------

class TestFetchWebappsErrors:
    def test_list_webapps_failure_returns_safe_defaults(self):
        client, project = _mock_client()
        project.list_webapps.side_effect = RuntimeError("webapps gone")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_webapps("BAD_PROJECT")
        assert result["webapp_count"] == 0
        assert result["webapp_types"] == []
        assert result["autostarter_webapp_count"] == 0

    def test_individual_webapp_get_settings_failure_still_counts_webapp(self):
        # webapp is listed and its type counted, but get_settings() fails → autostart not counted
        client, project = _mock_client()
        project.list_webapps.return_value = [
            {"id": "wa1", "type": "BOKEH"},
            {"id": "wa2", "type": "DASH"},
        ]
        good_settings = MagicMock()
        good_settings.get_raw.return_value = {"autoStart": True}

        bad_settings = MagicMock()
        bad_settings.get_raw.side_effect = RuntimeError("settings unreadable")

        good_webapp = MagicMock()
        good_webapp.get_settings.return_value = good_settings

        bad_webapp = MagicMock()
        bad_webapp.get_settings.return_value = bad_settings

        project.get_webapp.side_effect = lambda wid: (
            good_webapp if wid == "wa1" else bad_webapp
        )
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_webapps("MY_PROJECT")
        assert result["webapp_count"] == 2
        assert set(result["webapp_types"]) == {"BOKEH", "DASH"}
        assert result["autostarter_webapp_count"] == 1  # only the good one


# ---------------------------------------------------------------------------
# _fetch_scenarios
# ---------------------------------------------------------------------------

class TestFetchScenariosErrors:
    def test_list_scenarios_failure_returns_zero(self):
        client, project = _mock_client()
        project.list_scenarios.side_effect = RuntimeError("scenarios unavailable")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_scenarios("BAD_PROJECT")
        assert result["scenario_count"] == 0


# ---------------------------------------------------------------------------
# _fetch_jobs
# ---------------------------------------------------------------------------

class TestFetchJobsErrors:
    def test_list_jobs_failure_returns_none_defaults(self):
        client, project = _mock_client()
        project.list_jobs.side_effect = RuntimeError("job history unavailable")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_jobs("BAD_PROJECT")
        assert result["last_built_on"] is None
        assert result["recent_job_success_rate"] is None
        assert result["recent_jobs_evaluated"] == 0


# ---------------------------------------------------------------------------
# _fetch_notebooks
# ---------------------------------------------------------------------------

class TestFetchNotebooksErrors:
    def test_list_jupyter_notebooks_attribute_error_falls_back_to_list_notebooks(self):
        client, project = _mock_client()
        project.list_jupyter_notebooks.side_effect = AttributeError("no such method")
        project.list_notebooks.return_value = [MagicMock(), MagicMock()]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_notebooks("MY_PROJECT")
        assert result["notebook_count"] == 2

    def test_both_notebook_methods_fail_returns_zero(self):
        client, project = _mock_client()
        project.list_jupyter_notebooks.side_effect = AttributeError("missing")
        project.list_notebooks.side_effect = RuntimeError("also broken")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_notebooks("BAD_PROJECT")
        assert result["notebook_count"] == 0

    def test_list_jupyter_notebooks_non_attribute_error_returns_zero(self):
        client, project = _mock_client()
        project.list_jupyter_notebooks.side_effect = RuntimeError("kernel error")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_notebooks("BAD_PROJECT")
        assert result["notebook_count"] == 0


# ---------------------------------------------------------------------------
# _fetch_eval_stores
# ---------------------------------------------------------------------------

class TestFetchEvalStoresErrors:
    def test_list_model_evaluation_stores_failure_returns_zero(self):
        client, project = _mock_client()
        project.list_model_evaluation_stores.side_effect = RuntimeError("MES unavailable")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_eval_stores("BAD_PROJECT")
        assert result["model_evaluation_store_count"] == 0


# ---------------------------------------------------------------------------
# _fetch_bundles
# ---------------------------------------------------------------------------

class TestFetchBundlesErrors:
    def test_list_project_bundles_attribute_error_falls_back_to_list_bundles(self):
        client, project = _mock_client()
        project.list_project_bundles.side_effect = AttributeError("not in this version")
        project.list_bundles.return_value = [{"id": "b1"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_bundles("MY_PROJECT")
        assert result["bundle_count"] == 1

    def test_both_bundle_methods_fail_returns_safe_defaults(self):
        client, project = _mock_client()
        project.list_project_bundles.side_effect = AttributeError("missing")
        project.list_bundles.side_effect = RuntimeError("also broken")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_bundles("BAD_PROJECT")
        assert result["bundle_count"] == 0
        assert result["has_bundle_on_deployer"] is False

    def test_list_project_bundles_non_attribute_error_returns_safe_defaults(self):
        client, project = _mock_client()
        project.list_project_bundles.side_effect = RuntimeError("permission denied")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_bundles("BAD_PROJECT")
        assert result["bundle_count"] == 0
        assert result["has_bundle_on_deployer"] is False


# ---------------------------------------------------------------------------
# _fetch_workspaces
# ---------------------------------------------------------------------------

class TestFetchWorkspacesErrors:
    def test_list_workspaces_attribute_error_returns_not_in_workspace(self):
        client = MagicMock()
        client.list_workspaces.side_effect = AttributeError("no workspace support")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_workspaces("MY_PROJECT")
        assert result["in_workspace"] is False
        assert result["workspace_names"] == []

    def test_list_workspaces_general_failure_returns_not_in_workspace(self):
        client = MagicMock()
        client.list_workspaces.side_effect = RuntimeError("workspace API down")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_workspaces("MY_PROJECT")
        assert result["in_workspace"] is False

    def test_individual_workspace_item_check_failure_skips_and_continues(self):
        client = MagicMock()
        # Two workspaces: bad one raises, good one contains our project
        client.list_workspaces.return_value = [
            {"name": "ws-bad", "workspaceKey": "WS_BAD"},
            {"name": "ws-good", "workspaceKey": "WS_GOOD"},
        ]
        bad_ws = MagicMock()
        bad_ws.list_objects.side_effect = RuntimeError("workspace corrupt")

        good_ws = MagicMock()
        good_ws.list_objects.return_value = [{"projectKey": "MY_PROJECT"}]

        client.get_workspace.side_effect = lambda key: (
            bad_ws if key == "WS_BAD" else good_ws
        )
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_workspaces("MY_PROJECT")
        assert result["in_workspace"] is True
        assert result["workspace_names"] == ["ws-good"]


# ---------------------------------------------------------------------------
# _fetch_llm_agents
# ---------------------------------------------------------------------------

class TestFetchLlmAgentsErrors:
    def test_list_llm_confs_attribute_error_continues_silently(self):
        client, project = _mock_client()
        project.list_llm_confs.side_effect = AttributeError("not in this version")
        project.get_settings.return_value.get_raw.return_value = {}
        project.list_agents.side_effect = AttributeError("no agents API")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_llm_agents("MY_PROJECT")
        assert result["has_agents"] is False
        assert result["llm_connection_names"] == []

    def test_list_llm_confs_general_failure_continues(self):
        client, project = _mock_client()
        project.list_llm_confs.side_effect = RuntimeError("LLM API error")
        project.get_settings.return_value.get_raw.return_value = {}
        project.list_agents.side_effect = AttributeError("no agents API")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_llm_agents("MY_PROJECT")
        # Must not raise; returns empty lists
        assert "llm_connection_names" in result

    def test_get_settings_failure_continues(self):
        client, project = _mock_client()
        project.list_llm_confs.side_effect = AttributeError()
        project.get_settings.side_effect = RuntimeError("settings unreadable")
        project.list_agents.return_value = [MagicMock(), MagicMock()]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_llm_agents("MY_PROJECT")
        assert result["agent_count"] == 2
        assert result["has_agents"] is True

    def test_list_agents_attribute_error_continues_silently(self):
        client, project = _mock_client()
        project.list_llm_confs.side_effect = AttributeError()
        project.get_settings.return_value.get_raw.return_value = {}
        project.list_agents.side_effect = AttributeError("no agents in this version")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_llm_agents("MY_PROJECT")
        assert result["agent_count"] == 0
        assert result["has_agents"] is False

    def test_list_agents_general_failure_continues(self):
        client, project = _mock_client()
        project.list_llm_confs.side_effect = AttributeError()
        project.get_settings.return_value.get_raw.return_value = {}
        project.list_agents.side_effect = RuntimeError("agent API down")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_llm_agents("MY_PROJECT")
        assert result["agent_count"] == 0


# ---------------------------------------------------------------------------
# _fetch_dq_rules (Phase 2)
# ---------------------------------------------------------------------------

class TestFetchDqRulesErrors:
    def test_individual_dataset_failure_skips_and_continues(self):
        # 3 datasets; first fails, remaining two succeed (one has rules, one doesn't)
        client, project = _mock_client()

        def mock_get_dataset(name):
            ds = MagicMock()
            if name == "ds_bad":
                ds.get_settings.side_effect = RuntimeError("dataset corrupt")
            elif name == "ds_with_rules":
                ds.get_settings.return_value.get_raw.return_value = {"checks": [{"name": "not_null"}]}
            else:
                ds.get_settings.return_value.get_raw.return_value = {"checks": []}
            return ds

        project.get_dataset.side_effect = mock_get_dataset
        datasets_raw = [
            {"name": "ds_bad"},
            {"name": "ds_with_rules"},
            {"name": "ds_no_rules"},
        ]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            with patch("dss_mcp.tools.summary.time.sleep"):
                result = _fetch_dq_rules("MY_PROJECT", datasets_raw)
        # 1 out of 3 checked datasets has rules (bad counts as no-rules in denominator)
        assert result["pct_datasets_with_dq_rules"] == pytest.approx(1 / 3, rel=1e-3)

    def test_all_datasets_fail_returns_zero_pct(self):
        client, project = _mock_client()
        project.get_dataset.side_effect = RuntimeError("all datasets inaccessible")
        datasets_raw = [{"name": "ds1"}, {"name": "ds2"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            with patch("dss_mcp.tools.summary.time.sleep"):
                result = _fetch_dq_rules("MY_PROJECT", datasets_raw)
        assert result["pct_datasets_with_dq_rules"] == pytest.approx(0.0)

    def test_empty_datasets_raw_returns_none(self):
        # No datasets to check → pct is None, not 0
        result = _fetch_dq_rules("MY_PROJECT", [])
        assert result["pct_datasets_with_dq_rules"] is None

    def test_dataset_with_no_name_skipped(self):
        client, project = _mock_client()
        good = MagicMock()
        good.get_settings.return_value.get_raw.return_value = {"checks": [{"name": "c"}]}
        project.get_dataset.return_value = good
        datasets_raw = [{"no_name_key": "val"}, {"name": "ds_good"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_dq_rules("MY_PROJECT", datasets_raw)
        # Only ds_good was checked (1 out of 2 total, but 1 out of 1 checked)
        # Actually: to_check = both, but name is None for first → skipped entirely
        # has_rules_count=1, len(to_check)=2 → 0.5
        assert result["pct_datasets_with_dq_rules"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# _fetch_plugins (Phase 2)
# ---------------------------------------------------------------------------

class TestFetchPluginsErrors:
    def test_list_plugins_failure_falls_back_to_recipe_based_detection(self):
        client = MagicMock()
        client.list_plugins.side_effect = RuntimeError("plugins API unavailable")
        recipes_raw = [{"type": "com.example.myplugin.myrecipe"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_plugins("MY_PROJECT", recipes_raw, [])
        # Plugin extracted from recipe type even though list_plugins failed
        assert "com.example.myplugin" in result["plugins_used"]

    def test_list_plugins_failure_prevents_dataset_type_matching(self):
        # Without list_plugins we can't match dataset types to plugin IDs
        client = MagicMock()
        client.list_plugins.side_effect = RuntimeError("unavailable")
        datasets_raw = [{"type": "com.example.myplugin"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_plugins("MY_PROJECT", [], datasets_raw)
        # Dataset type can't be confirmed as a plugin without installed list
        assert result["plugins_used"] == []


# ---------------------------------------------------------------------------
# _fetch_data_collections (Phase 2)
# ---------------------------------------------------------------------------

class TestFetchDataCollectionsErrors:
    def test_list_data_collections_attribute_error_returns_zero(self):
        client = MagicMock()
        client.list_data_collections.side_effect = AttributeError("not available")
        datasets_raw = [{"name": "ds1"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_data_collections("MY_PROJECT", datasets_raw)
        assert result["datasets_in_data_collection"] == 0

    def test_list_data_collections_general_failure_returns_zero(self):
        client = MagicMock()
        client.list_data_collections.side_effect = RuntimeError("collections unavailable")
        datasets_raw = [{"name": "ds1"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_data_collections("MY_PROJECT", datasets_raw)
        assert result["datasets_in_data_collection"] == 0

    def test_individual_collection_item_check_failure_skips_and_continues(self):
        client = MagicMock()
        client.list_data_collections.return_value = [{"id": "c_bad"}, {"id": "c_good"}]

        bad_coll = MagicMock()
        bad_coll.get_items.side_effect = RuntimeError("collection corrupt")

        good_coll = MagicMock()
        good_coll.get_items.return_value = [
            {"projectKey": "MY_PROJECT", "datasetName": "ds1"},
        ]

        client.get_data_collection.side_effect = lambda cid: (
            bad_coll if cid == "c_bad" else good_coll
        )
        datasets_raw = [{"name": "ds1"}]
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(client)):
            result = _fetch_data_collections("MY_PROJECT", datasets_raw)
        assert result["datasets_in_data_collection"] == 1
