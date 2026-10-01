# 解读 77 · 协议适配:Dynamixel 系(STS/SCS 兼容)

> **解读对象**:`bam/bam/feetech/actuator.py`(155 行)+ `microduck-replica/docs/硬件规格速查.md`(执行器与总线)
> **需要的前置**:[解读 53](53-舵机协议.md)(两家协议映射)· [解读 01](01-总线调度.md)(sync_read 调度)

换舵机时最省钱的路线,是待在**协议兼容圈**里——包格式不变或高度相似,代码只改常量。
本篇讲 Dynamixel 系内部怎么换,以及飞特 STS/SCS 为什么算"半兼容",还有兼容圈的一个反例:
协议通了,固件行为也可能不一样。

## 1. Dynamixel 系内换型号:改的是常量,不是架构

官方总线的契约写在 《硬件规格速查》(`microduck-replica/docs/硬件规格速查.md`):单线半双工 TTL
3.3 V、Dynamixel Protocol V2、1 Mbps(EEPROM `baud_rate = 3`)、16 个设备一次 `sync_read`
读寄存器 124–136。在这个圈里换型号(XL330-M077 ↔ M288,甚至 MX 系),运行时架构不动,
要核对的只有:ID 表、`return_delay_time`、力矩/速度档位——全是寄存器值层面的常量。

MX-64/MX-106 还提示一件事:Dynamixel 家族本身有 TTL 与 RS-485 两种物理层,
官方 HAT 上 `J3/J11` 就是 RS-485 4P(SIT3088E 驱动),Microduck 的 XL330 走的是 `J13/J14` TTL。
同家族换型号,先确认它站在哪个物理层上。

## 2. STS/SCS:物理层完全相同,包格式不同

飞特 STS/SCS 与 Dynamixel 的关系,逆向文档的对照表说得很准:

| | Dynamixel V2 | 飞特 STS/SCS |
|---|---|---|
| 物理层 | 单线半双工 TTL、3 线、1 Mbps | **完全相同** |
| 包头 | `FF FF FD 00` + CRC-16 | `FF FF` + 取反和(~sum) |
| 批量读 | `sync read`(官方没用更快的 0x8A) | `sync read 0x82` |
| 出厂延时 | 250(=500 µs/设备,16 台吃掉 8 ms,40% 预算,必须写 0) | 第 7 号默认 0,"Not functional on STS" |

所以"把 IMU 做成总线上第 16 个设备"的思路在飞特上依然成立;软件侧也不必重写通信层——
Open Duck Mini 用的就是 `rustypot.feetech(port, 1000000)`,**同一个库,换协议模块**,
波特率同样 1 Mbps。飞特还占一个反直觉的便宜:出厂延时代价为零,普通写指令再配
第 8 号 Response Level=0(只读/回 ping)就能进一步省总线时间。

## 3. 协议兼容 ≠ 固件行为兼容

真正的深坑在 `bam/bam/feetech/actuator.py` 里。`STS3215Actuator` 与 XL330 同属
`VoltageControlledActuator`(电压级模型),却多了一层**有状态的目标限速**:

- 固件不直接追目标位置,而是移动一个内部目标 `q_target_smooth`,每步最多走
  `max_velocity × dt`——所以 `compute_control` 必须**按时序逐拍调用**(`stateful = True`);
- 占空比 = 位置误差 × kp(32)× `error_gain`(0.166,注释注明"用示波器在实物上测出"),
  钳到 `max_pwm = 0.97`;XL330 的同款参数是 kp=400、`error_gain` 由 4096 编码计数/256/885 推出。

这意味着:**即使你完美移植了协议,固件内部的位置环行为仍是另一套**——限速、增益换算、
PWM 饱和点都不同,它们最终都落进 BAM 辨识参数里(见 [解读 80](80-BAM参数逐字段.md))。
协议适配的完成标志不是"能通",是"辨识数据对得上"。

## 你带走的收获

- Dynamixel 系内换型号改的是常量(ID/延时/波特率档位);换物理层(TTL↔RS-485)才是硬件问题。
- STS/SCS 与 Dynamixel 物理层相同、包格式不同:`rustypot` 换协议模块即可,通信层不用重写。
- 出厂延时上飞特反而占优(XL330 出厂 250 要写 0,STS 天然没有),高频控制环的默认值必须逐个核对。
- 协议兼容不等于行为兼容:STS3215 固件有目标限速,`compute_control` 是有状态的——这是 bam 用一个 `stateful` 标记记录的事实。
- "能通"不是协议适配的验收线,"辨识数据对得上"才是。

## 延伸

- [解读 78](78-协议适配飞特系.md):飞特帧格式逐段与厂商私有协议
- [解读 64](64-磁编码协议.md):飞特寄存器表逐段解读
- [解读 69](69-软件适配.md):`RobotIo` trait 接缝上写新控制器
- `bam/bam/feetech/actuator.py`(`STS3215Actuator` 注释含示波器测参过程)
- `microduck-replica/docs/硬件方案逆向.md` 五之二(协议对照表与 fast sync read 更正)
