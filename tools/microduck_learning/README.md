# MicroDuck 学习辅助工具

分析工具只读取已有源码和 TensorBoard event 文件；仿真启动器只在外部 `microduck_rl`
目录准备依赖并调用上游命令，不修改当前 Rust 仓库或上游训练源文件。

## 采购前筛选更便宜的舵机

拿到候选型号的规格书后，先整理成 JSON，再运行只读筛选器：

```bash
python tools/microduck_learning/check_servo_candidate.py candidate.json \
  --json-out artifacts/servo-candidate-report.json
```

它只比较电压、总线、位置单位、花键和纸面扭矩，输出 `profile_candidate`、
`low_load_power_variant`、`new_bus_driver` 或 `insufficient_data`。任何结果的
`hardware_passed` 都会保持 `false`；候选型号仍必须先买 1 只做通信、10 分钟 CSV、
结构和动力学测试，不能凭这个报告批量采购或加载 ONNX。字段示例：

电压上下限必须为正且 `min <= max`，位置分辨率、范围、花键齿数和纸面扭矩也必须为正；
不符合这些基本物理约束的 JSON 会直接标为 `insufficient_data`，不会被归类成“低负载候选”。

```json
{
  "model": "candidate-v1",
  "voltage_min_v": 9,
  "voltage_max_v": 14,
  "protocol": "feetech_v1",
  "signal": "ttl_half_duplex",
  "position_counts": 4096,
  "position_range_deg": 360,
  "spline_teeth": 25,
  "torque_kgcm": 10,
  "datasheet_confirmed": true
}
```

## 汇总 HL-2915 台架数据

`hl2915_record` 生成 CSV 后，用标准库脚本检查格式并输出每只舵机的采样频率、位置范围、
最大速度/负载/电流、最低电压、最高温度、状态值和运动样本数；状态字出现非零故障值时摘要会判为 `failed`：

速度和负载仍保留原始 16 位寄存器值；摘要里的 `*_magnitude_max` 会分别去掉 Feetech 的
方向位（速度 bit15、负载 bit10），避免把方向误算成真实幅度。

```bash
python tools/microduck_learning/hl2915_bench_summary.py \
  artifacts/hl2915-bench.csv \
  --output artifacts/hl2915-bench-summary.json
```

脚本只整理测量证据，不会自动拟合或修改 BAM/MJCF 参数。先运行内置自检：

```bash
python tools/microduck_learning/hl2915_bench_summary.py --self-test
```

## 判读第一次 `hl2915_probe` 输出

把现场完整 stdout 保存为文本后，可以让脚本检查响应 ID、`status`、9–14V 电压、55°C 温度和
1.4A 电流门槛；它只读文本，不会重新打开串口，并能识别 Windows PowerShell 常见的 UTF-8/UTF-16 日志：

```powershell
.\target\release\hl2915_probe.exe COM3 1 *> artifacts\hl2915-probe-id1.txt
python tools\microduck_learning\validate_hl2915_probe_log.py `
  artifacts\hl2915-probe-id1.txt --ids 1 `
  --json-out artifacts\hl2915-probe-id1-report.json
```

`passed` 只表示这份探针输出满足软件门槛；`insufficient_data` 表示输出不完整；`failed` 会列出
ID、状态、电压、温度或电流的具体原因。它不能替代接线照片、万用表读数和 60/600 秒连续记录。

## Radxa 只读板卡报告

在 Radxa Zero 3W 上汇总串口、HAT 的 I²C 节点、摄像头、MPP/RGA、NPU 和 GStreamer：

```bash
python tools/microduck_learning/board_readonly_report.py \
  --json-out artifacts/board-readonly-report.json
```

报告会把 GStreamer `<1.22` 标为未通过；WSL Ubuntu 22.04 常见的 1.20 不能替代 Radxa 的媒体环境。
S4 还要求报告同时确认 `aarch64` 和候选串口；PC 上的串口节点不能冒充 Radxa。

