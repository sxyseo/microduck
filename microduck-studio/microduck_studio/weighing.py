"""Regional mass records against the official MJCF template, plus the servo ID map.

The official MJCF (robot_walk.xml) body inertial masses are the reference breakdown of
the robot: one weighing region per body. Studio parses that file read-only, stores the
operator's per-region measurements with scale/operator provenance, and can generate a
mass-corrected copy of the MJCF — the official file itself is never modified. The ID map
records which bus ID was written into which physical joint; it is operator-declared
evidence that bus probing verifies later, never a read from the bus.
"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

WEIGHING_RULE_VERSION = "weighing-v1"
WEIGHING_SCHEMA_VERSION = 1
ID_MAP_SCHEMA_VERSION = 1
WEIGHING_METHODS = {"scale", "derived", "mirror"}
MAX_MEASURED_G = 20_000.0
# Whole-robot deviation above this share of the official total is flagged for manual
# review; the flag is informational and the operator decides what to investigate.
TOTAL_DEVIATION_WARNING_PCT = 10.0
SCAN_DIR_LIMIT = 8
SCAN_RESULT_LIMIT = 10
SCAN_SKIP_DIRS = {".git", "node_modules", "target", ".venv", "dist", "__pycache__", ".zcode"}

# The joint names of the documented hl2915 backend convention (主仓手册 §5.4), offered as
# placeholders only: the record stores whatever mapping the operator actually wrote.
HL2915_ID_CONVENTION = {
    1: "left_hip_yaw", 2: "left_hip_roll", 3: "left_hip_pitch", 4: "left_knee",
    5: "left_ankle", 6: "neck_pitch", 7: "head_pitch", 8: "head_yaw", 9: "head_roll",
    10: "mouth", 11: "right_hip_yaw", 12: "right_hip_roll", 13: "right_hip_pitch",
    14: "right_knee", 15: "right_ankle",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_mjcf_masses(path: Path) -> dict:
    """Extract one weighing region per body with an explicit inertial mass (g)."""
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"MJCF 无法解析：{exc}") from exc
    bodies: list[dict] = []
    for element in tree.iter("body"):
        name = element.get("name")
        inertial = element.find("inertial")
        if not name or inertial is None or not inertial.get("mass"):
            continue
        try:
            mass_g = float(inertial.get("mass")) * 1000.0
        except ValueError as exc:
            raise ValueError(f"body {name} 的 inertial mass 不是数字") from exc
        if not math.isfinite(mass_g) or mass_g <= 0:
            raise ValueError(f"body {name} 的 inertial mass 不可信：{mass_g}")
        bodies.append({
            "body": name,
            "official_mass_g": round(mass_g, 2),
            "inertia_kind": "diaginertia" if inertial.get("diaginertia") else ("fullinertia" if inertial.get("fullinertia") else None),
        })
    if not bodies:
        raise ValueError("MJCF 中没有带显式 inertial mass 的 body")
    return {
        "bodies": bodies,
        "body_count": len(bodies),
        "official_total_g": round(sum(b["official_mass_g"] for b in bodies), 2),
        "path": str(path),
        "sha256": _sha256(path),
    }


def find_templates(project_root: Path, filename: str = "robot_walk.xml") -> list[dict]:
    """Bounded read-only scan for candidate MJCF templates under the project root.

    Priority: the MJLab training package (the model the corrected masses feed back into),
    then other `upstream/` sources, then working copies. Ordering stays deterministic
    within each tier.
    """
    root = Path(project_root).resolve()
    found: list[dict] = []
    if not root.is_dir():
        return found
    for path in root.rglob(filename):
        if not path.is_file():
            continue
        if SCAN_SKIP_DIRS & set(path.relative_to(root).parts):
            continue
        try:
            parsed = parse_mjcf_masses(path)
        except ValueError:
            continue
        relative = str(path.relative_to(root))
        found.append({
            "path": relative,
            "sha256": parsed["sha256"],
            "body_count": parsed["body_count"],
            "official_total_g": parsed["official_total_g"],
            "upstream": "upstream" in Path(relative).parts,
            "mjlab": "mjlab" in relative.lower(),
        })
        if len(found) >= SCAN_RESULT_LIMIT:
            break
    found.sort(key=lambda item: (not item["upstream"], not item["mjlab"], len(item["path"])))
    return found


def load_template(project_root: Path, relative_path: str | None) -> dict:
    root = Path(project_root).resolve()
    if relative_path is None:
        candidates = find_templates(root)
        if not candidates:
            raise ValueError("项目根目录下没有找到 robot_walk.xml 模板；可先用模板搜索确认路径")
        chosen = root / candidates[0]["path"]
    else:
        chosen = (root / relative_path).resolve()
        if not chosen.is_relative_to(root):
            raise ValueError("模板路径必须在项目根目录内")
    parsed = parse_mjcf_masses(chosen)
    parsed["relative_path"] = str(chosen.relative_to(root))
    return parsed


def _finite_number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def validate_weighing(data: dict, project_root: Path) -> dict:
    """Normalize a weighing submission; missing regions stay missing, never zero-filled."""
    if not isinstance(data, dict):
        raise ValueError("称重数据必须为对象")
    template = load_template(project_root, data.get("template_path"))
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries 必须为非空数组")
    template_bodies = {body["body"]: body for body in template["bodies"]}
    normalized: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("entries 项必须为对象")
        body = entry.get("body")
        if body not in template_bodies:
            raise ValueError(f"未知称重区域：{body!r}")
        if body in normalized:
            raise ValueError(f"称重区域重复：{body}")
        measured = entry.get("measured_g")
        if not _finite_number(measured) or not 0 < measured <= MAX_MEASURED_G:
            raise ValueError(f"区域 {body} 的实测质量必须为 0–{MAX_MEASURED_G:.0f} g 的有限数")
        method = entry.get("method")
        if method not in WEIGHING_METHODS:
            raise ValueError(f"区域 {body} 的称量方式必须是 {'/'.join(sorted(WEIGHING_METHODS))}")
        note = entry.get("note")
        normalized[body] = {
            "body": body,
            "measured_g": round(float(measured), 3),
            "method": method,
            "official_mass_g": template_bodies[body]["official_mass_g"],
            "delta_g": round(float(measured) - template_bodies[body]["official_mass_g"], 3),
            **({"note": note} if isinstance(note, str) and note.strip() else {}),
        }
    scale = data.get("scale") or {}
    if not isinstance(scale, dict):
        raise ValueError("scale 必须为对象")
    scale_model = scale.get("model")
    if scale_model is not None and (not isinstance(scale_model, str) or not scale_model.strip()):
        raise ValueError("秤型号应为非空字符串")
    operator = data.get("operator")
    if operator is not None and (not isinstance(operator, str) or not operator.strip()):
        raise ValueError("操作者应为非空字符串")

    missing = [body["body"] for body in template["bodies"] if body["body"] not in normalized]
    measured_list = list(normalized.values())
    measured_total = round(sum(entry["measured_g"] for entry in measured_list), 2)
    official_total = template["official_total_g"]
    result = {
        "rule_version": WEIGHING_RULE_VERSION,
        "template": {
            "path": template["relative_path"],
            "sha256": template["sha256"],
            "official_total_g": official_total,
        },
        "entries": sorted(measured_list, key=lambda item: item["body"]),
        "measured_total_g": measured_total,
        "official_total_g": official_total,
        "delta_g": round(measured_total - official_total, 2),
        "delta_pct": round((measured_total - official_total) / official_total * 100, 2),
        **({"scale": {"model": scale_model.strip(),
                      **({"precision_g": scale["precision_g"]} if _finite_number(scale.get("precision_g")) and scale["precision_g"] > 0 else {})}}
           if scale_model else {}),
        **({"operator": operator.strip()} if operator else {}),
        **({"note": data["note"]} if isinstance(data.get("note"), str) and data["note"].strip() else {}),
    }
    if missing:
        result["status"] = "insufficient_evidence"
        result["missing_regions"] = missing
        result["warnings"] = [f"缺少 {len(missing)} 个区域的实测值；总数只包含已称区域，不能与官方整机质量直接对账。"]
    else:
        result["status"] = "complete"
        result["warnings"] = (
            [f"实测总质量与官方模板偏差 {result['delta_pct']:.1f}%，超过 {TOTAL_DEVIATION_WARNING_PCT:.0f}% 提示线；请核对漏装、多装或模板版本。"]
            if abs(result["delta_pct"]) > TOTAL_DEVIATION_WARNING_PCT else []
        )
    return result


def validate_servo_id_map(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("ID 映射必须为对象")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("entries 必须为非空数组")
    normalized: list[dict] = []
    seen: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("entries 项必须为对象")
        servo_id = entry.get("servo_id")
        if not isinstance(servo_id, int) or isinstance(servo_id, bool) or not 1 <= servo_id <= 253:
            raise ValueError(f"舵机 ID 超出 1–253 或类型不可信：{servo_id!r}")
        if servo_id in seen:
            raise ValueError(f"舵机 ID 重复：{servo_id}")
        seen.add(servo_id)
        joint = entry.get("joint")
        if not isinstance(joint, str) or not joint.strip() or len(joint.strip()) > 80:
            raise ValueError(f"舵机 {servo_id} 的关节名为 1–80 字的非空字符串")
        normalized.append({"servo_id": servo_id, "joint": joint.strip()})
    operator = data.get("operator")
    if operator is not None and (not isinstance(operator, str) or not operator.strip()):
        raise ValueError("操作者应为非空字符串")
    note = data.get("note")
    matches = sorted(normalized, key=lambda item: item["servo_id"])
    expected = {servo_id: joint for servo_id, joint in HL2915_ID_CONVENTION.items()}
    actual = {item["servo_id"]: item["joint"] for item in matches}
    return {
        "entries": matches,
        "matches_default_convention": actual == expected,
        **({"operator": operator.strip()} if operator else {}),
        **({"note": note} if isinstance(note, str) and note.strip() else {}),
    }


def build_mass_corrected_mjcf(template_path: Path, entries: list[dict], header_lines: list[str]) -> str:
    """Return a copy of the MJCF with measured masses and proportionally scaled inertia."""
    try:
        tree = ET.parse(template_path)
    except (OSError, ET.ParseError) as exc:
        raise ValueError(f"官方模板无法解析：{exc}") from exc
    measured = {entry["body"]: entry["measured_g"] for entry in entries}
    replaced = 0
    for element in tree.iter("body"):
        name = element.get("name")
        inertial = element.find("inertial")
        if not name or inertial is None or not inertial.get("mass") or name not in measured:
            continue
        old_mass = float(inertial.get("mass"))
        new_mass = measured[name] / 1000.0
        inertial.set("mass", f"{new_mass:.6f}")
        ratio = new_mass / old_mass
        for attr in ("diaginertia", "fullinertia"):
            raw = inertial.get(attr)
            if not raw:
                continue
            values = raw.split()
            scaled = " ".join(f"{float(value) * ratio:.8g}" for value in values)
            inertial.set(attr, scaled)
        replaced += 1
    if replaced != len(measured):
        raise ValueError("部分称重区域在模板中找不到对应的显式 inertial mass，未生成副本")
    ET.indent(tree, space="  ")
    body = ET.tostring(tree.getroot(), encoding="unicode")
    comment = "\n".join(f"<!-- {line} -->" for line in header_lines)
    return f"{comment}\n{body}\n"


class WeighingStore:
    """Append-only weighing and ID-map records; project metadata comes from the shared DB."""

    def __init__(self, db_path, studio_store=None):
        self.db_path = db_path
        self.studio_store = studio_store
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS weighings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS servo_id_maps (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _project_root(self, conn, project_id) -> Path:
        row = conn.execute("SELECT root FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise KeyError(project_id)
        return Path(row["root"]).resolve()

    def save_weighing(self, project_id: str, data: dict) -> dict:
        with self.connect() as conn:
            root = self._project_root(conn, project_id)
        normalized = validate_weighing(data, root)
        record = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "status": normalized["status"],
            "data": normalized,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": WEIGHING_SCHEMA_VERSION,
        }
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO weighings VALUES (?, ?, ?, ?, ?)",
                (record["id"], project_id, record["status"], json.dumps(normalized, ensure_ascii=False, allow_nan=False), record["created_at"]),
            )
        return record

    def list_weighings(self, project_id: str) -> list[dict]:
        with self.connect() as conn:
            self._project_root(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM weighings WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [
            {**dict(row), "data": json.loads(row["data"]), "schema_version": WEIGHING_SCHEMA_VERSION}
            for row in rows
        ]

    def _load_weighing(self, conn, project_id: str, weighing_id: str) -> dict:
        row = conn.execute(
            "SELECT * FROM weighings WHERE id = ? AND project_id = ?", (weighing_id, project_id)
        ).fetchone()
        if not row:
            raise KeyError(weighing_id)
        return json.loads(row["data"])

    def build_model_copy(self, project_id: str, weighing_id: str, output_path: str, confirm: bool) -> dict:
        with self.connect() as conn:
            root = self._project_root(conn, project_id)
            weighing = self._load_weighing(conn, project_id, weighing_id)
        if weighing.get("status") != "complete":
            raise ValueError("只有所有区域都已实测的称重记录才能生成模型副本；缺失区域会静默混入官方质量")
        if not confirm:
            raise PermissionError("生成模型副本需要显式 confirm")
        target = (root / output_path).resolve()
        if not target.is_relative_to(root):
            raise ValueError("输出路径必须在项目根目录内")
        if target.suffix.lower() != ".xml":
            raise ValueError("输出文件必须是 .xml")
        if target.exists():
            raise PermissionError(f"输出文件已存在，不覆盖：{target}")
        template_relative = weighing["template"]["path"]
        template_path = (root / template_relative).resolve()
        if not template_path.is_file():
            raise ValueError("官方模板文件已不存在，无法生成副本")
        template = parse_mjcf_masses(template_path)
        if template["sha256"] != weighing["template"]["sha256"]:
            raise ValueError("官方模板文件已变化（SHA-256 不一致），请先重新保存称重记录")
        content = build_mass_corrected_mjcf(
            template_path,
            weighing["entries"],
            [
                "Mass-corrected copy generated by microduck-studio; official template left untouched.",
                f"weighing record: {weighing_id}",
                f"template: {template_relative} sha256:{template['sha256']}",
                "inertia scaled proportionally to mass per body; verify in simulation before deployment.",
            ],
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        result = {
            "output_path": str(target),
            "weighing_id": weighing_id,
            "template": {"path": template_relative, "sha256": template["sha256"]},
            "replaced_bodies": len(weighing["entries"]),
            "measured_total_g": weighing["measured_total_g"],
            "sha256": _sha256(target),
            "note": "副本中的质量来自称重记录，惯量按质量比例缩放；官方模板未修改。",
        }
        if self.studio_store is not None:
            result["artifact"] = self.studio_store.register_artifact(
                project_id, target, "model_mass_copy",
                metadata={"weighing_id": weighing_id, "template_sha256": template["sha256"]},
            )
        return result

    def save_id_map(self, project_id: str, data: dict) -> dict:
        with self.connect() as conn:
            self._project_root(conn, project_id)
        normalized = validate_servo_id_map(data)
        record = {
            "id": uuid.uuid4().hex,
            "project_id": project_id,
            "data": normalized,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": ID_MAP_SCHEMA_VERSION,
        }
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO servo_id_maps VALUES (?, ?, ?, ?)",
                (record["id"], project_id, json.dumps(normalized, ensure_ascii=False, allow_nan=False), record["created_at"]),
            )
        return record

    def list_id_maps(self, project_id: str) -> list[dict]:
        with self.connect() as conn:
            self._project_root(conn, project_id)
            rows = conn.execute(
                "SELECT * FROM servo_id_maps WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
            ).fetchall()
        return [
            {**dict(row), "data": json.loads(row["data"]), "schema_version": ID_MAP_SCHEMA_VERSION}
            for row in rows
        ]
