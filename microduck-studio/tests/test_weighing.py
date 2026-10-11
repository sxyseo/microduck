"""Weighing records bind to a read-only official MJCF; the ID map is declared, not read.

The official template provides one weighing region per body with an explicit inertial
mass. Records that miss regions stay insufficient_evidence (never zero-filled), the
mass-corrected copy is written only under explicit confirm and never overwrites the
official file or an existing target, and the ID map validates IDs/joints without
claiming they were read from a bus.
"""
from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from microduck_studio.core import StudioStore
from microduck_studio.weighing import (
    HL2915_ID_CONVENTION,
    WeighingStore,
    find_templates,
    parse_mjcf_masses,
)

MJCF = """<mujoco model="test">
  <worldbody>
    <body name="trunk_base" pos="0 0 0.1">
      <inertial pos="0 0 0" mass="0.1992" diaginertia="1e-4 2e-4 3e-4"/>
      <body name="upper_leg_left">
        <inertial pos="0 0 0" mass="0.0482" diaginertia="2e-5 2e-5 2e-5"/>
      </body>
    </body>
  </worldbody>
</mujoco>
"""


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "repo"
    upstream = root / "upstream" / "test" / "robot"
    upstream.mkdir(parents=True)
    (upstream / "robot_walk.xml").write_text(MJCF, encoding="utf-8")
    local = root / "kinematics"
    local.mkdir()
    (local / "robot_walk.xml").write_text(MJCF.replace("0.1992", "0.2500"), encoding="utf-8")
    db = tmp_path / "studio.db"
    store = StudioStore(db)
    project = store.create_project("test", str(root))
    weighing = WeighingStore(db, store)
    return weighing, store, project["id"], root, upstream / "robot_walk.xml"


def entries(**overrides) -> list[dict]:
    base = [
        {"body": "trunk_base", "measured_g": 210.0, "method": "scale"},
        {"body": "upper_leg_left", "measured_g": 50.0, "method": "mirror"},
    ]
    for key, value in overrides.items():
        for entry in base:
            if entry["body"] == key:
                entry.update(value)
    return base


def test_find_templates_prefers_upstream_and_parses(env):
    weighing, _, project_id, root, _ = env
    with weighing.connect() as conn:
        assert conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
    candidates = find_templates(root)
    assert candidates[0]["upstream"] is True
    assert candidates[0]["official_total_g"] == pytest.approx(247.4, abs=0.1)
    assert {c["path"] for c in candidates} >= {
        "upstream/test/robot/robot_walk.xml",
        "kinematics/robot_walk.xml",
    }


def test_parse_rejects_non_numeric_mass(tmp_path):
    bad = tmp_path / "robot_walk.xml"
    bad.write_text(MJCF.replace('mass="0.0482"', 'mass="heavy"'), encoding="utf-8")
    with pytest.raises(ValueError, match="不是数字"):
        parse_mjcf_masses(bad)


def test_weighing_complete_records_totals_and_deltas(env):
    weighing, _, project_id, _, _ = env
    record = weighing.save_weighing(project_id, {"entries": entries()})
    data = record["data"]
    assert record["status"] == "complete"
    assert data["measured_total_g"] == pytest.approx(260.0, abs=0.01)
    assert data["delta_g"] == pytest.approx(12.6, abs=0.05)
    assert data["delta_pct"] == pytest.approx(5.09, abs=0.05)
    assert data["warnings"] == []
    assert data["rule_version"] == "weighing-v1"


def test_partial_weighing_stays_insufficient(env):
    weighing, _, project_id, _, _ = env
    record = weighing.save_weighing(project_id, {"entries": entries()[:1]})
    assert record["status"] == "insufficient_evidence"
    assert record["data"]["missing_regions"] == ["upper_leg_left"]
    assert "不能与官方整机质量直接对账" in record["data"]["warnings"][0]


def test_weighing_rejects_bad_input(env):
    weighing, _, project_id, _, _ = env
    with pytest.raises(ValueError, match="未知称重区域"):
        weighing.save_weighing(project_id, {"entries": [{"body": "ghost", "measured_g": 1, "method": "scale"}]})
    with pytest.raises(ValueError, match="有限数"):
        weighing.save_weighing(project_id, {"entries": [{"body": "trunk_base", "measured_g": 0, "method": "scale"}]})
    with pytest.raises(ValueError, match="称量方式"):
        weighing.save_weighing(project_id, {"entries": [{"body": "trunk_base", "measured_g": 1, "method": "vibes"}]})
    with pytest.raises(ValueError, match="重复"):
        weighing.save_weighing(project_id, {"entries": entries() + entries()[:1]})
    with pytest.raises(KeyError):
        weighing.save_weighing("missing-project", {"entries": entries()})


