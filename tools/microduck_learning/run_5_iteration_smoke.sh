#!/usr/bin/env bash
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRAINING_DIR="${WORKSPACE}/microduck-replica/upstream/microduck_rl"
cd "${TRAINING_DIR}"

COMMAND=(
  uv run train Mjlab-Velocity-Flat-MicroDuck
  --gpu-ids None
  --env.scene.num-envs 8
  --agent.num-steps-per-env 24
  --agent.max-iterations 5
  --agent.logger tensorboard
  --agent.upload-model False
  --agent.run-name lesson-01-repro
)

if [[ "${1:-}" == "--dry-run" ]]; then
  printf '%q ' "${COMMAND[@]}"
  printf '\n'
  exit 0
fi

exec "${COMMAND[@]}"

