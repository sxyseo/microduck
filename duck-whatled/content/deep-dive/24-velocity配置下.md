# 解读 24 · velocity 配置(下):reward 与终止

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py` 第 639–950 行
> **需要的前置**:[解读 23](23-velocity配置中.md);curriculum(课程)= 随训练步数自动改参数的钩子

先纠正一个预期:本范围的主菜其实是**命令 + 奖励 + 课程 + RL 超参**;velocity 环境唯二
追加的终止项 `nan_state` 定义在 385–389 行(前一讲的区间),用 `robot_state_is_nan`
在物理数值爆炸时立即重置,防止 NaN 进入观测污染网络权重。

## 命令:固定范围 + 原地转桶

643–646 行 deepcopy 出 `twist` 命令(注释:其他环境会原地改 `commands["twist"]`,必须拷贝),
设 `rel_standing_envs=0.02`、`rel_heading_envs=0.0`。651–653 行是本任务最重要的三个数字:
`lin_vel_x ±0.4`、`lin_vel_y ±0.3`、`ang_vel_z ±1.0`,且**不做范围课程**——注释说试过放宽到
ang ±2.0,反而"超越机器人能力",千步之后奖励和回合长度一起掉。655–657 行把命令换成自研
`VelocityCommandCommandOnlyCfg` 并设 `rel_turn_in_place_envs = TURN_IN_PLACE_FRACTION`(0.15)。

669–692 行定义两组位姿命令:`head_pose` 是 4 维颈部/头部关节角增量(初始 ±0.05/±0.05/
±0.07/±0.015),`body_pose` 是 6 维躯干位姿增量(初始 ±0.005 m / ±0.05 rad);696–704 行把
这两组命令作为观测项 `head_command`(4)+`body_command`(6) 追加进 actor 与 critic——
至此 actor 观测凑满 61 维(3+3+14+14+14+3+4+6)。

## 奖励:谁在教什么

- `head_pose_tracking` 权重 2.0、std 0.5(713–717 行):头部跟踪是本环境**主目标**;注释算了
  一笔账——满偏 1.0 rad 时 `exp(-4)≈0.018`,梯度小而不死,课程放大范围不至断粮;
- `body_pose_tracking` 权重 0.0(720–730 行):管线保留、目标关闭,观测槽位活着;
- `head_pose_bias` 权重 0.0 起步(744–748 行):733–743 行的注释是一篇 mini 论文——头部占
  整机质量 38%,走路必然晃,收紧瞬时容差会让"站着不动"成为最优(实测 run 5yay13u4 三百
  迭代后停止行走),所以只惩罚**可逃逸的直流偏垂**(EMA 后取 L1);
- 地形分支(750–777 行):rough 时换 `MICRODUCK_ROUGH_TERRAINS_CFG`,并把 `nconmax`
  从 35 提到 200、solver iterations 10→30、ls_iterations 20→50——全是 NaN 事故换来的数字。

## 课程:六个时间表

781–910 行一口气注册七门课,全部走 `CurriculumTermCfg` + 自研函数(实现见
[解读 26](26-奖励函数库.md)):`action_rate_weight` 从 -0.1 起步,在 500/750/1000/1250/1500 迭代(×24 步/迭代)五档收紧到
-1.0(785–792 行);`standing_envs` 0.02→0.25(802–808 行);`head_pose_range`
五档放大到每关节机械极限的 ~90%(825–829 行);`body_pose_range` 单档保持小(840–849 行);
`com_range` 封顶 ±15 mm(866–869 行,注释:±30 mm 会超出脚底支撑多边形,后向平衡无法训练);
`head_pose_bias_weight` 0→1→2→3(903–908 行,600 迭代后才启动——步态没成型前谈姿态是干扰)。
891–893 行删掉用不上的 `terrain_levels`(flat)与 `command_vel`。

## 收尾:MicroduckRlCfg

915–952 行用 `RslRlOnPolicyRunnerCfg` 定义 PPO 超参:actor/critic 隐层 `(512, 256, 128)`、
elu、`obs_normalization=True`;`clip_param=0.2`、`entropy_coef=0.01`、`learning_rate=1.0e-3`
(adaptive,`desired_kl=0.01`)、`gamma=0.99`、`lam=0.95`;`num_steps_per_env=24`、
`max_iterations=50_000`、`save_interval=250`;`symmetry_cfg=SYMMETRY_CFG if ENABLE_SYMMETRY
else None`(944 行,呼应 28 行的总开关)。

## 你带走的收获

- **reward 权重是调出来的,不是设出来的**:每个权重旁边都有失败 run 的编号和代价估算。
- **课程表 = 时间轴上的参数曲线**,写成分档 dict 比隐式公式可审计得多。
- 固定指令范围+专项数据桶(turn-in-place)优于盲目放宽范围。
- 权重 0 ≠ 删除:保留管线让别的任务(standup)只改权重即可复用。

## 延伸

- 课程函数与奖励函数的实现:[解读 26](26-奖励函数库.md);
- 命令类 `VelocityCommandCommandOnly` 的重采样逻辑:[解读 26](26-奖励函数库.md);
- 本地路径:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py`
