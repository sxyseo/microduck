"""Project-scoped appearance records. These records never establish hardware readiness."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parents[1] / "microduck-color-studio/public/models/parts.json"
MATERIALS = {"pla", "matte-pla", "petg", "tpu"}


def model_manifest():
    return json.loads(MODEL_PATH.read_text())


def model_reference():
    model = model_manifest()
    return {"model_id": model["modelId"], "manifest_sha256": hashlib.sha256(MODEL_PATH.read_bytes()).hexdigest(),
            "source": model.get("source"), "upstream_revision": model.get("upstreamRevision"),
            "scope": "reference_geometry_only"}


def validate_binding(data):
    """An optional assembly link identifies reference geometry, not fitted hardware."""
    binding = data.get("model_binding")
    rows = data.get("checks", [])
    if binding is None:
        if any("part_ids" in row for row in rows):
            raise ValueError("关联零件需要 model_binding 模型来源")
        return None
    reference = model_reference()
    if not isinstance(binding, dict) or any(binding.get(k) != reference[k] for k in ("model_id", "manifest_sha256")):
        raise ValueError("装配模型版本不匹配，请重新选择参考模型")
    ids = {p["id"] for p in model_manifest()["parts"]}
    for row in rows:
        selected = row.get("part_ids", [])
        if not isinstance(selected, list) or any(not isinstance(x, str) or x not in ids for x in selected) or len(set(selected)) != len(selected):
            raise ValueError("装配记录包含未知或重复的模型零件")
    return reference


def _number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def _enum(value, choices):
    return isinstance(value, str) and value in choices


def _color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("颜色必须为六位十六进制色值")
    return value.upper()


def validate_visual(data):
    if not isinstance(data, dict):
        raise ValueError("外观配置必须为对象")
    model = model_manifest()
    palette, inventory = data.get("palette"), data.get("inventory")
    if not isinstance(palette, dict) or type(palette.get("schemaVersion")) is not int or palette.get("schemaVersion") != 1 or palette.get("modelId") != model["modelId"]:
        raise ValueError("配色格式或模型不匹配")
    name = palette.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValueError("方案名称应为 1–120 字")
    parts = palette.get("parts")
    if not isinstance(parts, dict) or set(parts) != {p["id"] for p in model["parts"]}:
        raise ValueError("配色必须包含当前模型的全部零件，不能包含未知零件")
    normalized_parts = {}
    for part in model["parts"]:
        finish = parts[part["id"]]
        if not isinstance(finish, dict) or not _enum(finish.get("material"), MATERIALS):
            raise ValueError("零件材质不可用")
        normalized = {"color": _color(finish.get("color")), "material": finish["material"]}
        if "coating" in finish:
            coating = finish["coating"]
            if not part.get("paintable") or not isinstance(coating, dict) or coating.get("kind") != "acrylic":
                raise ValueError("此零件不支持该涂层")
            normalized["coating"] = {"kind": "acrylic", "color": _color(coating.get("color"))}
        normalized_parts[part["id"]] = normalized
    lighting = palette.get("lighting")
    if not isinstance(lighting, dict) or not _enum(lighting.get("preset"), {"studio", "daylight", "warm"}) or not _number(lighting.get("intensity"), .3, 1.8) or not _number(lighting.get("azimuth"), -180, 180):
        raise ValueError("灯光参数不可用")
    surface = palette.get("surface")
    if not isinstance(surface, dict) or type(surface.get("layers")) is not bool:
        raise ValueError("打印层纹参数必须为布尔值")
    if not isinstance(inventory, dict) or type(inventory.get("schemaVersion")) is not int or inventory.get("schemaVersion") != 1 or not isinstance(inventory.get("items"), list) or len(inventory["items"]) > 200:
        raise ValueError("耗材库存格式不可用，最多 200 项")
    items, ids = [], set()
    for item in inventory["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item["id"]) or item["id"] in ids:
            raise ValueError("耗材编号不可用或重复")
        if not isinstance(item.get("name"), str) or not item["name"].strip() or len(item["name"].strip()) > 80 or not _enum(item.get("material"), MATERIALS):
            raise ValueError("耗材名称或材质不可用")
        ids.add(item["id"])
        items.append({"id": item["id"], "name": item["name"].strip(), "material": item["material"], "color": _color(item.get("color"))})
    return {"palette": {"schemaVersion": 1, "modelId": model["modelId"], "name": name,
                        "parts": normalized_parts, "lighting": {k: lighting[k] for k in ("preset", "intensity", "azimuth")},
                        "surface": {"layers": surface["layers"]}}, "inventory": {"schemaVersion": 1, "items": items}, "model_ref": model_reference()}


class RevisionConflict(ValueError):
    pass


class VisualStore:
    def __init__(self, db_path):
        self.db_path = db_path
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS visual_configs (project_id TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(project_id, revision))")

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _project(self, conn, project_id):
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise KeyError(project_id)

    def list(self, project_id):
        with self.connect() as conn:
            self._project(conn, project_id)
            rows = conn.execute("SELECT * FROM visual_configs WHERE project_id = ? ORDER BY revision DESC", (project_id,)).fetchall()
        return [{**dict(row), "data": json.loads(row["data"])} for row in rows]

    def save(self, project_id, data, expected_revision):
        normalized = validate_visual(data)
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._project(conn, project_id)
            latest = conn.execute("SELECT COALESCE(MAX(revision), 0) FROM visual_configs WHERE project_id = ?", (project_id,)).fetchone()[0]
            if type(expected_revision) is not int or latest != expected_revision:
                raise RevisionConflict("当前项目已有更新的配色版本，请重新载入后保存")
            record = {"project_id": project_id, "revision": latest + 1, "created_at": datetime.now(timezone.utc).isoformat(), "data": normalized}
            conn.execute("INSERT INTO visual_configs VALUES (?, ?, ?, ?)", (project_id, record["revision"], record["created_at"], json.dumps(normalized, ensure_ascii=False, allow_nan=False)))
        return copy.deepcopy(record)
