# microduck-community-kit 使用教程：hls_servo_debugger 与舵机标定

[microduck-community-kit](https://github.com/jyg9/microduck-community-kit)
（作者 jyg9，Apache-2.0，非官方仓）是 Microduck 复刻社区最实用的补充套件：
三块可打样的 PCB、一套 imu_to_dxl 固件、官方 robotd 的飞特适配补丁、一份飞特协议中文整理，
以及本教程的主角——**hls_servo_debugger 网页版舵机调试器**。

它的标定功能正对口 HD-1910 装机流程：把调试器放到鸭子核心板上跑起来，
电脑浏览器打开，**一次接一颗，摆好姿态，逐颗校准**。本仓已于 2026-10-11 部署实测。

## 1. 套件里有什么

| 内容 | 说明 |
|---|---|
| `software/hls_servo_debugger` | 网页版飞特舵机调试器（Flask + pyserial），9 个功能页，见 §2 |
| `hardware/imu_to_dxl` | 身体传感器桥板 KiCad 源文件 + Gerber + BOM（对应 [IMU 集成教程](IMU集成教程-I2C直读与imu_to_dxl.md) 路径 A） |
| `hardware/banana_pcb` | 电池上方转接板 |
| `hardware/dxl_hub` | 身体集线器板 |
| `firmware/v1` | imu_to_dxl 的 GD32F303 固件（双 slot 在线升级 bootloader）+ 主机升级工具 `upgrade.py/package.py` |
| `firmware/v1/patches/` | 官方 robotd 0.16.0 的飞特适配补丁（171KB）+ `feetech.rs`；配套外部仓 [microduck_ft1910](https://github.com/jyg9/microduck_ft1910) 可直接编译 |
| `docs/飞特通讯协议说明.md` | 飞特 SCS·HLS 串行协议逐条中文整理，自己写驱动的最好中文资料 |
| `firmware/v1/host/tools/` | `servo_probe.py` 等独立探测脚本，不依赖调试器 |

## 2. hls_servo_debugger 是什么

Flask 网页应用，电脑/手机浏览器操作，`HLSBus` 直接收发飞特 SCS v1 帧。
九个标签页：01 连接与扫描 / **02 舵机初始化（标定）** / 03 实时反馈 / 04 位置控制 /
05 速度·电流·PWM / 06 参数配置 / 07 同步读写 / 08 寄存器·原始指令 / 09 内存表参考。

关键事实（逐项对照过源码）：

| 项 | 值 |
|---|---|
| Web 端口 | 8765（`--port` 可改） |
| 串口 | 核心板 `/dev/ttyS2`（run.sh 自动检测）；台面 USB 调试板 `/dev/ttyACM1` 是内置默认 |
| 波特率 | 默认 1 Mbps（码值 0）；`/api/auto_detect` 按 1M→115200→500k→…→38400 依次试 |
| 增益默认 | **Kp=32 / Kd=0**——不要把 robotd 里 XL330 的 gain=200 搬过来，1910 上会自激振荡（README 实测 5A / 74°C） |
| 标定持久化 | **不写任何文件**：结果写进舵机自身 EPROM 的 31 号"位置偏移"寄存器（带符号 16 位，BIT15 是方向位），每次写完立即上锁（55 号） |
| 坐标约定 | 4096 计数/圈，2048 = 关节零点，方向 −1，0.0879°/计数 |
| 15 关节 ID | 右腿 10–14、左腿 20–24、头颈 30–34（与 [HD-1910 指南 §7](URT2-HD1910接线组装与测试指南.md) 官方表一致）；IMU 桥板占一个总线 ID，precheck 会 ping 它但不碰它 |
| 保护 | 电压/过流保护默认**关闭**（保护触发即卸力，站立的鸭子会摔）；多圈默认关（行程写 0/4095 单圈） |

## 3. 部署到鸭子核心板（本仓实测步骤）

前提：核心板（Radxa Zero 3W / Armbian，aarch64）SSH 可达；robotd 占着 `/dev/ttyS2`。

```bash
# 1) 取代码（板子没 git 就在开发机 clone 后 rsync）
git clone https://github.com/jyg9/microduck-community-kit.git
rsync -a --exclude .venv --exclude __pycache__ --exclude .git \
  microduck-community-kit/software/hls_servo_debugger/  root@<板子IP>:/opt/hls_servo_debugger/

# 2) 依赖：建 venv，严格守 pyproject 的 Flask<3.0 pin（Armbian 需先 apt install python3-venv）
ssh root@<板子IP>
python3 -m venv /opt/hls_servo_debugger/.venv
/opt/hls_servo_debugger/.venv/bin/pip install "Flask>=2.2,<3.0" "pyserial>=3.5"
#   本仓实测：Python 3.13.5 + Flask 2.3.3 + pyserial 3.5

# 3) 无硬件自检（不碰串口）
cd /opt/hls_servo_debugger && .venv/bin/python -m hls_debugger.selftest

# 4) 停掉占用串口的 robotd，只读探测一遍总线（只发 PING/READ，舵机不会动）
systemctl stop robotd
.venv/bin/python hw_test.py --port /dev/ttyS2 --baud 1000000

# 5) 启动（--host 0.0.0.0 才能从电脑访问；headless 加 --no-browser）
nohup ./run.sh --host 0.0.0.0 --no-browser --serial /dev/ttyS2 >/var/log/hls-debugger.log 2>&1 &
```

电脑浏览器打开 **`http://<板子IP>:8765/`**。用完恢复：

```bash
pkill -f hls_debugger && systemctl start robotd
```

三条安全纪律：

1. **只在可信局域网开**——页面能给任何在线舵机写寄存器，服务本身没有鉴权；
2. **不要做成开机自启**，它和 robotd 抢同一条串口，谁在跑谁拥有总线；
3. 工具虽有绕开 robotd 串口排他锁的逻辑，但流程上**先 `systemctl stop robotd`**，别并行。

## 4. 逐颗标定的工作流（一次一颗，摆好就校）

总线上同一时刻只允许一个主站；两颗出厂 ID=1 的舵机一起上线会同时应答。
所以装机阶段一颗一颗来：

1. **接一颗**：该颗舵机从整机拔下（或装机时逐颗接），上电；
2. **01 连接与扫描**：串口 `/dev/ttyS2`、波特率 1M（新舵机扫不到就点自动探测）；
3. **03 实时反馈**：确认 PING 通、读数在刷——先建立"这颗是健康的"的事实；
4. **02 舵机初始化**，四种模式按场景选：

| 模式 | 做什么 | 什么时候用 |
|---|---|---|
| `cal` | 发厂商 CAL 指令，**把当前物理位置写成 2048**，同时改写 31 号偏移 | 关节已摆到结构零位，直接"此处为零" |
| `offset` | 按 home 姿态反解目标偏移有界搜索（容差 8 计数），失败自动回写原值 | 已有 home 角度表，想按姿态角标 |
| `mid` | 转到 2048 并保持（开扭矩），**不写 EPROM** | 装/对舵盘时找中位 |
| `none` | 不校准，只改 ID | 新舵机入场第一件事 |

5. **校验**：回 03 实时反馈看位置是否 = 2048（或目标计数）、方向对不对；
   04 位置控制页给 ±5° 小指令复核方向；
6. **改 ID + 贴标**：按官方关节表写入目标 ID（10–14/20–24/30–34），舵机标签的 ID 手写框
   写上编号；断电重上电后按新 ID 再 PING 一次；
7. 下一颗。

**标定写进舵机 EPROM 后就跟着舵机走**——调试器不产生任何文件。robotd 侧的
`/etc/robot/feetech-ft5/hd1910-calibration.toml`（zero_raw/direction/min_rad/max_rad、
`motion_enabled` 门控）仍按 [HD-1910 指南 §8](URT2-HD1910接线组装与测试指南.md) 与
kissqy 中控的关节标定面板维护：调试器管"舵机自己的零位"，标定模板管"关节在整机里的零位、
方向与行程"，两份记录不要互相替代。

## 5. 红线（源码和 README 共同强调的）

- Kp 从 32 起步，别抄 XL330 的 200；
- 电压/过流保护默认关闭是**故意的**（保护=卸力=摔倒），代价是你必须靠电源限流和小步动作保护硬件；
- `/api/move` 只有数值钳位，**没有机械行程限制**——移动前确认结构不会撞；
- 一次只接一颗出厂舵机；RESET/CAL 在页面上都有确认弹窗，弹窗不是装饰；
- 写完 EPROM 的舵机已被上锁，改参数先解锁（55 号写 0），改完重新上锁。

## 6. 故障速查

| 现象 | 先查 |
|---|---|
| 扫描不到 | robotd 是否已停、串口号、波特率（自动探测）、线序（HD-1910 与 HL 相反，见 [HD-1910 指南 §4](URT2-HD1910接线组装与测试指南.md)） |
| 能连上一颗但写 ID 失败 | 写锁（55 号）：先解锁再写，写完把锁发给**新 ID**（旧 ID 已失聪） |
| 页面打不开 | 服务是否还在跑（`ss -tlnp | grep 8765`）、是否用了 `--host 0.0.0.0`、防火墙 |
| robotd 起不来 | 调试器是否还占着串口（`pkill -f hls_debugger` 再 `systemctl start robotd`） |

## 7. 文档地图

| 想深入哪块 | 去读 |
|---|---|
| 调试器 README（15 关节表、四种校准、真机实测记录） | `software/hls_servo_debugger/README.md`（38KB） |
| 飞特协议中文逐条整理 | `docs/飞特通讯协议说明.md` |
| 官方 robotd 打飞特补丁 | `firmware/v1/patches/` + [microduck_ft1910](https://github.com/jyg9/microduck_ft1910) |
| imu_to_dxl 桥板两条路径 | [IMU 集成教程](IMU集成教程-I2C直读与imu_to_dxl.md) |
| HD-1910 台架验收与标定门控 | [URT2 + HD-1910 指南](URT2-HD1910接线组装与测试指南.md) |
| 本仓自有的只读探针/REBOOT 清锁脚本 | `microduck-replica/rl-series/scripts/hd1910_*.py`（工作区文件） |

---

*致谢：hls_servo_debugger 与套件内固件/硬件由 jyg9 开源（Apache-2.0）。本教程的部署步骤
在 Radxa Zero 3W + HD-1910 总线上实测于 2026-10-11。*
