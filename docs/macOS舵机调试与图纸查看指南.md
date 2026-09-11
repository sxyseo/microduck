# macOS 舵机调试、ID 设置与图纸查看手册

> 回答三个问题：① Mac 上怎么调试舵机？② 怎么给舵机设置 ID？③ 各类图纸/电路图用什么软件看？
> 前置：[新手学习文档](新手学习文档.md)（概念）、[进阶篇](进阶学习文档-训练仿真与部署.md)（训练与部署）。
> 本手册只讲 macOS 实操，所有路径都对应你工作区里的真实文件。

---

## 0. 一张表先回答全部问题

| 你想干的事 | 硬件怎么连 | Mac 上用什么软件 |
|---|---|---|
| 调试 SG90（PWM 舵机） | Mac 无法直连 GPIO —— 用你手头的 **Pi 2 当代理**，Mac 只负责 `ssh` | 终端（ssh/scp）、VS Code Remote-SSH |
| 调试 Dynamixel（XL330） | **U2D2**（官方 USB 调试板）+ 独立供电 | **Dynamixel Wizard 2.0 有官方 macOS 版**（免费） |
| 调试 Feetech（STS/HL-1910） | **FE-URT-1**（¥45）等 USB 调试板 | macOS 上用 Python SDK；FD 图形软件是 Windows 的（见 §3.1 的三个替代） |
| 给总线舵机设 ID | 任意 USB 调试板，**一次只接一只** | Wizard（Dynamixel）或 SDK（Feetech），见 §4 |
| 看原理图/PCB/说明书 PDF | — | macOS 自带「预览 Preview」 |
| 打开 .eprj2（嘉立创工程） | — | 嘉立创 EDA 专业版（有 macOS 客户端，免费） |
| 打开官方 HAT 的 KiCad 工程 | — | KiCad 9 for Mac（免费） |
| 看 STL/STEP 三维文件 | — | 浏览器开 3dviewer.net（零安装）；要测量改 FreeCAD |

**一个核心认知先建立**：Mac 在整个项目里的角色是"指挥室"（终端、上位机软件、编译器），不是"接线台"。它没有 GPIO，也永远不要把舵机电源接到 Mac 的 USB 口上。

---

## 1. 调试 SG90：Pi 2 方案（本周就能做，¥0）

### 1.1 为什么必须经过 Pi

SG90 是 PWM 舵机：它需要一根线上的**精确脉冲**（0.5–2.5ms 脉宽对应角度）来指挥。Mac 没有任何能输出这种脉冲的接口。你的 Pi 2 有 40 个 GPIO，且仓库里已经写好了教学脚本。

### 1.2 准备（半小时）

1. Pi 2 刷 Raspberry Pi OS（用官方 Imager，刷时设置好用户名密码；没有屏幕就用 Imager 的 "Configure OS" 预开启 SSH）；
2. Pi 2 没有无线网卡 —— **插网线**到路由器；
3. Mac 上验证连通：

```bash
ssh 你的用户名@raspberrypi.local
# 解析不了就去路由器后台查 IP，用 ssh 用户名@192.168.x.x
```

### 1.3 接线（改线前永远先断电）

照 [pi_sg90_bench.py](../microduck-replica/rl-series/scripts/pi_sg90_bench.py) 头注释：

```
SG90 橙线(信号) → GPIO 17 / 27 / 22 / 23 / 24（BCM 编号，物理引脚见 pinout.xyz）
SG90 红线(电源) → 外接 5V≥3A 电源正极     ⚠️ 绝不要接 Pi 的 5V！
SG90 棕线(地)   → 外接电源负极，并且和 Pi 的 GND 至少连一根线（共地！）
```

没有 5V 大电流电源？**4 节 AA 电池盒（≈6V）对 SG90 完全安全**（SG90 规格 4.8–6V），而且自带共地问题也简单——电池负极接 Pi 的 GND 即可。

### 1.4 跑四课实验

```bash
# Mac 上把脚本拷到 Pi
scp ../microduck-replica/rl-series/scripts/pi_sg90_bench.py 用户名@raspberrypi.local:~/

# ssh 进 Pi 后逐课跑
python3 pi_sg90_bench.py 1   # ① 单舵机扫角：接线和行程对不对
python3 pi_sg90_bench.py 2   # ② 负载保持：挂 100–200g，听扫齿、摸温度
python3 pi_sg90_bench.py 3   # ③ 六舵机波浪：供电扛不扛得住
python3 pi_sg90_bench.py 4   # ④ 开环漂移：命令 90° 后手指捏住输出轴
```

