#!/usr/bin/env bash
if [ -z "${BASH_VERSION:-}" ]; then
  echo "请用 bash 运行此脚本：bash tools/microduck_learning/run_5_iteration_smoke.sh" >&2
  exit 2
fi
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ -n "${MICRODUCK_RL_DIR:-}" ]]; then
  TRAINING_DIR="${MICRODUCK_RL_DIR}"
elif [[ -d "${WORKSPACE}/microduck-replica/upstream/microduck_rl" ]]; then
  TRAINING_DIR="${WORKSPACE}/microduck-replica/upstream/microduck_rl"
else
  TRAINING_DIR="${WORKSPACE}/microduck_rl"
fi

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
RUN_NAME="lesson-01-repro"

if [[ -n "${MICRODUCK_BAM_JSON:-}" ]]; then
  if [[ "${MICRODUCK_BAM_JSON}" =~ ^[A-Za-z]:[\\/] ]]; then
    echo "MICRODUCK_BAM_JSON 必须是 WSL/Linux 路径，例如 /mnt/f/microduck/artifacts/bam/hl2915-m6.json；不要传 Windows F:\\ 路径。" >&2
    exit 2
  fi
  if [[ ! -f "${MICRODUCK_BAM_JSON}" ]]; then
    echo "找不到 MICRODUCK_BAM_JSON：${MICRODUCK_BAM_JSON}" >&2
    exit 2
  fi
  BAM_ACTUATOR="${MICRODUCK_BAM_ACTUATOR:-hl2915}"
  BAM_MODEL="${MICRODUCK_BAM_MODEL:-m6}"
  COMMAND+=(
    --env.scene.entities.robot.articulation.actuators.0.motor-name None
    --env.scene.entities.robot.articulation.actuators.0.model None
    --env.scene.entities.robot.articulation.actuators.0.json-path "${MICRODUCK_BAM_JSON}"
  )
  if [[ "${BAM_ACTUATOR}" == "hl2915" ]]; then
    # The upstream robot defaults are XL330's 6.5..8.2 V domain and 3..6 tick delay.
    # A JSON BAM fit alone does not replace those config fields, so pin the C001 bench
    # envelope explicitly until measured sag and bus delay are available.
    COMMAND+=(
      --env.scene.entities.robot.articulation.actuators.0.kp-fw 16.0
      --env.scene.entities.robot.articulation.actuators.0.vin-range 10.8,13.2
      --env.scene.entities.robot.articulation.actuators.0.vin-drop-gain-range 0.0,0.0
      --env.scene.entities.robot.articulation.actuators.0.vin-min 9.0
      --env.scene.entities.robot.articulation.actuators.0.delay-min-lag 0
      --env.scene.entities.robot.articulation.actuators.0.delay-max-lag 0
    )
    COMMAND=(
      uv run python "${WORKSPACE}/tools/microduck_learning/run_hl2915_training.py"
      --bam-json "${MICRODUCK_BAM_JSON}"
      "${COMMAND[@]:3}"
    )
  fi
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  printf 'TRAINING_DIR=%q\n' "${TRAINING_DIR}"
  printf 'cd %q && ' "${TRAINING_DIR}"
  printf '%q ' "${COMMAND[@]}"
  printf '\n'
  exit 0
fi

if [[ ! -d "${TRAINING_DIR}" ]]; then
  echo "未找到 microduck_rl：${TRAINING_DIR}" >&2
  echo "先 git clone https://github.com/pollen-robotics/microduck_rl，然后设置 MICRODUCK_RL_DIR=/绝对路径" >&2
  exit 2
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "找不到 uv；请先安装 uv，再运行本脚本。" >&2
  exit 2
fi

cd "${TRAINING_DIR}"
if [[ -n "${MICRODUCK_BAM_JSON:-}" ]]; then
  mkdir -p "${WORKSPACE}/artifacts"
  uv run python "${WORKSPACE}/tools/microduck_learning/check_bam_model.py" \
    "${MICRODUCK_BAM_JSON}" \
    --actuator "${BAM_ACTUATOR}" \
    --model "${BAM_MODEL}" \
    --json-out "${WORKSPACE}/artifacts/bam-model-${BAM_ACTUATOR}-${BAM_MODEL}.json"
fi
"${COMMAND[@]}"

# The upstream runner exports an ONNX beside the checkpoint.  Check the exact artifact from this
# smoke run before calling the training pipeline usable; a green PPO process with a bad export is
# not a deployable result.
LATEST_ONNX="$(find logs/rsl_rl/velocity -type f -name "*_${RUN_NAME}.onnx" -print | sort | tail -n 1)"
if [[ -z "${LATEST_ONNX}" ]]; then
  echo "训练完成但没有找到 *_${RUN_NAME}.onnx；保留日志后停止。" >&2
  exit 3
fi
mkdir -p "${WORKSPACE}/artifacts"
uv run python "${WORKSPACE}/tools/microduck_learning/check_onnx_contract.py" \
  "${LATEST_ONNX}" \
  --json-out "${WORKSPACE}/artifacts/onnx-contract-${RUN_NAME}.json"

if [[ -n "${MICRODUCK_BAM_JSON:-}" ]]; then
  uv run python "${WORKSPACE}/tools/microduck_learning/check_training_lineage.py" \
    --bam-contract "${WORKSPACE}/artifacts/bam-model-${BAM_ACTUATOR}-${BAM_MODEL}.json" \
    --onnx-contract "${WORKSPACE}/artifacts/onnx-contract-${RUN_NAME}.json" \
    --training-repo "${TRAINING_DIR}" \
    --purpose smoke \
    --json-out "${WORKSPACE}/artifacts/training-lineage-${RUN_NAME}.json"
fi
