from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from dss_mcp.tools.projects import (
    _is_viable_demo,
    _slim,
    _sufficient_commits,
    count_projects,
    list_all_tags,
    list_projects,
)


# ---------------------------------------------------------------------------
# _slim — pure function, no mocking needed
# ---------------------------------------------------------------------------

_NODE = "test-node"


class TestSlim:
    def test_extracts_project_key(self):
        p = {"projectKey": "MY_PROJECT", "tags": []}
        assert _slim(p, _NODE)["project_key"] == "MY_PROJECT"

    def test_extracts_name(self):
        p = {"name": "My Project", "tags": []}
        assert _slim(p, _NODE)["name"] == "My Project"

    def test_extracts_short_desc(self):
        p = {"shortDesc": "A description", "tags": []}
        assert _slim(p, _NODE)["short_desc"] == "A description"

    def test_extracts_owner_login(self):
        p = {"ownerLogin": "alice", "tags": []}
        assert _slim(p, _NODE)["owner_login"] == "alice"

    def test_string_tags_passed_through(self):
        p = {"tags": ["ml", "finance"]}
        assert _slim(p, _NODE)["tags"] == ["ml", "finance"]

    def test_dict_tags_extract_name(self):
        p = {"tags": [{"name": "ml"}, {"name": "finance"}]}
        assert _slim(p, _NODE)["tags"] == ["ml", "finance"]

    def test_mixed_tag_formats(self):
        p = {"tags": ["string-tag", {"name": "dict-tag"}]}
        assert _slim(p, _NODE)["tags"] == ["string-tag", "dict-tag"]

    def test_empty_dict_tags_filtered_out(self):
        p = {"tags": [{"name": ""}, {"name": "valid"}]}
        assert _slim(p, _NODE)["tags"] == ["valid"]

    def test_last_modified_from_version_tag(self):
        p = {"versionTag": {"lastModifiedOn": 1700000000}, "tags": []}
        assert _slim(p, _NODE)["last_modified_on"] == 1700000000

    def test_last_modified_fallback_when_no_version_tag(self):
        p = {"lastModifiedOn": 1600000000, "tags": []}
        assert _slim(p, _NODE)["last_modified_on"] == 1600000000

    def test_last_modified_none_when_missing_entirely(self):
        assert _slim({}, _NODE)["last_modified_on"] is None

    def test_missing_fields_return_none_or_empty(self):
        result = _slim({}, _NODE)
        assert result["project_key"] is None
        assert result["name"] is None
        assert result["short_desc"] is None
        assert result["owner_login"] is None
        assert result["tags"] == []

    def test_node_name_present(self):
        assert _slim({}, _NODE)["node_name"] == _NODE

    def test_non_dict_version_tag_falls_back(self):
        # If versionTag is present but not a dict, use top-level fallback
        p = {"versionTag": "not-a-dict", "lastModifiedOn": 999, "tags": []}
        assert _slim(p, _NODE)["last_modified_on"] == 999


# ---------------------------------------------------------------------------
# list_projects — mocked borrow_client
# ---------------------------------------------------------------------------

def _make_borrow(client):
    @contextmanager
    def _borrow(node_name=None):
        yield client
    return _borrow


class TestListProjects:
    def test_returns_slimmed_list(self):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [
            {"projectKey": "A", "name": "Alpha", "shortDesc": "", "tags": [],
             "ownerLogin": "alice", "versionTag": {"lastModifiedOn": 1}},
            {"projectKey": "B", "name": "Beta", "shortDesc": "desc", "tags": ["ml"],
             "ownerLogin": "bob", "versionTag": {"lastModifiedOn": 2}},
        ]
        # Both projects must pass the viability check
        mock_project = MagicMock()
        mock_project.list_datasets.return_value = [1, 2, 3]
        mock_project.list_recipes.return_value = [1, 2, 3]
        mock_project.list_jobs.return_value = [{"state": "DONE"}]
        mock_client.get_project.return_value = mock_project

        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_projects()

        assert len(result) == 2
        assert result[0]["project_key"] == "A"
        assert result[1]["project_key"] == "B"
        assert result[1]["tags"] == ["ml"]

    def test_returns_error_dict_on_exception(self):
        mock_client = MagicMock()
        mock_client.list_projects.side_effect = RuntimeError("connection refused")
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_projects()

        assert isinstance(result, dict)
        assert result["error"] == "list_projects_failed"
        assert "connection refused" in result["detail"]

    def test_empty_project_list(self):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = []
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_projects()

        assert result == []


# ---------------------------------------------------------------------------
# list_all_tags — mocked borrow_client
# ---------------------------------------------------------------------------

