import json
from urllib.error import URLError

import pytest

from microduck_studio.kissqy_connector import KissqyTrainingService


class Response:
    def __init__(self, value, status=200, headers=None):
        self.value = value
        self.status = status
        self.headers = headers or {}

    def read(self, *_):
        return self.value if isinstance(self.value, bytes) else json.dumps(self.value).encode()

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def fixture_service(tmp_path, payloads, calls):
    def opener(request, timeout):
        calls.append(request)
        key = request.full_url.split("?", 1)[0]
        value = payloads.get((request.method, key), payloads.get(key))
        if isinstance(value, Exception):
            raise value
        if value is None:
            return Response({"error": "missing"}, 404)
        return Response(value)

    return KissqyTrainingService(
        "http://127.0.0.1:8092", tmp_path / "studio.db", opener=opener
    )


def base_payloads():
    return {
        "http://127.0.0.1:8092/api/config": {
            "token": "server-only-token",
            "version": "Studio R1.5.17",
            "release": "R17",
            "platform": "linux",
        },
        "http://127.0.0.1:8092/api/state": {
            "target_runtime": "reference-runtime",
            "computer_verified": True,
            "environment": {"ready": True, "status": "ready", "message": "ready"},
            "profile": {"mode": "local", "repo": "/private/path"},
            "training_queue": {
                "enabled": False,
                "failure_policy": "pause",
                "entries": [
                    {
                        "id": "a" * 16,
                        "client_id": "queue-request-1",
                        "status": "waiting",
                        "request": {
                            "task": "walk-flat",
                            "label": "Reference walk",
                            "num_envs": 64,
                            "iterations": 12,
                            "checkpoint": "/private/model.pt",
                        },
                        "recipe": {"secret": "omit"},
                        "recipe_sha256": "b" * 64,
                        "progress": None,
                    }
                ],
            },
            "jobs": [
                {
                    "id": "c" * 16,
                    "op": "train",
                    "status": "running",
                    "created": 123,
                    "message": "Training",
                    "request": {"task": "walk-flat", "num_envs": 64, "iterations": 12, "checkpoint": "/private/model.pt"},
                    "progress": {"done": 3, "total": 12, "percent": 25},
                    "latest_metric": {"iteration": 3, "reward": 4.2, "secret": "omit"},
                    "logs": ["private log"],
                }
            ],
        },
        "http://127.0.0.1:8092/api/studio": {
            "recipe": {"baseline": "official_0151"},
            "tasks": {"tasks": [{"id": "walk-flat", "name": "平地行走", "enabled": True, "role": "walk"}]},
        },
        "http://127.0.0.1:8092/api/remote/state": {"target": "local", "status": "disconnected"},
    }


