from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from dss_mcp.tools.projects import _slim, list_all_tags, list_projects


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