class TestListAllTags:
    def test_deduplicates_and_sorts(self):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [
            {"tags": ["ml", "finance"]},
            {"tags": ["finance", "retail"]},
        ]
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_all_tags()

        assert result == ["finance", "ml", "retail"]

    def test_handles_dict_tags(self):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [
            {"tags": [{"name": "agents"}, {"name": "llm"}]},
        ]
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_all_tags()

        assert result == ["agents", "llm"]

    def test_handles_mixed_tag_formats(self):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [
            {"tags": ["string-tag", {"name": "dict-tag"}]},
        ]
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_all_tags()

        assert sorted(result) == ["dict-tag", "string-tag"]

    def test_skips_dict_tags_with_no_name(self):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [
            {"tags": [{"other_key": "val"}, {"name": "valid"}]},
        ]
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_all_tags()

        assert result == ["valid"]

    def test_returns_empty_list_on_exception(self):
        # Errors are caught per-node inside _collect_tags; failed nodes contribute
        # zero tags rather than surfacing an error dict.
        mock_client = MagicMock()
        mock_client.list_projects.side_effect = ConnectionError("timeout")
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_all_tags()

        assert result == []

    def test_empty_project_list_returns_empty(self):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = []
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_all_tags()

        assert result == []


# ---------------------------------------------------------------------------
# count_projects — mocked borrow_client + get_nodes
# ---------------------------------------------------------------------------

def _make_node(name="test-node", host="http://test-dss-host"):
    node = MagicMock()
    node.name = name
    node.host = host
    return node


class TestCountProjects:
    def test_returns_total_and_per_node_fields(self):
        mock_client = MagicMock()
        mock_client.list_project_keys.return_value = ["A", "B", "C"]
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)), \
             patch("dss_mcp.tools.projects.get_nodes", return_value=[_make_node()]):
            result = count_projects()

        assert result["total_project_count"] == 3
        assert len(result["nodes"]) == 1
        node = result["nodes"][0]
        assert node["project_count"] == 3
        assert node["node_name"] == "test-node"
        assert node["host"] == "http://test-dss-host"
        assert node["status"] == "ok"

    def test_empty_node_returns_zero(self):
        mock_client = MagicMock()
        mock_client.list_project_keys.return_value = []
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)), \
             patch("dss_mcp.tools.projects.get_nodes", return_value=[_make_node()]):
            result = count_projects()

        assert result["total_project_count"] == 0
        assert result["nodes"][0]["project_count"] == 0

    def test_node_error_sets_status_and_zero_count(self):
        mock_client = MagicMock()
        mock_client.list_project_keys.side_effect = RuntimeError("unreachable")
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)), \
             patch("dss_mcp.tools.projects.get_nodes", return_value=[_make_node()]):
            result = count_projects()

        assert result["total_project_count"] == 0
        node = result["nodes"][0]
        assert node["status"] == "error"
        assert "unreachable" in node["detail"]
        assert node["project_count"] == 0

    def test_multi_node_sums_counts(self):
        # Each call to list_project_keys returns a different list
        call_results = [["A", "B", "C"], ["D", "E", "F", "G", "H"]]
        mock_client = MagicMock()
        mock_client.list_project_keys.side_effect = call_results
        nodes = [_make_node("node1", "http://host1"), _make_node("node2", "http://host2")]
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)), \
             patch("dss_mcp.tools.projects.get_nodes", return_value=nodes):
            result = count_projects()

        assert result["total_project_count"] == 8
        assert len(result["nodes"]) == 2

    def test_multi_node_partial_error_sums_successful(self):
        mock_client = MagicMock()
        mock_client.list_project_keys.side_effect = [["A", "B"], RuntimeError("down")]
        nodes = [_make_node("ok-node", "http://ok"), _make_node("bad-node", "http://bad")]
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)), \
             patch("dss_mcp.tools.projects.get_nodes", return_value=nodes):
            result = count_projects()

        assert result["total_project_count"] == 2
        statuses = {n["node_name"]: n["status"] for n in result["nodes"]}
        assert statuses["ok-node"] == "ok"
        assert statuses["bad-node"] == "error"


# ---------------------------------------------------------------------------
# _sufficient_commits — pure function
# ---------------------------------------------------------------------------

class TestSufficientCommits:
    def test_version_above_2_passes(self):
        assert _sufficient_commits({"versionTag": {"versionNumber": 5}}) is True

    def test_version_3_passes(self):
        assert _sufficient_commits({"versionTag": {"versionNumber": 3}}) is True

    def test_version_2_filtered(self):
        assert _sufficient_commits({"versionTag": {"versionNumber": 2}}) is False

    def test_version_1_filtered(self):
        assert _sufficient_commits({"versionTag": {"versionNumber": 1}}) is False

    def test_version_0_filtered(self):
        assert _sufficient_commits({"versionTag": {"versionNumber": 0}}) is False

    def test_missing_version_tag_passes(self):
        assert _sufficient_commits({"projectKey": "P"}) is True

    def test_non_dict_version_tag_passes(self):
        assert _sufficient_commits({"versionTag": "not-a-dict"}) is True

    def test_version_tag_dict_missing_version_number_passes(self):
        assert _sufficient_commits({"versionTag": {"lastModifiedOn": 123}}) is True

    def test_empty_dict_passes(self):
        assert _sufficient_commits({}) is True


