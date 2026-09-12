# BAM 与 URDF 全流程小白教程

> 从机器人结构文件，到真实舵机建模，再到 MuJoCo 仿真、强化学习和真机部署。
>
> 适合第一次接触 URDF、MJCF、BAM、MuJoCo 或 sim-to-real 的读者。

## 0. 先记住结论

**BAM 不负责转换或“处理”URDF。**

正确流程是：

```text
CAD / 网格模型
      ↓
URDF 或 Xacro                    机器人结构
      ↓
转换为 MuJoCo MJCF
      ↓
检查质量、惯量、关节和碰撞
      ↓
加入 MuJoCo motor 执行器
      ↓
BAM 舵机模型                    执行器动力学
      ↓
仿真验证
      ↓
强化学习训练                    机器人行为
      ↓
导出 ONNX
      ↓
真机测试
```

可以把这几个文件想成：

| 名词 | 类比 | 负责什么 |
|---|---|---|
| URDF | 身体装配说明书 | 连杆、关节、网格、质量、惯量 |
| MJCF | MuJoCo 版身体说明书 | 仿真身体、碰撞、执行器、传感器、场景 |
| BAM | 舵机的性格档案 | 摩擦、延迟、电压、电机力矩、反驱特性 |
| Policy / ONNX | 大脑 | 根据传感器数据输出关节动作 |

一份 URDF 通常无法告诉 BAM：

- 舵机齿轮箱的真实摩擦；
- 驱动与反驱是否对称；
- 指令经过总线和固件后延迟了多少；
- 不同电压下能够输出多少力矩；
- 低速时是否有明显的 Stribeck 摩擦；
- 同型号舵机之间的个体差异。

这些参数需要使用 BAM 已发布的实测模型，或者通过单舵机台架重新辨识。

---

## 1. 先选择你的路线

### 路线 A：舵机已经被 BAM 支持

BAM 已提供若干实测模型，例如 Dynamixel XL330、XL320、MX-64、MX-106，以及部分 Feetech 和其他舵机。

这种情况不需要自己搭台架，可以直接加载：

```python
from bam.model import load_model

model = load_model(motor_name="xl330", model="m6")
```

