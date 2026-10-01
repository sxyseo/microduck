# 解读 60 · testbench:仿真-实物对照台

> **解读对象**:`microduck-replica/upstream/microduck_rl/scripts/testbench_sim2real.py`(611 行)与 `scripts/validate_bam_testbench.py`(277 行),交叉引用 `robot/testbench_constants.py`
> **需要的前置**:[解读 56](56-M1到M6.md)(模型从哪来) · [解读 57](57-辨识进仿真.md)(模型怎么进仿真)

辨识出的 BAM 参数到底准不准?这两个脚本给出可执行的答案:**让同一个 ONNX 策略(或同一条轨迹)分别在仿真和实物上跑,逐点对齐位置曲线,算 MAE**。整机走路之前,先在单舵机台架上把"仿真=实物"这件事量出来。

## testbench_sim2real.py:同一策略,两个世界

骨架是三个 rollout 函数加一个对比器:

- `make_target_schedule()`:生成确定性目标序列——每 4 s 在 ±80°(`MAX_ANGLE = math.radians(80.0)`)随机取一个角度,同一 `--seed` 仿真和实物拿到**同一条**轨迹;
- `rollout_sim_bam()`:轻量路径——`bam.MujocoController` + `bam/models["m6"]` 驱动,`VIN = 7.4`、`KP_FW = 200.0`,200 Hz 记录(`SIM_DT = 0.005`);`rollout_sim_mjlab()` 则启动真正的 mjlab 训练环境(`make_testbench_env_cfg()`),和策略训练用的执行器完全一致;
- `rollout_real()`:实物路径——`rustypot` 的 `Xl330PyController` 接真实 XL330(`--motor-id 1`、波特率默认 1_000_000),写 `position_p_gain` 后**回读确认**(注释:固件会静默钳位越界值);速度原始 tick 按常数 `DXL_VEL_TICK_TO_RAD_S ≈ 0.024 rad/s` 换算,读不到就差分兜底;
- `compare_and_plot()`:`MAE q (sim vs real)` + 四联图(位置/跟踪误差/速度/策略动作),`npz_to_bam_log()` 还能把 .npz 转回 BAM 日志格式,喂给 `bam.plot` 复用整条辨识工具链。

工作流写在文件头注释:sim 记 `sim.npz` → 实物记 `real.npz` → `--compare` 出对比图。

## validate_bam_testbench.py:验执行器内核本身

第二个脚本不跑策略,而是**回放真实台架录制**:把每条实测轨迹喂进 `mujoco_rollout()`——用 `compute_m6_friction()`(与 `bam/model.py` 同式的 M6 摩擦)一步步复现"固件 PD → 电压 → 电机力矩 → 摩擦裁剪"链路(`ERROR_GAIN = (4096/2π)/(256·885)` 是 XL330 固件的位置误差→PWM 增益),同时以 BAM 自家 Python 仿真器 `bam_python_rollout()` 作参照。输出三个数:`MAE bam_vs_real / mj_vs_real / bam_vs_mj`,判定逻辑写在 `main()`:`avg_diff > 0.01` → "BAM 和 MuJoCo 显著分叉,内核可能有 bug";三数接近 → 内核正确。

## 这套对照台在流程里的位置

台架硬件见 [解读 55](55-单摆台架.md)(120 g 负载,`TESTBENCH_ARM_MASS = 0.12`);换舵机重训全流程的测试金字塔里,它就是 **L2 仿真评估**的量尺:换 HL-1910 后,先用新辨识的 JSON 在台架上跑通"仿真-实物 MAE 可接受",再谈整机。策略级的验收(L3 的五指标、L5 吊装)是它的下游。

## 你带走的收获

- **"辨识对不对"必须变成一个数**:同轨迹同种子、MAE 对齐——验证设计成可重复实验,而不是"看着挺像"。
- 对照要三方:实物、你的仿真内核、官方参考实现(BAM Python 仿真器),两两比才能定位分歧在哪边。
- 实物路径的工程细节决定数据质量:增益写后回读、速度 tick 换算常数、差分兜底、200 Hz 定时采样。
- 轻量后端(bam+MuJoCo)和完整后端(mjlab)各留一条:一个跑得快,一个与训练零偏差,`--sim-backend` 一键切换。
- 先单舵机后整机:台架上的 MAE 是整机 sim2real 的先行指标。

## 延伸

- [解读 55](55-单摆台架.md):台架物理设计 · [解读 57](57-辨识进仿真.md):参数写回
- [解读 58](58-为什么必须重训.md):重训后的测试金字塔
- `microduck-replica/upstream/microduck_rl/scripts/testbench_sim2real.py`(三 rollout + 对比器)
- `microduck-replica/upstream/microduck_rl/scripts/validate_bam_testbench.py`(M6 内核验证)
- `microduck-replica/upstream/microduck_rl/src/mjlab_microduck/robot/testbench_constants.py`(台架实体配置)
