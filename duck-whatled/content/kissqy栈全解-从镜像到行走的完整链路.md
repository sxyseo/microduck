# kissqy 栈全解：从镜像到行走的完整链路

> 对象：kissqy/Microduck-kissqy 的 Public Image R1 一体镜像——刷进卡、连上 Wi-Fi、打开中控就能走的那只鸭，背后到底跑了什么。
> 本文不是"kissqy 官方文档"（它没有），而是把**官方 Microduck 0.15.1 底座 + kissqy 的飞特 HD-1910 适配层**从刷机到策略推理整条链路拆开讲清，全部命令可复现。
>
> 编写日期：2026-10-17。信息来源分三类标记，正文按此口径：
>
> | 标记 | 含义 |
> |---|---|
> | **实测** | 本站复刻鸭（官方骨架 + 15×HD-1910 + Radxa ZERO 3W）上真实执行过的操作与输出，2026-10-13–17 会话实录 |
> | **源码核对** | 在 kissqy 仓库源码中逐行读到的实现（给出文件路径） |
> | **转述** | 来自 kissqy 文档或社区套件（community-kit）实测记录、本站未独立复跑，使用时注明 |

## 0. 先分清四个版本号

开口问"你刷的什么版本"之前，先把这四个号分开——它们属于四个不同的东西：

| 版本号 | 属于谁 | 是什么 |
|---|---|---|
| **0.15.1** | 官方 Microduck 底座 | Pollen Robotics 官方系统基线，kissqy 栈的内核来源 |
| **control.40 / API40** | robotd（板上控制守护进程） | kissqy 编译的飞特 HD-1910 适配固件，`1fa8438-feetech-ft6-control.40` |
| **R17 V164（1.0.164）** | 电脑侧机器人中控 | 浏览器控制台，通过 SSH 操纵 Zero，页面 `http://127.0.0.1:8090` |
| **配网 R5** | 首次开机向导 | 热点 `Microduck-kissqy` + `http://10.42.0.1:8088` 配网页面 |

配套关系有约束：V164 中控随包的固件就是 control.40；训练中控 R1.5.27 是另一台电脑上的独立工具，不装在 Zero 上。核对版本用中控启动日志第一行：`[中控启动] R17 v1.0.164 · service · 默认显示启动四步、操作结果与失败原因`（**实测**）。

## 1. 栈总览：组件矩阵与安装布局

### 1.1 开机后 Zero 上跑着什么

`systemctl list-units` 实测（**实测**，标定模式下的状态）：

| 服务 | 职责 | 说明 |
|---|---|---|
| `robotd.service` | 控制守护进程 | 总线通信、标定、策略推理、IPC；**核心** |
| `padd.service` | 手柄意图客户端 | 50 Hz 把手柄输入翻译成 robotd 命令 |
| `gamesir-xboxd` | 手柄映射 | robotd 四步完成后拉起，盖世小鸡等手柄映射成 Xbox 键值（**实测** journal） |
| `mediad.service` | 摄像头与 WebRTC 网关 | 按需出流，API 40，生产者名 `duck-xxxx` |
| `tofd.service` | 头部 ToF 守护 | VL53L5CX 在 I²C 总线 3 的 0x29 |
| `btd.service` | BLE 传输适配 | |
| `configd.service` | 系统配置 | Wi-Fi、身份 |
| `updaterd.service` | 更新守护 | 标定模式下 inactive |
| `microduck-setup.service` | 首次配网 R5 | 一次性，配完即 dead |

### 1.2 文件都在哪

| 路径 | 内容 |
|---|---|
| `/opt/robot/feetech-ft5-r5/` | 运行时：`robotd`、`padd`、`mediad` 可执行文件与 `models/<哈希>/policy.onnx`（**实测** journal 的 exe 路径） |
| `/etc/robot/feetech-ft5/robotd.toml` | 主配置（bus、增益、策略槽，见 §6） |
| `/etc/robot/feetech-ft5/hd1910-calibration.toml` | 15 关节 + IMU 标定（见 §4，**实测**全文读回） |
| `/run/robotd.sock` | IPC 套接字，权限 660（**实测** journal） |
| 系统日志 | `journalctl -u robotd.service -b --no-pager -o cat` |

