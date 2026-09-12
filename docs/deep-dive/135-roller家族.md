# 解读 135 · roller 家族四配置

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/` 下 roller 四文件(velocity_rollers 669 行 / roller_crouch 479 行 / roller_slope 246 行 / roller_standup 551 行)
> **需要的前置**:[解读 21](21-任务注册表.md)(注册名)、[解读 22](22-velocity配置上.md)

## 基座:velocity_rollers(穿轮滑鞋滑行)

`make_microduck_velocity_rollers_env_cfg()`(:85)是家族共同祖先:14 个主动关节 + 每刀 2 个被动轮(**穿插**在关节序里,一切按名字解析),obs 统一 61D——head/body 槽 zero-padding(:532-538),critic 独享 4 轮轮速(:523-528)。语义重定义:cmd_x 的 0=滑行、>0=蹬、<0=刹车(:546-547);**唯一的正任务奖励是 `wheel_speed`**(权重 10.0,vel_scale 0.3,:253-257)——轮子不转什么都没有。风格由小项塑形:glide 4.0(单刀滑行)压过 skating_air_time 1.5(抬脚频率),single_support 3.0(反 swizzle)、feet_flat -2.0(只门支撑脚,:203-210)、`action_over_limit` -0.5(惩罚把命令推过硬限位 +0.3 裕量——部署管线不 clip,威慑必须烤进网络,:226-230)。轮轴承摩擦从 0 由课程爬到 0.0015(2000/3500/5000 迭代,:585-596);`entropy_coef=0.03` 比走路环境高(:652)。

## 三个衍生:同一套机器人,三种任务

**roller_crouch**(注册 `Mjlab-RollerCrouch-Flat-MicroDuck`):一次性"下蹲滑行"技能,挂在运行时的 ground-pick 槽上。命令换成 `GroundPickPhaseCommandCfg`(period 5.0、randomize_phase=False,:388-395),相位四段 0.10/0.50/0.60(:50-53);奖励核心 `crouch_glide_pose`(6.0,std 0.4)+ L1 引导(2.0),在 `STAND_POSE` 与 `CROUCH_POSE` 间按相位插值——两个姿态都是**从真机器人上读回来的**(:63-88);开局注入 `ENTRY_VELOCITY_X=(0.2,0.5)` 的前进速度(:42,:256)保住滑行惯性。

**roller_slope**(注册 `Mjlab-RollerSlope-Flat-MicroDuck`):被动下坡平衡。twist 全零 + `rel_standing_envs=1.0`(:100-107);删光滑冰奖励,只留 upright(3.0,自由平衡不给固定姿势)、alive(1.0)、`wheel_glide`(2.0,cap 0.35——奖励滚、不奖励蹬)、heading_hold(1.5);NaN 用 `nan_policy="sanitize"` 消毒(:200-201);课程只剩 `terrain_levels_slope`(:219-221),坡度 2°→20° 随难度插值(见 [解读 136](136-slope地形.md))。

**roller_standup**(注册 `Mjlab-RollerStandUp-Flat-MicroDuck`):轮滑版起身。关节索引重映射 `_LEG_JOINTS=[0–4,11–15]`(轮子穿插所致,:109-111);高度三层 `height_stand` 4.0(std 0.04)/ 4.0(std 0.015)/ L1 30.0,target 0.138 m(:201-226);`gentle_rise` 权重是**正的 +0.02**——`trunk_vertical_accel_penalty` 自带负号,旧负权重构成双重否定、实际在奖励暴烈起身(:244-262,run vweolw91 实测该项曾为正贡献)。最独特的是**倒置的轮摩擦课程**:0.05→0.0015 分五档下降(1000/2000/3000/4000 迭代,:449-462)——先让轮子近似"脚"来 bootstrap,再放开真物理;注释提醒只有最后一级之后的 checkpoint 才有 sim2real 资格。

## 你带走的收获

- 家族式配置 = 一个基座 + 三张"删除清单":每个衍生文件的开头都在删基座奖励。
- 唯一正奖励是任务语义的锚(wheel_speed),其余全是塑形与罚则——读配置先找正项。
- 部署不 clip,就把过冲威慑做成策略内的惩罚项:训练/部署一致性优先。
- 课程可以反向:物理从易到难不一定指参数变大,"逐步放开一个自由度"(摩擦、站姿)同样成立。

## 延伸

- swizzle 衍生精读:[解读 134](134-swizzle精读.md);坡地生成:[解读 136](136-slope地形.md)
- 摔倒恢复的走路版:[解读 133](133-velstand精读.md)
- 基座文件:`.../tasks/microduck_velocity_rollers_env_cfg.py`
