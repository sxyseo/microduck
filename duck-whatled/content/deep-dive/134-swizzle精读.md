# 解读 134 · swizzle 配置精读

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_swizzle_env_cfg.py`(198 行)
> **需要的前置**:[解读 135](135-roller家族.md)(roller 基座)、[解读 132](132-velocity课程.md)(课程手法)

## 做减法得到的新技能

swizzle(双刀贴地、双腿对称开合的"葫芦"滑法)不是从零写的:`make_microduck_velocity_swizzle_env_cfg()`(:34)先整体拿过 stride 版 roller 环境(:37),然后**删掉五个反 swizzle 项**——`_ANTI_SWIZZLE = (single_support, glide, skating_air_time, gait_symmetry, hip_roll_neutral)`(:31),正是基座里塑造"交替蹬步"的那组力——再加两块新奖励:`leg_symmetry`(权重 2.0,双腿互为镜像,:44-48)与 `grounded`(权重 1.0,双刀贴地,:50-54)。模块 docstring 交代了前提:基座 roller 配方天然收敛到 swizzle,所以只需拆掉围栏。

## 三组改造

**倒滑**:基座里 cmd_x<0 是刹车;这里 `wheel_speed` 打开 `bidirectional=True`、删掉 `braking`、命令范围对称成 (-0.6, 0.6)(:61-64)——负命令变成"倒着滑",想停就给 0,`grounded` 用 |cmd_x| 双向都把刀按在地上。

**航向两阶段**:基座为直线上滑禁了转向;这里把 ang_vel_z 范围重开到 ±0.5(:77,注释记录 ±1.0 训出的策略转向过猛,真机要用 `--max-angular-vel 0.3` 驯服),然后课程把 `heading_hold`(保持直行,1.0)与 `heading_tracking`(跟踪航向,0)在 1000/1750/2500 迭代交换主导权(:85-108)——先滑直,再学指哪滑哪。

**头部控制后挂**:头部命令与观测槽接入(:114-130),但 `head_pose_tracking` 从 0 起步、1500 迭代(swizzle 成形)后才爬到 4.0(:161-172),命令范围同步扩到与 velocity 环相同的终值 ±1.10/±1.40/±0.31(:176-188)。为了让头只听命令,还要拆掉两个"回家拉力":删 `neck_joint_pos_l2`(:142-143),pose 奖励的 std 表滤掉 neck/head、asset_cfg 限定腿关节(:146-157)。

文件尾一行值得看:`MicroduckSwizzleRlCfg = dataclasses.replace(MicroduckRollersRlCfg, experiment_name="velocity_swizzle", run_name=...)`(:194-198)——PPO 超参原样继承,只换实验名。注册名 `Mjlab-Velocity-Swizzle-MicroDuck`。

## 你带走的收获

- 新技能环境可以只是旧环境的"删除清单 + 两个奖励":先找到塑造旧行为的那组项,再拆。
- 交换两个奖励的主导权(航向 hold→track)是两阶段教学的通用形式,比硬调一个权重可解释。
- 引入命令跟踪前,必须清掉同一自由度上的既有拉力(颈部回 HOME),否则策略只听强的那个。
- `dataclasses.replace` 复制 runner 配置:家族内所有任务共享一套 PPO 底座。

## 延伸

- 基座四配置总览:[解读 135](135-roller家族.md);坡地生成:[解读 136](136-slope地形.md)
- 任务注册表与 `Mjlab-Velocity-Swizzle-MicroDuck`:[解读 21](21-任务注册表.md)
- 本文件:`.../tasks/microduck_velocity_swizzle_env_cfg.py`
