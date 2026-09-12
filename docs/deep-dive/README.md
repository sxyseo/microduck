# 深读 Microduck · 代码 / 结构 / 电路 / 舵机 解读系列

> 一个 200 篇的深度解读系列:逐文件、逐模块地读这个复刻项目里**真实存在的**代码与资源。
> 与《什么鸭公开课》(30 课,教学习方法)不同,这个系列是"拆开讲":每篇文章盯住一个真实的
> 源文件、一块板子或一个部件,讲它是什么、为什么这样设计、你能从中学到什么可迁移的知识。
>
> 每篇固定结构:**解读对象**(真实文件路径 + 规模)→ 逐段解读(引用真实的函数名、常量、参数)
> → 设计取舍(为什么这样写)→ **你带走的收获** → 延伸。
> 铁律不变:所有代码引用必须能在仓库里找到;数字必须有出处;没有证据的写"待验证"。

## 从这里开始

- **完全新手**:先去读[什么鸭公开课](/learn/course)的前 2 课建立框架,然后回来自[解读 01](01-总线调度.md)按编号顺序读——十六辑的编排就是一条"控制核心 → 感知服务 → 训练代码 → 结构 → 电路 → 舵机 → 换舵机 → 电压 → 基础课"的坡道,每篇 5–10 分钟。
- **带着问题来**:直接用下面的目录表定位。常见入口——想看懂机器人的主循环:[解读 112](112-robotd控制循环.md);想换舵机:[解读 73](73-换舵机决策树.md);电压不一样怎么办:[解读 85](85-电压全景.md);想查某个舵机的参数:[解读 169](169-xl330参数精读.md) 起的案例库;卡在报错:[解读 193](193-读报错.md)。
- **只想查资料**:第 169–180 篇是 8 个舵机型号的参数案例库,第 178 篇有横向对比总表,第 200 篇是全项目知识图谱。

