"""Read-only reachability adapter for the community-kit HLS servo debugger.

Studio checks whether the debugger deployed on the duck's core board is up and summarizes
its joint table. This adapter issues GET requests to /api/health and /api/joints only —
it never connects the serial port, never writes a register, and never proxies control
calls. Servo operations stay in the board tool's own web UI, where the operator holds the
bus exclusively.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

HEALTH_TIMEOUT_S = 2.0
JOINTS_TIMEOUT_S = 2.0
BOUNDARY_NOTE = (
    "此状态只做只读探活（GET /api/health 与 /api/joints）；舵机连接、校准与写寄存器"
    "都在板子工具自己的页面里完成，且一次只允许一个进程持有串口。"
)

DEFAULT_JOINT_COUNT = 15


def resolve_base_url(explicit: str | None = None, stored: str | None = None) -> str | None:
    """Precedence: page input > MICRODUCK_KIT_URL environment > project settings."""
    if explicit:
        value = explicit.strip().rstrip("/")
        return value or None
    env = (os.environ.get("MICRODUCK_KIT_URL") or "").strip().rstrip("/")
    if env:
        return env
    if stored:
        return str(stored).strip().rstrip("/") or None
    return None


def _get_json(base_url: str, path: str, timeout: float) -> tuple[dict | None, str | None]:
    try:
        with urllib.request.urlopen(f"{base_url}{path}", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), None
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def status(base_url: str | None, stored: str | None = None) -> dict:
    resolved = resolve_base_url(base_url, stored)
    if not resolved:
        return {
            "reachable": False,
            "base_url": None,
            "note": "未配置核心板调试台地址；在页面里填写并保存到项目设置，或用 MICRODUCK_KIT_URL 环境变量。",
            "boundary_note": BOUNDARY_NOTE,
        }
    if not resolved.startswith(("http://", "https://")):
        raise ValueError("调试台地址需要以 http:// 或 https:// 开头")
    health, health_error = _get_json(resolved, "/api/health", HEALTH_TIMEOUT_S)
    if not health or not health.get("ok"):
        return {
            "reachable": False,
            "base_url": resolved,
            "error": health_error or "health 应答不是预期的 ok 载荷",
            "note": "调试台未响应或不可达；确认板子上电、地址正确，且工具已用 deploy harness 启动。",
            "boundary_note": BOUNDARY_NOTE,
        }
    joints_payload, joints_error = _get_json(resolved, "/api/joints", JOINTS_TIMEOUT_S)
    joint_count = None
    if isinstance(joints_payload, dict):
        data = joints_payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("joints"), list):
            joint_count = len(data["joints"])
    tool = health.get("data") if isinstance(health.get("data"), dict) else {}
    return {
        "reachable": True,
        "base_url": resolved,
        "tool": {
            "name": tool.get("name"),
            "report_time": tool.get("time"),
            "joint_count": joint_count,
            "expected_joint_count": DEFAULT_JOINT_COUNT,
            "joints_error": joints_error,
        },
        "ui": f"{resolved}/",
        "boundary_note": BOUNDARY_NOTE,
    }
