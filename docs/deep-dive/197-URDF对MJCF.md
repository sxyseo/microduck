# 解读 197 · URDF vs MJCF

> **解读对象**:`Microduck-build-tutorial/microduck/src/model/` 下并排的两个目录:`urdf/robot.urdf` 与 `mjcf/robot.xml`(同一机器人、同一工具导出的两种格式)
> **需要的前置**:[解读 196](196-MJCF文件结构.md)(MJCF 结构逐段);[解读 157](157-自由度与关节.md)(关节类型)。

## 同一只鸭子,两份说明书

URDF(Unified Robot Description Format,通用机器人描述格式)是 ROS 生态的"普通话";MJCF 是 MuJoCo 的"母语"。这个工作区恰好把两种格式摆在同一个目录里:上游项目 `Microduck-build-tutorial/microduck/src/model/` 下,`urdf/robot.urdf` 与 `mjcf/robot.xml` 并排存放,两份文件头都是同一句:

```xml
<!-- Generated using onshape-to-robot -->
```

即 CAD 里建好模型,导出工具一键生成两种格式——**格式是给消费方选的**:要进 ROS 就用 URDF,要进 MuJoCo 仿真训练就用 MJCF。这只鸭子的训练栈(mjlab)与回放脚本(infer_policy.py)全在 MuJoCo 上,所以真正进入训练-部署闭环的永远是 MJCF 版。

## 结构差异:引用 vs 嵌套

URDF 是"扁平家谱":link(连杆)与 joint(关节)各自平铺,靠 parent/child 互相指认:

```xml
<joint name="head" type="revolute">
  <origin xyz="-0.00204165 -0 0.126" rpy="0 0 1.5708"/>
  <parent link="trunk"/>
  <child link="head"/>
  <axis xyz="0 0 1"/>
  <limit effort="10" velocity="10" lower="-1.5708" upper="1.5708"/>
</joint>
```

MJCF 则把关节直接写在子 body 体内(解读 196 的五层缩进树)。同一个事实,两种表达:URDF 的 `<limit>`(effort/lower/upper)对应 MJCF joint 的 `range` 与执行器的 `forcerange`;URDF 角度惯用弧度与米,MJCF 用 `compiler angle` 显式声明。信息量上 MJCF 更"厚":本项目 MJCF 版约 47KB、URDF 版约 27KB——多出来的正是 MuJoCo 特有的接触、阻尼、`<default>` 类与 `<keyframe>` 预设姿势,这些 URDF 根本没有对应物。

## 一个能看出定位差异的细节:IMU 怎么表示

URDF 没有传感器的位置,导出工具只能造假人:`<!-- Frame imu (dummy link + fixed joint) -->`——加一个什么都不连的 link,再用一个 fixed joint 固定到躯干上,凑出"IMU 装在这里"。MJCF 里则是一个一等公民:

```xml
<site group="3" name="imu" pos="-0.021 ... -0.0146984"/>
```

`<site>` 是专为"绑传感器/观测点"设计的元素,`<sensor>` 段直接引用它(framequat/gyro/accelerometer)。一个用补丁模拟,一个原生支持——这正是"通用交换格式"与"仿真原生格式"的定位差异:URDF 迁就整个 ROS 生态的最大公约数,MJCF 为物理引擎要算的东西(接触、传感器、执行器)专门建模。

## 为什么鸭子项目选 MJCF

三条真实证据链:①训练栈 mjlab 是 MuJoCo 的封装,MJCF 是唯一入口;②`kinematics/src/mjcf.rs` 的存在(解读 15)——代码里的几何要和 MJCF 逐位对齐;③逆向文档做硬件反推时,引的全是 MJCF 事实(`robot_walk.xml:235` 的 `jaw_soft` 刚体证明主控板在头里、IMU 站点绑定表)。URDF 版本在仓里更像"兼容性存档",证明想迁去 ROS 生态也有现成门票,但整条 RL 流水线一步都不需要它。

## 你带走的收获

- URDF 与 MJCF 描述同一台机器人,选哪个取决于下游:ROS 用 URDF,MuJoCo 用 MJCF。
- 结构上 URDF 靠 parent/child 引用,MJCF 用嵌套 body 树;`limit` 与 `range`/`forcerange` 一一对应。
- URDF 无 site/sensor/接触建模,IMU 只能靠 dummy link + fixed joint 凑;MJCF 原生支持。
- 本仓两条导出物同源(onshape-to-robot),但训练-部署闭环只用 MJCF。
- "格式厚薄"反映定位:交换格式求最大公约数,仿真原生格式为物理计算专门建模。

## 延伸

- MJCF 各段逐个拆:[解读 196](196-MJCF文件结构.md) · 代码与模型对齐:[解读 15](15-手部与模型对齐.md)
- 模型文件怎么变成可训练环境:[解读 137](137-testbench配置.md)(任务配置侧)
- 本地:`Microduck-build-tutorial/microduck/src/model/{urdf,mjcf}/`、`robot_walk.xml` 头部与 109 行 `site name="imu"`
