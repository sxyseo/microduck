# 解读 130 · infer_policy.py 主流程

> **解读对象**:`microduck-replica/upstream/microduck_rl/scripts/infer_policy.py`(1524 行)
> **需要的前置**:[解读 02](02-观测拼装.md)(真机 61 维)、[解读 23](23-velocity配置中.md)(训练侧观测)、[解读 32](32-导出与回放.md)

## 在做什么

这是部署前的"彩排":把 ONNX 策略放进 CPU 版 MuJoCo 里回放。`main()`(:896)解析参数、选场景 XML(默认 `scene.xml`,:21)、构建 `PolicyInference`(:211),然后进主循环:策略 50 Hz(decimation=4,:1149),每拍读一次终端按键、跑一次 `infer()`、`apply_action()`,物理走 4 个 0.005 s 子步。按键从终端读而不是从 viewer 窗口读——viewer 的按键会触发内置可视化快捷键,所以有专门的 `TerminalInput`(:143)在后台线程以 cbreak 模式收键。

## 61 维观测怎么拼

`get_observations()`(:655)按固定顺序拼接:

| 段 | 维度 | 来源 |
|---|---|---|
| base_ang_vel | 3 | `imu_ang_vel` 传感器 |
| projected_gravity(默认)或 raw_accelerometer | 3 | 四元数旋转重力 / 加速度计取反归一 |
| joint_pos | 14 | 当前值减 `DEFAULT_POSE`(:646) |
| joint_vel | 14 | qvel |
| last_action | 14 | 上一次网络输出 |
| command | 13(旧模式 3) | `_update_command()`(:460) |

3+3+14×3+13 = **61**;旧策略(命令 3 维)是 51。`main()` 开跑前先试拼一次核对维度(:1107-1120)。14 不是写死的:`joint_qpos_indices`(:389)从 `actuator_trnid` 反查每个执行器的关节 qpos 地址,roller 模型的 4 个被动轮穿插在关节序列里也能正确抽取。13 维命令槽布局是 `[twist(3), head(4), body(6)]`;sitstand 策略把 twist[0] 当坐/站旗标(:484-488);踢球/前滚翻等一次性技能要求**全零 13 维命令**(:474-479)——喂别的就是分布外输入。走路/站立双策略按命令幅值 0.05 的阈值自动切换(:514-533)。

## BAM 加载与执行器

策略在 warp 里对着 BAM M6 电压模型训练,回放就得装同一个执行器。常量区(:33-45)声明必须镜像 `microduck_constants.py` 的 `_BAM_ACTUATOR_KWARGS`(由 `tests/test_infer_policy_bam.py` 锁定):`BAM_KP_FW=200.0`、`BAM_VIN_RANGE=(6.5,8.2)`、`BAM_VIN_MIN=6.0`、刚性摩擦约束 `BAM_STIFF_SOLREF_FRICTION=(-5.0e4,-2.0e2)`。`load_bam_model()`(:48)加载 xl330 的 m6 模型并写入 `vin`(默认 7.4 V,2S 锂电标称);`load_mujoco_with_bam()`(:58)把 XML 位置执行器改造成电压受限的力矩电机:`force_limit = vin*kt/R`,关节 damping/frictionloss 清零交给 BAM 每步重写。主循环每个子步先 `bam_ctrl.update()`——固件 P 环、电机方程、摩擦预算都在这里发生(:1482-1489);`--no-bam` 可退回位置执行器,但会明说"这不是训练用的执行器"(:1004)。动作落地是 `DEFAULT_POSE + action*action_scale`(:865-874),`--delay MIN MAX` 用环形缓冲模拟执行器延迟(:444-458)。

## 你带走的收获

- 回放脚本的全部价值在"逐位一致":观测顺序、默认姿态(`DEFAULT_POSE`,:125)、动作缩放、执行器模型,任何一处漂移,sim2real 就静默劣化。
- 观测维度校验放在第一个控制步之前,维度错当场报警。
- 关节索引从执行器传动反查(`actuator_trnid`)而不是硬编码——被动关节穿插的模型也不怕。
- 一次性技能用"会话切换 + 定时归还"实现(:731-762),与训练时的全零命令约定配套。

## 延伸

- 真机端逐位对照:`duck-control/src/obs.rs`,见 [解读 100](100-obsrs一观测逐位.md)
- BAM 是什么:[解读 54](54-BAM是什么.md);P 键随机推撞对应训练的 push 事件:[解读 26](26-奖励函数库.md)
- 本文件:`microduck-replica/upstream/microduck_rl/scripts/infer_policy.py`
