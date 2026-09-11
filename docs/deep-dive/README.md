# 深读 Microduck · 代码 / 结构 / 电路 / 舵机 解读系列

> 一个 60 篇的深度解读系列:逐文件、逐模块地读这个复刻项目里**真实存在的**代码与资源。
> 与《什么鸭公开课》(30 课,教学习方法)不同,这个系列是"拆开讲":每篇文章盯住一个真实的
> 源文件、一块板子或一个部件,讲它是什么、为什么这样设计、你能从中学到什么可迁移的知识。
>
> 每篇固定结构:**解读对象**(真实文件路径 + 规模)→ 逐段解读(引用真实的函数名、常量、参数)
> → 设计取舍(为什么这样写)→ **你带走的收获** → 延伸。
> 铁律不变:所有代码引用必须能在仓库里找到;数字必须有出处;没有证据的写"待验证"。

- 网页版:<https://duck.whatled.com/learn/deep>(由 `duck-whatled/build_learn.py` 自动发现 `docs/deep-dive/` 下的文章生成)
- 配套课程:先读[什么鸭公开课](/learn/course)建立框架,再来本系列深挖。

## 第一辑 · 运动控制核心(duck-control 逐文件)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 01 | bus.rs:一条 1 Mbps 总线上的 15 个对话 | `duck-control/src/bus.rs` | 50 Hz 里怎么调度 15 个舵机的读写 |
| 02 | obs.rs:61 维观测是怎么拼出来的 | `duck-control/src/obs.rs` | 真机观测与训练观测如何保持逐位一致 |
| 03 | policy.rs:ONNX 策略的加载、预热与校验 | `duck-control/src/policy.rs` | 一个 .pt 变成可靠部署件要过几道门 |
| 04 | safety.rs:安全层怎么写进代码 | `duck-control/src/safety.rs` | 超程/超温/失联时谁先踩刹车 |
| 05 | fall.rs:摔倒检测与起身 | `duck-control/src/fall.rs` | 姿态判据怎么区分摔倒与正常动作 |
| 06 | imu.rs:从 IMU 原始数据到姿态 | `duck-control/src/imu.rs` | 加速度计+陀螺仪怎么变成 61 维里的那几个数 |
| 07 | model.rs 与 io.rs:机器人描述与硬件 IO | `duck-control/src/model.rs`、`io.rs` | 关节编号/方向/零位如何集中管理 |
| 08 | lib.rs 与 crate 组织:控制库的分层 | `duck-control/src/lib.rs` | 一个控制库应该怎么分模块 |
| 09 | robotd/main.rs + control.rs:守护进程的控制循环 | `robotd/src/main.rs`、`control.rs` | 进程级怎么组织 50 Hz 主循环 |
| 10 | robotd/intents.rs:意图层 | `robotd/src/intents.rs` | 语音/手柄/程序怎么统一成"意图" |
| 11 | robotd/params.rs + robotd-params:参数系统 | `robotd/src/params.rs`、`robotd-params/` | 参数怎么版本化、怎么下到板子 |
| 12 | robotd/soc.rs + sound.rs + theremin.rs + chorale.rs:电池、声音与彩蛋 | `robotd/src/{soc,sound,theremin,chorale}.rs` | 电量监测与声音系统的工程做法 |

