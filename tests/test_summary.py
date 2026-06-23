from contextlib import contextmanager
from unittest.mock import MagicMock, call, patch

import pytest

from dss_mcp.tools.summary import (
    _assemble,
    _empty_recipe_counts,
    _fetch_recipes,
    _infer_origin,
    _retry_read,
)

_REDACTED = "[REDACTED]"


# ---------------------------------------------------------------------------
# _infer_origin — pure function
# ---------------------------------------------------------------------------

class TestInferOrigin:
    def test_solutions_tag(self):
        result = _infer_origin(["solutions", "retail"], "", {})
        assert result["inferred_origin"] == "solutions_hub"
        assert result["origin_evidence"]

    def test_solutions_hub_tag(self):
        result = _infer_origin(["solutions-hub"], "", {})
        assert result["inferred_origin"] == "solutions_hub"

    def test_solution_app_type(self):
        result = _infer_origin([], "SOLUTION_APP", {})
        assert result["inferred_origin"] == "solutions_hub"

    def test_solution_in_app_type_case_insensitive(self):
        result = _infer_origin([], "solution", {})
        assert result["inferred_origin"] == "solutions_hub"

    def test_tutorial_tag(self):
        result = _infer_origin(["tutorial"], "", {})
        assert result["inferred_origin"] == "tutorial"

    def test_getting_started_tag(self):
        result = _infer_origin(["getting-started"], "", {})
        assert result["inferred_origin"] == "tutorial"

    def test_training_tag(self):
        result = _infer_origin(["training"], "", {})
        assert result["inferred_origin"] == "tutorial"

    def test_imported_from_field(self):
        result = _infer_origin([], "", {"importedFrom": "bundle://xyz"})
        assert result["inferred_origin"] == "imported"
        assert any("importedFrom" in e for e in result["origin_evidence"])

    def test_source_bundle_id(self):
        result = _infer_origin([], "", {"sourceBundleId": "my-bundle-v1"})
        assert result["inferred_origin"] == "imported"

    def test_import_source_field(self):
        result = _infer_origin([], "", {"importSource": "some-source"})
        assert result["inferred_origin"] == "imported"

    def test_original_when_no_signals(self):
        result = _infer_origin(["ml", "finance"], "", {})
        assert result["inferred_origin"] == "original"
        assert result["origin_evidence"] == []

    def test_solutions_takes_priority_over_tutorial(self):
        result = _infer_origin(["solutions", "tutorial"], "", {})
        assert result["inferred_origin"] == "solutions_hub"

    def test_solutions_takes_priority_over_imported(self):
        result = _infer_origin(["solutions"], "", {"importedFrom": "bundle"})
        assert result["inferred_origin"] == "solutions_hub"

    def test_tutorial_takes_priority_over_imported(self):
        result = _infer_origin(["tutorial"], "", {"importedFrom": "bundle"})
        assert result["inferred_origin"] == "tutorial"

    def test_tag_match_is_case_insensitive(self):
        result = _infer_origin(["SOLUTIONS"], "", {})
        assert result["inferred_origin"] == "solutions_hub"

    def test_empty_inputs_returns_original(self):
        result = _infer_origin([], "", {})
        assert result["inferred_origin"] == "original"


# ---------------------------------------------------------------------------
# _empty_recipe_counts — pure function
# ---------------------------------------------------------------------------

class TestEmptyRecipeCounts:
    def test_returns_all_zero_categories(self):
        counts = _empty_recipe_counts()
        assert counts == {"visual": 0, "code": 0, "prompt_llm": 0, "plugin": 0}

    def test_returns_new_dict_each_call(self):
        a = _empty_recipe_counts()
        b = _empty_recipe_counts()
        a["visual"] = 99
        assert b["visual"] == 0


# ---------------------------------------------------------------------------
# _retry_read — mock time.sleep to keep tests fast
# ---------------------------------------------------------------------------

class TestRetryRead:
    def test_returns_immediately_on_success(self):
        fn = MagicMock(return_value=42)
        result = _retry_read(fn)
        assert result == 42
        fn.assert_called_once()

    def test_retries_once_then_succeeds(self):
        fn = MagicMock(side_effect=[RuntimeError("transient"), "ok"])
        with patch("dss_mcp.tools.summary.time.sleep"):
            result = _retry_read(fn, max_attempts=2, base_delay=0.01)
        assert result == "ok"
        assert fn.call_count == 2

    def test_raises_after_max_attempts(self):
        fn = MagicMock(side_effect=RuntimeError("always fails"))
        with patch("dss_mcp.tools.summary.time.sleep"):
            with pytest.raises(RuntimeError, match="always fails"):
                _retry_read(fn, max_attempts=3, base_delay=0.01)
        assert fn.call_count == 3

    def test_sleep_uses_exponential_backoff(self):
        fn = MagicMock(side_effect=[RuntimeError(), RuntimeError(), "ok"])
        with patch("dss_mcp.tools.summary.time.sleep") as mock_sleep:
            _retry_read(fn, max_attempts=3, base_delay=1.0)
        # Delays should be 1.0 * 2^0 = 1.0, then 1.0 * 2^1 = 2.0
        assert mock_sleep.call_args_list == [call(1.0), call(2.0)]

    def test_no_sleep_on_first_attempt_success(self):
        fn = MagicMock(return_value="done")
        with patch("dss_mcp.tools.summary.time.sleep") as mock_sleep:
            _retry_read(fn)
        mock_sleep.assert_not_called()

    def test_works_with_lambda(self):
        result = _retry_read(lambda: {"key": "value"})
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# _fetch_recipes — mocked borrow_client, exercises categorization logic
# ---------------------------------------------------------------------------

