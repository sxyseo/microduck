#!/usr/bin/env python3
"""Extract TensorBoard scalars and create a compact article-ready plot."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator


IMPORTANT_TAGS = [
    "Train/mean_reward",
    "Train/mean_episode_length",
    "Loss/value",
    "Loss/surrogate",
    "Loss/entropy",
    "Policy/mean_std",
    "Episode_Reward/track_linear_velocity",
    "Episode_Reward/upright",
    "Episode_Reward/action_rate_l2",
    "Metrics/twist/error_vel_xy",
    "Metrics/twist/error_vel_yaw",
    "Episode_Termination/fell_over",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def load_scalars(run_dir: Path) -> dict[str, list[tuple[int, float]]]:
    event_files = sorted(run_dir.glob("events.out.tfevents*"))
    if not event_files:
        raise FileNotFoundError(f"No TensorBoard event file in {run_dir}")
    accumulator = EventAccumulator(
        str(event_files[-1]), size_guidance={"scalars": 0}
    )
    accumulator.Reload()
    return {
        tag: [(item.step, item.value) for item in accumulator.Scalars(tag)]
        for tag in accumulator.Tags().get("scalars", [])
    }


def write_csv(output: Path, scalars: dict[str, list[tuple[int, float]]]) -> None:
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["tag", "step", "value"])
        for tag in sorted(scalars):
            for step, value in scalars[tag]:
                writer.writerow([tag, step, f"{value:.9g}"])


def write_summary(output: Path, scalars: dict[str, list[tuple[int, float]]]) -> None:
    lines = [
        "# TensorBoard scalar summary",
        "",
        "This file is generated from the event file; it is not a hand-edited interpretation.",
        "",
        "| Tag | First | Last | Delta | Points |",
        "|---|---:|---:|---:|---:|",
    ]
    for tag in IMPORTANT_TAGS:
        values = scalars.get(tag, [])
        if not values:
            lines.append(f"| `{tag}` | missing | missing | missing | 0 |")
            continue
        first = values[0][1]
        last = values[-1][1]
        lines.append(
            f"| `{tag}` | {first:.6f} | {last:.6f} | {last - first:.6f} | {len(values)} |"
        )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot(output: Path, scalars: dict[str, list[tuple[int, float]]]) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), dpi=160)

    def draw(ax, tags: list[str], title: str) -> None:
        drawn = False
        for tag in tags:
            values = scalars.get(tag, [])
            if not values:
                continue
            ax.plot(
                [step for step, _ in values],
                [value for _, value in values],
                marker="o",
                linewidth=1.8,
                label=tag.split("/", 1)[-1],
            )
            drawn = True
        ax.set_title(title)
        ax.set_xlabel("iteration")
        ax.grid(alpha=0.25)
        if drawn:
            ax.legend(fontsize=7)
        else:
            ax.text(0.5, 0.5, "no data", ha="center", va="center")

    draw(axes[0, 0], ["Train/mean_reward", "Train/mean_episode_length"], "Training")
    draw(axes[0, 1], ["Loss/value", "Loss/surrogate", "Loss/entropy"], "PPO losses")
    draw(
        axes[1, 0],
        ["Metrics/twist/error_vel_xy", "Metrics/twist/error_vel_yaw", "Episode_Termination/fell_over"],
        "Tracking and falls",
    )
    draw(
        axes[1, 1],
        ["Policy/mean_std", "Episode_Reward/track_linear_velocity", "Episode_Reward/upright"],
        "Policy and task terms",
    )
    fig.suptitle("MicroDuck training evidence")
    fig.tight_layout()
    fig.savefig(output, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    scalars = load_scalars(args.run_dir)
    write_csv(args.output_dir / "scalars.csv", scalars)
    write_summary(args.output_dir / "summary.md", scalars)
    plot(args.output_dir / "metrics.png", scalars)
    print(f"wrote {args.output_dir / 'scalars.csv'}")
    print(f"wrote {args.output_dir / 'summary.md'}")
    print(f"wrote {args.output_dir / 'metrics.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

