# 解读 80 · BAM 参数:m6.json 逐字段

> **解读对象**:`bam/bam/params/xl330/m6.json`(18 个字段)+ 其余 7 个型号对照
> **需要的前置**:[解读 56](56-M1到M6.md)(M1–M6 各代表什么)· [解读 79](79-参数适配五落点.md)(json 怎么被训练加载)

前几篇说"辨识出一份 m6.json",这篇把它逐字段打开:是什么物理量、谁定合法范围。

## 1. 三段结构:电机 / 台架杂项 / 摩擦预算

xl330/m6.json 分三类。**第一类:电机模型**(`dynamixel/actuator.py` 的 `initialize()` 定范围):

| 字段 | xl330 辨识值 | 含义 | 初始值(范围) |
|---|---|---|---|
| `kt` | 0.346 | 力矩常数 N·m/A | 1.6(0.1–3.0) |
| `R` | 2.50 | 绕组电阻 Ω | 2.6(2.0–5.0) |
| `armature` | 0.0016 | 转子惯量反射到输出端 kg·m² | 0.005(0.0001–0.05) |

**第二类:台架杂项**——不是舵机属性,是实验装置误差:
`q_offset` = 0.0150 rad(编码器安装偏移,±0.1);
`command_delay` = 0.0102 s(传输滞后,0–0.05,回放时把目标序列平移)。

**第三类:摩擦预算**(`model.py` 定义),BAM 的正文:

| 字段 | xl330 值 | 含义 |
|---|---|---|
| `friction_base` | 0.0119 | 库仑静摩擦 N·m,只要转就有 |
| `friction_stribeck` | 0.00085 | Stribeck 附加项:低速时摩擦升高 |
| `load_friction_motor` / `_external` | 0.228 / 0.107 | 载荷相关摩擦系数(电机侧/外载侧) |
| `load_friction_motor_stribeck` / `_external_stribeck` | 1.5e-08 / 0.142 | 同上的低速附加分量 |
| `load_friction_motor_quad` / `_external_quad` | 0.0053 / 0.0030 | 二次耦合项(外载与电机扭矩异号时启用) |
| `dtheta_stribeck` | 0.261 | Stribeck 特征速度 rad/s |
| `alpha` | 8.53 | Stribeck 曲线陡度 |
| `friction_viscous` | 0.0058 | 黏性摩擦 N·m/(rad/s) |

(另有 `"model": "m6"` 与 `"actuator": "xl330"` 两个标识字段,后者须是注册表键名。)

## 2. 这些数怎么变成仿真里的摩擦

`Model.compute_frictions()` 每步算两个数,写进 MuJoCo 的 `dof_frictionloss` 与 `dof_damping`。白话版:

- 摩擦下限 = `friction_base` + 电机扭矩与外载扭矩加权差的绝对值(载荷项)+ Stribeck 附加;
- Stribeck 附加 = `friction_stribeck` × exp(−(|dθ/dtheta_stribeck|^alpha)):静止时全额,
  转快了指数衰减;`dtheta_stribeck` 定"多慢算慢",`alpha` 定衰减多陡;
- 黏性阻尼 = `friction_viscous` × 速度,走 `damping` 通道。

xl330 辨识出 alpha=8.53(上限 10):Stribeck 峰非常窄,只在近停转的一小段速度里摩擦陡增——
而走路时每次落脚,关节都要穿过这段"黏滞区"。

## 3. 八个型号对照:字段集本身也是信息

| 型号 | kt | R | armature | viscous | 独有/缺失 |
|---|---|---|---|---|---|
| xl330 | 0.346 | 2.50 | 0.0016 | 0.0058 | 有 `command_delay` |
| xl320 | 1.009 | **31.59** | 0.0012 | 0.0072 | R 高一个量级 |
| sts3215 | 1.275 | 2.75 | 0.0216 | 0.0282 | `error_gain_ratio` + `max_velocity` |
| waveshare_st3025 | 1.651 | 3.10 | 0.0048 | 0.0222 | `error_gain_ratio`,无 `command_delay` |
| mx64 | 1.602 | 2.32 | 0.0123 | 0.0253 | 无 `q_offset`/`command_delay` |
| mx106 | 2.210 | 2.03 | 0.0260 | 0.0507 | 同上 |
| erob80_50 | 4.897 | 1.07 | 0.362 | 1.403 | 无 `q_offset` |
| erob80_100 | 9.396 | **无** | **1.135** | **9.709** | 连 `R` 都没进 json |

字段缺失不一定是遗漏:**json 里有什么,由模型档位 + 执行器类共同决定**。sts3215 的
`error_gain_ratio`/`max_velocity` 对应固件目标限速(见 [解读 77](77-协议适配Dynamixel系.md));
erob80_100 的 `R` 缺失则另有一说:`ErobActuator` 类定义了 R(初始 2.0),缺的字段加载时
**回落到初始值**——可能辨识时被 `fit --set` 锁参冻结,待验证。

## 你带走的收获

- m6.json = 电机三参数 + 台架杂项两项 + 摩擦预算十三项;前两类是标定,第三类才是模型本体。
- `q_offset`/`command_delay` 是台架误差不是舵机属性——换台架重测,换舵机也重测。
- Stribeck 项是 exp(−(|dθ/dθ₀|^α)):xl330 的 α=8.53 说明摩擦峰集中在近停转区。
- json 字段集随执行器类变化,缺失 ≠ 数据丢失;缺的字段加载时回落到类里初始值,
  辨识值贴近范围上限(如 alpha 8.53/10)则提示模型"顶到了天花板"。

## 延伸

- [解读 73](73-换舵机决策树.md):8 个型号库总览
- [解读 57](57-辨识进仿真.md):参数写回 MJCF 的路径
- `bam/bam/params/xl330/m6.json` · `bam/bam/model.py`(`Parameter` 范围与摩擦公式)
- `bam/bam/dynamixel/actuator.py`、`bam/bam/feetech/actuator.py`(执行器类初始范围)
