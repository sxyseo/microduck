"""The servo guide stays a read-only reference and degrades honestly when absent.

microduck-servo-guide is served same-origin under /servo-guide when its prebuilt site
is found, and /api/servo-guide re-exports its ID reference. A missing site disables the
feature without touching anything else; an untrustworthy manifest (duplicate, unnamed or
out-of-range IDs) must fail loudly instead of being served as labelling guidance.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from microduck_studio import servo_guide


def build_site(root: Path, servos: list[dict], instances_extra: list[dict] | None = None) -> Path:
    site = root / "site"
    (site / "model").mkdir(parents=True)
    (site / "index.html").write_text("<!doctype html><title>guide</title>", encoding="utf-8")
    manifest = {
        "source": "test-source",
        "assembly": "00-test.SLDASM",
        "assembly_sha256": "abc",
        "units": "mm",
        "axes": {"forward": "+X", "left": "+Y", "up": "+Z"},
        "issues": [],
        "notes": ["test note"],
        "instances": servos + (instances_extra or []),
        "meshes": [],
    }
    (site / "model" / "model.json").write_text(json.dumps(manifest), encoding="utf-8")
    return site


def servo(servo_id: int, label: str = "测试关节", group: str = "right") -> dict:
    return {
        "servo": True,
        "id": servo_id,
        "label": label,
        "joint": f"joint_{servo_id}",
        "description": "测试位置描述",
        "group": group,
        "chain": ["装配体", "01_组件-FT"],
    }


@pytest.fixture
def fake_site(tmp_path, monkeypatch) -> Path:
    site = build_site(tmp_path, [servo(20, group="left"), servo(10)], [{"servo": False, "name": "外壳"}])
    monkeypatch.setattr(servo_guide, "site_candidates", lambda: [site])
    return site


def test_locate_site_accepts_candidate_with_index_and_manifest(tmp_path, monkeypatch):
    site = build_site(tmp_path, [servo(10)])
    monkeypatch.setattr(servo_guide, "site_candidates", lambda: [tmp_path / "missing", site])
    assert servo_guide.locate_site() == site


def test_locate_site_returns_none_without_candidates(monkeypatch):
    monkeypatch.setattr(servo_guide, "site_candidates", lambda: [])
    assert servo_guide.locate_site() is None
    value = servo_guide.payload(None)
    assert value["available"] is False
    assert value["mount"] is None
    assert value["searched"] == []
    assert "不可用" in value["note"]


def test_payload_sorts_servos_and_keeps_metadata(fake_site):
    value = servo_guide.payload(fake_site)
    assert value["available"] is True
    assert value["mount"] == "/servo-guide"
    reference = value["reference"]
    assert [s["id"] for s in reference["servos"]] == [10, 20]
    assert reference["servo_count"] == 2
    assert reference["part_instances"] == 3
    assert reference["servos"][0]["assembly"] == "01_组件-FT"
    assert reference["source"] == "test-source"
    assert reference["assembly_sha256"] == "abc"


def test_reference_rejects_duplicate_ids(tmp_path):
    site = build_site(tmp_path, [servo(10), servo(10)])
    with pytest.raises(ValueError, match="重复"):
        servo_guide.servo_reference(site)


def test_reference_rejects_out_of_range_id(tmp_path):
    site = build_site(tmp_path, [servo(300)])
    with pytest.raises(ValueError, match="1–253"):
        servo_guide.servo_reference(site)


def test_reference_rejects_unnamed_servo(tmp_path):
    broken = servo(10)
    broken["label"] = " "
    site = build_site(tmp_path, [broken])
    with pytest.raises(ValueError, match="label"):
        servo_guide.servo_reference(site)


def test_reference_rejects_unknown_group(tmp_path):
    site = build_site(tmp_path, [servo(10, group="middle")])
    with pytest.raises(ValueError, match="分组"):
        servo_guide.servo_reference(site)


def test_reference_rejects_unreadable_manifest(tmp_path):
    site = tmp_path / "site"
    (site / "model").mkdir(parents=True)
    (site / "index.html").write_text("x", encoding="utf-8")
    (site / "model" / "model.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="model.json"):
        servo_guide.servo_reference(site)


def test_payload_reports_reference_error_without_raising(tmp_path):
    site = build_site(tmp_path, [servo(10)])
    (site / "model" / "model.json").write_text("{broken", encoding="utf-8")
    value = servo_guide.payload(site)
    assert value["available"] is True
    assert "reference" not in value
    assert "model.json" in value["reference_error"]


def test_mount_serves_static_site(fake_site):
    app = FastAPI()
    app.mount("/servo-guide", StaticFiles(directory=fake_site, html=True), name="servo-guide")
    client = TestClient(app)
    assert client.get("/servo-guide/").status_code == 200
    assert client.get("/servo-guide/model/model.json").status_code == 200


def test_default_app_when_site_present():
    from microduck_studio.app import SERVO_GUIDE_SITE, app as default_app

    if SERVO_GUIDE_SITE is None:
        pytest.skip("microduck-servo-guide site 未安装")
    client = TestClient(default_app)
    data = client.get("/api/servo-guide").json()
    assert data["available"] is True
    reference = data["reference"]
    ids = [s["id"] for s in reference["servos"]]
    assert ids == [10, 11, 12, 13, 14, 20, 21, 22, 23, 24, 30, 31, 32, 33, 34]
    assert reference["servo_count"] == 15
    assert client.get("/servo-guide/").status_code == 200
    assert client.get("/servo-guide/assembly.html").status_code == 200


def test_default_app_without_site_still_answers(monkeypatch):
    import microduck_studio.app as app_module

    monkeypatch.setattr(app_module, "SERVO_GUIDE_SITE", None)
    client = TestClient(app_module.app)
    data = client.get("/api/servo-guide").json()
    assert data["available"] is False
    assert data["mount"] is None
