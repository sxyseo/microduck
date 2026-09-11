# MicroDuck 学习辅助工具

这些工具只读取或分析已有源码和 TensorBoard event 文件，不修改上游训练逻辑。

## 查看配置文件的指定区块

从工作区根目录执行：

```bash
python tools/microduck_learning/inspect_velocity_cfg.py --section observations
python tools/microduck_learning/inspect_velocity_cfg.py --section commands
```

可选区块：`globals`、`terrain`、`factory`、`observations`、`commands`、`terrain_runtime`、`curriculum`、`ppo`、`all`。

## 分析 TensorBoard

从训练项目目录执行：

```bash
cd microduck-replica/upstream/microduck_rl
uv run python /Volumes/dev/dev/microduck/tools/microduck_learning/analyze_tensorboard.py \
  --run-dir logs/rsl_rl/velocity/<run-directory> \
  --output-dir /Volumes/dev/dev/microduck/docs/microduck-30day/assets/<run-name>
```

工具会输出：

- `scalars.csv`：所有 scalar 的长表；
- `summary.md`：每个重点指标的首末值；
- `metrics.png`：适合放入文章的四宫格曲线图。

## 本地仿真：Windows

需要先安装 Git 和 `uv`。训练仓库不在当前 Rust 仓库中；脚本默认使用当前工作区的
兄弟目录 `microduck_rl`，不存在时会从上游仓库 clone。先用 dry run 检查路径和命令，再运行
固定的 5 次迭代 CPU smoke test：

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 -DryRun
pwsh -File tools/microduck_learning/setup_simulation.ps1 -Mode Smoke
```

也可以显式指定训练 checkout 和 Git ref（这些目录需要由你准备，当前仓库不包含训练 checkout）：

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 `
  -TrainingDir 'C:\path\to\microduck_rl' `
  -Ref '29e887ecfbf5d37144759e5a9f8a176dfb83d547' `
  -Mode Smoke
```

推理时必须显式传入已有的 walking policy：

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 `
  -Mode Inference `
  -WalkingPolicy 'C:\path\to\alpha_walking.onnx'
```

策略不会由本仓库下载，也不会提交到本仓库。推理成功信号是 MuJoCo viewer 启动并运行；
smoke test 成功信号是进程以退出码 `0` 结束，且日志中没有 `NaN` 或 observation/action shape 错误。

## 重跑第一个 smoke test（macOS/Linux）

脚本会优先使用环境变量 `MICRODUCK_RL_DIR`；如果不设置，则依次尝试
`microduck-replica/upstream/microduck_rl` 和工作区根目录下的 `microduck_rl`。
训练仓库不在本仓库里，需单独 clone：

```bash
git clone https://github.com/pollen-robotics/microduck_rl
export MICRODUCK_RL_DIR="$PWD/microduck_rl"
```

```bash
bash tools/microduck_learning/run_5_iteration_smoke.sh --dry-run
bash tools/microduck_learning/run_5_iteration_smoke.sh
```

该脚本与 Windows 入口使用同一组固定 smoke-test 参数（8 个环境、每环境 24 steps、5 次
iterations、`--gpu-ids None`、`lesson-01-repro`），并调用上游 `microduck_rl` 的同一训练实现。

正式训练前先运行 `--dry-run`，确认任务、环境数和迭代数。