先在官方列表确认名称：[BAM 已辨识执行器列表](https://bam.readthedocs.io/en/latest/usage/actuators.html)。

### 路线 B：使用 BAM 没有收录的新舵机

需要完成：

1. 编写或复用该厂商的通信适配器；
2. 搭建单摆台架；
3. 在不同负载、电压和 P 增益下采集数据；
4. 重采样原始日志；
5. 拟合 M1～M6；
6. 留出一组数据验证；
7. 生成自定义参数 JSON；
8. 将 JSON 接入 MuJoCo 或 mjlab；
9. 修改整机模型后重新训练。

不能把其他舵机的 `m6.json` 改个文件名当作新模型。

### 路线 C：Microduck 原始硬件没有变化

本仓库已经包含 MJCF：

[kinematics/assets/alpha/robot_walk.xml](../kinematics/assets/alpha/robot_walk.xml)

因此不需要再走 URDF → MJCF。原始 XL330 路线可以直接使用现有 BAM 模型与官方 ONNX。只有在更换舵机、传动、机械结构或控制接口时，才需要重新辨识或训练。

---

## 2. 准备工作目录

建议把结构、参数、日志和脚本分开：

```text
my_robot/
├─ robot.urdf
├─ robot_mjcf.xml
├─ meshes/
│  ├─ base.stl
│  ├─ thigh.stl
│  └─ foot.stl
├─ params/
│  └─ my_motor/
│     ├─ m1.json
│     └─ m6.json
├─ logs/
│  ├─ raw/
│  └─ processed/
└─ scripts/
   └─ convert_urdf_to_mjcf.py
```

路径尽量使用相对路径。这样移动项目、换电脑或进入训练容器后，不需要重写所有 mesh 路径。

---

## 3. 安装环境

### 3.1 只使用现成 BAM 模型

创建 Python 环境：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install "better-actuator-models[mujoco]"
```

或者使用 `uv`：

```powershell
uv add "better-actuator-models[mujoco]"
```

检查：

```powershell
python -c "import bam, mujoco; print('BAM + MuJoCo OK')"
```

### 3.2 需要采集和拟合新舵机

完整辨识工具在 BAM 源码仓库中：

```powershell
git clone https://github.com/Rhoban/bam.git
cd bam
uv sync --extra identification
```

先查看帮助，确认当前版本参数：

```powershell
uv run python -m bam.fit --help
uv run python -m bam.process --help
```

---

## 4. 准备 URDF

### 4.1 如果源文件是 Xacro

MuJoCo 不负责展开 ROS Xacro。先生成普通 URDF：

```bash
ros2 run xacro xacro robot.urdf.xacro > robot.urdf
```

有 ROS/urdfdom 环境时，可以先检查：

```bash
check_urdf robot.urdf
```

### 4.2 检查单位

机器人仿真常用单位：

| 物理量 | 单位 |
|---|---|
| 长度 | 米 `m` |
| 质量 | 千克 `kg` |
| 时间 | 秒 `s` |
| 角度 | 弧度 `rad` |
| 力矩 | 牛顿米 `N·m` |

最常见错误是 CAD 使用毫米，而 URDF/MuJoCo 按米解释。

```text
100 mm = 0.1 m
1 mm   = 0.001 m
```

单位错一千倍，质量、惯量和接触力都会跟着严重失真。

### 4.3 检查每个 link

每个参与动力学计算的 link 至少应该有：

```xml
<link name="left_thigh">
  <inertial>
    <origin xyz="0 0 -0.05" rpy="0 0 0"/>
    <mass value="0.12"/>
    <inertia
      ixx="0.0002" ixy="0" ixz="0"
      iyy="0.0003" iyz="0"
      izz="0.0001"/>
  </inertial>
</link>
```

不要：

- 把所有 link 的质量写成一样；
- 使用零质量或明显不可能的惯量；
- 把视觉网格的中心直接当作重心；
- 忘记重新计算改形状后的惯量。

### 4.4 检查每个 joint

```xml
<joint name="left_knee" type="revolute">
  <parent link="left_thigh"/>
  <child link="left_shin"/>
  <origin xyz="0 0 -0.1" rpy="0 0 0"/>
  <axis xyz="0 1 0"/>
  <limit lower="-1.5" upper="1.5" effort="1.0" velocity="5.0"/>
</joint>
```

逐个确认：

- 父 link 和子 link；
- 关节位置 `origin`；
- 旋转轴 `axis`；
- 正负方向；
- 角度、速度和力矩范围；
- 左右镜像是否正确。

如果目标是抬腿，仿真却向后踢，先检查关节轴与符号，不要先改 BAM。

### 4.5 检查 mesh

建议：

- 视觉模型使用较精细的 STL/OBJ；
- 碰撞模型使用简化 mesh、box、capsule 或 sphere；
- 不要直接用数十万面视觉网格做所有碰撞；
- 避免 `package://` 路径进入 MuJoCo 后无法解析；
- 所有 mesh 路径都实际存在，并注意大小写。

---

## 5. URDF 转 MJCF

MuJoCo 能读取 URDF，但 URDF 只能覆盖 MuJoCo 能力的一部分。官方推荐先加载 URDF、保存为 MJCF，再在 MJCF 中补充 MuJoCo 专用信息。通常转换一次后主要维护 MJCF。

参考：[MuJoCo Modeling：URDF extensions](https://mujoco.readthedocs.io/en/stable/modeling.html#urdf-extensions)。

创建 `scripts/convert_urdf_to_mjcf.py`：

```python
from pathlib import Path

import mujoco


source = Path("robot.urdf")
output = Path("robot_mjcf.xml")

spec = mujoco.MjSpec.from_file(str(source))
model = spec.compile()
spec.encode(str(output), model=model)

print(f"已生成: {output.resolve()}")
print(f"关节数量: {model.njnt}")
print(f"执行器数量: {model.nu}")
```

运行：

```powershell
python scripts/convert_urdf_to_mjcf.py
```

打开模型：

```powershell
python -m mujoco.viewer --mjcf=robot_mjcf.xml
```

`MjSpec.from_file()`、`compile()` 和 `encode()` 的用法见 [MuJoCo Python 文档](https://mujoco.readthedocs.io/en/stable/python.html#save-to-xml)。

### 转换失败时怎么查

按这个顺序排查：

1. XML 是否完整；
2. mesh 文件是否存在；
3. mesh 路径是否能从 URDF 所在目录解析；
4. link 是否存在零质量；
5. 惯量矩阵是否物理有效；
6. joint 是否引用了不存在的 link；
7. 是否仍含有未展开的 Xacro 表达式；
8. MuJoCo 错误信息指向的行号和列号。

先修 URDF 源文件，再重新转换。不要一边频繁改 URDF，一边在生成的 MJCF 中重复手工修相同错误。

---

## 6. 人工检查生成的 MJCF

转换成功只说明 XML 能被解析，不说明物理模型正确。

### 6.1 身体层级

```xml
<worldbody>
  <body name="base">
    <body name="left_thigh">
      <joint name="left_hip" type="hinge" axis="0 1 0"/>
      <body name="left_shin">
        <joint name="left_knee" type="hinge" axis="0 1 0"/>
      </body>
    </body>
  </body>
</worldbody>
```

父子层级错了，后面的控制和训练都无法补救。

### 6.2 关节

```xml
<joint
  name="left_knee"
  type="hinge"
  axis="0 1 0"
  range="-1.5 1.5"/>
```

检查：

- 轴方向；
- 正方向；
- 局部坐标；
- 角度范围；
- 关节名称是否唯一。

### 6.3 惯量和重心

质量与惯量不合理时常见现象：

- 模型加载后瞬间飞走；
- 腿像没有重量一样甩动；
- 机器人在地面持续振动；
- 关节获得极大速度；
- 接触求解器不稳定。

### 6.4 碰撞

视觉模型和碰撞模型最好分开。碰撞形状越简单，通常越稳定、越快：

```xml
<geom type="capsule" size="0.02 0.08"/>
```

### 6.5 地面、重力和时间步

最小场景至少需要合理的重力、时间步和地面：

```xml
<option gravity="0 0 -9.81" timestep="0.005"/>

<worldbody>
  <geom
    name="floor"
    type="plane"
    size="5 5 0.1"
    friction="0.8 0.005 0.0001"/>
</worldbody>
```

策略控制频率和物理时间步不是一回事。例如策略可以 50 Hz 更新一次，但 MuJoCo 在每个策略周期内进行多个 200 Hz 物理步。

---

## 7. 给 MJCF 加入 BAM 执行器

BAM 的 MuJoCo CPU 接口要求受控关节使用 `<motor>`，不要使用 `<position>` 或 `<velocity>`：

```xml
<actuator>
  <motor name="left_hip" joint="left_hip" gear="1"/>
  <motor name="left_knee" joint="left_knee" gear="1"/>
  <motor name="right_hip" joint="right_hip" gear="1"/>
  <motor name="right_knee" joint="right_knee" gear="1"/>
</actuator>
```

参考：[BAM MuJoCo CPU：XML setup](https://bam.readthedocs.io/en/latest/usage/mujoco_cpu.html#xml-setup)。

必须对齐三个名字：

```text
<joint name="left_knee">
<motor name="left_knee" joint="left_knee">
MujocoController(actuator=["left_knee"])
```

如果转换结果已经生成执行器，不要再添加重复执行器。先把已有的 `<position>`/`<velocity>` 改成 BAM 需要的 `<motor>`。

`gear="1"` 表示 BAM 参数和关节都按同一个输出轴定义。如果机器人还有额外减速器、同步带或连杆传动，需要单独核实传动比，不能始终假设为 1。

BAM 会在运行时写入：

```text
dof_armature
dof_frictionloss
dof_damping
```

因此 XML 中这些字段不是 BAM 运行时的最终值。

---

## 8. 使用 BAM 已有模型

下面是一个最小 CPU MuJoCo 示例：

```python
import mujoco

from bam.model import load_model
from bam.mujoco import MujocoController


# 1. 加载 MJCF
mj_model = mujoco.MjModel.from_xml_path("robot_mjcf.xml")
mj_data = mujoco.MjData(mj_model)

# 2. 加载官方辨识过的 XL330 M6
bam_model = load_model(motor_name="xl330", model="m6")

# 3. 使用真实机器人上的固件 P 增益与供电电压
bam_model.actuator.kp = 200.0
bam_model.actuator.vin = 7.4

# 4. 名字必须匹配 MJCF 中的 <motor name="...">
joint_names = [
    "left_hip",
    "left_knee",
    "right_hip",
    "right_knee",
]

controller = MujocoController(
    model=bam_model,
    actuator=joint_names,
    mujoco_model=mj_model,
    mujoco_data=mj_data,
)

targets = [0.0] * len(joint_names)

for _ in range(2000):
    for joint_name, target in zip(joint_names, targets):
        controller.set_q_target(joint_name, target)

    # 每个物理步之前都要更新力矩和摩擦
    controller.update()
    mujoco.mj_step(mj_model, mj_data)

print("仿真完成")
```

每一步发生的事情：

```text
目标角度
  ↓
BAM 模拟舵机固件的位置控制
  ↓
位置误差 → PWM/电压 → 电流 → 电机力矩
  ↓
BAM 根据速度、负载和方向计算摩擦预算
  ↓
写入 MuJoCo frictionloss / damping
  ↓
MuJoCo 求解下一步运动
```

`controller.update()` 必须位于 `mujoco.mj_step()` 之前。

### 可选：模拟电池与线缆压降

```python
controller = MujocoController(
    model=bam_model,
    actuator=joint_names,
    mujoco_model=mj_model,
    mujoco_data=mj_data,
    vin_drop_resistance=0.1,
    vin_min=6.0,
)
```

只有测量或估算过电池与线缆等效电阻后，才应该填写该参数。共用一块电池的同型号关节最好放在同一个 controller 中，否则各 controller 不会自动汇总整块电池的电流。

---

## 9. 新舵机：搭建 BAM 单摆台架

新舵机不能仅依靠 URDF。需要用已知负载，把未知的执行器特性测出来。

```text
固定支架
   │
舵机输出轴
   │
刚性摆臂
   │
已知质量的砝码
```

台架需要：

- 牢固的舵机支架；
- 多种长度的刚性摆臂；
- 多种已知质量的砝码；
- 舵机通信接口；
- 可调或可测的电源；
- 足够的摆动空间；
- 断电或急停手段。

官方要求与示例：[BAM Hardware Setup](https://bam.readthedocs.io/en/latest/identification/setup.html)。

### 安全要求

- 先使用轻负载、低增益、低速度；
- 摆臂运动范围内不能站人；
- 支架必须固定在稳定台面；
- 线缆不能进入摆臂轨迹；
- 不要长时间堵转；
- 记录电压、电流和温度；
- 每次换摆臂或砝码后重新确认紧固件。

### 必须测量的台架信息

| 字段 | 含义 |
|---|---|
| `mass` | 摆臂末端砝码质量 |
| `arm_mass` | 摆臂自身质量 |
| `length` | 输出轴到砝码重心的距离 |
| `kp` | 舵机固件的位置 P 增益 |
| `vin` | 实际输入电压 |

台架质量、长度或零位错误，会被拟合器误认为是舵机摩擦。

---

## 10. 新舵机：实现执行器接口

BAM 需要知道舵机如何把目标角度、实际角度和速度转换为电机力矩。

### 电压控制舵机

通常继承 `VoltageControlledActuator`，需要确认：

- `vin`：供电电压；
- `kp`：固件 P 增益；
- `error_gain`：固件误差单位到电压命令的换算；
- `max_pwm`：最大 PWM；
- `max_current`：固件电流限制，没有则为 `None`；
- `kt`：电机力矩常数；
- `R`：电机电阻；
- `armature`：反射到输出轴的等效惯量。

### 电流控制舵机

通常继承 `CurrentControlledActuator`。控制律应描述位置误差如何转成目标电流，并正确处理固件的电流限制。

新厂商一般需要：

```text
bam/<manufacturer>/
├─ actuator.py     与真实舵机通信、定义控制律
├─ record.py       播放一条轨迹并记录 JSON
└─ all_record.py   遍历 P 增益和多条轨迹
```

可以参考 BAM 已有的 `bam/dynamixel/` 实现。详细接口见 [BAM Modeling the actuator](https://bam.readthedocs.io/en/latest/identification/actuator_modeling.html)。

---

## 11. 采集原始数据

以 Dynamixel XL330 为例：

```powershell
uv run python -m bam.dynamixel.all_record --port COM3 --motor xl330 --mass 0.567 --arm-mass 0.016 --length 0.17 --vin 7.5 --logdir data_raw
```

Linux 端口通常类似：

```bash
/dev/ttyUSB0
```

自定义厂商的命令形式：

```powershell
uv run python -m bam.<manufacturer>.all_record --port <端口> --motor <型号> --mass <砝码kg> --arm-mass <摆臂kg> --length <长度m> --vin <电压V> --logdir data_raw
```

BAM 自带的典型激励轨迹包括：

| 轨迹 | 主要用途 |
|---|---|
| `sin_time_square` | 覆盖越来越快的速度 |
| `lift_and_drop` | 抬起后断力矩，观察重力和阻尼 |
| `up_and_down` | 强调低速、静摩擦和负载相关效应 |
| `sin_sin` | 使用多种频率激励执行器 |

一组可靠数据应该覆盖：

- 多个 P 增益；
- 多个负载；
- 多个摆臂长度；
- 正向和反向运动；
- 低速和高速；
- 多个实际工作电压；
- 冷机和热机状态。

不同厂商的 P 增益单位不同，不能照抄其他舵机的数字。可以从厂商默认 P 增益附近开始，例如测试 `kp/6`、`kp/4`、`kp/2`、`kp`，同时保证运动安全。

官方采集说明：[BAM Data Acquisition](https://bam.readthedocs.io/en/latest/identification/acquisition.html)。

原始日志大致是：

```json
{
  "mass": 0.5,
  "arm_mass": 0.02,
  "length": 0.15,
  "kp": 50,
  "vin": 7.5,
  "motor": "my_motor",
  "trajectory": "sin_time_square",
  "entries": [
    {
      "timestamp": 0.0077,
      "position": 0.0015,
      "speed": 0.024,
      "load": 0.0,
      "input_volts": 7.5,
      "goal_position": 0.0,
      "torque_enable": true
    }
  ]
}
```

每组数据都要保留原始文件。不要只保留处理后的曲线或拟合结果。

---

## 12. 检查和处理日志

### 12.1 查看采样抖动

```powershell
uv run python -m bam.jitter --logdir data_raw
```

如果时间戳出现大段空缺、明显跳变或通信错误，先修通信链路，不要让拟合器替通信故障背锅。

### 12.2 重采样到固定时间步

```powershell
uv run python -m bam.process --raw data_raw --logdir data_processed --dt 0.005
```

`0.005 s` 等于 `5 ms`，也就是 `200 Hz`。BAM 会在相邻记录之间插值，输出固定时间步的处理后日志。

### 12.3 先画原始曲线

```powershell
uv run python -m bam.plot --actuator <型号> --logdir data_processed
```

拟合前先检查：

- 目标位置是否连续；
- 实际位置是否存在跳点；
- 速度是否异常饱和；
- 断力矩阶段是否真的关闭；
- 元数据中的质量、长度、增益和电压是否正确。

---

## 13. 理解 M1～M6

M1～M6 是六种复杂度逐渐提高的模型，不是六个参数。

| 模型 | 增加的现象 | 小白理解 |
|---|---|---|
| M1 | 库仑摩擦 + 黏性摩擦 | 固定阻力，加上速度越快阻力越大 |
| M2 | Stribeck | 接近静止时更难启动 |
| M3 | 负载相关 | 执行器承受的力越大，摩擦也会变化 |
| M4 | Stribeck + 负载相关 | 同时描述低速和负载效应 |
| M5 | 方向相关 | 主动驱动与被外力反推时表现不同 |
| M6 | 二次方向项 | 描述更强的非线性负载耦合 |

理论和公式见 [BAM Friction Models M1–M6](https://bam.readthedocs.io/en/latest/theory/models.html)。

模型越复杂不一定越好。复杂模型可能更贴合训练数据，也可能更容易过拟合。最终应该根据验证数据选择。

---

## 14. 拟合 BAM 参数

先留出一个没有参与拟合的 P 增益作为验证集。例如：

```text
训练：kp = 50、100、200、300
验证：kp = 400
```

拟合 M6：

```powershell
uv run python -m bam.fit --actuator <型号> --model m6 --logdir data_processed --validation_kp <留出的kp> --output params/<型号>/m6.json
```

正式辨识建议对 M1～M6 分别运行，并保存：

```text
params/<型号>/m1.json
params/<型号>/m2.json
params/<型号>/m3.json
params/<型号>/m4.json
params/<型号>/m5.json
params/<型号>/m6.json
```

快速检查流水线时可以减少 `--trials`；最终结果应使用足够的搜索次数。BAM 当前默认是 100000 次评估，复杂模型通常需要更多计算时间。

拟合目标是让仿真位置和实测位置之间的平均绝对误差（MAE）尽量小。完整选项见 [BAM Fitting](https://bam.readthedocs.io/en/latest/identification/fitting.html)。

### 14.1 评估已有参数

```powershell
uv run python -m bam.fit --actuator <型号> --model m6 --logdir data_processed --eval --output params/<型号>/m6.json
```

### 14.2 画实测与仿真对比

```powershell
uv run python -m bam.plot --actuator <型号> --logdir data_processed --sim --params params/<型号>/m6.json
```

### 14.3 如何判断拟合是否可信

至少确认：

- 验证误差没有明显高于训练误差；
- 未参与拟合的 P 增益也能得到相似趋势；
- 低速、快速、正向、反向、轻载和重载都能对齐；
- 参数没有长期卡在搜索范围的上下边界；
- 增加模型复杂度确实改善验证误差；
- 多次拟合得到的关键参数不会完全不同。

不要只挑一张最好看的曲线作为成功证据。

---

## 15. 使用自定义 BAM JSON

拟合结果可以直接加载：

```python
from bam.model import load_model

bam_model = load_model(json_file="params/my_motor/m6.json")
```

然后交给 `MujocoController`：

```python
from bam.mujoco import MujocoController

controller = MujocoController(
    model=bam_model,
    actuator=["left_hip", "left_knee"],
    mujoco_model=mj_model,
    mujoco_data=mj_data,
)
```

加载方式二选一：

```python
# 官方已收录模型
load_model(motor_name="xl330", model="m6")

# 自己拟合的模型
load_model(json_file="params/my_motor/m6.json")
```

不要同时传 `json_file` 与 `motor_name`/`model`。

---

## 16. 接入 mjlab GPU 训练

如果使用 mjlab + MuJoCo Warp 训练，可以用 `BamActuatorCfg`。

### 使用官方模型

```python
from bam.mjlab import BamActuatorCfg

actuator_cfg = BamActuatorCfg(
    motor_name="xl330",
    model="m6",
    target_names_expr=(r".*",),
    kp_fw=200.0,
    vin_range=(7.0, 8.0),
)
```

### 使用自己的 JSON

```python
from bam.mjlab import BamActuatorCfg

actuator_cfg = BamActuatorCfg(
    json_path="params/my_motor/m6.json",
    target_names_expr=(r".*",),
    kp_fw=200.0,
    vin_range=(7.0, 8.0),
    vin_drop_gain_range=(0.05, 0.15),
    vin_min=6.0,
    delay_min_lag=1,
    delay_max_lag=3,
)
```

`json_path` 与 `motor_name + model` 二选一。

还需要在任务配置中注册 BAM 启动事件：

```python
from bam.mjlab import bam_init

cfg.events["bam_init"] = EventTermCfg(func=bam_init, mode="startup")
```

`EventTermCfg` 的导入路径以项目使用的 mjlab 版本为准。启动事件用于为并行环境展开 `dof_frictionloss` 与 `dof_damping` 字段。

官方示例与当前兼容说明见 [BAM mjlab GPU](https://bam.readthedocs.io/en/latest/usage/mjlab_gpu.html)。

### 域随机化参数从哪里来

不要凭感觉填写随机化范围。范围应该来自：

- 不同舵机样品之间的离散度；
- 电池从满电到低电量的实测电压；
- 总线与固件延迟；
- 冷机和热机摩擦变化；
- 线缆与连接器造成的压降；
- 回差实测值。

随机化范围太窄，策略无法适应真机差异；范围过宽，策略会把大量训练能力浪费在不可能出现的机器人上。

---

## 17. 从模型到强化学习

当 MJCF 与 BAM 都通过单独验证后，才开始训练。

```text
MJCF：身体正确吗？
  ↓
BAM：舵机响应正确吗？
  ↓
环境：观测和动作接口正确吗？
  ↓
Reward：奖励是否引导目标行为？
  ↓
PPO：训练是否收敛？
```

先跑很短的 smoke test，例如 Microduck：

```bash
uv run train Mjlab-Velocity-Flat-MicroDuck --env.scene.num-envs 64 --agent.max-iterations 5
```

五次迭代不用于训练出会走路的策略，只检查：

- 环境能够创建；
- 仿真能够 step；
- 没有 NaN/Inf；
- observation/action 维度正确；
- reward 数量级正常；
- BAM 执行器被正确选择；
- GPU 或 CPU 后端能够运行。

通过后再进行完整训练。

---

## 18. Microduck 的具体对应关系

Microduck 当前主线是：

```text
robot_walk.xml（MJCF）
      ↓
XL330 BAM M6
      ↓
mjlab / MuJoCo Warp
      ↓
PPO 训练
      ↓
官方 export.py
      ↓
ONNX：obs[1,61] → actions[1,14]
      ↓
robotd 以 50 Hz 运行
```

本仓库的 MJCF：

[kinematics/assets/alpha/robot_walk.xml](../kinematics/assets/alpha/robot_walk.xml)

训练代码位于独立的 [pollen-robotics/microduck_rl](https://github.com/pollen-robotics/microduck_rl) 仓库。本仓库主要负责加载 ONNX、运行控制循环和保护真机。

原始训练配置中的概念结构类似：

```python
_BAM_ACTUATOR_KWARGS = dict(
    motor_name="xl330",
    model="m6",
    kp_fw=200.0,
    vin_range=(6.5, 8.2),
)
```

这些数字描述原始 Microduck 的 XL330 工况，不是所有舵机的通用参数。

换新舵机后应改为：

```python
_BAM_ACTUATOR_KWARGS = dict(
    json_path="/absolute/path/params/my_motor/m6.json",
    kp_fw=<新舵机真实增益>,
    vin_range=(<实测最低电压>, <实测最高电压>),
)
```

实际训练时不建议新手直接编辑上游仓库的 `microduck_constants.py`。上游训练器已经支持
命令行覆盖，直接把拟合结果传给 smoke 脚本即可：

HL-2915 的拟合不能直接写 `--actuator sts3215`。本仓库提供
`tools/microduck_learning/fit_hl2915_bam.py`，它只在当前拟合进程注册 `hl2915`，并要求传入
实测的固件 `error_gain`：

```bash
uv run python /absolute/path/microduck/tools/microduck_learning/fit_hl2915_bam.py \
  --error-gain <实测值> --logdir data_processed --model m6 \
  --method cmaes --trials 2000 --workers 1 \
  --output params/hl2915/m6.json
```

没有示波器实测或飞特书面 `error_gain` 时，停在拟合前；不要用 STS3215 默认控制律制造一份
看起来完整、实际不可验证的 HL-2915 参数。

```bash
export MICRODUCK_RL_DIR=/home/<user>/microduck_rl
export MICRODUCK_BAM_JSON=/绝对路径/artifacts/bam/hl2915-m6.json
bash /绝对路径/microduck/tools/microduck_learning/run_5_iteration_smoke.sh
```

日志中应出现 `BamActuator`，并且进程以退出码 `0` 结束；这只证明 JSON 能加载和仿真能
step，不代表已经学会行走。正式训练前仍要按同样参数导出 ONNX，再做 `obs[1,61] →
actions[1,14]` 合同检查。

同时重新核实：

- 执行器质量与整机重心；
- 真实关节限位；
- 最大安全速度和力矩；
- 回差结构；
- 指令延迟；
- 摩擦随机化范围；
- 观测和动作中的关节顺序。

如果仍保持 Microduck 的软件接口，部署合同不能偷偷改变：

```text
输入：61 维 observation
输出：14 维 action
运行：50 Hz
```

更详细的本地资料：

- [进阶学习文档：训练、仿真与部署](进阶学习文档-训练仿真与部署.md)
- [解读 54：BAM 是什么](deep-dive/54-BAM是什么.md)
- [解读 55：单摆台架](deep-dive/55-单摆台架.md)
- [解读 56：M1 到 M6](deep-dive/56-M1到M6.md)
- [解读 57：辨识结果进入仿真](deep-dive/57-辨识进仿真.md)
- [解读 60：Testbench 验证](deep-dive/60-testbench验证.md)

---

## 19. 分层验收：不要一步跳到真机

### L1：URDF 静态检查

- XML 能解析；
- mesh 都能找到；
- link/joint 名称唯一；
- 父子关系正确；
- 单位正确；
- 质量和惯量非零且合理。

### L2：MJCF 加载检查

```python
import mujoco

model = mujoco.MjModel.from_xml_path("robot_mjcf.xml")
data = mujoco.MjData(model)
mujoco.mj_step(model, data)

print("joints:", model.njnt)
print("actuators:", model.nu)
```

### L3：无控制重力测试

关闭电机，让机器人自然下落。检查：

- 是否穿过地面；
- 是否瞬间飞走；
- 碰撞是否合理；
- 重心方向是否符合预期。

### L4：单关节测试

每次只控制一个关节：

```text
回零 → 小角度正向 → 回零 → 小角度反向
```

确认方向、限位、角度和执行器名字。

### L5：BAM 单摆验证

用同一条目标轨迹比较：

```text
真实单舵机
BAM 参考模拟器
MuJoCo + BAM
```

三方曲线能对齐，才说明参数与仿真接入都可信。

### L6：整机仿真 smoke test

检查环境能创建、能运行、没有 NaN、接口维度不变。

### L7：完整策略验证

顺序是：

```text
checkpoint 回放
      ↓
导出真正要部署的 ONNX
      ↓
CPU MuJoCo + BAM 回放该 ONNX
      ↓
吊装真机
      ↓
软垫和限速
      ↓
低风险平地测试
```

第一次真机运行必须有人随时能够断电，不要让未验证策略在桌面边缘或硬地高速运行。

---

## 20. 常见问题

| 现象 | 优先检查 |
|---|---|
| 找不到 STL/OBJ | mesh 路径、相对目录、大小写、`meshdir` |
| 模型比例不对 | 毫米与米的换算 |
| 模型一运行就飞走 | 质量、惯量、重叠碰撞、关节位置、时间步 |
| 关节方向反了 | joint `axis`、镜像、actuator `gear` |
| 关节不动 | 是否有 `<motor>`、名字是否一致、是否调用 `controller.update()` |
| BAM 没有效果 | 是否误用了 `<position>`/`<velocity>`、是否每步更新 |
| 拟合曲线有尖峰 | 通信丢包、时间戳抖动、编码器回绕 |
| 训练误差低、验证误差高 | 数据不足、模型过拟合、验证工况太不同 |
| 单摆拟合好、整机仍不对 | 整机延迟、电压、回差、质量或碰撞不匹配 |
| 仿真能走、真机会摔 | sim-to-real 随机化不足、接口顺序或归一化错误 |
| 换舵机后旧 ONNX 失效 | 策略学习的是原执行器动力学，需要重训 |

排错时按层进行：

```text
文件和依赖
  ↓
URDF/MJCF 能否加载
  ↓
关节几何和单位
  ↓
执行器名字与方向
  ↓
BAM 单舵机响应
  ↓
整机仿真
  ↓
观测/动作合同
  ↓
最后才检查 Reward 和 PPO
```

前一层没有通过，不要靠调后一层参数掩盖问题。

---

## 21. 最小学习路线

第一次接触时，不要一次完成整条链路。

### 第一天：只认识文件

1. 打开一个 URDF；
2. 找到 link、joint、axis、limit；
3. 打开一个 MJCF；
4. 找到 body、joint、geom、actuator；
5. 在 MuJoCo viewer 中加载模型。

### 第二天：只控制一个关节

1. 给一个关节加入 `<motor>`；
2. 用普通 MuJoCo 施加控制；
3. 确认方向和限位；
4. 再接入 BAM 已有模型。

### 第三天：理解 BAM

1. 读取一个官方 `m1.json`；
2. 读取同一舵机的 `m6.json`；
3. 比较多出的摩擦参数；
4. 运行一条 BAM 仿真轨迹。

### 第四天以后：新舵机辨识

1. 搭单摆台架；
2. 先采一组轻负载数据；
3. 完成 process → fit → plot；
4. 确认流水线正确；
5. 再扩展到完整负载、电压和增益矩阵。

### 最后：整机训练

只有在 MJCF 和 BAM 各自通过验证后，才进入整机强化学习。

---

## 22. 完成标准

一条完整的 BAM + URDF/MJCF 流程，至少应留下这些可复查产物：

- [ ] 原始 URDF/Xacro 与固定版本；
- [ ] 所有视觉和碰撞 mesh；
- [ ] 可独立加载的 MJCF；
- [ ] 关节名称、方向、限位检查记录；
- [ ] 台架质量、摆臂质量和长度记录；
- [ ] 原始 BAM 日志；
- [ ] 固定步长的处理后日志；
- [ ] M1～M6 参数文件；
- [ ] 未参与拟合的验证数据；
- [ ] 实测与仿真对比图；
- [ ] MuJoCo CPU 接入检查；
- [ ] mjlab smoke test；
- [ ] 真正要部署的 ONNX 回放结果；
- [ ] 吊装和软垫真机测试记录。

缺少原始日志或验证集时，即使有一份看起来合理的 `m6.json`，也很难证明模型真的可靠。

---

## 23. 官方资料

- [BAM 官方文档](https://bam.readthedocs.io/en/latest/)
- [BAM GitHub](https://github.com/Rhoban/bam)
- [BAM 已辨识执行器](https://bam.readthedocs.io/en/latest/usage/actuators.html)
- [BAM 台架搭建](https://bam.readthedocs.io/en/latest/identification/setup.html)
- [BAM 执行器建模](https://bam.readthedocs.io/en/latest/identification/actuator_modeling.html)
- [BAM 数据采集](https://bam.readthedocs.io/en/latest/identification/acquisition.html)
- [BAM 参数拟合](https://bam.readthedocs.io/en/latest/identification/fitting.html)
- [BAM M1～M6 理论](https://bam.readthedocs.io/en/latest/theory/models.html)
- [BAM MuJoCo CPU 接入](https://bam.readthedocs.io/en/latest/usage/mujoco_cpu.html)
- [BAM mjlab GPU 接入](https://bam.readthedocs.io/en/latest/usage/mjlab_gpu.html)
- [MuJoCo 建模文档](https://mujoco.readthedocs.io/en/stable/modeling.html)
- [MuJoCo Python 文档](https://mujoco.readthedocs.io/en/stable/python.html)
- [Microduck 训练仓库](https://github.com/pollen-robotics/microduck_rl)

---

## 24. 最后的判断表

| 改动 | 通常要做什么 |
|---|---|
| 只改颜色和视觉贴图 | 修改视觉 mesh/MJCF，一般不重训 |
| 修改外壳但质量和碰撞没变 | 修改视觉模型，验证后通常不重训 |
| 修改质量、腿长、重心或关节位置 | 更新 MJCF，通常重新训练 |
| 更换同型号舵机 | 验证个体差异，必要时扩大随机化 |
| 更换不同型号舵机 | 重新辨识 BAM，并重新训练 |
| 修改减速比或传动结构 | 更新 MJCF 传动与惯量，重新辨识并训练 |
| 修改控制频率、观测或动作顺序 | 更新训练与部署合同，重新训练 |
| 完全保持原始 Microduck 硬件 | 直接使用现有 MJCF、XL330 BAM 和官方 ONNX |

最稳妥的学习与实施顺序始终是：

```text
先几何
→ 再执行器
→ 再整机仿真
→ 再训练
→ 最后真机
```