这个命令不会扫描 I²C 地址、打开串口、启动服务、修改设备树或发送舵机命令。
相机要同时通过 `camera` 和 `camera_mainpath`：后者确认 vendor `rkisp_mainpath` 存在，
避免把任意 `/dev/video0`（例如 USB 摄像头）误判为项目 CSI 相机已经接通。
需要把“未准备好”作为脚本失败处理时，再加 `--strict`；普通模式即使硬件还没接好也会
输出报告，方便新手先看缺哪一层。

## 官方 Robot HAT I²C/音频功能 smoke

`board_readonly_report.py` 只证明节点和声卡被系统枚举。先对照
[Pollen Robotics 官方 Robot HAT 工程](https://github.com/pollen-robotics/elec_RPI_Robot_HAT)
确认实物版本，再在 Radxa 上运行有界功能测试：

```bash
python tools/microduck_learning/hat_smoke.py \
  --run --confirm-official-hat \
  --json-out artifacts/hat-smoke-first.json
```

它用 `i2cdetect -y -r 3` 核对 TLV320AIC3104 的 `0x18`，录制 2 秒临时音频，再播放
0.25 秒、2% 幅度的提示音。录音和提示音在退出时删除，只保留命令结果与字节数。第一次
听到声音后，再重跑并加 `--confirm-audible`，把最终结果写成 `artifacts/hat-smoke.json`；
没听到就不能加该参数。未知 HAT 不得使用 `--confirm-official-hat`，应先核对原理图。

## 汇总 S0–S8 证据

现场分别保存 CSV 摘要、混合协议日志、板卡报告、BAM JSON 和 ONNX 合同后，可以让一个
只读脚本给出总进度：

```bash
python tools/microduck_learning/bringup_status.py \
  --servo-a-validation artifacts/servo-a-id1-validation.json \
  --servo-b-validation artifacts/servo-b-id2-validation.json \
  --hat-smoke artifacts/hat-smoke.json \
  --media-smoke artifacts/media-smoke.json \
  --board-report artifacts/board-readonly-report.json \
  --bench-summary artifacts/hl2915-bench-summary.json \
  --mixed-log artifacts/hl2915-mixed-60s.txt \
  --bam-log artifacts/bam/raw/kp16-a10.json \
  --bam-model-contract artifacts/bam-model-hl2915-m6.json \
  --onnx-contract artifacts/onnx-contract-hl2915.json \
  --training-lineage artifacts/training-lineage-hl2915-candidate.json \
  --json-out artifacts/bringup-status.json
```

它不会打开串口、启动服务或驱动舵机；缺少证据会显示 `pending`，明确故障会显示 `failed`。
混合日志还必须来自当前探针，并包含 `max_stale_run`；连续 25 个完全相同的 IMU 数据块会被判为冻结。
`BAM data` 是原始摆锤日志，`BAM model` 是拟合后且明确标记为 `hl2915/m6` 的参数合同，二者不能混用。
模型合同还必须写明 `data_provenance`：`synthetic` 可以验证训练管线，只有 `measured` 才能通过真实硬件验收。
只有以后所有硬件和现场手工门槛都完成，才同时加上 `--confirm-ids --confirm-s8 --strict`；
两个 `confirm` 是操作者对照片、纸质验收表和断电记录的人工确认，不是程序替你伪造硬件证据。

## Radxa 相机/MPP/WebRTC 功能 smoke

`board_readonly_report.py` 只看节点和插件；在 Radxa 上再执行下面的有界测试，才会生成 S6 所需的功能证据：

```bash
python tools/microduck_learning/media_smoke.py \
  --run --frames 60 \
  --json-out artifacts/media-smoke.json
```

它只使用 `rkisp_mainpath`，采集 60 帧到临时文件，运行 `mpph264enc → h264parse → filesink`，
再运行 `filesrc → h264parse → avdec_h264`，并检查 `webrtcbin`/`webrtcsink`。失败 JSON 也要保留；
不要用“能看到 `/dev/video0`”替代功能 smoke。

没有 Radxa 时只能运行自检：

```bash
python tools/microduck_learning/media_smoke.py --self-test
```

自检不产生硬件证据，也不能让 S6 通过。

## 采集 HL-2915 的 BAM 原始日志

需要执行器辨识时，使用仓库内的 `hl2915_bam_record`，不要直接照抄上游 BAM 的旧版
`bam.feetech.record`：旧脚本把端口和 ID 写死，并不是 HL-2915 的安全现场流程。新记录器要求
独立摆锤、质量/长度参数和 `--confirm-motion`，默认只允许 `±10°` 小幅度轨迹，并在状态、温度、
电压或电流越界时停止。它生成的 JSON 已符合 `bam.process` 所需的字段：

```powershell
New-Item -ItemType Directory -Force .\artifacts\bam\raw | Out-Null
cargo +1.89.0 run -p duck-control --bin hl2915_bam_record -- `
  COM3 1 --mass-kg 0.05 --arm-length-m 0.10 `
  --output .\artifacts\bam\raw\kp16-a10.json --confirm-motion
```

在 Linux/WSL2 中使用上游 BAM：

```bash
cd /home/<user>/microduck_rl
uv pip install --python .venv/bin/python "optuna>=4,<5" "wandb>=0.24,<0.25" cmaes
uv run python -m bam.process --raw /mnt/f/microduck/artifacts/bam/raw \
  --logdir /mnt/f/microduck/artifacts/bam/processed --dt 0.01
uv run python /mnt/f/microduck/tools/microduck_learning/fit_hl2915_bam.py \
  --error-gain <实测值> \
  --logdir /mnt/f/microduck/artifacts/bam/processed \
  --output /mnt/f/microduck/artifacts/bam/hl2915-m6.json \
  --method cmaes --model m6 --trials 2000 --workers 1
```

`fit_hl2915_bam.py` 只在当前进程中注册 `hl2915`，不会修改安装的 BAM。它复用 BAM 的
Feetech 电压控制实现，以 C001 的 110 RPM 和 9.3 kgf·cm/A 作为可优化起点，并保留限速与
电流限制；`--error-gain` 是“位置误差 × 固件 P 增益 → PWM 占空比”的实测换算，不能抄
STS3215 的数值。没有示波器实测或飞特书面值时，停在这一步，不生成伪参数。先验证适配器：

```bash
uv run python /mnt/f/microduck/tools/microduck_learning/fit_hl2915_bam.py \
  --error-gain <实测值> --self-test
```

先用 2000 trials 验证流程，再增加 trials 做正式辨识；拟合后运行 `check_bam_model.py`，确认
输出明确写着 `actuator=hl2915`、`model=m6`。

没有 BAM 文件时，可以先验证合同检查器本身：

```bash
python tools/microduck_learning/check_bam_model.py --self-test
```

这只检查内存中的合成合同，不会把合成数据当成真实 HL-2915 参数，也不会通过真实硬件门槛。

采集完先做一个不依赖 BAM 的结构化检查：

```bash
python tools/microduck_learning/validate_bam_log.py \
  artifacts/bam/raw/kp16-a10.json
python tools/microduck_learning/validate_bam_log.py --self-test
```

这个检查还会拒绝 `motor` 不是 `hl2915` 的日志，避免把其他候选舵机的摆锤数据误送进 C001 的拟合流程。以后验证其他型号时可以显式传入 `--motor <型号>`，但仍需要该型号自己的适配器和模型。

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

## 检查 ONNX 部署合同

训练或导出后，先在训练仓库的 `uv` 环境中运行这个只读检查，再把文件拷到 Radxa：

```bash
python tools/microduck_learning/check_onnx_contract.py \
  logs/rsl_rl/velocity/<run>/<run>.onnx \
  --json-out artifacts/onnx-contract.json
```

它要求且实际调用 CPU Runtime 验证 `obs[1,61] → actions[1,14]`，并拒绝 NaN/无穷大；
合同同时记录模型文件的 `sha256` 和 `size_bytes`，用于上传 Radxa 后逐字节核对。
它不会打开串口、启动 `robotd` 或让舵机运动。先运行 `--self-test` 可检查工具自身。

## 用 HL-2915 的 BAM JSON 做 smoke test

上游训练器已经原生支持 `json_path`。不需要手改上游 Python；把 `bam.fit` 生成的 JSON
路径交给项目脚本即可。脚本会把 `motor-name` 和 `model` 设为 `None`，避免同时传入两套
互斥参数：

```bash
export MICRODUCK_BAM_JSON=/绝对路径/artifacts/bam/hl2915-m6.json
bash tools/microduck_learning/run_5_iteration_smoke.sh
```

脚本会先运行 `check_bam_model.py`：默认要求 JSON 的 `actuator=hl2915`、`model=m6`，并检查
M6 所需的有限数值字段；原始 BAM 采集日志、XL330 示例参数或缺字段文件会在训练前拒绝。
开发阶段若只是验证上游示例，可以明确写出例外：

当 `BAM_ACTUATOR=hl2915` 时，脚本还会覆盖上游 XL330 默认的执行器域：
`kp_fw=16`、`vin_range=10.8..13.2 V`、`vin_min=9 V`、压降随机化先为 `0..0`，
延迟先为 0。训练日志必须看到类似 `vin=range=(10.8, 13.2)`；如果仍显示
`6.5..8.2 V`，不要把该 smoke 当成 HL-2915 结果，应检查脚本版本和命令输出。

```bash
MICRODUCK_BAM_ACTUATOR=xl330 MICRODUCK_BAM_MODEL=m6 \
  MICRODUCK_BAM_JSON=/path/to/bam/params/xl330/m6.json \
  bash tools/microduck_learning/run_5_iteration_smoke.sh
```

通过后会留下 `artifacts/bam-model-<actuator>-<model>.json`、ONNX 合同和
`artifacts/training-lineage-lesson-01-repro.json`。最后一份报告固定记录 BAM/ONNX 的 SHA-256、
训练仓库 commit 和 clean 状态；5 轮脚本生成的 `purpose=smoke` 只能证明管线可运行。
这份合同只证明“参数文件格式和型号一致”，不替代真实 HL-2915 台架辨识。

完整训练、仿真回放和正式导出都通过后，再为最终那一个 ONNX 生成候选报告：

```bash
python tools/microduck_learning/check_training_lineage.py \
  --bam-contract artifacts/bam-model-hl2915-m6.json \
  --onnx-contract artifacts/onnx-contract-hl2915-candidate.json \
  --training-repo /home/<user>/microduck_rl \
  --purpose candidate \
  --json-out artifacts/training-lineage-hl2915-candidate.json
```

训练仓库有未提交改动、任一文件哈希不符、BAM 不是 `measured`，都会阻止最终验收；
即使候选报告通过，也还要先仿真回放和吊装真机测试。

PowerShell 入口的实际训练必须在 WSL2/Linux 执行；Windows 只做 dry-run：

```powershell
pwsh -File tools/microduck_learning/setup_simulation.ps1 `
  -Mode Smoke `
  -TrainingDir /home/<user>/microduck_rl `
  -BamJsonPath /绝对路径/artifacts/bam/hl2915-m6.json `
  -BamActuator hl2915 -BamModel m6
```

这一步只证明“自定义执行器 JSON 能被环境加载并完成 step”，不证明 HL-2915 已经适合行走。
仍然必须先完成单舵机辨识、MJCF 质量/限位修改、完整训练和 ONNX 合同检查。

不要在 PowerShell 里把 `bash tools/microduck_learning/run_5_iteration_smoke.sh` 当成正式训练入口：
Windows 的 `wsl.exe` 启动提示可能以 UTF-16 乱码混入日志。进入 Ubuntu/WSL 终端后，在 Linux 文件系统中的
训练 checkout 内执行同一命令；PowerShell 只用于 `setup_simulation.ps1 -DryRun`，查看将要执行的命令。
同理，`MICRODUCK_BAM_JSON` 要在 WSL 内用 Linux 路径设置，例如
`export MICRODUCK_BAM_JSON=/mnt/f/microduck/artifacts/bam/hl2915-m6.json`；不要在 PowerShell
里设置 `F:\...` 后再期待 `wsl.exe` 自动转换并传递变量。

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

注意：上游 `scripts/infer_policy.py` 当前导入 POSIX 专用的 `termios`。因此原生 Windows
只能把 `-DryRun` 当作路径检查；实际 `Inference` 和 `Smoke` 运行必须在 Linux、macOS
或 WSL2 中完成。不要为了让 Windows 命令“变绿”而修改上游训练代码。WSL 中使用
同样的 `uv run ...` 命令，继续使用上面的退出码、NaN 和 `obs[1,61] → actions[1,14]`
形状作为验收标准。

WSL 请把训练 checkout 放在 Linux 文件系统（例如 `/home/<user>/microduck_rl`），不要
放在 `/mnt/f/...`；后者在同步大型 CUDA/PyTorch 依赖时可能卡住。以下命令会执行上游
`uv sync`、CLI 探针和同一组 5 次迭代 CPU smoke 参数；本仓库开发机已在固定 commit 上
完成一次 WSL CPU smoke，仍需在你的机器上重跑并保存自己的日志：

本次验证还观察到：在 `/mnt/f` 共享盘上同一命令可能因文件 I/O 超时；这不是训练失败的
证据。若长时间没有日志，停止该进程，把 checkout 放到 WSL 的 `/home/...` 或 `/tmp/...`
后重跑，并确保一次只运行一份 smoke。

```bash
git clone https://github.com/pollen-robotics/microduck_rl "$HOME/microduck_rl"
cd "$HOME/microduck_rl"
git checkout --detach 29e887ecfbf5d37144759e5a9f8a176dfb83d547
uv sync
uv run scripts/infer_policy.py --help
uv run train Mjlab-Velocity-Flat-MicroDuck \
  --gpu-ids None \
  --env.scene.num-envs 8 \
  --agent.num-steps-per-env 24 \
  --agent.max-iterations 5 \
  --agent.logger tensorboard \
  --agent.upload-model False \
  --agent.run-name lesson-01-repro
```

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

### Windows/WSL 常见卡点：`.venv` 无效或训练目录有改动

如果 `uv run ...` 提示类似“`.venv` 不是有效 Python 环境”，或者启动器提示训练仓库有未提交修改，
不要删除 `.venv`、不要 `git reset`、也不要在这个目录上强行切换 commit。训练 checkout 属于独立资料，
里面的改动可能是用户自己的。

最安全的做法是在 WSL 的 Linux 文件系统里新建一个干净副本：

```bash
mkdir -p ~/microduck-work
cd ~/microduck-work
git clone https://github.com/pollen-robotics/microduck_rl.git microduck_rl_clean
cd microduck_rl_clean
git checkout --detach 29e887ecfbf5d37144759e5a9f8a176dfb83d547
uv sync
uv run scripts/infer_policy.py --help
```

然后把训练入口指向这个新目录；原来的 Windows 目录保留不动。若已有一个干净的 WSL checkout，
直接使用它即可。`/mnt/f/...` 共享盘只适合传递小文件和日志，正式训练优先放在 `~/microduck-work`，
以免跨文件系统 I/O 变慢或超时。