硬件前提：Radxa ZERO 3W + HAT（UART→半双工总线 `/dev/ttyS2`，IMU 走 I²C），总线上 15 颗 HD-1910（关节 ID `10–14 / 20–24 / 30–34`）+ IMU 桥（DXL ID 200）。总线上出现 ID 1 = 有出厂未编号的新舵机（**实测**：URT2 台架上 Ping ID 1 应答、15 关节 ID 无应答）。

## 2. 从零复现：刷机 → 配网 → 中控

### 2.1 刷镜像

Armbian Imager 选自定义镜像写入 TF 卡，无需手动解压 `.img.xz`。刷完校验 SHA256（镜像发布页有值，**转述** kissqy 发布说明）。

### 2.2 首次配网 R5

1. 手机连热点 `Microduck-kissqy`（密码 `12345678`）；
2. 自动弹出配网页，没有就访问 `http://10.42.0.1:8088`；
3. 填家庭 Wi-Fi + 新的系统密码（这就是之后 `radxa@` 的 SSH/sudo 密码）。

配网由 `microduck-setup.service` 一次性完成，配完即退（**实测**：`loaded inactive dead`，描述"R5 first-boot Wi-Fi onboarding"）。

### 2.3 电脑侧中控

完整解压 `Microduck-Console-R17-V164.zip`，进目录执行 `start.cmd`（Windows）或 `bash start.command`（macOS/Linux），浏览器自动开 `http://127.0.0.1:8090`。等价的手动入口：`python3 console.py --dashboard --feetech --open`（**源码核对** `console.py`：`--feetech` 决定 `service` 模式，日志里的 `· service ·` 就来自它）。

页面顶部填 `radxa@机器人IP` + 密码连接。中控用自带的 `ssh-askpass` 脚本把密码喂给 `ssh`——脚本读环境变量 `MICRODUCK_SSH_PASSWORD`（**源码核对** `ssh-askpass`，全文 8 行）。**macOS 坑（实测）**：解压后 `ssh-askpass` 常丢可执行位，报 `ssh_askpass: exec(...ssh-askpass): Permission denied`，`chmod +x ssh-askpass` 即修；另外 Chrome 的 Web Serial 会占住 URT2 的 `/dev/cu.*` 设备名导致串口 Errno 16，关掉占用网页即可。

中控只绑 `127.0.0.1`（**源码核对** `console.py`：`--bind` 非 127.0.0.1 直接报错拒绝，"为保护未认证的诊断数据"），远程用 SSH 隧道。

## 3. robotd 四步启动与两种模式

robotd 启动输出四步状态，中控"启动四步 1/4～4/4"就是它（**实测** journal 原文）：

```text
step 1  配置读取、实例锁、IPC socket、控制线程已启动
step 2  标定模式：读取已有标定，关闭并确认扭矩，初始化 IMU
        → 标定采集第一份有效反馈已读取
step 3  标定模式不加载策略模型
step 4  标定采集首个周期完成；运动策略关闭
随后    robotd 四步已完成；启动 padd → gamesir-xboxd
```

两种模式（中控页顶部按钮切换）：

| 模式 | robotd 状态 | 能做什么 |
|---|---|---|
| **标定模式 commissioning** | 扭矩 OFF、策略不加载、只读遥测 | 手摆关节、保存标定、台架调试 |
| **运动模式 motion** | 按标定跑控制环、可加载策略 | HOME、手柄行走与动作 |

切换会**先释放扭矩**（中控确认框原话："请确认机身有支撑；切换会先释放扭矩，完成后不自动 HOME 或启动策略"）。镜像自带有效标定时直接可切运动模式；`motion_ready` 与"本机保存的 15 关节标定与 IMU 已通过检查"来自管理面回读（**实测** SSH 输出 JSON）。

## 4. 控制链核心：一次关节角的全旅程

### 4.1 一个数学式子管全部

固件层关节角与舵机编码器 counts 的换算（**源码核对** `service_control.py:611`，与 community-kit 对 `feetech.rs` 的核对一致）：

```text
关节角(rad) = direction × (counts − zero_raw) × 2π / 4096
counts     = zero_raw + direction × 关节角 × 4096 / 2π
```

- 4096 counts = 一圈，1 count ≈ 0.0879°；
- `zero_raw`：该关节"关节角 0°"对应的编码器读数——**每关节一个**，来自标定文件；
- `direction`：+1/−1，HD-1910 在本装配下实测全为 **−1**（**转述** community-kit 方向核对；与标定文件实测一致）；
- 2048 只是编码器几何中心，**不是**装配零位（中控关节工作台原话："2048 是编码器中心，不是装配零位"）。