第 ④ 课是整个台架的灵魂：**你捏住舵机轴，软件读到的"位置"永远是它自己写进去的 0.5——真实角度无人知晓。** 这就是鸭子必须用带编码器的总线舵机的全部理由，亲眼看一次胜过读十遍。

小技巧：Mac 装 VS Code + Remote-SSH 插件，就能在 Mac 上直接编辑 Pi 里的脚本，体验和本地一样。

---

## 2. 总线舵机调试：硬件与供电

> 适用 XL330（Dynamixel）和 STS3215/HL-1910（Feetech）。这是第 2–3 周买回"USB 调试板 + 1 只总线舵机"之后的事。

### 2.1 买哪个调试板

| 路线 | 调试板 | 价格 | macOS 软件 |
|---|---|---|---|
| Dynamixel（保官方模型） | ROBOTIS **U2D2**（+ 建议配 U2D2 Power Hub 供电） | ≈¥200/套 | **Wizard 2.0 官方 Mac 版** ✅ |
| Feetech（省钱重训） | **FE-URT-1**（飞特官方店）或 ¥22–26 第三方 ST/SC 转接板 | ¥22–45 | 图形软件是 Windows 的，见下 |

来源：[电控采购清单](../microduck-replica/docs/电控采购清单.md)（含淘宝实链）、[Microduck-build-tutorial BOM](../microduck-build-tutorial/README.md)。

**Feetech 舵机 + 没有图形软件的三个替代**（按省事排序）：
1. **Python SDK**：Feetech 官方 SCServo SDK（GitHub 上有 Python 版），Mac 终端直接跑，扫 ID、改 ID、读角度几行代码的事；
2. **在 Pi 上跑**：把调试板插 Pi，用 SDK/串口调试，Mac ssh 过去——和 SG90 台架同一套工作流；
3. **借一台 Windows 笔记本用一次**：装 Feetech 的 FD 软件设完 ID 就还回去（设置 ID 是一次性工作，借一次不亏）。UTM 虚拟机装 Windows 也能跑但 USB 透传对新手偏玄学，不作为首选。

### 2.2 供电与共地（本节最重要）

**USB 调试板只传数据，不供电。** 舵机必须独立供电：

| 台架对象 | 供电方案 |
|---|---|
| 1–2 只 XL330 | 4×AA 电池盒（6V）✅ 最简单；或 2S 锂电（7.4V，XL330 规格 5.0–7.4V）；或可调电源 6V |
| Feetech STS/SCS | 同上，多数规格 6–8.4V，按 datasheet |
| SG90 | 4×AA 或 5V≥3A |

**共地铁律**：调试板（U2D2/FE-URT-1）的 GND 必须和舵机电源的 GND 连通。用 U2D2 Power Hub 则自动完成；手动接线就拿一根杜邦线把电源负极和调试板 GND 连起来。**忘了共地 = 扫描不到舵机或乱码**，这是新手第一大故障。

上电顺序：接完线 → 万用表通断档确认电源正负没短路 → 先给舵机上电 → 再插 USB。改任何线之前断电。

### 2.3 macOS 串口准备（一分钟）

```bash
# 插上 USB 调试板后：
ls /dev/tty.usb*
# 应看到 /dev/tty.usbserial-XXXX（U2D2/FTDI 芯片）或 /dev/tty.usbserial-XXXX（FE-URT-1）
```

