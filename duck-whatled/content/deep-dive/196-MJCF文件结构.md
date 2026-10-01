# 解读 196 · MJCF 文件结构

> **解读对象**:`mjlab_microduck/robot/microduck/robot_walk.xml`(`mjlab_microduck` 与 `microduck-replica/upstream/microduck_rl` 下各有一份)· MJCF 章节参见 `microduck-replica/docs/硬件方案逆向.md`
> **需要的前置**:[解读 195](195-什么是MuJoCo.md)(物理引擎在跑的就是这个文件);[解读 15](15-手部与模型对齐.md)(代码几何与 MJCF 对齐)。

## 一个 XML,一张"机器人的说明书"

MJCF(MuJoCo Modeling Format, MuJoCo 的模型描述格式)就是给物理引擎看的说明书:每个零件多重、重心在哪、关节往哪转、谁来驱动。文件第一行自报家门,还留了"出生证明"——它是从 Onshape CAD 自动导出的:

```xml
<mujoco model="microduck">
  <compiler angle="radian" meshdir="assets" autolimits="true"/>
  <!-- Generated using onshape-to-robot -->
```

注意 `angle="radian"`:整个文件的角度一律用弧度,和代码里的策略观测一致。

## worldbody / body:身体是嵌套的

MJCF 的骨架是**一层套一层的 `<body>`**,不像家谱图那样互相引用,而是直接把"孩子"写进"父母"体内。左腿这条链一共套了五层,缩进就是解剖结构:

```xml
<worldbody>
  <body name="trunk_base" pos="0 0 0.12">
    <freejoint name="trunk_base_freejoint"/>
    <body name="yaw2roll" ...>      <!-- left_hip_yaw -->
      <body name="hip_l" ...>       <!-- left_hip_roll -->
        <body name="upper_leg_left" ...>  <!-- left_hip_pitch -->
          <body name="leg" ...>     <!-- left_knee -->
            <body name="ankle_left" ...>  <!-- left_ankle -->
```

`worldbody` 是世界根节点;`trunk_base`(躯干)挂着 `freejoint`,即整个身体有 6 个自由度,会整体移动和翻倒——摔倒检测检测的就是它。

## inertial:每个零件的"身份证"

每个 body 必须知道自己的质量分布。真实的躯干一行:

```xml
<inertial pos="-0.0226332 -2.70828e-05 0.00280064" mass="0.199224"
          fullinertia="0.000123975 0.000145931 0.000115351 ..."/>
```

`mass="0.199224"` 即躯干约 199 克;`pos` 是重心偏移;`fullinertia` 是转动惯量张量(解读 164 讲过它的意义)。头部刚体 `jaw_soft` 的 `mass="0.188766"` 约 189 克——正是解读 165"头的 189g"的出处。**这些数字不是估的,是 CAD 算的**,仿真里每次摔倒的姿态都由它们决定。

## joint / geom / site / actuator:会动、会撞、会看、受控

- **joint**:每个 body 相对父体的运动方式。真实的膝关节一行:`<joint axis="0 0 1" name="left_knee" type="hinge" range="-1.5707963267948983 1.5707963267948948" class="chosen_actuator"/>`——绕 Z 轴的铰链,限位 ±π/2,`range` 就是代码里安全层的超程依据。
- **geom**:外形网格(visual 组只管好看,collision 组管碰撞),轴承 `seeed_bearing__configuration__22x16x4` 等每个零件都在场。
- **site**:绑传感器的"观测点"。`<site name="imu" .../>` 挂在 `trunk_base` 上;逆向文档强调:策略用的传感器**全绑躯干**,因为"角速度和投影重力只取决于 IMU 所固连刚体的姿态"。
- **actuator**:谁出力。文件末尾 14 个位置执行器:`<position class="chosen_actuator" name="left_hip_yaw" joint="left_hip_yaw"/>`,每个对应一个关节;`class="chosen_actuator"` 继承文件头 `<default>` 里的参数(kp 0.55、forcerange ±0.96——注意逆向文档提醒,forcerange 是仿真力限,不是厂商值)。

另有 `<sensor>` 段(framequat/gyro/accelerometer)和场景文件 scene.xml 里的 `<keyframe>`(STAND/SIT/FOLD 等预设姿势)。

## 你带走的收获

- MJCF 是嵌套的 body 树:缩进就是解剖结构,trunk_base 的 freejoint 让整机有 6 个自由度。
- inertial 的质量/重心/惯量来自 CAD,是仿真动态的全部依据;头 189g、躯干 199g 都可从此行读出。
- joint 的 range、actuator 的 forcerange 都在模型文件里,代码安全层与逆向分析都拿它当基准。
- site 决定传感器绑在哪个刚体上——绑错身体,sim-to-real 直接失配。
- 这份 XML 由 onshape-to-robot 从 CAD 自动生成:改机器人要回 CAD 改,不要手改导出物。

## 延伸

- MJCF 与 URDF 两个格式的比较:[解读 197](197-URDF对MJCF.md)
- 转动惯量与质心的物理课:[解读 164](164-转动惯量.md)、[解读 165](165-质心与配重.md)
- 本地:`.../mjlab_microduck/robot/microduck/robot_walk.xml`(84–92、113、217、411–426 行)、`microduck-replica/docs/硬件方案逆向.md`(IMU 绑定表)
