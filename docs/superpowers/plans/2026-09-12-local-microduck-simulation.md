# 本地 MicroDuck 仿真环境 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Windows 开发机上用一条可复现命令准备 `microduck_rl`，运行官方 MuJoCo 推理或 5 轮 CPU smoke test。

**Architecture:** 当前 Rust 仓库只提供 PowerShell 编排入口和说明；物理模型、训练任务和 Python 依赖继续由独立的 `microduck_rl` 仓库提供。启动器只做路径/工具/版本检查、调用 `uv`，不复制或修改上游训练代码。

**Tech Stack:** PowerShell 7+/Windows PowerShell、Git、uv、MuJoCo/Python（由 `microduck_rl` 的 `uv sync` 管理）。

**Spec:** `docs/superpowers/specs/2026-09-12-local-microduck-simulation-design.md`

## Global Constraints

- 不把 Python、MuJoCo 或训练依赖加入 Rust workspace。
- 不下载或提交大体积 ONNX 权重到本仓库。
- 已有训练目录不执行 `reset`、`clean` 或覆盖用户文件。
- 默认使用基线 commit `29e887ecfbf5d37144759e5a9f8a176dfb83d547`；显式 `-Ref` 才切换其他 ref。
- smoke test 固定使用 8 个环境、24 steps/env、5 iterations、`--gpu-ids None`。

---

### Task 1: 添加 Windows 仿真启动器

**Files:**
- Create: `tools/microduck_learning/setup_simulation.ps1`

**Interfaces:**
- Consumes: `microduck_rl` Git remote and optional `-TrainingDir`/`-WalkingPolicy` paths.
- Produces: exit code `0` on successful preparation/run; non-zero with a human-readable error otherwise.

- [ ] **Step 1: Add parameter contract and path resolution**

Implement these parameters at the top of the script:

```powershell
[ValidateSet("Inference", "Smoke")]
[string]$Mode = "Smoke",
[string]$TrainingDir = "",
[string]$Ref = "29e887ecfbf5d37144759e5a9f8a176dfb83d547",
[string]$Remote = "https://github.com/pollen-robotics/microduck_rl.git",
[string]$WalkingPolicy = "",
[switch]$SkipSync,
[switch]$DryRun
```

Resolve the workspace from `$PSScriptRoot\..\..`; if `-TrainingDir` is empty, default to the sibling directory `..\microduck_rl`. Convert both paths to absolute paths without requiring the target directory to exist.

- [ ] **Step 2: Add non-destructive repository preparation**

Add a helper that invokes external commands as argument arrays and throws when `$LASTEXITCODE` is non-zero. For a missing training directory, create only its parent if needed and run `git clone $Remote $TrainingDir`, then `git -C $TrainingDir checkout --detach $Ref`. For an existing directory, verify `git -C $TrainingDir rev-parse --show-toplevel`; if `git status --porcelain` is non-empty, throw before changing refs; otherwise run `git -C $TrainingDir checkout --detach $Ref`. Never call `reset`, `clean`, or overwrite files.

- [ ] **Step 3: Add dry-run and tool checks**

Build the exact `uv` command arrays before execution. `-DryRun` must print `TrainingDir`, `Mode`, and each command, then exit `0` without checking out, cloning, syncing, or requiring `git`/`uv`. Normal execution must check `git` and `uv` with `Get-Command` and throw messages that name the missing tool.

- [ ] **Step 4: Add sync, dependency probe, and mode commands**

Unless `-SkipSync` is set, run `uv sync` in `$TrainingDir`. Always run `uv run scripts/infer_policy.py --help` as the dependency probe. For `Inference`, require `-WalkingPolicy` and an existing file, then run:

```text
uv run scripts/infer_policy.py --walking <WalkingPolicy> --new-cmd-obs
```

For `Smoke`, run:

```text
uv run train Mjlab-Velocity-Flat-MicroDuck --gpu-ids None --env.scene.num-envs 8 --agent.num-steps-per-env 24 --agent.max-iterations 5 --agent.logger tensorboard --agent.upload-model False --agent.run-name lesson-01-repro
```

