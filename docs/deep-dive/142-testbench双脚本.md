# 解读 142 · testbench 双脚本函数级

> **解读对象**:`microduck-replica/upstream/microduck_rl/scripts/testbench_sim2real.py`(611 行)+ `scripts/validate_bam_testbench.py`(277 行),函数级全走
> **需要的前置**:[解读 60](60-testbench验证.md)(导览:双脚本在验证流程的位置)、[解读 56](56-M1到M6.md)(M6 六参数)

导览(60 篇)讲了动机;本篇逐函数下钻。`testbench_sim2real.py` 验**策略**(同一 ONNX 跑两世界),`validate_bam_testbench.py` 验**执行器内核**(同一实测轨迹喂两个仿真器)。

## 底盘(testbench_sim2real.py:39-96)

`CONTROL_DT = 0.02`(50 Hz = decimation 4 × 0.005)、`SIM_DT = 0.005`(200 Hz)、`DXL_VEL_TICK_TO_RAD_S = 0.229·2π/60`(:47;速度原始 tick,每 tick = 0.229 RPM)。`make_target_schedule`(:55-71)用种子化 rng 每 4 秒在 ±80° 采一个新目标;同一 seed 保证两世界**同一条**轨迹。`PolicyRunner`(:74-96)是薄包装:`step`(:87-96)拼 4 维观测 `[q - DEFAULT_POS, qd, last_action, target]`(:90-93),缓存 `last_action`(:95),返回 `DEFAULT_POS + action·action_scale`。

## 两个仿真后端(104-291)

`rollout_sim_bam`(:104-210):200 Hz、无 torch,但执行器非训练时那份(:105-109)。载入 xl330 的 m6 json(:118-121),设 `VIN = 7.4`、`KP_FW = 200.0`(:123-124)。细节(:143-155):position actuator 转 motor(`act.set_to_motor()`,限幅 `±VIN·kt/R`),铰链 damping/frictionloss 清零——摩擦归 BAM 管。主循环(:183-208)外层 50 Hz、内层 `decim=4`:每内步先 200 Hz 记录六元组,再 `set_q_target` + `update()`(写力矩、推摩擦进 dof)+ `mj_step`。

`rollout_sim_mjlab`(:213-291)用**真正的**训练环境:`resampling_time_range = (1e6, 1e6)`(:232)关自动重采样、`enable_corruption = False`(:236)公平对照,每拍写 `cmd_term._target[0, 0]` 注入目标(:258)。讲究处在 `observation_manager.compute(update_history=True)`(:262):joint_vel 观测带 1 拍延迟,历史缓冲必须每拍推进,否则速度陈旧。再手动复刻 decimation 循环(:272-288)以 200 Hz 采样。

## 实物路径与分析器(299-533)

`rollout_real`(:299-413)先配舵机(position 模式、P=kp、I/D=0)并**回读确认**(:322-325,固件会静默钳位)。主循环(:349-409)每 20 ms 开头读一次、跑一次、写一次;速度读失败用 `(q - prev_q) / CONTROL_DT` 差分兜底(:357-358);deadline 定时凑足 200 Hz(:376-379);结束关扭矩(:412)。注意 :362 有行被注释掉的 `np.clip`——策略输出限幅被有意放开。分析侧:`_mae`(:421);`npz_to_bam_log`(:426-472)把 .npz 转回 BAM 日志格式(load/temp 为占位,dt 取实测均值(:441)),喂 `bam.plot`;`compare_and_plot`(:475-533)出四联图。`main`(:541-607)分派 `--compare`/`--to-bam`/rollout 三模式。

## validate_bam_testbench.py:内核的三方对质

模块头(:22-41)钉死路径与固件常数:`ERROR_GAIN = (4096/2π)/(256·885)`(:39,位置误差→PWM 增益)、`VIN = 7.4`。`bam_python_rollout`(:44-58)调 BAM 官方 `Simulator.rollout_log(simulate_control=True)` 当参照。`compute_m6_friction`(:61-83)复刻 M6 摩擦:stribeck 项(:64)、两路负载摩擦(:66-73)、`friction_base`+粘性阻尼,合成 `friction_budget`;二次项被注释跳过(:79)。

`mujoco_rollout`(:86-178)是核心,每 entry 走六步链:①`duty = clip(误差·kp·ERROR_GAIN, ±1)`,电压 = VIN·duty(:151-153);②电机力矩 `kt·V/R − kt²·dq/R`(:156);③外力矩取 `-qfrc_bias`(:161,符号约定相反);④摩擦预算(:164);⑤静摩擦裁剪 `min(|τ_stop|, budget)`(:167-171);⑥`ctrl = motor + friction`(:174,bias 由 MuJoCo 加回)。arm 质量/惯量按日志缩放(:112-120)。`main`(:181-273)对每条录音算三个 MAE(bam_vs_real / mj_vs_real / bam_vs_mj),判定(:241-246):`avg_diff > 0.01` 即内核有 bug;`avg_mj > 1.5×avg_bam` 即动力学差异;否则 ✓。

## 你带走的收获

- 对照的前提被代码化:同 seed 目标序列+一致观测与 50/200 Hz 节拍,差一项 MAE 不可信。
- 实物数据质量在细节:增益回读、tick 换算、差分兜底、deadline 定时采样。
- 内核验证要三方对质(你的实现/官方参考/实物),两两 MAE 定位分歧。
- `npz_to_bam_log` 让产物回流辨识工具链,而非一次性图片。

## 延伸

- 导览与流程位置:[解读 60](60-testbench验证.md);台架物理:[解读 55](55-单摆台架.md);M6 参数含义:[解读 56](56-M1到M6.md)
- 训练配置:[解读 137](137-testbench配置.md);参数写回:[解读 57](57-辨识进仿真.md)
- 本地路径:`microduck-replica/upstream/microduck_rl/scripts/testbench_sim2real.py`、`scripts/validate_bam_testbench.py`
