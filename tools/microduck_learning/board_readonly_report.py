#!/usr/bin/env python3
"""Collect a read-only Radxa bring-up report.

This deliberately checks files and command availability only. It never scans an I2C bus,
opens a serial port, starts a service, changes device-tree state, or sends a motor command.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

CommandRunner = Callable[[list[str]], str | None]
_MIN_GSTREAMER = (1, 22, 0)


def _run_command(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _check(name: str, status: str, value: object, detail: str, required: bool = True) -> dict:
    return {
        "name": name,
        "status": status,
        "value": value,
        "detail": detail,
        "required": required,
    }


def _existing(root: Path, relative: str) -> bool:
    return (root / relative.lstrip("/\\")).exists()


def _matches(root: Path, pattern: str) -> list[str]:
    return sorted(str(path.relative_to(root)).replace("\\", "/") for path in root.glob(pattern.lstrip("/\\")) if path.exists())


def _gstreamer_version(text: str) -> tuple[int, int, int] | None:
    matches = re.findall(r"(?<!\d)(\d+)\.(\d+)(?:\.(\d+))?(?!\d)", text)
    if not matches:
        return None
    return tuple(int(part or 0) for part in matches[-1])


def collect_report(
    root: Path | str = "/",
    *,
    machine: str | None = None,
    command_runner: CommandRunner = _run_command,
) -> dict:
    """Return a JSON-serialisable report rooted at ``root``.

    ``root`` and ``command_runner`` are injectable so the decision logic can be tested without a
    Radxa or fake device files. In normal use they are ``/`` and the real subprocess runner.
    """

    root = Path(root)
    machine = machine or platform.machine()
    checks: list[dict] = []

    checks.append(
        _check(
            "architecture",
            "pass" if machine == "aarch64" else "warn",
            machine,
            "Radxa Zero 3W expects aarch64" if machine == "aarch64" else "not an aarch64 board",
        )
    )

    serial_paths = [path for path in ("/dev/ttyS2", "/dev/ttyUSB0", "/dev/ttyACM0") if _existing(root, path)]
    checks.append(
        _check(
            "serial",
            "pass" if serial_paths else "missing",
            serial_paths,
            "至少一个候选串口存在；不会自动打开" if serial_paths else "未发现 ttyS2/ttyUSB0/ttyACM0",
        )
    )
    checks.append(
        _check(
            "imu",
            "unknown",
            "Dynamixel v2 ID=200",
            "只读报告不打开串口；必须用 imu_probe 或 hl2915_mixed_probe 实际读取",
            required=False,
        )
    )

    hat_paths = [path for path in ("/dev/i2c-pihat", "/dev/i2c-3") if _existing(root, path)]
    checks.append(
        _check(
            "hat_i2c",
            "pass" if hat_paths else "missing",
            hat_paths,
            "发现 HAT I²C 设备节点；未主动扫描地址" if hat_paths else "未发现 i2c-pihat 或 i2c-3",
        )
    )

    camera_paths = _matches(root, "/dev/video*")
    checks.append(
        _check(
            "camera",
            "pass" if camera_paths else "missing",
            camera_paths,
            "发现 V4L2 视频节点" if camera_paths else "未发现 /dev/video*；先检查 overlay、排线和 vendor kernel",
        )
    )

    # A random USB /dev/video0 is not proof that the CSI camera reached Radxa's ISP.  The
    # media pipeline needs the vendor rkisp main path specifically, so expose that distinction
    # instead of letting a user tick the camera gate on the wrong node.
    video_name_files = _matches(root, "/sys/class/video4linux/*/name")
    camera_mainpaths = []
    for relative in video_name_files:
        try:
            name = (root / relative).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if "rkisp_mainpath" in name:
            camera_mainpaths.append({"path": relative, "name": name})
    checks.append(
        _check(
            "camera_mainpath",
            "pass" if camera_mainpaths else "missing",
            camera_mainpaths,
            "发现 vendor rkisp_mainpath，CSI 摄像头已到 ISP" if camera_mainpaths else "未发现 rkisp_mainpath；/dev/video* 可能只是 USB 或 overlay 尚未生效",
        )
    )

    mpp_present = _existing(root, "/dev/mpp_service")
    checks.append(
        _check(
            "mpp",
            "pass" if mpp_present else "missing",
            "/dev/mpp_service" if mpp_present else None,
            "Rockchip MPP 设备存在" if mpp_present else "未发现 /dev/mpp_service",
        )
    )

    rga_present = _existing(root, "/dev/rga")
    checks.append(
        _check(
            "rga",
            "pass" if rga_present else "missing",
            "/dev/rga" if rga_present else None,
            "RGA 设备存在" if rga_present else "未发现 /dev/rga；MPP 编码可能无法完成格式转换",
            required=False,
        )
    )

    npu_paths = [
        path
        for path in ("/dev/rknpu", "/sys/kernel/debug/rknpu/version", "/proc/rknpu/version")
        if _existing(root, path)
    ]
    checks.append(
        _check(
            "npu",
            "pass" if npu_paths else "missing",
            npu_paths,
            "发现 RKNN/NPU 入口" if npu_paths else "未发现 NPU 入口；不影响舵机和 IMU 台架测试",
            required=False,
        )
    )

    audio_cards = root / "proc/asound/cards"
    audio_text = audio_cards.read_text(encoding="utf-8", errors="replace") if audio_cards.is_file() else ""
    audio_present = any(token in audio_text.lower() for token in ("aic3104", "aic3x", "tlv320"))
    checks.append(
        _check(
            "hat_audio",
            "pass" if audio_present else "missing",
            audio_text.strip() or None,
            "发现 TLV320/AIC3104 声卡" if audio_present else "未发现 HAT 音频卡；若不使用音频可暂不处理",
            required=False,
        )
    )

    tof_state = command_runner(["systemctl", "is-active", "tofd"])
    checks.append(
        _check(
            "tof_service",
            "pass" if tof_state and tof_state.strip() == "active" else "unknown",
            tof_state.strip() if tof_state else None,
            "tofd 正在运行；仍需查看 tof.stream 是否有帧" if tof_state and tof_state.strip() == "active" else "没有确认 tofd active；ToF 是可选 HAT 外设",
            required=False,
        )
    )

    gst_version = command_runner(["gst-inspect-1.0", "--version"])
    if gst_version is None:
        checks.append(
            _check(
                "gstreamer",
                "unknown",
                None,
                "gst-inspect-1.0 不可用；运行 setup-gstreamer.sh 安装后再检查",
            )
        )
    else:
        elements = {element: command_runner(["gst-inspect-1.0", element]) is not None for element in (
            "rkisp",
            "mpph264enc",
            "webrtcbin",
            "webrtcsink",
        )}
        missing = [name for name, present in elements.items() if not present]
        version = _gstreamer_version(gst_version)
        if version is None:
            missing.append("gstreamer>=1.22")
        elif version < _MIN_GSTREAMER:
            missing.append("gstreamer>=1.22")
        checks.append(
            _check(
                "gstreamer",
                "pass" if not missing else "missing",
                {"version": gst_version.strip(), "parsed_version": version, "elements": elements},
                "GStreamer 版本和所需元素均满足（>=1.22）" if not missing else f"缺少元素或版本过旧：{', '.join(missing)}",
            )
        )

    required_checks = [check for check in checks if check["required"]]
    status = "ready" if all(check["status"] == "pass" for check in required_checks) else "incomplete"
    counts = {state: sum(check["status"] == state for check in checks) for state in ("pass", "warn", "missing", "unknown")}
    return {
        "schema_version": 1,
        "read_only": True,
        "status": status,
        "machine": machine,
        "checks": checks,
        "summary": counts,
    }


def render_text(report: dict) -> str:
    lines = [f"board report: {report['status']} (read_only={report['read_only']})"]
    for check in report["checks"]:
        lines.append(f"{check['status']:>7}  {check['name']:<12} {check['detail']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="只读汇总 Radxa 的串口、HAT、相机、MPP、NPU 和 GStreamer 状态")
    parser.add_argument("--json-out", type=Path, help="保存 JSON 报告；不指定则不写文件")
    parser.add_argument("--root", type=Path, default=Path("/"), help=argparse.SUPPRESS)
    parser.add_argument("--strict", action="store_true", help="必需检查不完整时返回 1")
    args = parser.parse_args()

    report = collect_report(args.root)
    print(render_text(report))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"json: {args.json_out}")
    return 1 if args.strict and report["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
