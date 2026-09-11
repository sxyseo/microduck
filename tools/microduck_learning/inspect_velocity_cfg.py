#!/usr/bin/env python3
"""Print selected, line-numbered sections of the MicroDuck velocity config."""

from __future__ import annotations

import argparse
from pathlib import Path


SECTIONS: dict[str, tuple[int, int, str]] = {
    "globals": (1, 87, "全局开关、随机化范围和命令范围"),
    "terrain": (127, 190, "地形和接触传感器"),
    "factory": (193, 390, "环境工厂、动作、reward 和终止条件"),
    "observations": (532, 638, "actor/critic observation、噪声和延迟"),
    "commands": (639, 748, "twist、head pose 和 body pose 命令"),
    "terrain_runtime": (749, 777, "平地/崎岖地形和 MuJoCo 参数"),
    "curriculum": (778, 917, "课程学习"),
    "ppo": (928, 950, "PPO 网络和训练参数"),
}


def default_cfg_path() -> Path:
    workspace = Path(__file__).resolve().parents[2]
    return workspace / (
        "microduck-replica/upstream/microduck_rl/"
        "src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--section",
        choices=[*SECTIONS, "all"],
        default="all",
        help="section to print (default: all)",
    )
    parser.add_argument("--cfg", type=Path, default=default_cfg_path())
    args = parser.parse_args()

    lines = args.cfg.read_text(encoding="utf-8").splitlines()
    names = SECTIONS if args.section == "all" else {args.section: SECTIONS[args.section]}

    for name, (start, end, description) in names.items():
        print(f"\n## {name}: {description} ({start}-{end})")
        for number in range(start, min(end, len(lines)) + 1):
            print(f"{number:4d} | {lines[number - 1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

