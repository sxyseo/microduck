"""Read-only HD-1910 servo ID reference, integrated from the microduck-servo-guide site.

The guide is an independent static site (Three.js assembly viewer plus an ID table).
Studio serves it same-origin under /servo-guide and re-exports its structured ID
reference through /api/servo-guide. The labelled IDs are the project joint numbering by
position — not values read from CAD or from a real bus — and nothing here opens a serial
port or records evidence. Model assets are CC BY-NC-SA 4.0; attribution stays in the
served credits.html.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

GROUPS = {"left", "right", "head"}


def site_candidates() -> list[Path]:
    # Inside the studio directory first (the color-studio convention), then as a sibling
    # checkout in the same workspace.
    return [
        ROOT / "microduck-servo-guide" / "site",
        ROOT.parent / "microduck-servo-guide" / "site",
    ]


def locate_site() -> Path | None:
    for candidate in site_candidates():
        if (candidate / "index.html").is_file() and (candidate / "model" / "model.json").is_file():
            return candidate
    return None


def servo_reference(site: Path) -> dict:
    """Parse the guide's model manifest into a servo ID reference.

    Raises ValueError when the manifest is unreadable or the servo entries cannot be
    trusted: a reference table with duplicate, out-of-range or unnamed IDs must not be
    served as guidance for labelling hardware.
    """
    try:
        model = json.loads((site / "model" / "model.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"model.json 不可读或不是有效 JSON：{exc}") from exc
    instances = model.get("instances")
    if not isinstance(instances, list) or not instances:
        raise ValueError("model.json 缺少 instances 列表")
    servos: list[dict] = []
    seen: set[int] = set()
    for instance in instances:
        if not instance.get("servo"):
            continue
        servo_id = instance.get("id")
        if not isinstance(servo_id, int) or isinstance(servo_id, bool) or not 1 <= servo_id <= 253:
            raise ValueError(f"舵机 ID 超出 1–253 或类型不可信：{servo_id!r}")
        if servo_id in seen:
            raise ValueError(f"舵机 ID 重复：{servo_id}")
        seen.add(servo_id)
        for field in ("label", "joint", "description"):
            if not isinstance(instance.get(field), str) or not instance[field].strip():
                raise ValueError(f"舵机 {servo_id} 缺少可用的 {field}")
        if instance.get("group") not in GROUPS:
            raise ValueError(f"舵机 {servo_id} 的分组不可用：{instance.get('group')!r}")
        chain = instance.get("chain")
        servos.append(
            {
                "id": servo_id,
                "label": instance["label"],
                "joint": instance["joint"],
                "group": instance["group"],
                "description": instance["description"],
                "assembly": chain[-1] if isinstance(chain, list) and chain else "",
            }
        )
    if not servos:
        raise ValueError("model.json 未包含任何舵机实例")
    servos.sort(key=lambda servo: servo["id"])
    return {
        "servos": servos,
        "servo_count": len(servos),
        "part_instances": len(instances),
        "source": model.get("source"),
        "source_url": model.get("source_url"),
        "assembly": model.get("assembly"),
        "assembly_sha256": model.get("assembly_sha256"),
        "units": model.get("units"),
        "axes": model.get("axes"),
        "issues": model.get("issues", []),
        "notes": model.get("notes", []),
    }


def payload(site: Path | None) -> dict:
    """Availability plus reference for /api/servo-guide; never raises for a missing site."""
    if site is None:
        return {
            "available": False,
            "mount": None,
            "searched": [str(candidate) for candidate in site_candidates()],
            "note": "未找到 microduck-servo-guide 的 site 目录；舵机编号对照不可用，其他功能不受影响。",
        }
    value = {
        "available": True,
        "mount": "/servo-guide",
        "index": "/servo-guide/",
        "assembly_viewer": "/servo-guide/assembly.html",
    }
    try:
        value["reference"] = servo_reference(site)
    except ValueError as exc:
        value["reference_error"] = str(exc)
    return value