### 4.2 标定文件逐字段

`/etc/robot/feetech-ft5/hd1910-calibration.toml`（**实测**全文读回，摘录）：

```toml
motion_enabled = false          # 每次成功 capture 会置 false,需重新启用运动
imu_mount_verified = true       # IMU 安装确认(中控"保存安装确认")
imu_mount_quat = [0.0376, 0.7014, -0.0359, 0.7109]   # 传感器→躯干四元数,标量在前

[[joints]]
name = "left_hip_yaw"
id = 20
zero_raw = 2281                 # 该关节 0° 的编码器读数
direction = -1
min_rad = -0.4363               # 保存的软限位(−25°)
max_rad = 0.5236                # (+30°)
calibrated = true
```

15 个关节全部同构。零位因人而异：镜像内置的是 kissqy 那台鸭（duck-10e4）的装配值，你的鸭必须逐关节核对/重存——这正是"预装软件 ≠ 免标定"的原因。

### 4.3 标定保存（capture）的精确语义

中控"保存当前关节"发给 robotd 的 `capture`（**源码核对** `robotd/src/feetech_commissioning.rs`）：

```text
zero = 当前counts − direction × 已知角度/360 × 4096      # 已知角度=你手摆的姿势对应的关节角
校验1: zero ∈ [0, 4095]
校验2: min/max 两个限位端点 counts 也必须 ∈ [0, 4095]
      → 否则报 "joint limits cross the single-turn encoder boundary"
```

三条实测经验（**实测**，2026-10-14 会话踩坑）：

1. **起作用的是点击瞬间的读数**。标定模式无力，摆好姿势到点按钮之间关节会回弹；
2. **已知角度不必填 0**。把关节停在行程中段（counts 落在 1200–2900），填估算的已知角度（±5° 精度足够），零位照样算对，且天然不越界；
3. 已知角度必须在 [min, max] 之内、min < max（源码前置校验）。

capture 成功会**整份重写标定文件并置 `motion_enabled = false`**——所以每改一个关节都要重新"切到运动模式"。

### 4.4 两套坐标的对账：URT2 CAL ↔ 中控 capture

台面初始化（hls_servo_debugger，见 [microduck-community-kit使用教程](microduck-community-kit使用教程.md)）用 **CAL 把当前物理位置写成 2048**；整机标定（中控 capture）用 **zero_raw + direction** 两参数。对账闭环（**实测**流程）：

1. URT2 台架：舵盘对到装配基准位 → CAL（保存到 EPROM）→ 该关节零位读数恒为 2048；
2. 装回整机：中控 capture 已知角度填 0 → 算出 zero_raw = 2048，**永不触边界**；
3. 方向、限位在 capture 里一并保存；IMU 四元数单位长度校验后单独保存（`verify-imu`）。

## 5. IPC 调试面：/run/robotd.sock

robotd 对本机暴露 JSON-RPC（按行分帧）。最实用的只读盘点（**实测**命令）：

```bash
ssh radxa@鸭子IP
echo '123456789123456' | sudo -S python3 -c "
import socket
s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.connect('/run/robotd.sock')
s.sendall(b'{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"robot.busStatus\"}\n')
print(s.recv(65536).decode())"
# → {"result":{"build":"1fa8438-feetech-ft6-control.40","mode":"commissioning",
#             "phase":"configuring_bus","port":"/dev/ttyS2"}}
```

方法面（**源码核对** `main.rs` 分发表 + `feetech_commissioning.rs` BusCommand 枚举）：

| 方法/动作 | 作用 | 备注 |
|---|---|---|
| `robot.busStatus` | 构建/模式/相位快照 | 标定模式下**不含**关节数值 |
| `robot.busCommand` + `calibration-status` | 读回整份标定与未标定清单 | 无需运动模式 |
| `busCommand: relax / move / center / capture / verify-imu / reboot / shutdown` | 台架动作 | `move` 把舵机压到目标位后**再释放扭矩**；`center` 仅限未装配（需 `unassembled:true`） |
| `robot.startupSubscribe` | 订阅四步启动事件 | |
| `robot.subscribe` | 50Hz 遥测订阅 | **标定模式被拒**：`-32600 robotd is read-only`（**实测**） |

