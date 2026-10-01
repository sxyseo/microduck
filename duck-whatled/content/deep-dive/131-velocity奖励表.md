# 解读 131 · velocity reward 表逐项

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py`(952 行;奖励集中在 275–362 行与 639–748 行)
> **需要的前置**:[解读 24](24-velocity配置下.md)(reward 骨架)、[解读 26](26-奖励函数库.md)(mdp.py 实现)

## 跟踪层:策略靠什么挣钱

velocity 环的奖励主体在 `make_microduck_velocity_env_cfg()` 内两处。基础栈(275–362 行)直接改写 mjlab 模板:

| 项 | 权重 | 出处与要点 |
|---|---|---|
| track_linear_velocity | 2.0 | std=√0.1(:346) |
| track_angular_velocity | 2.0 | std=√0.5(:348);ang ±1.0 才让转弯可学(:649-650) |
| air_time | 3.0 | 窗口 [0.04, 0.300] s(:333-339),0.04 是给"真抬脚"付钱 |
| pose | 1.0 | 只评腿关节(:285-287),头归 head_pose_tracking 管 |
| upright | 2.0 | std=√0.05,专治 +2–4° 前倾(:293-301) |
| foot_slip | -0.1 | 故意弱:强了压制 pivot 转身(:312-315) |
| self_collisions | -1.0 | 腿别撞电池仓(:323-327) |

## 命令层:639–748 行的三件套

这一段定义"奖励指向的命令"。twist 命令范围**固定不扩**:lin_x (-0.4,0.4)、lin_y (-0.3,0.3)、ang (-1.0,1.0)(:651-653);另留 15% 环境原地转圈(`TURN_IN_PLACE_FRACTION=0.15`,:25 与 :657)。head_pose 命令 4 维,起步范围很小(颈/头俯仰 ±0.05、头偏航 ±0.07、头滚转 ±0.015,:669-677)。奖励三件套:

- `head_pose_tracking`,权重 2.0、std 0.5(:713-717):满量程 ±1.0 rad 命令下不跟踪也有 exp(-4)≈0.018 的非零梯度,4 关节取均值,部分跟踪得部分分。
- `body_pose_tracking`,权重 0.0(:720-730):基础设施留着、obs 槽活着,但本任务不出钱——standup 环境会抬这个权重。
- `head_pose_bias`,权重 0.0 起步(:744-748):2026-08-20 的"点头修复"。实测策略顶着 14.6° 低头偏差走路;把 std 收紧到 0.1 的尝试让策略 300 迭代就干脆不走了——瞬时紧公差对走路是每步 0.77 的**不可逃脱**税(280 g 的头走路必振荡),而 DC 偏置是可消除的,只对它收 L1(:732-743)。

## 罚则的爬坡与 PPO 底座

`action_rate_l2` 起步 -0.1(:352),由课程每 250 迭代一档爬到 -1.0(:781-794)——先让步态诞生,再收紧平滑。rough 地形把 `nconmax` 35→200、solver iterations 10→30、ls_iterations 20→50(:765-772),防接触溢出的 NaN。文件尾的 `MicroduckRlCfg`(:915-952)是训练底座:MLP (512,256,128)、学习率 1e-3 自适应、gamma 0.99、entropy 0.01、`num_steps_per_env=24`、`save_interval=250`、`max_iterations=50_000`。

## 你带走的收获

- 奖励表几乎每项都挂着失败运行的注释:权重不是调出来的,是**事故报告**堆出来的。
- 分工要干净:腿的 pose 与头的 head_pose_tracking 各管一摊,混管时梯度强的那个会吃掉命令。
- 惩罚的"可逃脱性"决定符号:对振荡收税是逼停走路,对偏置收税是逼正姿势。
- std 决定高斯奖励的工作距离:速度容差 √0.1、头部容差 0.5,各自匹配该项的物理可达性。

## 延伸

- 这张表的课程引擎:[解读 132](132-velocity课程.md);函数实现在 `tasks/mdp.py`,见 [解读 26](26-奖励函数库.md)
- 同文件上半部(开关与观测):[解读 22](22-velocity配置上.md)、[解读 23](23-velocity配置中.md)
