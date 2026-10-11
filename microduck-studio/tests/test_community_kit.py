"""The community-kit bridge stays a read-only reachability check plus a draft builder.

The adapter GETs /api/health and /api/joints on the board tool with short timeouts and
never proxies serial or register operations. URL resolution prefers the explicit query
over the MICRODUCK_KIT_URL environment; a malformed URL is refused, not guessed. The UI
contract keeps the card registered and the draft bridge pointed at the calibration form.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from urllib.error import URLError

import pytest

from microduck_studio import community_kit


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def patch_urlopen(monkeypatch, responses: dict[str, dict]):
    def fake_urlopen(url, timeout):
        for path, payload in responses.items():
            if url.endswith(path):
                return FakeResponse(json.dumps(payload).encode("utf-8"))
        raise URLError(f"no fake for {url}")

    monkeypatch.setattr(community_kit.urllib.request, "urlopen", fake_urlopen)


HEALTH = {"data": {"name": "hls-servo-debugger", "time": 1.0}, "ok": True}
JOINTS = {"data": {"joints": [{"id": 20, "name": "left_hip_yaw"}, {"id": 21, "name": "left_hip_roll"}]}}


def test_url_resolution_prefers_explicit_then_env_then_settings(monkeypatch):
    monkeypatch.setenv("MICRODUCK_KIT_URL", "http://10.0.0.9:8765/")
    assert community_kit.resolve_base_url(None) == "http://10.0.0.9:8765"
    assert community_kit.resolve_base_url(" http://192.168.31.217:8765/ ") == "http://192.168.31.217:8765"
    # Project settings only apply when neither the page nor the environment says anything.
    assert community_kit.resolve_base_url(None, stored="http://192.168.31.4:8765") == "http://10.0.0.9:8765"
    monkeypatch.delenv("MICRODUCK_KIT_URL")
    assert community_kit.resolve_base_url(None, stored="http://192.168.31.4:8765") == "http://192.168.31.4:8765"
    assert community_kit.resolve_base_url(None) is None


def test_status_unconfigured_is_honest(monkeypatch):
    monkeypatch.delenv("MICRODUCK_KIT_URL", raising=False)
    value = community_kit.status(None)
    assert value["reachable"] is False
    assert value["base_url"] is None
    assert "填写" in value["note"]


def test_status_reachable_summarizes_joints(monkeypatch):
    patch_urlopen(monkeypatch, {"/api/health": HEALTH, "/api/joints": JOINTS})
    value = community_kit.status("http://192.168.31.217:8765")
    assert value["reachable"] is True
    assert value["tool"]["name"] == "hls-servo-debugger"
    assert value["tool"]["joint_count"] == 2
    assert value["ui"] == "http://192.168.31.217:8765/"
    assert "只读" in value["boundary_note"]


def test_status_unreachable_reports_error_without_raising(monkeypatch):
    def fail(url, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(community_kit.urllib.request, "urlopen", fail)
    value = community_kit.status("http://192.168.31.99:8765")
    assert value["reachable"] is False
    assert "URLError" in value["error"]


def test_status_refuses_non_http_scheme():
    with pytest.raises(ValueError, match="http"):
        community_kit.status("ftp://192.168.31.217:8765")


def test_deploy_harness_script_is_valid_shell():
    script = Path(__file__).parents[1] / "scripts" / "deploy_hls_debugger.sh"
    assert script.is_file()
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


def test_kit_card_is_registered_and_wired():
    web = Path(__file__).parents[1] / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'id="card-kit"' in html
    assert 'src="/assets/kit-studio.js' in html
    assert "window.KitStudio.init();" in html
    js = (web / "studio.js").read_text(encoding="utf-8")
    assert "['kit','核心板校准台']" in js
    assert "window.KitStudio?.receiveReport(data);" in js


def test_project_settings_store_kit_url(tmp_path):
    from microduck_studio.core import StudioStore

    store = StudioStore(tmp_path / "studio.db")
    project_id = store.create_project("test", str(tmp_path / "repo"))["id"]
    saved = store.save_project_settings(project_id, {
        "community_kit_url": " http://192.168.31.217:8765/ ",
        "execution_target": {"kind": "local"},
    })
    assert saved["data"]["community_kit_url"] == "http://192.168.31.217:8765"
    with pytest.raises(ValueError, match="http"):
        store.save_project_settings(project_id, {"community_kit_url": "192.168.31.217:8765"})
    cleared = store.save_project_settings(project_id, {"community_kit_url": ""})
    assert cleared["data"]["community_kit_url"] == ""
    # Server settings saves REPLACE the record: a save without the key drops it. Both
    # frontend writers (settings form, kit card) therefore GET-merge before PUT.
    dropped = store.save_project_settings(project_id, {"execution_target": {"kind": "local"}})
    assert "community_kit_url" not in dropped["data"]


def test_settings_form_and_kit_card_merge_before_saving():
    web = Path(__file__).parents[1] / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    # The settings form saves the whole record; it must carry the saved kit URL through.
    handler = html.split("$('settings-save').onclick")[1][:1200]
    assert "community_kit_url" in handler
    js = (web / "kit-studio.js").read_text(encoding="utf-8")
    assert "current.data" in js


def test_project_endpoint_reads_settings_url(monkeypatch, tmp_path):
    import microduck_studio.app as app_module
    from fastapi.testclient import TestClient

    store = app_module.store
    project_id = store.create_project("kit-url-test", str(tmp_path / "repo"))["id"]
    store.save_project_settings(project_id, {"community_kit_url": "http://192.168.31.99:8765"})
    monkeypatch.delenv("MICRODUCK_KIT_URL", raising=False)

    def fail(url, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr(app_module.community_kit.urllib.request, "urlopen", fail)
    client = TestClient(app_module.app)
    value = client.get(f"/api/projects/{project_id}/community-kit/status").json()
    assert value["reachable"] is False
    assert value["base_url"] == "http://192.168.31.99:8765"
    missing = client.get("/api/projects/missing/community-kit/status")
    assert missing.status_code == 404
