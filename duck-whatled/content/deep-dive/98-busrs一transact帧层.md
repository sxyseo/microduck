# 解读 98 · bus.rs(一):`transact` 帧层

> **解读对象**:`duck-control/src/bus.rs`(708 行)
> **需要的前置**:[解读 01](01-总线调度.md)(总线调度导览)、[解读 53](53-舵机协议.md)(寄存器对照)

导览见解读 01,本篇逐函数下钻。先交代一个名字:仓库里并没有叫 `transact` 的函数,"帧层"指的是一次总线事务的收发与解码,它住在 `RobotIo::read`/`write` 与 rustypot 的 `sync_read_raw_data`/`sync_write_goal_position` 里(`io.rs:58` 把这类失败统一叫 "bus transaction failed")。

## 1. 把串口包成协议控制器:`open_controller` 与 `open`

签名(bus.rs:400):`fn open_controller(port: &str, baud: u32) -> Result<Xl330Controller>`。三步各管一事(bus.rs:401-410):`serialport::new(port, baud).timeout(READ_TIMEOUT).open()` 打开串口,超时取 `READ_TIMEOUT = 30 ms`(bus.rs:52)——健康的 16 设备读远快于此,设上限是让"缺一台设备"变成有界卡顿,而不是挂在串口驱动默认超时上;然后 `Xl330Controller::new().with_protocol_v2().with_serial_port(serial)` 包成 Dynamixel 协议 2 控制器。`DynamixelIo::open`(bus.rs:117)再定发言名单:`ids` 第 0 位是 IMU 板 `IMU_DXL_ID = 200`(model.rs:78),后面按 `JOINT_IDS` 顺序跟 15 个关节(bus.rs:120-122)——应答块回来的顺序就是这份名单的顺序,所以 `blocks[0]` 永远是 IMU。`port` 字符串也单独留一份(bus.rs:104-106):rustypot 独占串口句柄、不支持原地改波特率,换速度只能整个重开(见解读 99 的 `reopen`)。

## 2. `read`:12 字节块的逐字节解码

`RobotIo::read`(bus.rs:426)一句话发出问询:`sync_read_raw_data(&self.ids, READ_ADDR, READ_LEN)`(bus.rs:429),从地址 124 起读 12 字节(bus.rs:30-31)。返回块数对不上名单就报 `IoError::ShortRead`(bus.rs:432-438)——"少答了"必须显式当错误,不能默默当默认值。解码循环用切片 `blocks[1..]`(跳过第 0 块 IMU,切片是 Rust 里对连续一段的借用视图)配 `enumerate`(bus.rs:467),每块 12 字节的布局浓缩成一行注释(bus.rs:475):`[0..2] present_pwm, unused · [2..4] current · [4..8] velocity · [8..12] position`。三个换算各有一个测试钉着:

- 电流:`i16::from_le_bytes` 后取绝对值(bus.rs:476);
- 速度:i32 计数乘 `RAD_PER_SEC_PER_COUNT`(bus.rs:34),即 0.229 转/分每计数换算成 rad/s。测试 `velocity_scale_matches_the_datasheet_figure`(bus.rs:637)的理由很直白:这个数错一步,观测里所有关节速度被同一常数缩放,"策略刚好容忍到能难看地走路"(bus.rs:633-635);
- 位置:`2π × count / 4096 − π`(bus.rs:480),把 0..4095 计数映到 −π..π。`position_conversion_round_trips_through_rustypot`(bus.rs:625)验证它与 rustypot 写出方向的换算互逆——否则"环路命令的角度,和它以为读回的角度,不是同一个"(bus.rs:621-623)。

## 3. `write` 与 `reboot`:写帧的两种宽容

`RobotIo::write`(bus.rs:486-490)只有一条 `sync_write_goal_position(&JOINT_IDS, &targets.positions)`:一帧广播全部目标位置,失败即报错,没有部分成功。`RobotIo::reboot`(bus.rs:497-504)则刻意宽容:注释说状态包是"舵机在复位前未必来得及给的礼节",所以只有**发不出去**才算错(bus.rs:498-499),`.map(|_| ())` 把成功应答直接丢弃。同样是事务:读要逐字节校验,写要按语义区分"没送达"和"没等到回执"——半双工总线上这是两种不同的失败,混为一谈就会把正常的 reboot 当成故障。

## 你带走的收获

- 帧层的正确性锚在换算常数上:每个系数配一个与对方实现互逆、或对数据手册的测试。
- "应答块数量不对"要显式报 ShortRead:半双工总线上,静默缺答是最常见的故障形态。
- 串口超时是帧层的兜底:30 ms 上限把"设备缺失"从挂死变成可恢复的卡顿。
- 应答顺序由请求名单的顺序决定:把 IMU 放第 0 位,解析就不需要按名字找。
- reboot 只把"发送失败"当错误:区分"没送达"与"没回执"是半双工协议的基本功。

## 延伸

- 快慢分离的调度账:[解读 01](01-总线调度.md)
- 读回的四组数怎么进 61 维观测:[解读 02](02-观测拼装.md)
- 慢速轮询与一次性轮询:[解读 99](99-busrs二慢速轮询.md)
- 课程对照:`/Volumes/dev/dev/microduck/docs/course/10-舵机从SG90到总线.md`
