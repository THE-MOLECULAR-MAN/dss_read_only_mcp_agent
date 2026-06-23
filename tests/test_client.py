"""Tests for dss_mcp.client — node loading and configurable cert checking."""
from unittest.mock import MagicMock, patch

import pytest


class TestNoCertificateCheck:
    """DSS_NO_CHECK_CERTIFICATE env var controls TLS verification in _make_client."""

    def _call_make_client(self, env_value=None):
        """Call _make_client with a mocked DSSClient and return the constructor kwargs."""
        env = {}
        if env_value is not None:
            env["DSS_NO_CHECK_CERTIFICATE"] = env_value

        mock_client_instance = MagicMock()
        mock_client_instance._session = MagicMock()

        with patch.dict("os.environ", env, clear=False):
            with patch("dataikuapi.DSSClient", return_value=mock_client_instance) as mock_cls:
                from dss_mcp.client import _make_client
                _make_client("http://test-host", "test-key")
                return mock_cls.call_args

    def test_default_skips_cert_check(self):
        """no_check_certificate defaults to True when env var is unset."""
        with patch.dict("os.environ", {}, clear=False):
            # Remove the var if it happens to be set
            import os
            os.environ.pop("DSS_NO_CHECK_CERTIFICATE", None)
            call_args = self._call_make_client(env_value=None)
        assert call_args.kwargs["no_check_certificate"] is True

    def test_explicit_true_skips_cert_check(self):
        call_args = self._call_make_client(env_value="true")
        assert call_args.kwargs["no_check_certificate"] is True

    def test_explicit_true_uppercase(self):
        call_args = self._call_make_client(env_value="TRUE")
        assert call_args.kwargs["no_check_certificate"] is True

    def test_false_enables_cert_check(self):
        call_args = self._call_make_client(env_value="false")
        assert call_args.kwargs["no_check_certificate"] is False

    def test_false_uppercase_enables_cert_check(self):
        call_args = self._call_make_client(env_value="FALSE")
        assert call_args.kwargs["no_check_certificate"] is False

    def test_false_mixed_case_enables_cert_check(self):
        call_args = self._call_make_client(env_value="False")
        assert call_args.kwargs["no_check_certificate"] is False

    def test_any_non_false_value_skips_cert_check(self):
        # Any value other than "false" (case-insensitive) should behave as True
        call_args = self._call_make_client(env_value="yes")
        assert call_args.kwargs["no_check_certificate"] is True


class TestLoadNodesMissingEnvVars:
    """_load_nodes raises a clear RuntimeError when required env vars are absent.

    We call _load_nodes() directly (not via module import) so we don't touch
    sys.modules and contaminate other tests that already hold references to
    module-level functions like borrow_client.
    """

    def _env_without(self, *remove_keys):
        import os
        return {k: v for k, v in os.environ.items()
                if k not in remove_keys and not k.startswith("DSS_NODE_")}

    def test_missing_dss_host_raises_runtime_error(self):
        from dss_mcp.client import _load_nodes
        env = self._env_without("DSS_HOST")
        env["DSS_API_KEY"] = "test-key"
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="DSS_HOST"):
                _load_nodes()

    def test_missing_dss_api_key_raises_runtime_error(self):
        from dss_mcp.client import _load_nodes
        env = self._env_without("DSS_API_KEY")
        env["DSS_HOST"] = "http://test-host"
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(RuntimeError, match="DSS_API_KEY"):
                _load_nodes()
