import subprocess

from fastapi.testclient import TestClient

import app.main as m


def test_system_parses_nvidia_smi(monkeypatch):
    # nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: b"42, 7800, 12288\n")
    r = TestClient(m.app).get("/system")
    assert r.status_code == 200
    d = r.json()
    assert d["util"] == 42
    assert d["vram_used_gb"] == round(7800 / 1024, 1)
    assert d["vram_total_gb"] == round(12288 / 1024, 1)


def test_system_handles_missing_nvidia_smi(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("nvidia-smi not found")
    monkeypatch.setattr(subprocess, "check_output", boom)
    r = TestClient(m.app).get("/system")
    assert r.status_code == 200
    assert r.json()["util"] is None