Use `Push-Location`/`Pop-Location` so the caller’s directory is restored even when commands fail.

- [ ] **Step 5: Run the dry-run checks**

Run:

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 -DryRun
pwsh -File tools/microduck_learning/setup_simulation.ps1 -Mode Inference -WalkingPolicy C:\tmp\walk.onnx -SkipSync -DryRun
```

Expected: both commands exit `0`, print the resolved training directory and the exact `uv` commands, and do not create `microduck_rl` or touch files.

- [ ] **Step 6: Commit the launcher**

```powershell
git add tools/microduck_learning/setup_simulation.ps1
git commit -m "feat: add local simulation setup launcher"
```

### Task 2: Document the local workflow

**Files:**
- Modify: `tools/microduck_learning/README.md`

**Interfaces:**
- Consumes: the launcher contract from Task 1.
- Produces: copy-pasteable Windows and POSIX setup/run commands and acceptance checks.

- [ ] **Step 1: Add Windows prerequisites and setup commands**

Document that the user needs Git and `uv`, that the script defaults to a sibling `microduck_rl` directory, and show:

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 -DryRun
pwsh -File tools/microduck_learning/setup_simulation.ps1 -Mode Smoke
```

Include `-TrainingDir` and `-Ref` examples without claiming that the current Rust repository contains the training checkout.

- [ ] **Step 2: Add inference command and policy-path rule**

Show:

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 `
  -Mode Inference `
  -WalkingPolicy 'C:\path\to\alpha_walking.onnx'
```

Explain that the policy is passed explicitly and is not downloaded or committed by this repository. State that the MuJoCo viewer is the inference success signal; the smoke test success signal is process exit `0` without NaN or observation/action shape errors.

- [ ] **Step 3: Keep POSIX entry point and align acceptance notes**

Keep the existing Bash command, add a short note that it is for macOS/Linux, and point both platforms to the same fixed smoke-test parameters and upstream `microduck_rl` implementation.

- [ ] **Step 4: Validate Markdown and command examples**

Run `git diff --check` and inspect the README section to ensure all paths, parameter names, and commands match `setup_simulation.ps1` exactly.

- [ ] **Step 5: Commit the documentation**

```powershell
git add tools/microduck_learning/README.md
git commit -m "docs: document local simulation workflow"
```

### Task 3: Run the real environment checks

**Files:**
- Test: `tools/microduck_learning/setup_simulation.ps1`
- Test: `tools/microduck_learning/run_5_iteration_smoke.sh`

**Interfaces:**
- Consumes: the external `microduck_rl` checkout and its `uv` environment.
- Produces: proof that the dependency probe and smoke test can start on the current machine.

- [ ] **Step 1: Prepare the external checkout**

Run the launcher without `-DryRun` once. It may clone `microduck_rl` into the default sibling directory, checkout the pinned commit, and run `uv sync`; do not add that directory to this repository.

- [ ] **Step 2: Probe the upstream CLI**

Run:

```powershell
Push-Location ..\microduck_rl
uv run scripts/infer_policy.py --help
Pop-Location
```

Expected: exit `0` and help text, with no MuJoCo policy file required.

- [ ] **Step 3: Run the five-iteration CPU smoke test**

Run:

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 -Mode Smoke -SkipSync
```

Expected: the upstream trainer exits `0`; inspect its output for no NaN, missing environment, or observation/action shape errors. If the upstream repository or dependencies are unavailable, report the exact command and error instead of weakening the checks.

- [ ] **Step 4: Run repository-local checks**

Run:

```powershell
git diff --check
bash tools/microduck_learning/run_5_iteration_smoke.sh --dry-run
```

Expected: no whitespace errors and the existing POSIX launcher prints the same task/iteration settings.

- [ ] **Step 5: Record result without committing generated artifacts**

Confirm `git status --short` lists only intentional source/documentation changes. Do not commit `.venv`, TensorBoard logs, ONNX files, or the external checkout.

