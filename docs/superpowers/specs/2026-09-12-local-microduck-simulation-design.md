# 本地 MicroDuck 仿真环境设计

## 目标

在 Windows 开发机上提供一条可复现的本地仿真路径：准备官方 `microduck_rl` 训练仓库，安装其 MuJoCo/Python 依赖，运行官方策略推理，并启动一个小规模 CPU smoke test。仿真代码仍由 `microduck_rl` 维护，本仓库只提供薄启动器和使用说明。

## 非目标

- 不把 Python、MuJoCo 或训练依赖加入 Rust workspace。
- 不实现新的物理模型、训练任务或策略转换逻辑。
- 不下载或提交大体积 ONNX 权重到本仓库。
- 不用 Docker 取代本机 `uv` 环境。

## 方案

新增 `tools/microduck_learning/setup_simulation.ps1`，作为 Windows 入口：

1. 解析训练仓目录（默认工作区旁的 `microduck_rl`，可用参数覆盖）。
2. 检查 `git` 和 `uv`；缺少工具时返回可执行的安装提示。
3. 训练仓不存在时按指定远程地址 clone；存在时复用，不覆盖本地改动。
4. 默认切换到文档锁定的基线 commit；显式传入 `-Ref` 才允许使用其他 ref。
5. 执行 `uv sync`，随后用 `uv run scripts/infer_policy.py --help` 做依赖可用性检查。
6. 根据模式运行推理或 5 轮 smoke test。推理模式要求显式提供 walking ONNX 路径；smoke test 使用 8 个环境、24 steps/env 和 5 iterations，默认关闭 GPU。

现有 `run_5_iteration_smoke.sh` 继续作为 macOS/Linux 入口，README 同步记录两种平台的命令和验收标准。启动器只负责编排，不复制上游训练逻辑。

## 数据流与接口

```text
microduck (当前仓库，策略/运行时)
          │ 可选的 walking.onnx 路径
          ▼
setup_simulation.ps1 ── uv sync ──▶ microduck_rl/.venv
          │
          ├─ inference ──▶ scripts/infer_policy.py ── MuJoCo viewer
          └─ smoke ──────▶ train Mjlab-Velocity-Flat-MicroDuck
```

脚本参数保持少量且稳定：`-TrainingDir`、`-Ref`、`-Mode (Inference|Smoke)`、`-WalkingPolicy`、`-SkipSync`、`-DryRun`。命令以数组传递给 PowerShell，避免路径空格和 shell 拼接问题。

## 错误处理

- 工具缺失、训练仓不存在、策略文件不存在、依赖命令失败均返回非零退出码。
- clone 前检查目标目录；已有目录只复用，不执行 reset、clean 或覆盖用户文件。
- 推理模式缺少策略时，在启动 MuJoCo 前报告完整路径和下一步命令。
- `-DryRun` 只打印将执行的目录和命令，不访问网络、不修改文件。

## 验证

最小检查集：

1. `setup_simulation.ps1 -DryRun`：验证路径解析和命令组装。
2. `setup_simulation.ps1 -Mode Inference -SkipSync -DryRun`：验证推理参数透传。
3. 实际 `uv sync` 后运行 `uv run scripts/infer_policy.py --help`。
4. 运行 5 轮 smoke test；检查进程正常退出且日志没有 NaN/shape 错误。

不添加测试框架；PowerShell 的 dry-run 和上游命令本身就是这条编排逻辑的最小可执行检查。

## 文件范围

- 新增：`tools/microduck_learning/setup_simulation.ps1`
- 修改：`tools/microduck_learning/README.md`
- 视需要微调：`tools/microduck_learning/run_5_iteration_smoke.sh`

不修改 `robotd`、策略协议或其他运行时模块。