# ---------------------------------------------------------------------------
# _is_viable_demo — mocked borrow_client
# ---------------------------------------------------------------------------

def _make_viable_project():
    """Return a mock project handle that passes all three viability checks."""
    project = MagicMock()
    project.list_datasets.return_value = [1, 2, 3]
    project.list_recipes.return_value = [1, 2, 3]
    project.list_jobs.return_value = [{"state": "DONE"}]
    return project


class TestIsViableDemo:
    def test_passes_when_all_thresholds_met(self):
        mock_client = MagicMock()
        mock_client.get_project.return_value = _make_viable_project()
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is True

    def test_filtered_when_fewer_than_2_datasets(self):
        mock_client = MagicMock()
        project = _make_viable_project()
        project.list_datasets.return_value = [1]
        mock_client.get_project.return_value = project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is False

    def test_filtered_when_zero_datasets(self):
        mock_client = MagicMock()
        project = _make_viable_project()
        project.list_datasets.return_value = []
        mock_client.get_project.return_value = project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is False

    def test_filtered_when_fewer_than_2_recipes(self):
        mock_client = MagicMock()
        project = _make_viable_project()
        project.list_recipes.return_value = [1]
        mock_client.get_project.return_value = project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is False

    def test_filtered_when_no_jobs_ever_run(self):
        mock_client = MagicMock()
        project = _make_viable_project()
        project.list_jobs.return_value = []
        mock_client.get_project.return_value = project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is False

    def test_passes_when_exactly_2_datasets_and_2_recipes(self):
        mock_client = MagicMock()
        project = _make_viable_project()
        project.list_datasets.return_value = [1, 2]
        project.list_recipes.return_value = [1, 2]
        mock_client.get_project.return_value = project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is True

    def test_fail_open_when_dataset_api_errors(self):
        mock_client = MagicMock()
        project = _make_viable_project()
        project.list_datasets.side_effect = RuntimeError("datasets unavailable")
        mock_client.get_project.return_value = project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is True

    def test_fail_open_when_recipe_api_errors(self):
        mock_client = MagicMock()
        project = _make_viable_project()
        project.list_recipes.side_effect = RuntimeError("recipes unavailable")
        mock_client.get_project.return_value = project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            assert _is_viable_demo("P", _NODE) is True

    def test_fail_open_when_borrow_client_errors(self):
        def _bad_borrow(node_name=None):
            raise RuntimeError("pool exhausted")
        with patch("dss_mcp.tools.projects.borrow_client", _bad_borrow):
            assert _is_viable_demo("P", _NODE) is True


# ---------------------------------------------------------------------------
# list_projects — filtering integration
# ---------------------------------------------------------------------------

class TestListProjectsFiltering:
    def _make_viable_client(self, projects):
        mock_client = MagicMock()
        mock_client.list_projects.return_value = projects
        mock_project = MagicMock()
        mock_project.list_datasets.return_value = [1, 2, 3]
        mock_project.list_recipes.return_value = [1, 2, 3]
        mock_project.list_jobs.return_value = [{"state": "DONE"}]
        mock_client.get_project.return_value = mock_project
        return mock_client

    def test_commit_filter_removes_stub_projects(self):
        stub = {"projectKey": "STUB", "name": "Stub", "tags": [],
                "versionTag": {"versionNumber": 1, "lastModifiedOn": 1}}
        real = {"projectKey": "REAL", "name": "Real", "tags": [],
                "versionTag": {"versionNumber": 10, "lastModifiedOn": 2}}
        mock_client = self._make_viable_client([stub, real])
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_projects()
        keys = [r["project_key"] for r in result]
        assert "STUB" not in keys
        assert "REAL" in keys

    def test_dataset_filter_removes_sparse_projects(self):
        project_key = "SPARSE"
        raw = {"projectKey": project_key, "name": "Sparse", "tags": [],
               "versionTag": {"versionNumber": 5}}
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [raw]
        sparse_project = MagicMock()
        sparse_project.list_datasets.return_value = [1]  # only 1 dataset → filtered
        sparse_project.list_recipes.return_value = [1, 2, 3]
        sparse_project.list_jobs.return_value = [{"state": "DONE"}]
        mock_client.get_project.return_value = sparse_project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_projects()
        assert result == []

    def test_job_filter_removes_never_run_projects(self):
        raw = {"projectKey": "IDLE", "name": "Idle", "tags": [],
               "versionTag": {"versionNumber": 5}}
        mock_client = MagicMock()
        mock_client.list_projects.return_value = [raw]
        idle_project = MagicMock()
        idle_project.list_datasets.return_value = [1, 2, 3]
        idle_project.list_recipes.return_value = [1, 2, 3]
        idle_project.list_jobs.return_value = []  # no jobs → filtered
        mock_client.get_project.return_value = idle_project
        with patch("dss_mcp.tools.projects.borrow_client", _make_borrow(mock_client)):
            result = list_projects()
        assert result == []
