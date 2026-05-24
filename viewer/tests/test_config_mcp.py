"""Tests for MCP_* config settings."""
import pytest


def test_mcp_disabled_when_key_empty(tmp_workspace, monkeypatch):
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_enabled is False


def test_mcp_enabled_requires_base_url(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "k" * 48)
    monkeypatch.delenv("MCP_PUBLIC_BASE_URL", raising=False)
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    with pytest.raises(RuntimeError, match="MCP_PUBLIC_BASE_URL"):
        _ = _cfg.settings.mcp_enabled


def test_mcp_enabled_true_when_both_set(mcp_enabled_workspace):
    from app import config as _cfg
    assert _cfg.settings.mcp_enabled is True


def test_mcp_short_key_disabled(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_API_KEY", "short")
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", "http://localhost:8090")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_enabled is False


def test_origin_derive_default(mcp_enabled_workspace, monkeypatch):
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    origins = _cfg.settings.mcp_allowed_origins_set
    assert "http://localhost:8090" in origins
    assert "http://localhost" in origins
    assert "http://127.0.0.1" in origins
    assert "*" not in origins


def test_origin_explicit_wildcard(mcp_enabled_workspace, monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "*")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_allowed_origins_set == {"*"}


def test_origin_explicit_csv(mcp_enabled_workspace, monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://a.com, https://b.com")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    assert _cfg.settings.mcp_allowed_origins_set == {"https://a.com", "https://b.com"}


def test_mcp_require_translation_default_true(tmp_workspace):
    from app.config import Settings
    s = Settings()
    assert s.MCP_REQUIRE_TRANSLATION is True


def test_mcp_require_translation_env_false(tmp_workspace, monkeypatch):
    monkeypatch.setenv("MCP_REQUIRE_TRANSLATION", "false")
    from app.config import Settings
    s = Settings()
    assert s.MCP_REQUIRE_TRANSLATION is False
