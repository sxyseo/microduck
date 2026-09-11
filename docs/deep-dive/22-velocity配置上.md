# 解读 22 · velocity 配置(上):前 87 行的开关与范围

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py` 第 1–87 行(全文件 952 行)
> **需要的前置**:[解读 21](21-任务注册表.md)(谁调用这个文件);域随机化(DR)= 训练时故意扰动物理参数让策略更皮实

读一个大配置文件,别从 `make_microduck_velocity_env_cfg()` 函数体开始——作者把所有
"总开关"和"随机化范围"提成模块级常量放在最前面,前 87 行就是整份训练的**声明式摘要**。

## 模块 docstring:一份变更日志

第 1–17 行的 docstring 不是客套话,它直接给出了几条关键设计决定及其理由:
`foot_slip` 保持 -0.1(更强会限制这只机器人"以原地转为核心"的转向方式)、指令范围
固定不放宽(ang ±1.0 让转向可学)、15% 环境强制原地转(2026-07 审计:独立均匀采样下
原地转只占约 2% 数据,等于没训)、`body_pose` 追踪保留观测槽位但权重为 0。

## 开关区(第 22–53 行):True/False 就是实验记录

`NUM_STEPS_PER_ENV = 24`(22 行)、`TURN_IN_PLACE_FRACTION = 0.15`(25 行)、
`ENABLE_SYMMETRY = False`(28 行)之后,31–42 行是 12 个 DR 开关,每个都带一行注释说明
历史或理由。最值得学的是"注释即实验日志"的写法:

- `ENABLE_KP_RANDOMIZATION = False # Was True`(33 行)——增益随机化被关掉,但保留痕迹;
- `ENABLE_JOINT_FRICTION_RANDOMIZATION = True`(36 行)注明它是通过
  `FrictionDRBamActuator.friction_scale` 缩放 BAM 摩擦预算(BAM = 执行器摩擦模型);
- `ENABLE_VELOCITY_PUSHES = True`(39 行)、`ENABLE_ENCODER_BIAS = True`(41 行,
  编码器偏置只进 actor 观测)。

## 范围区(第 55–87 行):数字后面全有出处

- `COM_RANDOMIZATION_RANGE = 0.003`(57 行,±3 mm):注意 57 行注释说"课程升到 ±8 mm",
  但下方真正的课程表(855–872 行)末段是 0.015(±15 mm,2026-07 审计封顶)——**注释滞后于
  代码**,读配置要以课程表为准;
- `HEAD_BODY_NAMES`(66–72 行)列出头部 5 个 body,注释坦白 `bearing_roll` 是"一直
  列错了、为保持 DR 行为不变而保留"的右髋 link;
- `MASS_INERTIA_RANDOMIZATION_RANGE = (0.95, 1.05)`(73 行):质量与惯量**一起**缩放 ±5%;
- `VELOCITY_PUSH_RANGE = (-0.3, 0.3)`(80 行)注释很长:曾是 ±0.5,比最大步速 0.4 还大的
  加性踢腿让策略学成"永久紧张的摔倒恢复步态",2026-07 审计降到 ±0.3;
- `IMU_ORIENTATION_RANDOMIZATION_ANGLE = 6.0`(84 行):零中心随机轴,训练对**错装幅度**
  的容忍;真机 ~5° 的系统性俯仰偏差在运行时修正,不在这里;
- `ENCODER_BIAS_RANGE = (-0.015, 0.015)`(85 行,±0.86°)、
  `BASE_ORIENTATION_MAX_PITCH_DEG = 10.0` / `ROLL = 5.0`(86–87 行,开关却是 False)。

## 你带走的收获

- **先读常量区再读函数体**:开关+范围是配置文件的 API,函数体只是把它们接线。
- **每个魔法数字配一行"为什么"**,包括被否决的旧值(`Was True`、`Was ±0.5`),半年后还能复盘。
- **注释也会撒谎**(±8 mm vs 课程表 ±15 mm):关键数值要向下追溯到真正生效的那一段。
- 随机化范围是"保守起步、课程放大"的:`0.003` 起步,由 curriculum 逐段抬升。

## 延伸

- 这些常量如何被消费:[解读 23](23-velocity配置中.md)(动作/观测接线)、[解读 24](24-velocity配置下.md)(课程表本体);
- 事件(event)与经理(manager)机制的函数实现:[解读 26](26-奖励函数库.md);
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py`