每篇文章的数字和代码引用都能在仓库里找到出处;发现讲得不清楚的地方,欢迎去[复刻仓库](https://github.com/fanhao375/microduck-replica)提 issue。

## 内容版图 · 200 篇在讲什么

**拆代码 · 80 篇**——机器人的软件是怎么写出来的:

- **第一辑 01–12 运动控制核心**:总线调度、61 维观测拼装、ONNX 策略加载、安全层、摔倒检测、姿态解算([解读 01](01-总线调度.md) 起)
- **第二辑 13–20 感知与系统服务**:运动学、里程估计、ToF 驱动、OTA 更新与回滚、配置与 IPC([解读 13](13-数学工具.md) 起)
- **第三辑 21–32 训练代码**:任务注册表、velocity 配置三段拆解、mdp 函数库、导出与回放([解读 21](21-任务注册表.md) 起)
- **第十~十二辑 95–142 逐函数精读**:上面这些文件的函数级下钻——每个函数讲签名、真实行号与设计取舍([解读 95](95-policy一Net与技能.md) 起)

**读硬件 · 28 篇**——机械、电路与舵机的真实设计:

- **第四辑 33–40 结构**:从 47 个 STL 反推装配体,躯干/髋/腿/踝脚/头颈逐个拆,紧固件与轴承([解读 33](33-装配反推方法.md) 起)
- **第五辑 41–50 电路**:电控架构、官方开源 HAT、imu_to_dxl 自绘板、电源树、打样全流程([解读 41](41-电控架构总览.md) 起)
- **第六辑 51–60 舵机与执行器**:尺寸链、协议寄存器、BAM 建模、单摆辨识、辨识进仿真与验证([解读 51](51-HL1910尺寸链.md) 起)

**换舵机与电压 · 46 篇**——"换成别的舵机怎么改?电压不一样怎么改?"的完整答案:

- **第七辑 61–72 HL-2915-C001 换装全流程**:七阶段路线,从单舵机台架六课、协议寄存器、ID 校准,到软件适配、辨识重训、整机部署([解读 61](61-HL2915是什么.md) 起)
- **第八辑 73–84 通用换舵机方法论**:决策树、选型六维、机械/电气/协议适配、五个参数落点、混装策略与总检查清单([解读 73](73-换舵机决策树.md) 起)
- **第九辑 85–94 电压专项**:三代舵机电压窗对照、电池节数的数学、代码里的 vin_range、过压保护、LDO/buck/UBEC、换电压改造清单([解读 85](85-电压全景.md) 起)
- **第十五辑 169–180 型号案例库**:xl330/xl320/STS3215/ST3025/MX-64/MX-106/eRob80 逐个参数精读 + 两篇端到端换装推演([解读 169](169-xl330参数精读.md) 起)

**小白基础课 · 46 篇**——零基础也能看懂上面所有内容:

- **第十三辑 143–156 电气课**:电压电流功率、万用表、蜂鸣档、LDO/buck、电容、上拉、UART/I2C/SPI、PCB、焊接、安全([解读 143](143-电是什么.md) 起)
- **第十四辑 157–168 机械课**:自由度、轴承、紧固件、打印材料与参数、公差配合、减速比、惯量、质心、CAD、装配、强度([解读 157](157-自由度与关节.md) 起)
- **第十六辑 181–200 基础课**:强化学习、策略网络、奖励设计、域随机化、TensorBoard、uv/Git、Rust 入门四讲、调试、ONNX/MuJoCo/MJCF/50Hz/PID,第 200 篇是全项目知识图谱([解读 181](181-强化学习是什么.md) 起)


---

## 第一辑 · 运动控制核心(duck-control 逐文件)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 01 | [bus.rs:一条 1 Mbps 总线上的 15 个对话](01-总线调度.md) | `duck-control/src/bus.rs` | 50 Hz 里怎么调度 15 个舵机的读写 |
| 02 | [obs.rs:61 维观测是怎么拼出来的](02-观测拼装.md) | `duck-control/src/obs.rs` | 真机观测与训练观测如何保持逐位一致 |
| 03 | [policy.rs:ONNX 策略的加载、预热与校验](03-策略加载.md) | `duck-control/src/policy.rs` | 一个 .pt 变成可靠部署件要过几道门 |
| 04 | [safety.rs:安全层怎么写进代码](04-安全层.md) | `duck-control/src/safety.rs` | 超程/超温/失联时谁先踩刹车 |
| 05 | [fall.rs:摔倒检测与起身](05-摔倒检测.md) | `duck-control/src/fall.rs` | 姿态判据怎么区分摔倒与正常动作 |
| 06 | [imu.rs:从 IMU 原始数据到姿态](06-姿态解算.md) | `duck-control/src/imu.rs` | 加速度计+陀螺仪怎么变成 61 维里的那几个数 |
| 07 | [model.rs 与 io.rs:机器人描述与硬件 IO](07-模型与IO.md) | `duck-control/src/model.rs`、`io.rs` | 关节编号/方向/零位如何集中管理 |
| 08 | [lib.rs 与 crate 组织:控制库的分层](08-crate分层.md) | `duck-control/src/lib.rs` | 一个控制库应该怎么分模块 |
| 09 | [robotd/main.rs + control.rs:守护进程的控制循环](09-主循环.md) | `robotd/src/main.rs`、`control.rs` | 进程级怎么组织 50 Hz 主循环 |
| 10 | [robotd/intents.rs:意图层](10-意图层.md) | `robotd/src/intents.rs` | 语音/手柄/程序怎么统一成"意图" |
| 11 | [robotd/params.rs + robotd-params:参数系统](11-参数系统.md) | `robotd/src/params.rs`、`robotd-params/` | 参数怎么版本化、怎么下到板子 |
| 12 | [robotd/soc.rs + sound.rs + theremin.rs + chorale.rs:电池、声音与彩蛋](12-电池声音与彩蛋.md) | `robotd/src/{soc,sound,theremin,chorale}.rs` | 电量监测与声音系统的工程做法 |

## 第二辑 · 感知、运动学与系统服务

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 13 | [kinematics/math.rs:变换与向量工具](13-数学工具.md) | `kinematics/src/math.rs` | 机器人数学的最小集 |
| 14 | [kinematics/head.rs:头部 3 自由度运动学](14-头部运动学.md) | `kinematics/src/head.rs` | 往哪看的问题怎么解 |
| 15 | [kinematics/hand.rs + mjcf.rs:手部与模型对齐](15-手部与模型对齐.md) | `kinematics/src/hand.rs`、`mjcf.rs` | 代码里的几何怎么和 MJCF 对上 |
| 16 | [odometry/lib.rs:里程估计](16-里程估计.md) | `odometry/src/lib.rs` | 没有轮子怎么知道走了多远 |
| 17 | [tof/sensor.rs + status.rs:ToF 传感器驱动](17-ToF驱动.md) | `tof/src/sensor.rs`、`status.rs` | 8×8 ToF 点云的驱动写法 |
| 18 | [updater(上):manifest 与验证](18-OTA清单与验证.md) | `updater/src/{manifest,verify,preflight}.rs` | OTA 更新怎么保证不刷成砖 |
| 19 | [updater(下):reconcile 与回滚](19-OTA回滚.md) | `updater/src/{reconcile,orphan,faults}.rs` | 出错回滚的状态机 |
| 20 | [configd + duckctl + duck-ipc-proto:配置、命令行与 IPC](20-配置与IPC.md) | `configd/`、`duckctl/`、`duck-ipc-proto/` | 板子上多个进程怎么协作 |

## 第三辑 · 训练代码逐段解读(microduck_rl)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 21 | [tasks/__init__.py:任务注册表](21-任务注册表.md) | `microduck_rl/.../tasks/__init__.py`(278 行) | 任务名如何映射到配置类 |
| 22 | [velocity 配置(上):前 87 行的开关与范围](22-velocity配置上.md) | `.../microduck_velocity_env_cfg.py` | 全局开关、随机化范围怎么读 |
| 23 | [velocity 配置(中):动作与观测](23-velocity配置中.md) | 同上 193–638 行 | 14 动作、61/76 维观测的拼装 |
| 24 | [velocity 配置(下):reward 与终止](24-velocity配置下.md) | 同上 639–950 行 | 每一项 reward 在教什么 |
| 25 | [mdp.py(上):observation 函数库](25-观测函数库.md) | `tasks/mdp.py`(7188 行)抽读 | 观测函数的写法模式 |
| 26 | [mdp.py(下):reward 与事件函数库](26-奖励函数库.md) | 同上抽读 | 奖励塑形的工程实现 |
| 27 | [standup 配置:起身的课程设计](27-起身课程.md) | `microduck_standup_env_cfg.py`(1159 行) | 摔倒起身怎么拆成课程 |
| 28 | [sitstand 配置:坐下与站立的对称性](28-坐下站立对称.md) | `microduck_sitstand_env_cfg.py`(929 行) | 一对互逆动作怎么共用结构 |
| 29 | [spin 与 roulade:特技动作的任务设计](29-特技任务.md) | `microduck_spin_env_cfg.py`、`microduck_roulade_env_cfg.py` | 特技的评价函数长什么样 |
| 30 | [ball_kick 与 ground_pick:带物体的任务](30-带物体任务.md) | `microduck_ball_kick_env_cfg.py`、`microduck_ground_pick_env_cfg.py` | 接触丰富任务的奖励设计 |
| 31 | [symmetry.py 与 backlash.py:对称与齿隙](31-对称与齿隙.md) | `tasks/symmetry.py`、`backlash.py` | 左右对称镜像与齿隙建模 |
| 32 | [export.py 与 infer_policy.py:导出与回放](32-导出与回放.md) | `scripts/export.py`、`scripts/infer_policy.py` | 部署件的最后一公里 |

## 第四辑 · 结构解读(从 STL 到工程件)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 33 | [47 个 STL 反推出装配体的方法](33-装配反推方法.md) | `microduck-replica/docs/硬件方案逆向.md`(选读) | 没有图纸怎么逆向装配关系 |
| 34 | [躯干主体:装配基准件](34-躯干基准件.md) | `microduck-replica-cad/组件图/01-躯干主体*.png` + 逆向文档 | 基准件上承载了什么 |
| 35 | [髋关节:pitch 与 roll 的轴线](35-髋关节轴线.md) | `组件图/02/03-左髋*.png` + 关节参数 | 两条轴线怎么布置 |
| 36 | [大腿与小腿:连杆设计](36-腿部连杆.md) | `组件图/04/05-左*.png` | 连杆的刚度与走线空间 |
| 37 | [踝脚:落地点的设计](37-踝脚落地点.md) | `组件图/06-左踝脚*.png` | 脚底接触与摩擦的机械基础 |
| 38 | [头颈三自由度:191g 的配重艺术](38-头颈配重.md) | `组件图/07–10-头颈*.png` | 头重为什么是走路大敌 |
| 39 | [M2 紧固件系统与热熔螺母](39-M2紧固件系统.md) | `microduck-replica/docs/紧固件反推.md` | 孔特征反推出整套紧固件 |
| 40 | [轴承与公差:从仿真 STL 到工程件](40-轴承与公差.md) | `docs/打印工艺调整表.md`、`硬件规格速查.md` | Ø22×16×4 / Ø15×10×3 用在哪 |

## 第五辑 · 电路解读(从原理图到上电)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 41 | [硬件方案逆向总览](41-电控架构总览.md) | `microduck-replica/docs/硬件方案逆向.md` | 整机电控架构一张图 |
| 42 | [Robot HAT C1:官方开源板怎么读](42-官方HAT解读.md) | pollen-robotics/elec_RPI_Robot_HAT(本仓引用)+ 逆向文档 | 官方 KiCad 工程里有什么 |
| 43 | [imu_to_dxl:这块自绘板要解决什么](43-imu_to_dxl使命.md) | `microduck-replica/docs/imu_to_dxl-设计包/` | IMU 数据如何伪装成总线设备 |
| 44 | [LSM6DSV16X:IMU 芯片的读取路径](44-IMU芯片路径.md) | 设计包内芯片资料引用 + 连接表 | 寄存器、SPI/I2C、CS 拉 3V3 的坑 |
| 45 | [电源树:8.4V 总线 / 5V 逻辑 / 舵机供电](45-电源树.md) | `docs/硬件规格速查.md` + 逆向文档 | 一块电池怎么分三路 |
| 46 | [半双工总线电平与转接板](46-半双工总线.md) | 设计包连接表 + 电控采购清单 | TTL 电平/针序为什么必须核对 |
| 47 | [接线表逐行解读](47-接线表逐行.md) | `microduck-replica/hardware/imu_to_dxl/imu_to_dxl-接线表.md` | 网络名+引脚名的连接表方法 |
| 48 | [LDO 与去耦:小芯片的大前提](48-LDO与去耦.md) | 设计包框图(HT75xx 一类) | 耐压 ≥25V 的由来 |
| 49 | [立创 EDA 打样流程实战](49-打样流程.md) | `docs/电控采购清单.md` + 构建日志 09-06 | 从连接表到下单的全流程 |
| 50 | [供电冲突:2S 直供 vs 6V 舵机](50-供电冲突.md) | `docs/硬件规格速查.md` + 站点风险台账 | 上电前必须闭环的一号风险 |

## 第六辑 · 舵机与执行器解读

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 51 | [Feetech HL-1910-C001 尺寸图解读](51-HL1910尺寸链.md) | 飞特尺寸图(HD-1910M-C001)+ `docs/执行器选型.md` | 换舵机要核对哪些尺寸链 |
| 52 | [XL330-M288 vs HL-1910:参数逐项对比](52-执行器对比.md) | `docs/执行器选型.md`、BOM | 官方件与替代件的真实差距 |
| 53 | [舵机协议:Dynamixel 与 Feetech 寄存器](53-舵机协议.md) | `docs/硬件规格速查.md` + bus.rs 交叉引用 | 两家协议怎么映射到同一套代码 |
| 54 | [BAM 是什么:执行器摩擦建模](54-BAM是什么.md) | `bam/` 仓库结构 + `docs/换舵机重训全流程.md` | 为什么要给执行器建数学模型 |
| 55 | [单摆台架:辨识实验的物理设计](55-单摆台架.md) | `docs/换舵机重训全流程.md` | 摆动数据里藏着动力学参数 |
| 56 | [M1–M6:从采集到拟合](56-M1到M6.md) | 同上 | 六个参数各自代表什么物理量 |
| 57 | [辨识结果如何进入仿真](57-辨识进仿真.md) | 同上 + MJCF 执行器段 | 模型参数写回仿真的路径 |
| 58 | [换舵机为什么必须重训策略](58-为什么必须重训.md) | `docs/换舵机重训全流程.md` 全文逻辑 | 官方 9 个 ONNX 降级为参考的原因 |
| 59 | [舵机 ID 分配与控制模式](59-ID分配与模式.md) | `硬件规格速查.md` + macOS 舵机指南交叉引用 | 15 个 ID 怎么排、位置/速度模式区别 |
| 60 | [testbench:仿真-实物对照台](60-testbench验证.md) | `scripts/testbench_sim2real.py`、`validate_bam_testbench.py` | 辨识对不对,用什么验证 |

---

## 第七辑 · 换装 HL-2915-C001 全流程(专辑)

| # | 标题 | 解读对象 | 核心问题 |
|---|---|---|---|
| 61 | [HL-2915-C001:它是什么,为什么值得一条专门路线](61-HL2915是什么.md) | `docs/HL-2915路线全流程教程.md` §0–1 + bench 脚本注释 | 三代舵机的定位对比与关键规格 |
| 62 | [从 2 只舵机到会走路的鸭子:七阶段路线](62-七阶段路线图.md) | 教程 §0 路线图 | 每阶段一个验收的工程意义 |
| 63 | [hl2915_bench.py:单舵机台架六课](63-台架六课.md) | `rl-series/scripts/hl2915_bench.py`(744 行) | 摸一颗新舵机的通用方法论 |
| 64 | [飞特磁编码协议:寄存器表逐段解读](64-磁编码协议.md) | bench 脚本寄存器表 + 协议内存表 220328 | 与 Dynamixel 的对照 |
| 65 | [设 ID、改波特率、校零位](65-ID与校准.md) | bench `set-id/set-baud/cal` | 哪一步会动、哪一步可逆 |
| 66 | [9–14V 意味着什么:电池与电源选型](66-供电选型.md) | 教程 §5.1 + bench 硬件前提 | 供电窗口倒逼架构重设计 |
| 67 | [全机电力拓扑:3S 电池怎么分三路](67-电力拓扑.md) | 教程 §5.2 | 断电接线与蜂鸣档复查 |
| 68 | [阶段 B/C:IMU 接入两条路与摄像头](68-IMU与摄像头.md) | 教程 §3–4 | 五步验证法 |
| 69 | [阶段 E:写 Feetech2915Io,改哪些文件](69-软件适配.md) | 教程 §6 代码地图 + `duck-control/src/io.rs` | 新协议适配的最小改动面 |
| 70 | [阶段 F:从阶跃 CSV 到新策略](70-辨识与重训.md) | 教程 §7 + `scripts/export.py` | 辨识→参数→冒烟→训练→导出 |
| 71 | [阶段 G:装配、部署与测试金字塔](71-整机部署.md) | 教程 §8 | 上电顺序与逐级验收 |
| 72 | [一次性投入与下一次换舵机](72-降本与验收.md) | 教程 §9–11 | 降本路线、故障速查、总验收 |

## 第八辑 · 通用换舵机方法论(换成其他舵机怎么改)

| # | 标题 | 解读对象 |
|---|---|---|
| 73 | [换舵机决策树:从需求到型号](73-换舵机决策树.md) | `bam/bam/params/`(8 型号库)总览 |
| 74 | [选型六维:扭矩/电压/编码器/协议/尺寸/价格](74-选型六维.md) | `docs/执行器选型.md` 方法论 |
| 75 | [机械适配:尺寸链与打印件修改](75-机械适配.md) | `硬件方案逆向.md` 尺寸章节 |
| 76 | [电气适配:插头/线序/调试板](76-电气适配.md) | `macOS舵机调试指南.md` §2 |
| 77 | [协议适配:Dynamixel 系(STS/SCS 兼容)](77-协议适配Dynamixel系.md) | `bam/bam/feetech/actuator.py`、`docs/硬件规格速查.md` |
| 78 | [协议适配:飞特系与厂商私有协议](78-协议适配飞特系.md) | `hl2915_bench.py` 协议表、`docs/新手学习文档.md` §12 |
| 79 | [参数适配:训练侧五个落点](79-参数适配五落点.md) | `microduck_constants.py`(`_BAM_ACTUATOR_KWARGS` 等) |
| 80 | [BAM 参数:m6.json 逐字段](80-BAM参数逐字段.md) | `bam/bam/params/xl330/m6.json` 等 |
| 81 | [策略影响评估:什么时候必须重训](81-策略影响评估.md) | `docs/换舵机重训全流程.md` §4 |
| 82 | [混装与渐进替换:一次换一只](82-混装与渐进替换.md) | `构建日志.md` 采购与门控 |
| 83 | [换舵机检查清单大全](83-换舵机检查清单.md) | 教程 §11 + 全流程 §2 汇总 |
| 84 | [案例复盘:HL-1910→HL-2915 的真实决策](84-案例复盘HL1910到HL2915.md) | `docs/HL-2915路线全流程教程.md` §9 + 构建日志 |

## 第九辑 · 电压专项(电压不一样怎么改)

| # | 标题 | 解读对象 |
|---|---|---|
| 85 | [电压全景:三代舵机窗口对照](85-电压全景.md) | `执行器选型.md` 电压真相章节 |
| 86 | [电池节数怎么定:1S/2S/3S 的数学](86-电池节数.md) | 教程 §5.1 + bench 硬件前提 |
| 87 | [代码里的电压:`vin_range` 与 BAM](87-代码里的电压.md) | `microduck_constants.py`、`bam/model.py` |
| 88 | [过压保护与 14 号寄存器](88-过压保护.md) | `hl2915_bench.py`(`--volt-max`)、接线表 |
| 89 | [LDO:从 12.6V 到 3.3V 的路径](89-LDO线性稳压.md) | `imu_to_dxl-设计包/` 框图 |
| 90 | [buck 降压:5V 逻辑从哪来](90-buck开关降压.md) | `硬件方案逆向.md` §四 |
| 91 | [UBEC 选择与电流计算](91-UBEC选择.md) | `电控采购清单.md` + 教程 §5.2 |
| 92 | [电压遥测与电量计:`BATTERY_FULL_V/EMPTY_V`](92-电压遥测与电量计.md) | `duck-control/src/model.rs` |
| 93 | [换电压的完整改造清单](93-换电压改造清单.md) | 三代舵机路线交叉汇总 |
| 94 | [电压事故与保护:经验案例](94-电压事故与保护.md) | `构建日志.md`、`macOS舵机指南.md` §2.2 |

## 第十辑 · duck-control 逐函数精读(非常详细的代码解读)

| # | 标题 | 解读对象 |
|---|---|---|
| 95 | [policy.rs(一):`Net` 与技能枚举](95-policy一Net与技能.md) | `duck-control/src/policy.rs`(811 行) |
| 96 | [policy.rs(二):`validate` 与加载门](96-policy二加载门.md) | 同上 |
| 97 | [policy.rs(三):推理路径与切换阈值](97-policyrs三推理阈值.md) | 同上 |
| 98 | [bus.rs(一):`transact` 帧层](98-busrs一transact帧层.md) | `duck-control/src/bus.rs`(708 行) |
| 99 | [bus.rs(二):sync_read 与慢速轮询](99-busrs二慢速轮询.md) | 同上 |
| 100 | [obs.rs(一):61 维观测逐位](100-obsrs一观测逐位.md) | `duck-control/src/obs.rs`(406 行) |
| 101 | [obs.rs(二):`scatter_action` 写回](101-obsrs二scatter写回.md) | 同上 |
| 102 | [safety.rs(一):`gate` 死手开关](102-safetyrs一gate.md) | `duck-control/src/safety.rs`(612 行) |
| 103 | [safety.rs(二):`apply` 与受限动作](103-safetyrs二apply.md) | 同上 |
| 104 | [fall.rs 全函数走读](104-fallrs全函数.md) | `duck-control/src/fall.rs`(272 行) |
| 105 | [imu.rs:SFLP 解码与滤波](105-imursSFLP解码.md) | `duck-control/src/imu.rs`(355 行) |
| 106 | [io.rs:trait 六方法逐个](106-iors六方法.md) | `duck-control/src/io.rs`(351 行) |
| 107 | [model.rs:常量、关节表与电池](107-modelrs常量.md) | `duck-control/src/model.rs`(241 行) |
| 108 | [hl2915.rs(一):`Hl2915Bus` 帧层](108-hl2915rs一帧层.md) | `duck-control/src/hl2915.rs`(620 行) |
| 109 | [hl2915.rs(二):`Hl2915RobotIo` 实现](109-hl2915rs二实现.md) | 同上 |
| 110 | [sim.rs:仿真 IO 后端](110-simrs仿真后端.md) | `duck-control/src/sim.rs`(441 行) |
| 111 | [robotd/main.rs(一):启动与参数](111-robotd启动与参数.md) | `robotd/src/main.rs`(8273 行)选段 |
| 112 | [robotd/main.rs(二):`control_loop` 全走读](112-robotd控制循环.md) | 同上 |
| 113 | [robotd/control.rs:`Controller` 抽象](113-robotd控制抽象.md) | `robotd/src/control.rs`(747 行) |
| 114 | [robotd/intents.rs:槽、快照与权力](114-robotd意图层.md) | `robotd/src/intents.rs`(703 行) |

## 第十一辑 · 服务与训练工具逐函数

| # | 标题 | 解读对象 |
|---|---|---|
| 115 | [params.rs 与 robotd-params crate](115-params系统.md) | `robotd/src/params.rs`、`robotd-params/` |
| 116 | [soc.rs:电池电量监测](116-soc电量.md) | `robotd/src/soc.rs`(84 行) |
| 117 | [sound.rs(一):播放管线](117-soundrs一播放管线.md) | `robotd/src/sound.rs`(947 行) |
| 118 | [sound.rs(二):合成与混音](118-soundrs二合成混音.md) | 同上 |
| 119 | [theremin.rs:特雷门琴彩蛋](119-theremin特雷门琴.md) | `robotd/src/theremin.rs`(489 行) |
| 120 | [chorale.rs(一):合唱结构](120-chorale一合唱结构.md) | `robotd/src/chorale.rs`(1320 行) |
| 121 | [chorale.rs(二):曲子数据与调度](121-chorale二曲子调度.md) | 同上 |
| 122 | [mdp.py(一):文件结构与公共设施](122-mdp一文件结构.md) | `tasks/mdp.py`(7188 行,254 函数) |
| 123 | [mdp.py(二):观测函数精选](123-mdp二观测函数.md) | 同上 |
| 124 | [mdp.py(三):reward 函数精选](124-mdp三reward函数.md) | 同上 |
| 125 | [mdp.py(四):事件与随机化函数](125-mdp四事件随机化.md) | 同上 |
| 126 | [mdp.py(五):命令与课程函数](126-mdp五命令课程.md) | 同上 |
| 127 | [microduck_constants.py 逐段](127-constants逐段.md) | `robot/microduck_constants.py`(275 行) |
| 128 | [export.py 全函数](128-export全函数.md) | `mjlab_microduck/export.py`(311 行) |
| 129 | [hf_jobs.py:云训练入口](129-hfjobs云训练.md) | `mjlab_microduck/hf_jobs.py`(483 行) |
| 130 | [infer_policy.py 主流程](130-infer主流程.md) | `scripts/infer_policy.py` |

## 第十二辑 · 任务配置与脚本逐文件

| # | 标题 | 解读对象 |
|---|---|---|
| 131 | [velocity reward 表逐项](131-velocity奖励表.md) | `microduck_velocity_env_cfg.py` 639–950 行 |
| 132 | [velocity 课程六门逐门](132-velocity课程.md) | 同上 781–910 行 |
| 133 | [velstand 配置精读](133-velstand精读.md) | `microduck_velstand_env_cfg.py` |
| 134 | [swizzle 配置精读](134-swizzle精读.md) | `microduck_velocity_swizzle_env_cfg.py` |
| 135 | [roller 家族四配置](135-roller家族.md) | `microduck_roller_*.py` |
| 136 | [slope_terrain.py:坡地生成](136-slope地形.md) | `tasks/slope_terrain.py` |
| 137 | [testbench_env_cfg.py](137-testbench配置.md) | `tasks/testbench_env_cfg.py` |
| 138 | [symmetry.py 全函数](138-symmetry全函数.md) | `tasks/symmetry.py` |
| 139 | [backlash.py 全函数](139-backlash全函数.md) | `tasks/backlash.py`(92 行) |
| 140 | [play_latest.py](140-playlatest.md) | `scripts/play_latest.py` |
| 141 | [crouch_pose_editor.py](141-crouch编辑器.md) | `scripts/crouch_pose_editor.py` |
| 142 | [testbench 双脚本函数级](142-testbench双脚本.md) | `scripts/testbench_sim2real.py`、`validate_bam_testbench.py` |

## 第十三辑 · 小白电气课

| # | 标题 | 解读对象 |
|---|---|---|
| 143 | [电是什么:电压/电流/功率(鸭子实例)](143-电是什么.md) | `新手学习文档.md` §12.1/§12.3 + 教程 §5.1 |
| 144 | [万用表怎么用](144-万用表.md) | 教程 §5.2 + `新手学习文档.md` §7/§9 |
| 145 | [蜂鸣档与通断检查](145-蜂鸣档通断.md) | 教程 §5.2 |
| 146 | [串联电池与节数计算](146-串联电池节数.md) | 教程 §5.1 |
| 147 | [什么是 LDO(线性稳压)](147-什么是LDO.md) | `imu_to_dxl-设计包/` |
| 148 | [什么是 buck(开关降压)](148-什么是buck.md) | `硬件方案逆向.md` §四 |
| 149 | [电容:去耦与储能](149-电容去耦储能.md) | 设计包 BOM |
| 150 | [上拉电阻:为什么悬空不可靠](150-上拉电阻.md) | `imu_to_dxl-接线表.md` |
| 151 | [半双工 UART 入门](151-半双工UART.md) | `bus.rs` + `hl2915_bench.py` |
| 152 | [I2C 入门](152-I2C入门.md) | 设计包连接表 |
| 153 | [SPI 入门](153-SPI入门.md) | 接线表 SPI 方案 |
| 154 | [PCB 是什么:层、走线、过孔](154-PCB是什么.md) | `hardware/imu_to_dxl/README.md` |
| 155 | [焊接入门](155-焊接入门.md) | `docs/硬件入门.md` |
| 156 | [静电、短路与安全习惯](156-静电短路与安全.md) | `新手学习文档.md` §10 |

## 第十四辑 · 小白机械课

| # | 标题 | 解读对象 |
|---|---|---|
| 157 | [自由度与关节类型](157-自由度与关节.md) | `新手学习文档.md` §6.2 |
| 158 | [轴承怎么选:两个规格的故事](158-轴承怎么选.md) | `docs/硬件规格速查.md` |
| 159 | [螺丝与紧固件体系](159-螺丝与紧固件.md) | `docs/紧固件反推.md` |
| 160 | [3D 打印材料:PLA/TPU/PETG](160-打印材料.md) | `docs/打印工艺调整表.md` |
| 161 | [打印参数:层高/填充/方向](161-打印参数.md) | 同上 |
| 162 | [公差与配合:测试片的数学](162-公差与配合.md) | 同上 + 构建日志 |
| 163 | [齿轮与减速比](163-齿轮与减速比.md) | `bam/bam/model.py`(执行器建模) |
| 164 | [转动惯量入门](164-转动惯量.md) | `docs/硬件方案逆向.md` 质量章节 |
| 165 | [质心与配重:头的 189g](165-质心与配重.md) | `microduck-replica/README.md` 装配结构 |
| 166 | [CAD 软件入门](166-CAD软件入门.md) | `microduck-replica-cad/README.md` |
| 167 | [装配设计:基准与顺序](167-装配设计.md) | `新手学习文档.md` §6.6 |
| 168 | [强度入门:材料失效](168-强度入门.md) | `docs/打印工艺调整表.md` |

## 第十五辑 · 其他舵机案例库(bam 8 型号 + PWM)

| # | 标题 | 解读对象 |
|---|---|---|
| 169 | [xl330:m6.json 逐字段](169-xl330参数精读.md) | `bam/bam/params/xl330/` |
| 170 | [xl320 案例研究](170-xl320案例.md) | `bam/bam/params/xl320/` |
| 171 | [feetech_sts3215(7.4V)案例](171-sts3215案例.md) | `bam/bam/params/feetech_sts3215_7_4V/` |
| 172 | [waveshare_st3025 案例](172-st3025案例.md) | `bam/bam/params/waveshare_st3025/` |
| 173 | [mx64 案例研究](173-mx64案例.md) | `bam/bam/params/mx64/` |
| 174 | [mx106 案例研究](174-mx106案例.md) | `bam/bam/params/mx106/` |
| 175 | [erob80_50 案例研究](175-erob80x50案例.md) | `bam/bam/params/erob80_50/` |
| 176 | [erob80_100 案例研究](176-erob80x100案例.md) | `bam/bam/params/erob80_100/` |
| 177 | [SG90:PWM 舵机台架六课](177-SG90台架.md) | `rl-series/scripts/pi_sg90_bench.py` |
| 178 | [八型号横向对比总表](178-八型号对比总表.md) | `bam/bam/params/` 全量 + `actuators.py` |
| 179 | [端到端推演:换成 STS3215](179-推演换STS3215.md) | 型号库 + 换舵机方法论(73–84) |
| 180 | [端到端推演:换成 MX-64](180-推演换MX64.md) | 同上 |

## 第十六辑 · 小白基础课(RL/工具/Rust)

| # | 标题 | 解读对象 |
|---|---|---|
| 181 | [强化学习是什么:从奖励说起](181-强化学习是什么.md) | `docs/course/02` 延伸、HuggingFace RL 课 |
| 182 | [策略网络:61→14 在学什么](182-策略网络.md) | `obs.rs`+`policy.rs` 交叉 |
| 183 | [奖励设计的艺术与陷阱](183-奖励设计艺术.md) | `mdp.py` reward 章 |
| 184 | [域随机化细讲](184-域随机化细讲.md) | `mdp.py` 随机化函数 |
| 185 | [TensorBoard 逐指标](185-TensorBoard逐指标.md) | `构建日志.md`、实验记录 |
| 186 | [Python 环境:uv 入门](186-uv入门.md) | `进阶学习文档.md` §1 |
| 187 | [Git 入门:commit 是证据](187-Git入门.md) | `30day README` 记录原则 |
| 188 | [Rust 入门(一):变量与所有权](188-Rust一所有权.md) | `duck-control` 代码实例 |
| 189 | [Rust 入门(二):Result 与错误处理](189-Rust二Result.md) | `io.rs` 的 `IoError` |
| 190 | [Rust 入门(三):trait 与泛型](190-Rust三trait.md) | `io.rs` 的 `RobotIo` |
| 191 | [Rust 入门(四):async 与 tokio](191-Rust四async.md) | `robotd/src/main.rs` 选段 |
| 192 | [调试程序:打印、断言与日志](192-调试程序.md) | `bus.rs` 日志实例 |
| 193 | [读报错的艺术](193-读报错.md) | `构建日志.md` 踩坑案例 |
| 194 | [什么是 ONNX](194-什么是ONNX.md) | `export.py` |
| 195 | [什么是 MuJoCo](195-什么是MuJoCo.md) | `infer_policy.py` |
| 196 | [MJCF 文件结构](196-MJCF文件结构.md) | `docs/硬件方案逆向.md` MJCF 章节 |
| 197 | [URDF vs MJCF](197-URDF对MJCF.md) | 同上 |
| 198 | [50Hz 控制环的由来](198-50Hz的由来.md) | `model.rs:80` 起 |
| 199 | [PID 控制入门:舵机内部的黑盒](199-PID控制入门.md) | `set_gain` 与 21/22 寄存器 |
| 200 | [第 200 篇:整个项目的知识图谱](200-知识图谱.md) | 全系列收束 |

## 写作与维护

- 文件命名:`docs/deep-dive/NN-slug.md`,构建脚本自动发现并生成 `/learn/deep-NN`。
- 状态标记:✅ 已发布 / 🚧 更新中 / ⬜ 未开始(写完一篇在对应表格改一格)。
- 定期任务:每月校对数字与链接;若源码发生大版本变化,标记受影响篇目并重写。