串口独占：robotd 用 `TIOCEXCL` 开 `/dev/ttyS2`，但 root 进程互相拦不住（**转述** community-kit 实测）——中控因此在连接前扫进程占用并返回 `409 port_busy`。想用调试器接管总线，先 `sudo systemctl stop robotd`，用完再 `start`。

## 6. 策略执行链：模型怎么变成动作

### 6.1 配置：robotd.toml 的策略段

镜像随包配置（**源码核对** `packaging/robotd-profile.toml`，部署时合并进 `/etc/robot/feetech-ft5/robotd.toml`）：

```toml
[bus]
port = "/dev/ttyS2"
feetech_calibration = "/etc/robot/feetech-ft5/hd1910-calibration.toml"
[control]
hz = 50
[policy]
custom_only = true            # 坏模型不回退官方——kissqy 明确改动
mode = "walk"
walk = "/opt/robot/feetech-ft5-r5/models/1cbf87.../policy.onnx"   # 7 个槽位,按模型哈希
gain = 5                      # 位置环 Kp——HD1910 实测整定值,不是官方 XL330 的 200
action_scale = 0.7            # 全局动作缩放
standing_action_scale = 1.0
[safety]
limp_fall = false
[[policy.skill]]              # 一次动作窗口:roulade 1.0s / 踢球 0.5s 等
name = "kick_left"
duration = 0.5
```

增益这条值得单独记：XL330 时代的 `gain = 200` 在飞特 0..254 标度上是顶格，会自激振荡（5 A、74 °C，**转述** community-kit 台架实测）；kissqy 镜像出厂给 **5**，URT2 初始化工具默认写 32/0——两边不一致时 robotd 接管后会按 toml 覆盖 RAM。

### 6.2 推理链（50 Hz 一拍）

```text
IMU + 15 关节反馈 ──> 拼 61 维观测(观测归一化已内嵌 ONNX) ──> policy.onnx
                                                            │ 14 维动作
HOME 姿态 + action_scale × 动作 ──> 头/腿低通 ──> 关节角目标
        ──> §4.1 的公式换成 counts ──> 位置环(gain) ──> 总线写目标
```

（**源码核对** R17-CHANGES：`control.rs` 按合同精确 HOME、训练倍率、EMA 解释，"最终动作继续通过官方全局缩放和头腿低通"；观测归一化 `embedded_in_onnx_once`，运行端不重复做——**转述**模型使用说明。）ONNX Runtime 1.28.0。

### 6.3 模型包与"上车"

随包 **10 个模型**：常规 6（walk 行走 / stand 站立 / sitstand 起坐 / ground_pick 捡取 / kick_left·kick_right 踢球 / roulade 前滚翻）+ 滑轮 4（swizzle 对称滑 / crouch 蹲下 / spin 原地转 / standup 倒地起身）。每个模型包结构统一（**源码核对** `packaging/models/<哈希>/`）：

```text
policy.onnx              # 交给 robotd 的推理图
checkpoint.pt            # 训练续训用,不能直接推理
manifest.json            # 官方 schema 2,只记参数
deployment-contract.json # 动作/观测顺序、Home、BAM 参数——robotd 按它校验
deployment-profile.toml  # 官方 [policy] 配置片段——合并进运行端,不整份覆盖
training-config.json     # 训练快照(环境/奖励/课程/齿隙/质量)
使用说明.md              # 口径:包内标定只作记录,不覆盖实机零点
```

自训模型上车两条路：① kissqy 训练中枢 R1.5.27（NVIDIA GPU + WSL2）导出 → 中控"模型管理"导入；② 自己的 PPO 管线（见 [HD1910仿真迁移与PPO训练教程](HD1910仿真迁移与PPO训练教程.md)）按同样包结构导出。要点：**电压补偿与增益沿用运行端现有配置**（模型包不管这两项）；`custom_only = true` 下坏模型不会被官方模型顶替。

## 7. 手柄与意图链：padd

padd 以 50 Hz 订阅手柄并翻译成 robotd 命令；`gamesir-xboxd` 先把通用手柄映射成 Xbox 键值。按键表（**转述** kissqy 中控文档，行走/捡取/踢球/滚翻/滑轮已**实测**）：