## 第二辑 · 感知、运动学与系统服务

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 13 | kinematics/math.rs:变换与向量工具 | `kinematics/src/math.rs` | 机器人数学的最小集 |
| 14 | kinematics/head.rs:头部 3 自由度运动学 | `kinematics/src/head.rs` | 往哪看的问题怎么解 |
| 15 | kinematics/hand.rs + mjcf.rs:手部与模型对齐 | `kinematics/src/hand.rs`、`mjcf.rs` | 代码里的几何怎么和 MJCF 对上 |
| 16 | odometry/lib.rs:里程估计 | `odometry/src/lib.rs` | 没有轮子怎么知道走了多远 |
| 17 | tof/sensor.rs + status.rs:ToF 传感器驱动 | `tof/src/sensor.rs`、`status.rs` | 8×8 ToF 点云的驱动写法 |
| 18 | updater(上):manifest 与验证 | `updater/src/{manifest,verify,preflight}.rs` | OTA 更新怎么保证不刷成砖 |
| 19 | updater(下):reconcile 与回滚 | `updater/src/{reconcile,orphan,faults}.rs` | 出错回滚的状态机 |
| 20 | configd + duckctl + duck-ipc-proto:配置、命令行与 IPC | `configd/`、`duckctl/`、`duck-ipc-proto/` | 板子上多个进程怎么协作 |

## 第三辑 · 训练代码逐段解读(microduck_rl)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 21 | tasks/__init__.py:任务注册表 | `microduck_rl/.../tasks/__init__.py`(278 行) | 任务名如何映射到配置类 |
| 22 | velocity 配置(上):前 87 行的开关与范围 | `.../microduck_velocity_env_cfg.py` | 全局开关、随机化范围怎么读 |
| 23 | velocity 配置(中):动作与观测 | 同上 193–638 行 | 14 动作、61/76 维观测的拼装 |
| 24 | velocity 配置(下):reward 与终止 | 同上 639–950 行 | 每一项 reward 在教什么 |
| 25 | mdp.py(上):observation 函数库 | `tasks/mdp.py`(7188 行)抽读 | 观测函数的写法模式 |
| 26 | mdp.py(下):reward 与事件函数库 | 同上抽读 | 奖励塑形的工程实现 |
| 27 | standup 配置:起身的课程设计 | `microduck_standup_env_cfg.py`(1159 行) | 摔倒起身怎么拆成课程 |
| 28 | sitstand 配置:坐下与站立的对称性 | `microduck_sitstand_env_cfg.py`(929 行) | 一对互逆动作怎么共用结构 |
| 29 | spin 与 roulade:特技动作的任务设计 | `microduck_spin_env_cfg.py`、`microduck_roulade_env_cfg.py` | 特技的评价函数长什么样 |
| 30 | ball_kick 与 ground_pick:带物体的任务 | `microduck_ball_kick_env_cfg.py`、`microduck_ground_pick_env_cfg.py` | 接触丰富任务的奖励设计 |
| 31 | symmetry.py 与 backlash.py:对称与齿隙 | `tasks/symmetry.py`、`backlash.py` | 左右对称镜像与齿隙建模 |
| 32 | export.py 与 infer_policy.py:导出与回放 | `scripts/export.py`、`scripts/infer_policy.py` | 部署件的最后一公里 |

## 第四辑 · 结构解读(从 STL 到工程件)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 33 | 47 个 STL 反推出装配体的方法 | `microduck-replica/docs/硬件方案逆向.md`(选读) | 没有图纸怎么逆向装配关系 |
| 34 | 躯干主体:装配基准件 | `microduck-replica-cad/组件图/01-躯干主体*.png` + 逆向文档 | 基准件上承载了什么 |
| 35 | 髋关节:pitch 与 roll 的轴线 | `组件图/02/03-左髋*.png` + 关节参数 | 两条轴线怎么布置 |
| 36 | 大腿与小腿:连杆设计 | `组件图/04/05-左*.png` | 连杆的刚度与走线空间 |
| 37 | 踝脚:落地点的设计 | `组件图/06-左踝脚*.png` | 脚底接触与摩擦的机械基础 |
| 38 | 头颈三自由度:191g 的配重艺术 | `组件图/07–10-头颈*.png` | 头重为什么是走路大敌 |
| 39 | M2 紧固件系统与热熔螺母 | `microduck-replica/docs/紧固件反推.md` | 孔特征反推出整套紧固件 |
| 40 | 轴承与公差:从仿真 STL 到工程件 | `docs/打印工艺调整表.md`、`硬件规格速查.md` | Ø22×16×4 / Ø15×10×3 用在哪 |

