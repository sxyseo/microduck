# 解读 23 · velocity 配置(中):动作与观测

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py` 第 193–638 行
> **需要的前置**:[解读 22](22-velocity配置上.md)(开关常量);term(项)= 挂在某个 manager 下"一个函数+参数+权重"的最小单元

`make_microduck_velocity_env_cfg(play=False, rough=False)`(193 行)不是从零写配置,而是
"取 mjlab 官方模板,再逐项改造":263 行 `cfg = make_velocity_env_cfg()` 拿到基座,266 行
把机器人换成 `MICRODUCK_WALK_ROBOT_CFG`,267 行装上三个自研传感器配置
(`feet_ground_cfg` 220 行、`self_collision_cfg` 234 行、`foot_height_scan_cfg` 246 行)。

## 动作:14 维关节位置,缩放 1.0

271–273 行把 `cfg.actions["joint_pos"]`(一个 `JointPositionActionCfg`)的 `scale` 设为
1.0——策略输出直接是目标关节位置偏移,14 个下肢与颈部关节(两条腿各 5 + 颈部 4)。623–627 行解释了为什么
观测恰好也是 14 维:`passive_*` 下颌连杆关节被正则 `^(?!passive_).*` 排除,否则观测会是
原始的 16 维,与动作维数对不上。

## 观测改造:删、换、加延迟、加噪声

这一段是全文件最能体现 sim2real 思路的部分(534–638 行):

- **删**:actor 组删掉 `base_lin_vel`(535 行,真机没有这个量)和 `height_scan`(539–540 行,
  机器人没装机身地形传感器);
- **加 privilege**:critic 组单独补回 `base_lin_vel`(543–546 行)——critic(critic=价值网络,
  只在训练时用)可以吃策略看不到的"特权信息";
- **延迟**:560–573 行给 `base_ang_vel` 与重力项 deepcopy 后设 `delay_min_lag=0`,
  `delay_max_lag=1`,`delay_update_period=64`(注释:曾为 3,真机 IMU 链路实测快,收紧到
  ±20 ms 包络);611–616 行给 `joint_vel` 固定 1 拍延迟——Dynamixel 固件的 present_velocity
  是滑动平均,天生旧一拍;
- **换函数**:598–605 行(若 `ENABLE_IMU_ORIENTATION_RANDOMIZATION`)把观测函数换成
  `base_ang_vel_imu_misaligned` / `projected_gravity_imu_misaligned`(实现见
  [解读 25](25-观测函数库.md));
- **噪声**:590–593 行,`Unoise` 即均匀噪声配置:角速度 ±0.03、重力 ±0.01、关节位置
  ±0.001、关节速度 ±0.25(注释都标了旧值 0.2/0.15/0.05/2.0——从"拍脑袋"收敛到实测);
- **防串味**:626 行 deepcopy 每个观测 term,因为 actor/critic 共享同一 term 对象,直接改
  会互相泄漏(比如下面的 `biased` 标志);633–636 行让 actor 读带偏置的关节角
  (`biased=True`),critic 读真值。

## 顺带的奖励微调与事件

同区间还夹着奖励覆盖:`pose` 权重 1.0(289 行)、`upright` 权重 2.0/std²=0.05(300–301 行,
注释给出 4° 前倾代价从 0.05→0.19/步的计算)、`foot_slip` 弱化到 -0.1(314 行)、`air_time`
权重 3.0、`threshold_min=0.04`(333–339 行)。事件区注册了 `push_robot`(398–409 行)与
一排 DR 事件(`randomize_com` 417、`randomize_head_com` 429、`randomize_mass_inertia` 465
等),实现见 [解读 26](26-奖励函数库.md)。

## 你带走的收获

- **"模板+补丁"式配置**:不复制官方配置,取 `make_velocity_env_cfg()` 再逐项覆盖,上游升级不丢。
- **观测每维都要过一遍"真机有没有"**:没有的删,有的加延迟/噪声/偏置,critic 才准吃特权。
- **共享配置对象必须 deepcopy**——actor/critic 共用 term 时,一处原地修改两边都变。
- 延迟建模精确到固件行为(1 拍 joint_vel),而不是笼统"加噪声"。

## 延伸

- 观测维数怎么凑成 61:命令项 `head_command`/`body_command` 在 [解读 24](24-velocity配置下.md) 696–704 行补齐;
- 被换上的观测函数实现:[解读 25](25-观测函数库.md);
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py`