def test_deviation_warning_above_threshold(env):
    weighing, _, project_id, _, _ = env
    record = weighing.save_weighing(
        project_id, {"entries": entries(trunk_base={"measured_g": 400.0})}
    )
    assert record["status"] == "complete"
    assert any("偏差" in warning for warning in record["data"]["warnings"])


def test_model_copy_requires_complete_and_confirm(env):
    weighing, _, project_id, _, _ = env
    partial = weighing.save_weighing(project_id, {"entries": entries()[:1]})
    with pytest.raises(ValueError, match="缺失区域"):
        weighing.build_model_copy(project_id, partial["id"], "out.xml", confirm=True)
    record = weighing.save_weighing(project_id, {"entries": entries()})
    with pytest.raises(PermissionError):
        weighing.build_model_copy(project_id, record["id"], "out.xml", confirm=False)


def test_model_copy_writes_scaled_masses_and_registers_artifact(env):
    weighing, store, project_id, root, template = env
    official_before = template.read_text(encoding="utf-8")
    record = weighing.save_weighing(project_id, {"entries": entries()})
    result = weighing.build_model_copy(project_id, record["id"], "artifacts/mjcf/robot_walk_hl1910.xml", confirm=True)
    output = Path(result["output_path"])
    assert output.is_relative_to(root) and output.is_file()
    tree = ET.parse(output)
    masses = {b.get("name"): float(b.find("inertial").get("mass")) for b in tree.iter("body")}
    assert masses["trunk_base"] == pytest.approx(0.21, abs=1e-6)
    assert masses["upper_leg_left"] == pytest.approx(0.05, abs=1e-6)
    ratio = 0.21 / 0.1992
    inertia = tree.iter("body").__next__().find("inertial").get("diaginertia").split()
    assert float(inertia[0]) == pytest.approx(1e-4 * ratio, rel=1e-4)
    assert template.read_text(encoding="utf-8") == official_before
    assert result["artifact"]["kind"] == "model_mass_copy"
    with pytest.raises(PermissionError):
        weighing.build_model_copy(project_id, record["id"], "artifacts/mjcf/robot_walk_hl1910.xml", confirm=True)


def test_model_copy_rejects_escape_and_template_change(env):
    weighing, _, project_id, _, template = env
    record = weighing.save_weighing(project_id, {"entries": entries()})
    with pytest.raises(ValueError, match="项目根目录"):
        weighing.build_model_copy(project_id, record["id"], "../escape.xml", confirm=True)
    template.write_text(MJCF.replace("0.1992", "0.3000"), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        weighing.build_model_copy(project_id, record["id"], "fresh.xml", confirm=True)


def test_id_map_validates_and_flags_convention(env):
    weighing, _, project_id, _, _ = env
    default = [{"servo_id": sid, "joint": joint} for sid, joint in sorted(HL2915_ID_CONVENTION.items())]
    record = weighing.save_id_map(project_id, {"entries": default})
    assert record["data"]["matches_default_convention"] is True
    swapped = [dict(entry) for entry in default]
    swapped[0]["joint"] = "right_ankle"
    other = weighing.save_id_map(project_id, {"entries": swapped, "operator": "abel"})
    assert other["data"]["matches_default_convention"] is False
    assert other["data"]["operator"] == "abel"
    with pytest.raises(ValueError, match="重复"):
        weighing.save_id_map(project_id, {"entries": [default[0], default[0]]})
    with pytest.raises(ValueError, match="1–253"):
        weighing.save_id_map(project_id, {"entries": [{"servo_id": 300, "joint": "x"}]})
    listed = weighing.list_id_maps(project_id)
    assert [item["id"] for item in listed] == [other["id"], record["id"]]


def test_weighing_and_id_map_never_mix_projects(env):
    weighing, store, project_id, root, _ = env
    other = store.create_project("other", str(root))["id"]
    weighing.save_weighing(project_id, {"entries": entries()})
    assert weighing.list_weighings(other) == []
    assert weighing.list_id_maps(other) == []