## 第五辑 · 电路解读(从原理图到上电)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 41 | 硬件方案逆向总览 | `microduck-replica/docs/硬件方案逆向.md` | 整机电控架构一张图 |
| 42 | Robot HAT C1:官方开源板怎么读 | pollen-robotics/elec_RPI_Robot_HAT(本仓引用)+ 逆向文档 | 官方 KiCad 工程里有什么 |
| 43 | imu_to_dxl:这块自绘板要解决什么 | `microduck-replica/docs/imu_to_dxl-设计包/` | IMU 数据如何伪装成总线设备 |
| 44 | LSM6DSV16X:IMU 芯片的读取路径 | 设计包内芯片资料引用 + 连接表 | 寄存器、SPI/I2C、CS 拉 3V3 的坑 |
| 45 | 电源树:8.4V 总线 / 5V 逻辑 / 舵机供电 | `docs/硬件规格速查.md` + 逆向文档 | 一块电池怎么分三路 |
| 46 | 半双工总线电平与转接板 | 设计包连接表 + 电控采购清单 | TTL 电平/针序为什么必须核对 |
| 47 | 接线表逐行解读 | `microduck-replica/hardware/imu_to_dxl/imu_to_dxl-接线表.md` | 网络名+引脚名的连接表方法 |
| 48 | LDO 与去耦:小芯片的大前提 | 设计包框图(HT75xx 一类) | 耐压 ≥25V 的由来 |
| 49 | 立创 EDA 打样流程实战 | `docs/电控采购清单.md` + 构建日志 09-06 | 从连接表到下单的全流程 |
| 50 | 供电冲突:2S 直供 vs 6V 舵机 | `docs/硬件规格速查.md` + 站点风险台账 | 上电前必须闭环的一号风险 |

## 第六辑 · 舵机与执行器解读

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 51 | Feetech HL-1910-C001 尺寸图解读 | 飞特尺寸图(HD-1910M-C001)+ `docs/执行器选型.md` | 换舵机要核对哪些尺寸链 |
| 52 | XL330-M288 vs HL-1910:参数逐项对比 | `docs/执行器选型.md`、BOM | 官方件与替代件的真实差距 |
| 53 | 舵机协议:Dynamixel 与 Feetech 寄存器 | `docs/硬件规格速查.md` + bus.rs 交叉引用 | 两家协议怎么映射到同一套代码 |
| 54 | BAM 是什么:执行器摩擦建模 | `bam/` 仓库结构 + `docs/换舵机重训全流程.md` | 为什么要给执行器建数学模型 |
| 55 | 单摆台架:辨识实验的物理设计 | `docs/换舵机重训全流程.md` | 摆动数据里藏着动力学参数 |
| 56 | M1–M6:从采集到拟合 | 同上 | 六个参数各自代表什么物理量 |
| 57 | 辨识结果如何进入仿真 | 同上 + MJCF 执行器段 | 模型参数写回仿真的路径 |
| 58 | 换舵机为什么必须重训策略 | `docs/换舵机重训全流程.md` 全文逻辑 | 官方 9 个 ONNX 降级为参考的原因 |
| 59 | 舵机 ID 分配与控制模式 | `硬件规格速查.md` + macOS 舵机指南交叉引用 | 15 个 ID 怎么排、位置/速度模式区别 |
| 60 | testbench:仿真-实物对照台 | `scripts/testbench_sim2real.py`、`validate_bam_testbench.py` | 辨识对不对,用什么验证 |

---

## 写作与维护

- 文件命名:`docs/deep-dive/NN-slug.md`,构建脚本自动发现并生成 `/learn/deep-NN`。
- 状态标记:✅ 已发布 / 🚧 更新中 / ⬜ 未开始(写完一篇在对应表格改一格)。
- 定期任务:每月校对数字与链接;若源码发生大版本变化,标记受影响篇目并重写。
