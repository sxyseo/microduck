# IMU 集成教程：I²C 直读与 imu_to_dxl 总线桥

这份文档回答一个问题：**鸭子的姿态数据从哪来，怎么接、怎么验。**

鸭子身上有两颗 IMU，只有一颗真正进控制闭环：

| IMU | 在哪 | 谁用它 |
|---|---|---|
| BMI088 | 官方 Robot HAT 板载，I²C | 当前步态**不用它**——看见它不等于步态 IMU 已通过 |
| LSM6DSV16X | 外接模块，片上 SFLP 直接输出四元数 | 控制闭环的唯一姿态来源，主机不做姿态融合 |

LSM6DSV16X 进主机有两条运输路径，产出**同一份 12 字节载荷**（陀螺 6 字节 + 四元数 6 字节），
主机侧协议不变，差别只在物理传输：

```text
路径 A：imu_to_dxl 桥板 —— IMU 模块挂在小板上，小板"伪装成 ID 200 的舵机"，
        挂在舵机总线上，和 15 颗真舵机在同一次 sync_read 里被读回。
路径 B：I²C 直读 —— robotd 直接通过板载 I²C 总线读传感器，不占舵机总线 ID。
```

当前装机主线（HD-1910 + kissqy 适配）用的是**路径 B**，已部署上板实测 46Hz 实时；
路径 A 的设计与固件全部就绪，对应官方 XL330 路线的原始方案。两条路径的切换是
`robotd.toml` 里的一个配置项，不是代码改造。

## 1. 主机侧契约（两条路径共用）

这是固件/驱动唯一要对齐的东西，全部从上游 Rust 源码逐行核实
（出处：`microduck-replica/docs/imu_to_dxl-设计包/设计规格.md`）：

| 项 | 值 |
|---|---|
| 总线 ID（路径 A） | **200**，且不在 15 个舵机 ID（10–14/20–24/30–34）里 |
| 波特率/格式 | 1 Mbps，8N1，TTL 单线半双工（路径 A） |
| 读地址/长度 | **124 / 12 字节** |
| 主机超时 | 30 ms（单次 tick 的 sync_read 全程） |
| 块 0..6 | 陀螺 x/y/z，i16 小端原始计数，**量程锁定 ±500 dps**（主机按 17.5 mdps/LSB 换算） |
| 块 6..12 | SFLP 四元数 x/y/z，IEEE fp16 小端；w = √(1−x²−y²−z²) 主机自算 |
| 异常容错 | 无效四元数沿用上一好值（last_quat），不报错不跳变 |
| 一次事务 | 路径 A 时 15 舵机 + 本板共 16 台设备 |

**量程 ±500 dps 是硬契约**：固件若配了别的量程，主机读到的角速度整体错一个倍数，
观测向量直接污染。改任何 IMU 固件先核这张表。

## 2. 路径 A：imu_to_dxl 总线桥

### 2.1 一句话原理

让 IMU 伪装成一个 Dynamixel（或飞特）舵机：主机发标准读指令，桥板回 12 字节载荷。
主机不跑姿态融合——LSM6DSV16X 片上 SFLP（sensor fusion low power）直接出四元数，
桥板只做透传，不占第二条总线、不需要额外 UART。

### 2.2 硬件：自绘板的三条设计决策

设计包在 `microduck-replica/docs/imu_to_dxl-设计包/`（设计规格、原理图连接表、BOM、
固件源码俱全，画板照连接表连即可）。三个值得知道的决策：

1. **半双工用缓冲器，不用引脚原生单线**：STM32G031 的 TX 经 `SN74LVC1G126` 缓冲再上总线，
   OE 挂 10k 下拉 = **上电默认断开**，固件初始化完成才接通。15 颗舵机的总线，上电瞬间
   浮空引脚抢线是事故，不是瑕疵。
2. **不做电池电压测量**：主机直接读舵机自报电压（寄存器 144–146），桥板省掉 ADC 和分压。
3. **连接器 JST EH 2.5mm 3P**：与官方 HAT 及飞特线材同间距（早期设计误选 PH 2.0，已勘误）。