- 没出现 → 换根 USB 线试试（有些线只能充电），再装 [FTDI 官方 VCP 驱动](https://ftdichip.com/drivers/)（Apple Silicon 兼容）；
- 出现了就别用 `screen` 命令去调 1Mbps——macOS 的 `screen` 波特率上限不够，**总线调试一律用 Wizard 或 Python（pyserial 支持 1Mbps）**。

---

## 3. 用 Dynamixel Wizard 2.0 调试（Dynamixel 路线）

1. **安装**：ROBOTIS 官网 Support → Software → 下载 **DYNAMIXEL Wizard 2.0 macOS 版**（免费 dmg），拖进应用程序；
2. **连接**：打开 Wizard → 上方齿轮/Options → 勾选你的端口（`/dev/tty.usbserial-XXX`）→ 协议勾 **2.0** → 波特率先只勾 **57600** → OK；
3. **扫描**：点 Scan。**第一次必须用 57600** —— XL330 出厂默认波特率就是它，1Mbps 是你待会儿要改上去的参数。扫不到换波特率再扫；
4. 找到舵机后左侧出现设备树，点开就是 **Control Table**（一张"寄存器表格"：ID、波特率、当前位置、温度、电压……总线舵机的全部秘密都在这张表里，每一行都能读能写）。

之后按第 4 节设置 ID。日常调试好用的几行：Control Table 里实时看 **Present Position/Velocity/Temperature/Voltage**，手转舵机轴看位置数字变化——这就是"有反馈"和 SG90 的本质区别， wizard 里一眼就懂。

---

## 4. 设置舵机 ID（重点）

### 4.1 先懂概念

总线上所有舵机共享一根线，靠 **ID（门牌号）** 区分"这句话是喊谁的"。ID 冲突 = 两只舵机同时应答 = 总线瘫痪。所以有两条铁律：

> **铁律一：总线上同时只允许存在一只"还没设好 ID"的舵机。**
> **铁律二：每设好一只，断电、贴标签，再接下一只。**

原因：XL330 和 STS3215 出厂都是 ID=1。如果你把两只出厂舵机一起挂上总线，两只都抢着应答，谁也通信不了，新手会以为板子坏了。

### 4.2 Wizard 里改 ID 的精确操作

在 Control Table 找到这几行（括号内是寄存器地址），逐项改：

| 项目 | 出厂值 | 改成 | 为什么 |
|---|---|---|---|
| **ID** (3) | 1 | 目标 ID（见 4.3 的表） | 门牌号 |
| **Baud Rate** (4) | 57600 | **1000000** | 运行时全总线 1Mbps |
| **Return Delay Time** (5) | 250 | **0** | 出厂 250=500µs 延迟，16 台设备一 tick 白吃 8ms（40% 预算！），官方运行时要求写 0（出处：`duck-control/src/model.rs`） |
| PWM Slope | 255 | 255（不用改） | 推荐参数 |
| **Shutdown** (18) | 含 Input Voltage Error | **去掉电压错误触发** | 电池带载电压波动会误停机（出处：build-tutorial README） |

改完 ID 后 Wizard 会用新 ID 重连。**断电 → 在舵机机身贴标签写上 ID → 接下一只出厂舵机 → 重复。** 15 只大约一个傍晚设完，别偷懒跳过贴标签——两周后你不会记得哪只是 13 号。

### 4.3 目标 ID 表（两条路线，选一条就别混用）

**官方/复刻路线**（Radxa Zero 3W + 官方 Rust 运行时——你的路线）：

| ID | 部位 | ID | 部位 |
|---|---|---|---|
| 10–14 | 右腿（髋yaw/roll/pitch、膝、踝） | 20–24 | 左腿（同序） |
| 30–34 | 颈/头 yaw·roll·pitch/嘴 | 200 | IMU 板（自己画的 imu_to_dxl，不是舵机） |

出处：[硬件规格速查](../microduck-replica/docs/硬件规格速查.md)。

**平价教程路线**（Pi Zero 2W + OpenRB-150，仅作对照）：ID 1–15（1=右踝…10=左踝…11–14=头颈，15=嘴），出处见 [Microduck-build-tutorial](../microduck-build-tutorial/README.md)。

装错表的后果：部署代码按 ID 找关节，表混了 = 左腿当成右腿 = 一上电就劈叉。

### 4.4 Feetech 舵机设 ID

同样一次一只（出厂 ID 也是 1）。FD 软件里直接改 ID/波特率；Python SDK 里调 `WriteByte(ID, 5, new_id)` 一类的接口（不同 SDK 封装略有差异，照其 examples/ping 改）。飞特出厂 Return Delay 已是 0（出处：[电控采购清单](../microduck-replica/docs/电控采购清单.md) 注释）， baud 出厂 1Mbps，要改的主要就是 ID。改完同样贴标签。

### 4.5 SG90 没有 ID

PWM 舵机每只独占一根信号线，"地址"就是它插的 GPIO 脚号（17/27/22/23/24/25）——这也是 PWM 方案 15 只舵机要拉 15 根线、总线方案只要一根线的直观区别。

---

## 5. 图纸与电路图：文件类型 → macOS 软件

你仓库里的图纸共 8 种格式，一一对应：

| 文件（去哪找） | 是什么 | macOS 怎么开 | 要装软件吗 |
|---|---|---|---|
| `microduck-replica/hardware/imu_to_dxl/imu_to_dxl-原理图.pdf` / `-PCB.pdf` | 原理图/PCB 图 | **「预览」双击即开** | ❌ |
| `microduck-replica-cad/安装说明书/microduck装配安装说明书.pdf` | 21 页装配说明书 | 预览 | ❌ |
| `microduck-replica/assets/hw/Microduck硬件图集.pdf` | 7 张 A3 硬件图集 | 预览 | ❌ |
| `microduck-replica/hardware/imu_to_dxl/imu_to_dxl.eprj2` | 嘉立创 EDA 专业版工程（可编辑原理图+PCB+3D） | **嘉立创 EDA 专业版**（官网有 macOS 客户端），或网页版导入 | 免费 |
| 官方 HAT（github `pollen-robotics/elec_RPI_Robot_HAT`） | KiCad 9 工程 + Gerber | **KiCad 9 for Mac**（免费）；Gerber 也可拖进网页 tracespace.io 看 | 免费 |
| `cad/*.stl`、`print/打印件/*.stl` | 三维零件/装配体 | **浏览器开 3dviewer.net 拖入**（零安装）；要测量/剖切/改动 → **FreeCAD**（免费） | 浏览器即可 |
| `microduck-replica/hardware/imu_to_dxl/imu_to_dxl-PCB.step` | 电路板 3D 模型 | 3dviewer.net 或 FreeCAD | 浏览器即可 |
| `microduck-replica-cad/SolidWorks 源文件` | 可编辑装配体 | **不用装**——组件图已出成 PNG、说明书出成 PDF；非要打开装 **eDrawings for Mac**（官方免费查看器，只能看不能编） | 可不装 |
| `*.md`（接线表/BOM/构建日志） | 文本文档 | VS Code（推荐，装个 Markdown 预览） | 推荐 |
| `robot_walk.xml` 等 MJCF | 仿真模型（文本 XML） | VS Code 看结构 + `uv run scripts/infer_policy.py` 在 MuJoCo 里看动态 | 已有 |

**建议的阅读顺序**（配合新手篇第 5、6 节的读图五步法）：先看 [硬件规格速查](../microduck-replica/docs/硬件规格速查.md) 的系统框图（知道有哪些块）→ 接线表（知道每根线去哪）→ 原理图 PDF（块内怎么连）→ 嘉立创 EDA 打开工程（对照 3D 看 PCB）→ 装配爆炸图 PNG（机械侧）→ 21 页说明书（装配顺序）。

---

## 6. 一个周末的实操串联

**周六（SG90 日，¥0）**
1. Pi 2 刷机 + 网线 + ssh 通（1 小时）；
2. 接线四要点自查：信号脚号、外接供电、共地、断电改线（30 分钟）；
3. 跑四课脚本，第 ④ 课"开环漂移"务必做（1.5 小时）；
4. 构建日志记三条观察。

**周日（读图日，¥0）**
1. 「预览」打开硬件图集 PDF，看懂五个模块（40 分钟）；
2. 接线表 + 原理图 PDF 对照，把 23 个网络里电源类（VDD_BUS/VDD_F/+3V3/GND）四个吃透（1 小时）；
3. 3dviewer.net 打开一个腿部 STL 转着看，找 M2 过孔和轴承座（30 分钟）；
4. 有兴致：装嘉立创 EDA 打开 eprj2，看 PCB 3D 视图（30 分钟）。

**下周再花钱**：USB 调试板 + 1 只总线舵机（§2），按第 3–4 节扫描、读 Control Table、设 ID、贴标签。

---

## 7. 故障排查表

| 症状 | 按顺序查 |
|---|---|
| `ls /dev/tty.usb*` 什么都 没有 | 换 USB 线（很多线只能充电）→ 换口 → 装 FTDI VCP 驱动 |
| Wizard 扫描不到舵机 | ① 舵机电源有没有独立供？② 调试板和电源**共地**了吗？③ 波特率勾对了吗（新舵机 57600，设过的 1000000）？④ 总线上是不是挂了两只同 ID 舵机？⑤ 数据线插反没（Dynamixel 3pin 有方向） |
| 舵机烫手/发抖 | 立刻断电。查：供电电压超规格没、是否堵转（被结构卡死）、ID 冲突 |
| Pi 一动舵机就重启 | 供电不足——舵机电源绝不能取自 Pi 5V，独立 5V≥3A 或 4×AA |
| Wizard 能连，读数乱跳 | 共地不良（最常见）、杜邦线接触、波特率勉强 |
| `screen` 连不上 1Mbps | 正常，macOS screen 波特率上限不够——用 Wizard 或 Python |
| 改了 ID 但重启后又变回去 | ID 是写 EEPROM 的，Wizard 改完要确认写入成功（表里回读一下）；某些 SDK 要单独发 save/REG WRITE+ACTION |

---

*到这里，"Mac + Pi 2 + 一只舵机 + 一叠 PDF"就是你全部的实验环境——这套配置已经能完成台架、设 ID、读图三件事，而这些正是舵机大单到货前唯一需要准备的能力。*
