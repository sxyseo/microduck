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

## 重跑第一个 smoke test

```bash
bash tools/microduck_learning/run_5_iteration_smoke.sh --dry-run
bash tools/microduck_learning/run_5_iteration_smoke.sh
```

正式训练前先运行 `--dry-run`，确认任务、环境数和迭代数。

