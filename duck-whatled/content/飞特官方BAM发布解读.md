# 飞特官方 BAM 发布解读：HD-1910 已辨识执行器模型

> **解读对象**：[gitee.com/ftservo/ftservo-bam](https://gitee.com/ftservo/ftservo-bam)（飞特官方 Gitee 组织，2026-09-23 至 09-30 定稿，Apache-2.0，本地克隆于 `ftservo-bam/`）
> **需要的前置**：[HD-1910 仿真迁移与 PPO 训练教程 §5](HD1910仿真迁移与PPO训练教程.md)（执行器模型与 m1–m6 命名）· [称重与标定模板-HD1910 §0.5](../microduck-replica/docs/称重与标定模板-HD1910.md)（参照链命名纪律，工作区文件）

## 0. 一句话结论

飞特官方把 **HD-1910 的全套 BAM 执行器模型（m1–m6，7.4 V）** 发布出来了——制造商、
自己的台架、正确的 `actuator: "hd1910"` 身份、恰好是我们 2S 母线的电压。
它是目前可信度最高的一份 HD-1910 动力学先验，直接插入项目的执行器参照链，
**但不改变红线：最终模型仍然是 `hd1910_our_measured_m1..m6`（实测），官方值是参照不是替身。**

## 1. BAM 是什么（30 秒版）

BAM（Better Actuator Models）出自 Rhoban 团队（ICRA 2025 论文 *Extended Friction Models
for the Physics Simulation of Servo Actuators*，Apache-2.0）。MuJoCo/IsaacGym 默认的
Coulomb-Viscous 摩擦模型太简，盖不住 Stribeck 效应、负载相关摩擦和二次速度项；
BAM 用录制的轨迹辨识出一族由简到繁的模型，直接吃进 MuJoCo CPU 和 MuJoCo Warp（GPU）。

模型族编号就是项目里一直在用的 m1–m6（JSON 键即模型项，由简到繁）：

| 模型 | 摩擦项 |
|---|---|
| m1 | 基础库仑 + 粘滞 + 指令延迟 |
| m2 | m1 + Stribeck（速度项） |
| m3 | m1 + 负载相关摩擦（不分侧） |
| m4 | m3 + Stribeck |
| m5 | 负载摩擦**分电机侧/外侧**，各带 Stribeck |
| m6 | m5 + 二次速度项（最全） |

公共电气/机械参数每次都重新辨识：kt（力矩常数）、R（绕组电阻）、armature、q_offset、
command_delay。

## 2. 官方发布里有什么

ftservo-bam 在 Rhoban 原版基础上新增（主仓 `bam/` 是旧版快照，README 尚无 HD-1910）：

| 内容 | 说明 |
|---|---|
| `bam/params/feetech_hd1910_7_4V/` | **HD-1910 m1–m6 全套已辨识参数**（7.4 V 台架） |
| `bam/params/feetech_sts3215_7_4V/` | STS3215 m1–m6（7.4 V）；另有 waveshare_st3025 |
| `bam/feetech/actuator.py` | `HD1910Actuator` / `STS3215Actuator` 控制律：`vin=7.4, kp=32, error_gain=0.163, max_pwm=0.97`，内部目标平滑（有状态） |
| `bam/feetech/record.py` | 基于 `scservo_sdk` 的轨迹采集：位置换算 0 rad=2048、±π=0/4095；Windows 下把定时器精度提到 1ms 再做毫秒级 sleep |
| `bam/dynamixel/measure_delay.py` | command_delay 的专项测量脚本 |
| `bam/mjlab.py` + `BamActuatorCfg` | mjlab（MuJoCo Warp GPU）集成：`bam_init` startup 事件 + 全并行环境向量化的执行器（电压控制律 + DC 电机 + BAM 摩擦预算），兼容 mjlab 1.3 |
| PyPI | `pip install better-actuator-models[mjlab]` |

两个与本项目互相印证的细节：官方采集脚本里
`ADDR_P_GAIN_MAP = {"sts3215": 21, "hd1910": 50}`——HD-1910 的 P 增益在寄存器 50，
与 kissqy 适配驱动（临时 P/D @50）一致；`kp=32` 与 community-kit 调试器的默认增益一致。

## 3. 关键对比：官方 m6 vs 陆吾/XGODUCK 参照

项目此前唯一现成的 HD-1910 m6 是 kissqy 携带的陆吾参照
（`hd1910_m6.json`，与 XGODUCK `1910_m6.json` 字节级相同，**actuator 字段还错标 sts3215**，
只配当数值先验）。两份 m6 的实质差异（官方 7.4 V m6 vs 陆吾 m6）：

| 参数 | 官方 HD1910（7.4 V） | 陆吾/XGODUCK m6 | 差多少 |
|---|---|---|---|
| kt（N·m/A，按库口径） | 0.564 | 0.624 | −10% |
| R（Ω） | **2.97** | **4.91** | −40% |
| command_delay（s） | **0.00098** | **0.0060** | **6 倍** |
| friction_base | 0.0120 | 0.0158 | −24% |
| load_friction_motor | **0.353** | **0.069** | **5 倍** |
| load_friction_external | 0.043 | 0.158 | −73% |
| 摩擦分侧结构 | 电机侧主导 | 外侧主导 | **几乎对调** |
| actuator 身份 | **hd1910** | sts3215（错标） | — |
| error_gain_ratio | 未提供 | 1.32 | 陆吾自带拟合质量指标 |

解读：两份模型不是同一颗舵机的两种拟合，而是**两种不同的物理画像**——延迟差 6 倍会直接
改变观测-动作对齐，摩擦分侧对调会改变带载下的力矩预算。训练侧此前把陆吾参照当
"第一版仿真基线"（`hd1910_kissqy_reference_m6`），官方模型出现后，参照链应更新为：

```text
hd1910_our_measured_m1..m6      # 终点：我们自己台架的实测（红线不变）
hd1910_ftservo_official_m6      # 新增：制造商 7.4V 官方辨识 ← 当前最强先验
hd1910_kissqy_reference_m6      # 降级为历史参照（820g 模型配套，身份错标）
xgoduck_1910_reference_m6       # 同上（与 kissqy 那份字节级相同）
```

三条使用纪律：**不混文件**（在仿真里与既有配置隔离命名，永不覆盖 our_measured 槽位）；
**对齐电压口径**（官方 7.4 V 恰是 2S 标称，带载 6.6–8.2 V 内插值可接受，但不要拿它外推 8.4 V 满电）；
**error_gain_ratio 官方没给**，评估拟合质量要靠自己回放比对。

## 4. 怎么用：两条接线（MuJoCo CPU / mjlab GPU）

### 4.0 先修一个坑（2026-10-11 快照实测）

PyPI 的 `better-actuator-models`（1.0.2，2026-07-16）**不含 HD1910**——只有 STS3215。
要用官方 HD1910，必须本地安装 Gitee 克隆；且该快照直接加载会报错：

```python
import sys; sys.path.insert(0, "ftservo-bam")          # 或 pip install -e ftservo-bam
from bam import model as bam_model
# 坑 1：bundled 名是参数目录名，不是 "HD1910"（报错信息会列出可用名）
# 坑 2：注册表键是 "HD1910"（大写），JSON 里 actuator="hd1910"（小写）→ KeyError
bam_model.actuators.setdefault("hd1910", bam_model.actuators["HD1910"])   # 一行别名修复
m = bam_model.load_model(motor_name="feetech_hd1910_7_4V", model="m6")    # OK
```

加载成功后模型自带官方执行器常量：vin=7.4、kp=32、error_gain=0.163、max_pwm=0.97。
（这个大小写不一致已报给上游并提交了修复 PR：
[issue #1](https://github.com/ftservo/ftservo-bam/issues/1) ·
[PR #2](https://github.com/ftservo/ftservo-bam/pull/2)。合并前用上面的别名绕过，
合并后可删。）
另注意 pyproject 钉死 `requires-python = ">=3.12,<3.13"`——训练环境要用 Python 3.12。

### 4.1 MuJoCo CPU（回放验证、单机实验）

```bash
pip install -e /Volumes/dev/dev/microduck/ftservo-bam[mujoco]   # 本地克隆，勿用 PyPI
```

用法（`docs/usage/mujoco_cpu.rst`，线上 https://bam.readthedocs.io ）：`load_model`
得到模型 → MJCF 里执行器必须声明为 **`motor`**（BAM 运行时覆写 `frictionloss`、
`damping`、`armature`，XML 里的值被忽略）→ `MujocoController(model=…, actuator=[关节名], …)`
→ 每步 `set_q_target` + `update()` 后 `mj_step`。电压跌落与 mjlab GPU 路径逐位一致
（同一推导），CPU 回放看到的就是训练时的电池行为。

### 4.2 mjlab GPU（插进训练任务——本仓落点已找准）

我们自己的训练仓 `xgoduck_rl/src/mjlab_microduck/robot/microduck_constants.py`
**本来就在用 BAM**（`FrictionDRBamActuatorCfg`，摩擦随机化走 BAM 原生 `friction_scale`），
当前配置是 `motor_name="xl330", model="m6", kp_fw=200`——XL330 官方参数。
换成官方 HD-1910 就是改这一处：

```python
import bam.model
bam.model.actuators.setdefault("hd1910", bam.model.actuators["HD1910"])   # §4.0 别名

_BAM_ACTUATOR_KWARGS = dict(
    motor_name="feetech_hd1910_7_4V",   # ← 原来是 "xl330"（或用 json_path 指向 m6.json）
    model="m6",
    target_names_expr=(r"^(?!passive_).*",),
    kp_fw=32.0,          # ← 官方 HD1910 执行器常量；200 是 XL330 的，别带过来
    vin_range=(6.5, 8.2),   # 2S 带载区间，保持不变
    vin_drop_gain_range=(0.0, 0.2),
    vin_min=6.0,
    delay_min_lag=3,        # 第一轮 A/B 保持不变——单变量原则，只换执行器模型
    delay_max_lag=6,
)
```

`actuators` 与 `backlash_actuators`（backlash 模型用）共用这套 kwargs，一处改两边生效。
**单变量纪律**：第一轮 A/B 只换模型与 kp_fw，电压/延迟随机化保持原值，跑完与 XL330 基线
对照 reward、fell_over、air_time（对应 [HD1910 仿真迁移教程 §9](HD1910仿真迁移与PPO训练教程.md)
的评测方法），再逐项放开。

### 4.3 复刻官方辨识（可选，喂 our_measured）

`bam/feetech/record.py` 是官方的采集脚本（scservo_sdk，毫秒级定时），
`bam/dynamixel/measure_delay.py` 可借鉴测 command_delay。它与仓库已有的
PD 阶跃采集（[换舵机重训全流程 §2.3](../microduck-replica/docs/换舵机重训全流程.md)，工作区文件）
是同一件事的两种实现：官方脚本换了 SDK，我们的管线换了轨迹设计。跑
our_measured 时把官方 m6 当"已知答案"对照，是免费的校验器。

## 5. 边界与提醒

- **官方值 ≠ 我们的实测**：同一型号不同个体、不同温度、不同台架装夹都会有偏差；
  官方 m1–m6 是参照链上的强先验，`hd1910_our_measured` 的辨识流程照旧执行。
- **7.4 V 口径**：官方目录名自带电压后缀（`feetech_hd1910_7_4V`），其它电压下这些参数
  不能直接外推（尤其 R 与 kt 的温升耦合）。
- **PyPI 版没有 HD1910**：`better-actuator-models` 1.0.2（2026-07-16）只有 STS3215 等
  Rhoban 原版型号；HD1910 只在 Gitee 克隆里，本地安装并用 §4.0 的别名绕过大小写坑。
- **主仓 `bam/` 是旧版**：README 与参数库都没有 HD-1910；要用官方新模型，请直接用
  `ftservo-bam/` 克隆，不要指望主仓快照自更新。
- **许可**：Apache-2.0；学术使用引用 Rhoban 的 ICRA 2025 论文（README 内含 BibTeX）。

## 6. 文档地图

| 想深入哪块 | 去读 |
|---|---|
| 官方库全文档 | https://bam.readthedocs.io · 本地 `ftservo-bam/docs/` |
| m1–m6 模型族与 JSON 参数含义 | `ftservo-bam/bam/parameter.py` · `docs/usage/` |
| HD-1910 仿真侧怎么接 | [HD-1910 仿真迁移与 PPO 训练教程](HD1910仿真迁移与PPO训练教程.md) |
| 参照链命名纪律 | `microduck-replica/docs/称重与标定模板-HD1910.md` §0.5–0.6（工作区文件） |
| 台架辨识方法论（解读 55–57、60、203） | [deep-dive 系列](deep-dive/README.md) |
| 舵机台架与标定工具 | [microduck-community-kit 教程](microduck-community-kit使用教程.md) |

---

*口径提醒：官方发布解决的是"HD-1910 长什么样"，解决不了"我们这 15 颗长什么样"——
后者仍然只有台架实测一条路。*