| 按键 | 行为 |
|---|---|
| Start（首次） | 执行 HOME；之后 = 策略启用开关（关闭时回 HOME） |
| 左摇杆 / 右摇杆 | 行走速度 / 目标航向（robotd 用 IMU 航向算误差） |
| A / X | 地面捡取 / 前滚翻 |
| RB / LB | 右脚 / 左脚踢球（0.5 s 单次动作窗口） |
| 十字下 / Y·B | 起坐切换 / 头部·身体姿态模式 |
| RT·LT | 鸭嘴与声音 |
| Select 短按 / 长按 2 s | 卸力 / 坐下卸力关机 |
| 滑轮：↑ 长按 3 s | 行走↔滑轮模式切换（A=蹲下；← 长按 2 s 切 A 动作；L3=倒地起身） |

安全语义有一条反直觉（**转述** community-kit）：**写目标位置会自动上扭矩**——"关闭扭矩"后再写位置会重新带电；卸力请在最后一次位置写入之后做。

## 8. 其余外设服务

- **摄像头**：`mediad` 常驻、按需出流——页面点"连接"才开始采集，最后一名观众退出即休眠；信令 8443，WebRTC 接收（**实测**：仅开系统不出流）。
- **ToF**：`tofd` 读 I²C 总线 3 的 0x29（VL53L5CX），集成与验收见 [ToF集成教程](ToF集成教程-I2C识别与tofd验收.md)。
- **IMU**：HAT 上的 LSM6DSV16X 走 I²C 直读（≈46 Hz），安装四元数在标定文件里，见 [IMU集成教程](IMU集成教程-I2C直读与imu_to_dxl.md)。
- **音箱/音频**：remote_audio + 鸭嘴发声单元（RT/LT 控制）。

## 9. 故障排查实录（每条都真实发生过）

| 症状 | 根因 | 修法 |
|---|---|---|
| 中控 SSH 报 `exec(ssh-askpass): Permission denied` | 脚本丢可执行位（解压/克隆常见） | `chmod +x ssh-askpass` |
| 标定保存报 `joint limits cross the single-turn encoder boundary` | 零位或限位端点 counts 出了 0..4095 一圈 | 用"行程中段 + 已知角度"保存法（§4.3）；或先 URT2 CAL 归中 |
| 关节自己猛甩/打印件损坏 | `move` 命令全扭矩驱动，大目标距+短时长 = 甩 | 台面上不用大步长 move；确认目标距当前 < 数十 counts 再动 |
| URT2 串口 `Errno 16 Resource busy` | 别的进程占着（Chrome Web Serial 占 cu 名） | 关占用方；工具侧查 tty/cu 两个名字 |
| 遥测订阅被拒 `-32600 robotd is read-only` | 标定模式本来就不给 50Hz 遥测 | 用 `calibration-status` 与单次读，不是故障 |
| 中控页面打不开 | 8765/8090 端口被占（本站曾撞上 microduck-studio） | 换端口或停占用进程 |

通用武器：`journalctl -u robotd.service -b --no-pager -o cat`；中控"导出启动诊断"（只读）。

## 10. 从零到行走：复现清单

1. 刷镜像 → 热点配网（§2）
2. 电脑装中控，`chmod +x ssh-askpass`，`radxa@IP` 连接，等四步 4/4（§2.3/§3）
3. 标定模式：逐关节"手摆 + 已知角度 + 方向 + 限位"保存（§4.3），IMU 安装确认
4. 核对 15/15 已保存、方向全 −1、3D 姿态与实物一致
5. 切运动模式（机身有支撑）→ 手柄 Start HOME → 保持 → 摇杆行走（§7）
6. 动作逐项验收：A 捡取、X 前滚翻、RB/LB 踢球、十字下起坐
7. 可选：滑轮模式、自训模型导入（§6.3）
8. 全程异常先 **Select 卸力**；长期不用 Select 长按关机

## 11. 边界声明

- **实测覆盖**：刷机配网、中控连接、标定闭环（含边界报错与两套坐标对账）、IPC 只读盘点、四步启动、总线点检、基础运动（前进/后退/横移）、首走影像。
- **源码核对但未真机复跑**：策略推理链细节、skill 时序、custom_only 回退语义、模型包合并行为。
- **转述未复跑**：增益 200→32 对比数据、56 号读数超圈事件、9/11 号多圈开关、19 号卸载条件出厂值。
- **未实测**：滑轮模式与四个 roller 模型、摄像头 WebRTC 多端、ToF 数据进控制回路。
- 标定模式扭矩虽 off，**写位置类命令会自动上扭矩**——任何驱动操作前先确认机械可以甩。