def _make_borrow(client):
    @contextmanager
    def _borrow(node_name=None):
        yield client
    return _borrow


class TestFetchRecipes:
    def _run(self, recipe_list):
        mock_client = MagicMock()
        mock_client.get_project.return_value.list_recipes.return_value = recipe_list
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(mock_client)):
            return _fetch_recipes("MY_PROJECT")

    def test_visual_recipe_counted(self):
        result = self._run([{"type": "shaker"}, {"type": "join"}])
        assert result["recipe_counts_by_category"]["visual"] == 2
        assert result["recipe_counts_by_category"]["code"] == 0

    def test_code_recipe_counted(self):
        result = self._run([{"type": "python"}, {"type": "sql"}])
        assert result["recipe_counts_by_category"]["code"] == 2

    def test_llm_recipe_counted(self):
        result = self._run([{"type": "llm"}])
        assert result["recipe_counts_by_category"]["prompt_llm"] == 1

    def test_plugin_recipe_counted_by_dot_notation(self):
        result = self._run([{"type": "com.dataiku.myplugin.myrecipe"}])
        assert result["recipe_counts_by_category"]["plugin"] == 1

    def test_empty_type_string_skipped(self):
        result = self._run([{"type": ""}, {"type": "python"}])
        assert result["recipe_count"] == 2  # both recipes exist
        assert result["recipe_counts_by_category"]["code"] == 1
        # The empty-type recipe must NOT be counted as a plugin
        assert result["recipe_counts_by_category"]["plugin"] == 0

    def test_missing_type_key_skipped(self):
        result = self._run([{"name": "no-type-key"}, {"type": "shaker"}])
        assert result["recipe_counts_by_category"]["visual"] == 1
        assert result["recipe_counts_by_category"]["plugin"] == 0

    def test_total_recipe_count(self):
        result = self._run([{"type": "python"}, {"type": "shaker"}, {"type": "llm"}])
        assert result["recipe_count"] == 3

    def test_types_present_sorted(self):
        result = self._run([{"type": "shaker"}, {"type": "python"}, {"type": "shaker"}])
        assert result["recipe_types_present"] == ["python", "shaker"]

    def test_raw_list_included(self):
        recipes = [{"type": "python", "name": "my_recipe"}]
        result = self._run(recipes)
        assert result["_raw"] == recipes

    def test_returns_error_defaults_on_exception(self):
        mock_client = MagicMock()
        mock_client.get_project.return_value.list_recipes.side_effect = RuntimeError("boom")
        with patch("dss_mcp.tools.summary.borrow_client", _make_borrow(mock_client)):
            result = _fetch_recipes("MY_PROJECT")
        assert result["recipe_count"] == 0
        assert result["_raw"] == []

    def test_mixed_recipe_types(self):
        recipes = [
            {"type": "python"},        # code
            {"type": "shaker"},        # visual
            {"type": "join"},          # visual
            {"type": "llm"},           # prompt_llm
            {"type": "com.x.plugin"},  # plugin
            {"type": ""},              # skipped
        ]
        result = self._run(recipes)
        counts = result["recipe_counts_by_category"]
        assert counts["code"] == 1
        assert counts["visual"] == 2
        assert counts["prompt_llm"] == 1
        assert counts["plugin"] == 1


# ---------------------------------------------------------------------------
# _assemble — pure function (operates on pre-built p1/p2 dicts)
# ---------------------------------------------------------------------------