LSM6DSV16X 的 I²C 地址由 SA0 脚决定：接 GND = **0x6A**，接 VDD = **0x6B**。设计包的板
SA0→GND 用 0x6A；当前装机的模块（路径 B）实测在 **0x6B**。`i2cdetect` 扫不到时先查这个。

### 2.3 固件：两个分支，一个开关

| 分支 | 协议 | 用在哪 |
|---|---|---|
| `dxl_slave` | Dynamixel Protocol 2.0 从站，ID 200，读 124/12 | 官方 XL330 路线 |
| `feetech_slave` | 飞特 SCS v1 从站（PING/READ/SYNC_READ），主机测试 10/10 通过 | HD-1910 飞特总线 |

两个分支在 `main.c` 的 `IMU_PROTO` 双协议开关下切换，共享同一份 IMU 采样与载荷打包。
仓库内实现：`microduck-replica/docs/imu_to_dxl-设计包/firmware/`（STM32G031 版）；
community-kit 另有 GD32F303 版 `firmware/v1`（CMake + JLink + **双 slot 在线升级
bootloader** + 主机 `upgrade.py/package.py` 升级工具，见
[microduck-community-kit 教程](microduck-community-kit使用教程.md)）。

### 2.4 验收

1. 桥板单独上台架：`imu_probe`（官方路线探针）单独验收 ID=200——只读，不碰别的设备；
2. 挂上整机总线：16 台设备（15 舵机 + ID 200）一次 `sync_read` 全部应答，主机 30ms 预算内；
3. 读数合理性：静止时陀螺三轴接近 0（±500dps 计数下 |raw| < 几十），四元数模长 ≈ 1；
4. `robotctl health` 不再报 IMU 缺失/过期。

## 3. 路径 B：I²C 直读（当前装机主线，已上板）

### 3.1 它是什么

robotd 绕过舵机总线，直接通过核心板引出的 I²C 总线读 LSM6DSV16X。实现是 kissqy 适配的
`imu_i2c.rs`（`Microduck-kissqy/microduck-hd1910/firmware/duck-control/src/`），头注一句话：

> The FT6 bridge and this sensor produce the same 12-byte gyro/SFLP payload, but they are
> different physical transports. **This reader never claims ID 200.**

永不占 ID 200 是刻意的：舵机总线上没有这个 ID，sync_read 预算不被挤占，桥板坏了也不影响姿态。

### 3.2 配置三行 + 一个 systemd 放行

板上 `/etc/robot/feetech-ft5/robotd.toml` 的生效配置（2026-10-11 实录）：

```toml
[bus]
imu_source = "i2c_lsm6dsv16x"     # 可选值: "ft6"（总线桥）| "i2c_lsm6dsv16x"（直读）
imu_i2c_device = "/dev/i2c-pihat" # 官方 HAT 40-pin 上的 I²C 总线（3/5 脚）
imu_i2c_address = 107             # 0x6B，SA0 接 VDD 的模块
```

robotd 跑在 systemd 沙箱里（DeviceAllow 白名单），I²C 设备节点必须显式放行，
否则报权限错误且日志很隐晦。drop-in
`/etc/systemd/system/robotd.service.d/zzzz-i2c-imu.conf`：

```ini
[Service]
DeviceAllow=/dev/i2c-3 rw
DeviceAllow=/dev/i2c-pihat rw
```

改完 `systemctl daemon-reload && systemctl restart robotd`。

### 3.3 驱动内幕（读源码前先知道的四件事）

- **WHO_AM_I（0x0F）必须读到 0x70**，否则直接报芯片不匹配——接错总线/地址在 open 阶段就失败；
- 采样走片上 SFLP 的 **FIFO GAME 流**（tag 0x13），驱动做 FIFO 排干防延迟累积；
- 新鲜度有独立口径（imu_fresh 门控），中控 IMU 页显示来源标签 **「I²C LSM6DSV16X」** 与 live 徽标；
- **舵机容错**：舵机总线不在线时 IMU 独立运行（phase `servo_read_error`）；舵机一恢复，
  约 100ms 内自动补做扭矩确认转 `ready`，**不需要重启 robotd**。

### 3.4 验收

