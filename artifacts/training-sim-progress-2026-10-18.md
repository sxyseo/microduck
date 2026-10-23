# 训练与仿真推进记录（2026-10-18）

## 已执行

- 本机 `microduck_rl` CPU 训练 smoke：`Mjlab-Velocity-Flat-MicroDuck`，64 环境 × 5 iterations，run `codex-smoke-20261018`。训练完成并导出 ONNX；actor 为 61 维输入、14 维输出。此运行使用仓库当前工作树的实验差异 `air_time.threshold_min=0.04` 和默认 BAM M6/XL330 执行器配置。
- 两个 ONNX 均通过 `check_onnx_contract.py`：输入 `[1,61]`、输出 `[1,14]`、CPU ONNX Runtime 可推理且零观测输出有限。合同文件分别为 `onnx-contract-codex-smoke-20261018.json` 和 `onnx-contract-expE-12500-20261018.json`。
- 旧 expE `model_12500.pt` 对应 ONNX 在 MuJoCo/BAM M6 中做了三组各 10 秒闭环：前进 `vx=0.10 m/s`、横移 `vy=0.05 m/s`、转向 `wz=0.20 rad/s`。脚本报告 1 秒平均速度在首秒后接近 0，躯干高度约 117 mm；该检查点未通过这三项命令跟踪。CSV 分别为 `sim-expE-vx010-20261018.csv`、`sim-expE-vy005-20261018.csv`、`sim-expE-wz020-20261018.csv`。
- 使用 `uv run play ... --viewer viser --video True --video-length 500` 对 expE 检查点完成 10 秒、50 Hz 的可视化回放。视频位于训练仓 `logs/rsl_rl/velocity/2026-09-08_22-55-20_expE-gait-ramp/videos/play/rl-video-step-0.mp4`。
- expE 原训练日志末尾在 iteration 12689/50000：`air_time_mean=0.0466 s`、`fell_over=0.4583`、`error_vel_xy=0.3919`、`error_vel_yaw=1.1412`。日志没有推进到 50,000；当前目录仍只有 `model_12500.pt` 检查点。
- 从 expE `model_12500.pt` 续训了两个独立短程，均未改动原实验目录：
  - `codex-expE-cpu250-20261018`：64 环境 × 250 iterations（+384,000 transitions），Mac CPU 约 12 分钟。训练 reward 从 1.98 升到 48.48，但末段 `error_vel_xy=0.2409`、`error_vel_yaw=0.6838`、`fell_over=1.375`，波动很大。原 expE 是 512 环境；这次批量样本由 12,288 降到 1,536，故只作诊断，不作为原训练的可比续训。
  - `codex-expE-cpu512x10-20261018`：按原 512 环境、24 steps/env、4 mini-batches 做 10 iterations（+122,880 transitions），CPU 约 4 分钟。最后 `mean_reward=-0.4819`、`error_vel_xy=0.0355`、`error_vel_yaw=0.0946`、`fell_over=13.4583`。这段很短，只验证同配置续训能跑通；指标显示该段不稳定。
- 两个续训均成功导出 ONNX，并通过接口合同与 CPU ONNX Runtime 检查：`[1,61] -> [1,14]`、零观测输出有限。SHA 分别记录在 `onnx-contract-expE-cpu250-20261018.json`、`onnx-contract-expE-cpu512x10-20261018.json`。
- 对照旧 expE 与 `cpu250` ONNX，在相同 BAM M6 推理器中各做三组 500 帧（10 秒）闭环仿真：`vx=0.10 m/s`、`vy=0.05 m/s`、`wz=0.20 rad/s`。旧 expE 和 cpu250 的末段速度都约为 0；躯干高度分别约 117 mm 和 117.5 mm。动作 RMS 增大但命令跟踪没有改善。CSV、完整控制台日志在 `codex-expE-cpu250-20261018/sim-eval/`。
- 对 `cpu512x10` ONNX 做同样的三组 500 帧仿真，三组均未跟随命令，躯干高度降到约 40 mm，机器人在仿真中倒下。CSV 和日志在 `codex-expE-cpu512x10-20261018/sim-eval/`。

## 当前判定

- 训练与 ONNX 导出通道的 smoke 级验证通过；5 次迭代不代表学会行走。
- expE、cpu250 和 cpu512x10 检查点都不是可部署候选。cpu250 的长一点续训没有解决速度跟踪；cpu512x10 同配置短训出现跌倒。ONNX 形状通过仅证明接口和 CPU 推理，不证明动作能力或真机兼容。
- 下一次正式续训不能直接拿短段的末尾权重继续堆迭代；先找出 expE 从有效行为退化到 12689 的训练原因，并确定可复现的基线评测。正式对照固定 512 环境、随机种子、当前工作树差异、奖励/课程配置和评测命令，同时保留最佳检查点而不只保留最后检查点。
- 本机无 CUDA 设备；训练日志确认 MuJoCo Warp 使用 CPU。R1.5.27 训练台环境为 `unchecked`，目标版本是 Microduck 0.15.1 / HD1910。
- HL-2915 BAM 合同 `bam-model-hl2915-m6.json` 标记 `data_provenance=synthetic`，不能代表实测执行器动力学。新鲜 bring-up 汇总 `bringup-status-codex-20261018.json` 因 BAM 模型失败而 overall `failed`，且 S0–S6 与真机 S8 仍缺现场证据。
- 当前 Mac 没有 Radxa/机器人 SSH 主机配置，也没有可见的 USB 串口设备；因此没有执行真机读写或运动测试。

## 下一道门

1. 确认实体机实际舵机型号、固件/校准与 Radxa 连接方式。
2. 按已确认的实体舵机型号完成只读身份与双舵机台架记录；若确为 HL-2915，再采集真实 BAM 数据并重建对应仿真执行器模型。
3. 准备可用的 CUDA/WSL2 或 SSH GPU 训练主机，在硬件匹配的训练环境跑正式 smoke 与中等规模训练；固定策略评测矩阵后再训练长跑。
4. 按 `artifacts/README.md` 的 S0–S8 门槛补齐板端证据，再从只读检查逐级进入受保护的小幅动作验证。当前 expE 与 5-iteration smoke ONNX 都不进入真机。