def _make_p1():
    return {
        "core": {
            "name": "Demo Project",
            "short_desc": "A great demo",
            "tags": ["ml", "retail"],
            "owner_login": "alice",
            "last_modified_on": 1700000000,
            "project_standards_enforced": 3,
            "flow_zone_count": 2,
            "contributor_count": 5,
            "inferred_origin": "solutions_hub",
            "origin_evidence": ["tags=['solutions']"],
        },
        "recipes": {
            "recipe_count": 10,
            "recipe_counts_by_category": {"visual": 6, "code": 3, "prompt_llm": 1, "plugin": 0},
            "recipe_types_present": ["python", "shaker"],
            "_raw": [{"type": "python"}],  # _raw must be stripped from output
        },
        "datasets": {
            "dataset_count": 15,
            "connection_types_used": ["S3", "SQL_SERVER"],
            "connection_names_used": ["my-s3-conn"],
            "_raw": [{"name": "ds1"}],  # _raw must be stripped from output
        },
        "jobs": {
            "last_built_on": 1699999999,
            "recent_job_success_rate": 0.9,
            "recent_jobs_evaluated": 10,
        },
        "dashboards": {"dashboard_count": 3, "total_tile_count": 12},
        "webapps": {"webapp_count": 2, "webapp_types": ["BOKEH"], "autostarter_webapp_count": 1},
        "scenarios": {"scenario_count": 4},
        "notebooks": {"notebook_count": 2},
        "eval_stores": {"model_evaluation_store_count": 1},
        "bundles": {"bundle_count": 1, "has_bundle_on_deployer": True},
        "workspaces": {"in_workspace": True, "workspace_names": ["ws-prod"]},
        "llm_agents": {
            "has_agents": True,
            "agent_count": 2,
            "has_agent_tools": True,
            "has_agent_hub": False,
            "llm_connection_names": ["openai-conn"],
        },
        "ml_tasks": {"ml_task_count": 2, "ml_tasks": [{"name": "pred", "task_type": "PREDICTION"}]},
    }


def _make_p2():
    return {
        "dq_rules": {"pct_datasets_with_dq_rules": 0.6},
        "plugins": {"plugins_used": ["com.dataiku.myplugin"]},
        "data_collections": {"datasets_in_data_collection": 3},
    }


class TestAssemble:
    def test_project_key_present(self):
        result = _assemble("MY_PROJECT", None, _make_p1(), _make_p2())
        assert result["project_key"] == "MY_PROJECT"

    def test_identity_fields_from_core(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["name"] == "Demo Project"
        assert result["short_desc"] == "A great demo"
        assert result["tags"] == ["ml", "retail"]
        assert result["owner_login"] == "alice"

    def test_timestamps(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["last_modified_on"] == 1700000000
        assert result["last_built_on"] == 1699999999

    def test_origin_fields(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["inferred_origin"] == "solutions_hub"
        assert result["origin_evidence"] == ["tags=['solutions']"]

    def test_recipe_fields(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["recipe_count"] == 10
        assert result["recipe_counts_by_category"]["visual"] == 6
        assert result["recipe_types_present"] == ["python", "shaker"]

    def test_dataset_fields(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["dataset_count"] == 15
        assert result["connection_types_used"] == ["S3", "SQL_SERVER"]

    def test_raw_keys_stripped(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        for key in result:
            assert not key.startswith("_"), f"Internal key leaked: {key}"

    def test_dq_rules_from_phase2(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["pct_datasets_with_dq_rules"] == 0.6

    def test_plugins_from_phase2(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["plugins_used"] == ["com.dataiku.myplugin"]

    def test_data_collections_from_phase2(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["datasets_in_data_collection"] == 3

    def test_job_success_rate(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["recent_job_success_rate"] == 0.9
        assert result["recent_jobs_evaluated"] == 10

    def test_llm_agent_fields(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["has_agents"] is True
        assert result["agent_count"] == 2
        assert result["llm_connection_names"] == ["openai-conn"]

    def test_workspace_fields(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["in_workspace"] is True
        assert result["workspace_names"] == ["ws-prod"]

    def test_empty_phase_results_produce_safe_defaults(self):
        result = _assemble("K", None, {}, {})
        assert result["project_key"] == "K"
        assert result["recipe_count"] == 0
        assert result["dataset_count"] == 0
        assert result["pct_datasets_with_dq_rules"] is None
        assert result["plugins_used"] == []
        assert result["datasets_in_data_collection"] == 0

    def test_redact_applied_to_output(self):
        # Insert a base64-looking value into a field; _assemble must redact it
        p1 = _make_p1()
        p1["core"]["owner_login"] = "A" * 40  # looks like a base64 credential
        result = _assemble("K", None, p1, _make_p2())
        assert result["owner_login"] == _REDACTED

    def test_contributor_count(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["contributor_count"] == 5

    def test_bundle_fields(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["bundle_count"] == 1
        assert result["has_bundle_on_deployer"] is True

    def test_node_name_none_when_not_provided(self):
        result = _assemble("K", None, _make_p1(), _make_p2())
        assert result["node_name"] is None
        assert result["project_url"] is None

    def test_node_name_included_when_provided(self):
        result = _assemble("K", "my-node", _make_p1(), _make_p2())
        assert result["node_name"] == "my-node"
