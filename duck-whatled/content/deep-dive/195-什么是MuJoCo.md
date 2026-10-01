# 解读 195 · 什么是 MuJoCo

> **解读对象**:`microduck-replica/upstream/microduck_rl/scripts/infer_policy.py`(1525 行,文件头自述"Run ONNX policy inference in MuJoCo with rendering")
> **需要的前置**:[解读 130](130-infer主流程.md)(回放主流程);[解读 181](181-强化学习是什么.md)(策略是怎么训练出来的)。

## 物理引擎:给机器人一个"练习场"

让鸭子真摔真坏地学走路,代价太大。**MuJoCo**(Multi-Joint dynamics with Contact,带接触的多关节动力学,通用背景)是一个物理引擎:你告诉它"机器人长什么样、多重、关节怎么连、地面多滑",它就能按物理定律一步步算出"接下来会发生什么"——重力拉它、脚底踩地、关节互相较劲。训练(在 mjlab/GPU 里)和回放(在 MuJoCo 里)都在这个练习场里进行,鸭子一百万次摔倒都不用买零件。

infer_policy.py 开头第一行就是练习场的入场券:

```python
MICRODUCK_XML = "src/mjlab_microduck/robot/microduck/scene.xml"
```

## infer_policy.py 用它做什么

这个脚本把"训练好的 ONNX 策略"放回物理引擎里开卷考试,五步全是 MuJoCo 的典型用法:

1. **加载模型**:`mujoco.MjSpec.from_file(xml_path)` / `MjModel.from_xml_path` 读入鸭子的 MJCF 描述;`MjData` 是这场仿真的"当前状态"(所有东西在哪、速度多少)。
2. **设置时钟**:`model.opt.timestep = 0.005`——物理每 5 毫秒推进一步;`decimation = 4` 即策略每 4 步才想一次,`control_dt = 0.02`,所以启动横幅打印 `Control frequency: 50 Hz (decimation: 4)`。
3. **读传感器**:策略要的观测不凭空给,而是从引擎"传感器"里取——`mj_name2id(..., "imu_ang_vel")` 找到 IMU 传感器,再从 `data.sensordata` 读数;关节位置/速度读 `data.qpos`/`data.qvel`。
4. **推理与施令**:61 维观测喂 ONNX,拿回 14 维动作,算出目标位置写进 `data.ctrl`(或 BAM 控制器的 `q_target`)。
5. **前进一步**:`mj_forward(model, data)` 更新状态;循环 1 秒约 50 次,配合 `mujoco.viewer` 你就能在屏幕上看鸭子走路(native 窗口 / viser 浏览器两条路)。

一个佐证"仿真不是儿戏"的细节:脚本还有 `--foot-friction`/`--foot-solref` 参数,专门调脚底接触的摩擦与软硬,用来排查"真机为什么前摔"——物理引擎里连鞋底都是一个可调的物理参数。

## 为什么仿真先行

构建日志给了最硬的证据。一句判断:"**仿真 STL 不是可打印工程件**——仿真只保证外形与惯量,不保证配合公差、螺纹、埋件座和走线空间",所以这只鸭子的机械件要按打印工艺重做;反过来,动作能力又是仿真里练出来的:用户问"3 万步为什么不会走",诊断是"回放是冻结权重的重放,不产生学习;真正差距是训练量"——CPU 续训 2000 迭代后 reward 从 0.80 涨到 12.77,回放 240 步零摔倒。**先仿真、后实机**,不是偷懒,是把会摔的试错放在便宜的世界里做完,再把幸存的策略(和验证过的模型文件)交给现实。

## 你带走的收获

- 物理引擎 = 可编程的练习场:模型(MJCF)+ 状态(MjData)+ 步进(mj_forward)三件套。
- 回放五步:载模型 → 定时钟(0.005s × 4 = 50Hz)→ 读传感器 → ONNX 推理 → 写 ctrl。
- 策略的观测来自仿真传感器,不是魔法:imu 角速度、qpos、qvel 都是引擎按物理算出来的。
- 仿真先行的价值:试错免费;但仿真模型(外形/惯量)与工程件(公差/螺纹)是两回事。
- "不会走"的答案常常是训练量,不是模型坏了——冻结权重回放不产生学习。

## 延伸

- 回放主流程逐段:[解读 130](130-infer主流程.md) · ONNX 是什么:[解读 194](194-什么是ONNX.md)
- 仿真里策略"看到"的世界:观测函数库 [解读 25](25-观测函数库.md)
- 本地:`scripts/infer_policy.py`(头部常量、`load_mujoco_with_bam`、`decimation = 4`)、`microduck-replica/构建日志.md`(expC 各条)
