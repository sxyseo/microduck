# 解读 99 · bus.rs(二):sync_read 与慢速轮询

> **解读对象**:`duck-control/src/bus.rs`(708 行)
> **需要的前置**:[解读 01](01-总线调度.md)(总线调度导览)、[解读 98](98-busrs一transact帧层.md)(帧层)

导览见解读 01,本篇逐函数下钻。总线上不是所有数据都配得上每秒 50 次问询;这一篇看慢速读、旧数据计数,以及启动期的一次性轮询。

## 1. `slow_sensors`:一秒一笔的第二本账

签名(bus.rs:541):`fn slow_sensors(&mut self) -> Result<SlowSensors>`。一笔 `sync_read_raw_data(&JOINT_IDS, 144, 3)`(bus.rs:544)同时拿回 15 个舵机的输入电压(`u16`,每计数 0.1 V,bus.rs:48)与温度。循环里有个容易看漏的过滤:`if v > 0.0 { volts.push(v) }`(bus.rs:568-570)——答出 0 的设备不许进平均,否则一块正常的电池会被坏读数稀释成"半没电";全空则 `volts.is_empty()` 直接报 ShortRead(bus.rs:574-580)。返回的电压是 15 个读数的平均(bus.rs:582),温度不是——理由在注释里(bus.rs:531-534):同一块电池,平均是降噪;"一个发热的关节"才是要看的信号,均值会把它藏掉。另外(bus.rs:536-540):rustypot 的 sync_read 等齐所有 ID,一台不应答则**整笔失败**——慢速读是 all-or-nothing,调用方应保留上个样本,别把一次失手当新闻。

## 2. `StaleImuTracker::observe`:给"重复的答案"计数

结构体只有 `last: Option<[u8; IMU_BLOCK_LEN]>` 与计数(bus.rs:80-86)。初值用 `Option` 而不是全零是刻意的(bus.rs:81-83):SFLP 表还没写时,板子发的恰恰就是全零块——拿它当"上一块",启动第一拍就会误判陈旧。`observe`(bus.rs:91-99)一行完成比较加存储:`self.last.replace(*block) == Some(*block)`——`replace` 存入新值并返回旧值,正好顺手比;相同则 `saturating_add`(饱和加法,到顶不回绕)累计,不同则 run 清零、total 保留——测试(bus.rs:673)点破分工:"total 是这故障多久来一次,run 是现在是否正在发生"。告警的限流写在 `read` 里(bus.rs:450-457):run 首次到达 `STALE_RUN_WARN = 25`(50 Hz 下的半秒,bus.rs:72)报一次,之后每 500 次才再报——"第一次重复就喊,只会教会所有人无视这条消息"(bus.rs:66-69)。`imu_stale()`/`imu_ready()`(bus.rs:587-593)把计数器交给 `RobotIo` trait,供上层健康报告取用。

## 3. 一次性轮询:`missing_servos` 与 `replacement_target`

`missing_servos`(bus.rs:192-204)逐个 ping `JOINT_IDS`,返回不应答者的名单;每次 ping 受 `READ_TIMEOUT` 约束,舵机断电时全程约半秒、正常时几毫秒(bus.rs:188-190)。它只在启动跑一次,是收养的"侦察"。`replacement_target`(bus.rs:418-423)只有四行,却是一道闸——`match missing { [one] => Some(*one), _ => None }`:切片模式 `[one]` 只匹配"恰好一个"元素,两个静默时分不清新舵机该顶替谁,"猜错就是把腿关节刷成脖子关节"(bus.rs:600-602);零个静默则无事可做。测试(bus.rs:604-609)把 0/1/2/15 四种长度全钉住。

## 4. `adopt_replacement`:把出厂舵机变成"它一直在"

`adopt_replacement`(bus.rs:221-306)的几个顺序都有注释背书。先在当前波特率下 ping 出厂 ID(`ping_fresh`,bus.rs:309):已被刷到 1 Mbps 但保留出厂 ID 的舵机会被重开串口弄丢(bus.rs:228-229);找不到再以出厂波特率 `reopen`(bus.rs:233、320-324)——ttys 独占,旧句柄不死、新口开不了。改 ID 在前、改波特率在后(bus.rs:247-249),两条写命令都在已知速度下得到确认。收尾的 reboot 不只是规矩:刷写会置起硬件错误报警、扣着扭矩不放,所以等 `REBOOT_SETTLE = 500 ms`(bus.rs:57,早 ping 会把"还在启动"读成"刷写失败")后读 `hardware_error_status` 复核(bus.rs:284-298)——否则症状是"一条查不出来的瘸腿"(bus.rs:282-283)。

## 你带走的收获

- 慢变量单独成一笔事务;sync_read 等齐所有 ID,慢速读天然 all-or-nothing,调用方要自己保留上一拍。
- "读失败"会抛错,"读到旧值"只有显式计数器能看见——后者必须靠 tracker。
- 告警首次设阈值、后续限流,是高频日志唯一可持续的形态。
- 有歧义时拒绝行动(只认"恰好一个缺席")比聪明地猜更安全。

## 延伸

- 每 tick 的那一笔读怎么解码:[解读 98](98-busrs一transact帧层.md)
- 电压温度到上层之后:[解读 04](04-安全层.md)
- 课程对照:`/Volumes/dev/dev/microduck/docs/course/10-舵机从SG90到总线.md`
