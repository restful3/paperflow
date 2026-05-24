"""Shared pytest fixtures for viewer tests."""
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(tmp_path, monkeypatch):
    """Isolated PaperFlow workspace: outputs/, archives/, newones/, logs/."""
    for sub in ("outputs", "archives", "newones", "newones/.meta", "newones/.mcp_tmp", "logs"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("BASE_DIR", str(tmp_path))
    # JWT_SECRET_KEY required for config.validate_runtime in some flows
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 48)

    # Force a fresh Settings instance that reads the new env
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()

    yield tmp_path

    # Restore default settings after test
    _cfg.settings = _cfg.Settings()


@pytest.fixture
def mcp_enabled_workspace(tmp_workspace, monkeypatch):
    """tmp_workspace + MCP env vars set. Cleans up MCP env to prevent pollution."""
    monkeypatch.setenv("MCP_API_KEY", "a" * 48)
    monkeypatch.setenv("MCP_PUBLIC_BASE_URL", "http://localhost:8090")
    from app import config as _cfg
    _cfg.settings = _cfg.Settings()
    try:
        yield tmp_workspace
    finally:
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        monkeypatch.delenv("MCP_PUBLIC_BASE_URL", raising=False)
        _cfg.settings = _cfg.Settings()