def test_endpoint_must_be_a_loopback_origin(tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        KissqyTrainingService("http://training.example:8092", tmp_path / "db.sqlite")
    with pytest.raises(ValueError, match="origin"):
        KissqyTrainingService("http://127.0.0.1:8092/private", tmp_path / "db.sqlite")


def test_snapshot_projects_useful_training_state_without_secrets_or_paths(tmp_path):
    calls = []
    service = fixture_service(tmp_path, base_payloads(), calls)

    value = service.snapshot("project-1")

    assert value["connected"] is True
    assert value["service_version"] == "Studio R1.5.17"
    assert value["queue"]["entries"][0]["request"]["task"] == "walk-flat"
    assert value["jobs"][0]["progress"]["percent"] == 25
    assert value["tasks"] == [{"id": "walk-flat", "name": "平地行走", "enabled": True, "role": "walk"}]
    serialized = json.dumps(value)
    assert "server-only-token" not in serialized
    assert "/private/" not in serialized
    assert "private log" not in serialized


def test_queue_add_is_idempotent_and_uses_server_side_token(tmp_path):
    calls = []
    payloads = base_payloads()
    payloads[("POST", "http://127.0.0.1:8092/api/queue/add")] = {"entry_id": "d" * 16}
    service = fixture_service(tmp_path, payloads, calls)
    request = {
        "task": "walk-flat",
        "label": "Small validation run",
        "num_envs": 64,
        "iterations": 12,
        "training_firmware_p": 3,
        "training_action_scale": 0.9,
        "action_filter": {"enabled": True, "head_alpha": 0.5, "legs_alpha": 0.7},
        "request_id": "queue-request-1",
    }

    first = service.add_to_queue("project-1", request)
    second = service.add_to_queue("project-1", request)

    posts = [call for call in calls if call.method == "POST"]
    assert first["entry_id"] == second["entry_id"] == "d" * 16
    assert len(posts) == 1
    assert posts[0].get_header("X-training-token") == "server-only-token"
    assert posts[0].get_header("Origin") == "http://127.0.0.1:8092"
    body = json.loads(posts[0].data)
    assert body["client_id"] == "queue-request-1"
    assert "execution_profile" not in body


def test_queue_add_requires_an_enabled_reference_task(tmp_path):
    calls = []
    payloads = base_payloads()
    service = fixture_service(tmp_path, payloads, calls)
    request = {
        "task": "unknown",
        "num_envs": 64,
        "iterations": 12,
        "training_firmware_p": 3,
        "training_action_scale": 0.9,
        "action_filter": {"enabled": True, "head_alpha": 0.5, "legs_alpha": 0.7},
        "request_id": "queue-request-2",
    }

    with pytest.raises(ValueError, match="启用"):
        service.add_to_queue("project-1", request)

    assert not [call for call in calls if call.method == "POST"]


def test_uncertain_queue_timeout_is_not_retried(tmp_path):
    calls = []
    payloads = base_payloads()
    payloads[("POST", "http://127.0.0.1:8092/api/queue/add")] = URLError("timed out")
    service = fixture_service(tmp_path, payloads, calls)
    request = {
        "task": "walk-flat",
        "num_envs": 64,
        "iterations": 12,
        "training_firmware_p": 3,
        "training_action_scale": 0.9,
        "action_filter": {"enabled": True, "head_alpha": 0.5, "legs_alpha": 0.7},
        "request_id": "queue-request-3",
    }

    with pytest.raises(RuntimeError, match="未确认"):
        service.add_to_queue("project-1", request)
    with pytest.raises(RuntimeError, match="未确认"):
        service.add_to_queue("project-1", request)

    assert len([call for call in calls if call.method == "POST"]) == 1


def test_snapshot_reconciles_a_timed_out_add_by_client_id(tmp_path):
    calls = []
    payloads = base_payloads()
    payloads[("POST", "http://127.0.0.1:8092/api/queue/add")] = URLError("timed out")
    payloads["http://127.0.0.1:8092/api/state"]["training_queue"]["entries"] = [{
        "id": "e" * 16,
        "client_id": "queue-request-4",
        "status": "waiting",
        "request": {"task": "walk-flat", "label": "Recoverable add", "num_envs": 64, "iterations": 12},
        "recipe_sha256": "f" * 64,
    }]
    service = fixture_service(tmp_path, payloads, calls)
    request = {
        "task": "walk-flat", "num_envs":64, "iterations":12,
        "training_firmware_p":3, "training_action_scale":0.9,
        "action_filter":{"enabled":True,"head_alpha":0.5,"legs_alpha":0.7},
        "request_id":"queue-request-4",
    }

    with pytest.raises(RuntimeError, match="未确认"):
        service.add_to_queue("project-1", request)
    reconciled = service.add_to_queue("project-1", request)
    current = service.snapshot("project-1")

    assert reconciled == {"entry_id":"e" * 16,"duplicate":True,"reconciled":True}
    assert current["queue"]["entries"][0]["linked_to_project"] is True
    assert len([call for call in calls if call.method == "POST"]) == 1


def test_start_cannot_run_unlinked_queue_items_from_another_project(tmp_path):
    calls = []
    payloads = base_payloads()
    service = fixture_service(tmp_path, payloads, calls)

    with pytest.raises(ValueError, match="未关联到当前项目"):
        service.control_queue("start", project_id="project-1")

    assert not [call for call in calls if call.method == "POST"]


def test_start_is_allowed_for_a_queue_linked_only_to_this_project(tmp_path):
    calls = []
    payloads = base_payloads()
    payloads["http://127.0.0.1:8092/api/state"]["training_queue"]["entries"] = [{
        "id":"a" * 16,
        "client_id":"queue-request-1",
        "status":"waiting",
        "request":{"task":"walk-flat","label":"Project run","num_envs":64,"iterations":12},
        "recipe_sha256":"b" * 64,
    }]
    payloads[("POST", "http://127.0.0.1:8092/api/queue/control")] = {"okay":True}
    service = fixture_service(tmp_path, payloads, calls)
    with service._connect() as conn:
        conn.execute(
            "INSERT INTO kissqy_queue_requests(project_id,request_id,state,entry_id,payload,created_at) VALUES(?,?,?,?,?,?)",
            ("project-1","queue-request-1","queued","a" * 16,json.dumps({"task":"walk-flat","label":"Project run"}),"2026-10-08T00:00:00+00:00"),
        )

    assert service.control_queue("start", project_id="project-1")["okay"] is True
    posts = [call for call in calls if call.method == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0].data) == {"action":"start"}


def test_queue_control_is_allowlisted_and_requires_a_supported_action(tmp_path):
    calls = []
    payloads = base_payloads()
    payloads[("POST", "http://127.0.0.1:8092/api/queue/control")] = {"okay": True}
    service = fixture_service(tmp_path, payloads, calls)

    assert service.control_queue("stop")["okay"] is True
    with pytest.raises(ValueError, match="不支持"):
        service.control_queue("setup")

    posts = [call for call in calls if call.method == "POST"]
    assert len(posts) == 1
    assert json.loads(posts[0].data) == {"action": "stop"}


def test_studio_route_requires_project_and_second_confirmation(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import microduck_studio.app as app_module
    from microduck_studio.core import StudioStore

    store = StudioStore(tmp_path / "route.db")
    project_id = store.create_project("fixture", tmp_path)["id"]

    class Connector:
        calls = []

        def control_queue(self, action, entry_id, selected_project):
            self.calls.append((action, entry_id, selected_project))
            return {"okay": True}

    connector = Connector()
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "kissqy_training", connector)
    client = TestClient(app_module.app)

    missing = client.post("/api/projects/missing/kissqy/queue/control", json={"action":"start","confirm":True})
    unconfirmed = client.post(f"/api/projects/{project_id}/kissqy/queue/control", json={"action":"start"})
    accepted = client.post(f"/api/projects/{project_id}/kissqy/queue/control", json={"action":"start","confirm":True})

    assert missing.status_code == 404
    assert unconfirmed.status_code == 409
    assert accepted.status_code == 200
    assert connector.calls == [("start", None, project_id)]
