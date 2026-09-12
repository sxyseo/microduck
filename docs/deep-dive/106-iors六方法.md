# 解读 106 · io.rs:trait 六方法逐个

> **解读对象**:`duck-control/src/io.rs`(351 行)
> **需要的前置**:[解读 07](07-模型与IO.md)(接缝导览)、[解读 69](69-软件适配.md)(谁来实现它)

导览见解读 07,本篇逐函数下钻:六个必选方法逐个过签名,再补两个默认方法与测试替身的应答机。`set_gain` 的 kP 故事与 `SlowSensors` 的温度均值问题 07 已讲,这里不重复。

## 1. 两个数据类型与一本错误词典

trait 的出入参先定下来:`Sensors`(io.rs:16-25)是一次原子采样——位置、速度、电流幅值、IMU 打包在一起,因为硬件上它们就是同一笔 `sync_read` 回来的(io.rs:6-9);`JointTargets`(io.rs:40-48)只有一个 `positions` 数组,"仅位置控制——alpha 没有速度模式的关节"(io.rs:38)。错误侧 `IoError`(io.rs:50-71)用 `thiserror` 派生,`#[error("…")]` 属性把人话写一次就够,四个变体是整个 IO 层的词汇表:`Port { path, source }`(io.rs:52-57)包住 `std::io::Error` 并附上串口路径;`Bus(String)`(io.rs:58-59)是协议层失败;`ShortRead { what, expected, got }`(io.rs:63-68)带三个字段,文档写明"上报而不是糊弄过去——静默的短读会让半个关节数组停在旧值";`Simulated`(io.rs:69-70)只属于测试替身。`type Result<T> = std::result::Result<T, IoError>`(io.rs:73)把签名缩写成一个词。

## 2. 六个必选方法、两个默认方法

`RobotIo`(io.rs:113)依次是:`read() -> Result<Sensors>`(io.rs:115)与 `write(&JointTargets)`(io.rs:116),一拍一进一出;`set_gain(kp: u16)`(io.rs:124);`set_torque(on: bool)`(io.rs:135);`reboot(id: u8)`(io.rs:143);`slow_sensors()`(io.rs:151)。逐个的理由 07 讲过大半,这里补两条只在源码注释里的:`reboot` 的文档(io.rs:137-142)说清了代价——舵机离线几百毫秒,回来时扭矩关、RAM 寄存器(含增益)回到 EEPROM 默认,"把它们写回去是调用方的责任";`slow_sensors` 的文档(io.rs:145-150)说清了为什么单独一笔事务——电压温度寄存器在 144–146,越过 `read` 那段连续块的末尾,"约一毫秒,一秒一次可忽略,50 Hz 下就是 5% 预算"。最后两个方法带默认实现:`imu_stale()` 默认返回 `ImuStale::default()`(io.rs:159-161,零计数),`imu_ready()` 默认返回 `true`(io.rs:164-166)——"让假后端不必发明诊断"(io.rs:153-155)。注意默认方向的选择:忘了实现的后端被当成"IMU 已收敛、无可报告",诊断是渐进采用的,不会拖垮接入。

## 3. `FakeIo`:一台应答机

`FakeIo`(io.rs:174-204)永远编译进 crate,所以 `cargo test` 不需要硬件。它对六方法各有一套应答机。`read`(io.rs:265-276)先看两道失败注入:`fail_next_read` 触发一次即自清(io.rs:266-269),`fail_reads` 倒计数逐次消耗(io.rs:270-273)——一个"板子先起、舵机后上电"的机器人,后来有电了。`write`(io.rs:278-285)把目标存进 `last_written`,并按 `track_targets` 决定是否让位置回声——`frozen()`(io.rs:243-246)关掉它,就是那台瘸腿的、被手推的鸭子。`slow_sensors`(io.rs:307-309)一行 `self.slow.ok_or(IoError::Simulated)`:`slow` 是 `Option<SlowSensors>`,置 `None` 就是"总线上没有东西在答"。真正区分好替身与坏替身的是计数器:`torque_writes`(io.rs:201)让测试分得清"上电一次"和"每拍都在写扭矩"——后者意味着每关节每拍一笔总线事务;`reboots: Vec<u8>`(io.rs:203)按顺序记下每个被重启的 ID。构造器风格的方法 `at(DEFAULT_POSITION)`(io.rs:235-239)、`failing_reads(n)`(io.rs:250-253)让测试一行搭出场景;`simulated_read_failure_clears_itself`(io.rs:345-350)钉住失败注入必须一次性——否则"注入过失败的测试永远恢复不了,循环的重试路径就测不到"(io.rs:342-343)。

## 你带走的收获

- 错误枚举是接口语义的一半:四个变体各自命名一类失败,`ShortRead` 连"少了多少"都写进类型。
- 默认方法让诊断可以渐进采用,但默认值方向要选"忘记实现时无害"的那边。
- 测试替身的失败必须可控且可恢复:一次性触发、倒计数、`None` 三档,各模拟一种真实故障。
- "次数"和"顺序"也是可断言的状态:`torque_writes` 与 `reboots` 让重复调用无处遁形。

## 延伸

- 两个真后端如何实现这条 trait:[解读 98](98-busrs一transact帧层.md)、[解读 109](109-hl2915rs二实现.md)
- trait 之上的第一层消费者:[解读 04](04-安全层.md)
- 本地路径:`/Volumes/dev/dev/microduck/duck-control/src/io.rs`
