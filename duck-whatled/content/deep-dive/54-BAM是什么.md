# 解读 54 · BAM 是什么:执行器摩擦建模

> **解读对象**:`bam/` 仓库(本地副本,上游 [Rhoban/bam],Apache-2.0)`bam/bam/README.md`、`bam/bam/model.py`、`bam/bam/params/xl330/m6.json`
> **需要的前置**:[解读 56](56-M1到M6.md)(六个模型怎么拟合出来)

BAM = **Better Actuator Models**(Rhoban 实验室开源,作者 Marc Duclusaud 与 Grégoire Passault)。README 第一句话就说清了动机:仿真器(MuJoCo、IsaacGym)普遍只实现**库仑-黏性**摩擦模型,太简单,表达不了 Stribeck 效应、载荷相关摩擦、二次项这些真实现象——而模型精度直接影响强化学习策略能不能迁移到真机。

## 它建的不是"一个摩擦系数",是一整条链

`执行器选型.md` 对 BAM M6 的概括:BAM 是**电压级**模型——不是简单 PD,而是模拟**固件 PD → PWM → 电压 → 电流 → 力矩**的完整链路,再叠加负载相关的摩擦(库仑 + Stribeck + 载荷项)。

M6 的摩擦部分在 `model.py` 的 `compute_frictions()` 里:由 `friction_base`(基础静摩擦)、`friction_stribeck`(近零速时额外摩擦,按 `exp(-(|dq|/dtheta_stribeck)^alpha)` 的系数衰减)、`load_friction_motor` / `load_friction_external`(电机侧/外力侧的载荷相关项)、`friction_viscous`(黏性)合成一个**摩擦预算 τ_fm**,仿真器把"停止力矩"裁剪在 ±τ_fm 内——这就是它落进 MuJoCo `dof_frictionloss` / `dof_damping` 的方式。

## 真实参数长什么样

`bam/bam/params/xl330/m6.json` 是 XL330-M288-T 的实测辨识结果,几个关键值:电机常数 `kt=0.346`、电阻 `R=2.50`、反射惯量 `armature=0.00157`、`friction_base=0.0119` N·m、`friction_viscous=0.0058` N·m/(rad/s)、指令延迟 `command_delay=0.0102` s。 Microduck 训练配置(`microduck_constants.py` 的 `_BAM_ACTUATOR_KWARGS`)里的 `motor_name="xl330", model="m6"` 加载的正是这份 JSON——**训练策略所依据的执行器模型,是从一颗实物 XL330-M288-T 台架辨识出来的**(`执行器选型.md` 的型号证据链)。

## 为什么换舵机必须重新拟合

BAM 自带的已辨识模型库只有:Dynamixel MX-64 / MX-106 / XL-320 / XL330-M288-T、eRob80:50 / :100、Feetech STS3215(README 列表)。**没有 HL-1910。** 训练参数调整指南 §11.4 的原话:"正确路径是实测拟合一个自定义 JSON","不要拿另一款舵机的 JSON 改个文件名"。辨识流程见 [解读 55](55-单摆台架.md) 与 [解读 56](56-M1到M6.md)。

## 你带走的收获

- **为什么"差不多"的舵机也不能抄参数**:摩擦是 Stribeck + 载荷相关 + 方向性的合成,换一颗舵机整条曲线都变了。
- BAM 的思路是"摩擦预算":算出当前状态最多能有多大的阻力,让求解器去裁剪,而不是硬加一个固定摩擦力。
- 一颗 18 g 舵机的真实画像 = 电机(kt、R)+ 减速箱(armature、回差)+ 摩擦五六个参数 + 延迟,全部可测可拟合。
- 已辨识模型库是公共财富:XL330 的 JSON 免费拿;你的舵机没有,就自己测——这正是本系列 55–57 篇的作业。
- 模型精度 = sim2real 迁移率,这是 BAM 论文(ICRA 2025)的核心论点。

## 延伸

- [解读 55](55-单摆台架.md):辨识实验的物理设计 · [解读 56](56-M1到M6.md):从采集到拟合
- [解读 57](57-辨识进仿真.md):m6.json 写回训练配置的路径
- `bam/README.md`(动机与已辨识模型库)
- `bam/bam/model.py`(M1–M6 定义与 `compute_frictions`)
- `bam/bam/params/xl330/m6.json`(本仓真实加载的参数)