```bash
i2cdetect -y 3            # 或对应总线号：应见 0x6b（模块 SA0=VDD）或 0x6a
robotctl health           # phase ready，IMU 实时
# 中控 IMU 页：来源标签「I²C LSM6DSV16X」、状态 live、陀螺/四元数读数随姿态变化
```

实测基线：46Hz 实时（上电自启，无需人工干预）。

## 4. 安装方向核验（两条路径通用，是运动门控的一部分）

传感器装上不等于方向对了。方向没核验前 `imu_mount_verified` 必须保持 false，
`motion_enabled` 不开。五阶段（与 kissqy 标定门控一致）：

1. 传感器**刚性固定**到躯干（转动/挪动会直接污染观测）；
2. 正立：重力向量 ≈ `[0, 0, -1]`；
3. 翻转/低头：陀螺与重力**符号**与物理方向一致；
4. ±90° 转动：四元数连续，**无跳变**；
5. 全部通过后执行 `bus verify-imu --confirmed` 确认——注意标定文件里记录的 IMU 来源
   必须与 `robotd.toml` 的 `imu_source` 一致，打包校验会拒绝不一致的组合。

安装姿态的传感器→躯干旋转官方约定是**绕 Y +90°**（`imu_mount_quat = [0.7071, 0, 0.7071, 0]`）；
这个四元数用于方向修正，不能当 heading/pose 复位用。

## 5. 两条路径怎么选

| 场景 | 选 |
|---|---|
| 官方 XL330 路线 + 官方 HAT | 路径 A（dxl_slave 分支，ID 200）——官方原型方案 |
| HD-1910 飞特总线，且 imu_to_dxl 板已打样 | 路径 A（feetech_slave 分支） |
| HD-1910 + 官方 HAT 40-pin 引出的 I²C | **路径 B（当前装机主线的选择）**：不占总线 ID、不挤 16 台 sync_read 的 30ms 预算、少一块板少一个故障点 |
| 想要双保险 | 两路都留着：`imu_source` 一行切换；桥板做备份 |

## 6. 故障速查

| 现象 | 先查 |
|---|---|
| `i2cdetect` 看不到 0x6a/0x6b | 接线（3/5 脚 + 3.3V + GND）、上拉、SA0 电平决定地址（GND=0x6A，VDD=0x6B） |
| robotd 日志报 I²C 权限错误 | systemd drop-in 的 DeviceAllow 是否包含实际设备节点；`daemon-reload` 了吗 |
| WHO_AM_I 不匹配 | 地址错（0x6A vs 0x6B）、总线号错、模块不是 LSM6DSV16X |
| 四元数跳变/漂移 | 安装松动（先刚性固定）、温度骤变、FIFO 未排干（确认固件/驱动版本） |
| 陀螺读数整体偏大/偏小固定倍数 | 固件量程不是 ±500 dps——主机按 17.5 mdps/LSB 换算，硬契约 |
| 路径 A 下某 tick 超时 | 30ms 预算内 16 台没读完：查波特率、菊花链长度、桥板缓冲器 OE |
| health 里 IMU 一直 not fresh | `imu_source` 与实际硬件不符（配了 ft6 但板上是直读，或反之） |

## 7. 文档地图

| 想深入哪块 | 去读 |
|---|---|
| 设计包（原理图连接表/BOM/固件源码） | `microduck-replica/docs/imu_to_dxl-设计包/` |
| kissqy 直读驱动 | `Microduck-kissqy/microduck-hd1910/firmware/duck-control/src/imu_i2c.rs` |
| community-kit 的 GD32 固件、三块板、飞特协议中文文档 | [microduck-community-kit 教程](microduck-community-kit使用教程.md) |
| 官方 HAT 与两颗 IMU 的区别 | [新手学习文档 §12.1](新手学习文档.md) |
| 传感器到躯干的安装与方向核验 | [1910-HAT 接线与标定清单](1910-HAT接线与标定清单.md)（工作区文件） |
| HD-1910 台架与整机验收 | [URT2 + HD-1910 指南](URT2-HD1910接线组装与测试指南.md) |

---

*本教程的口径：BMI088 在板上不等于步态 IMU 可用；LSM6DSV16X 的两条路径产出同一份
12 字节载荷，切换是配置不是改造；方向核验通过之前，`imu_mount_verified` 保持 false。*
