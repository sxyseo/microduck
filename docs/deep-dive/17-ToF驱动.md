# 解读 17 · tof/sensor.rs + status.rs:ToF 传感器驱动

> **解读对象**:`tof/src/sensor.rs`(424 行)+ `tof/src/status.rs`(104 行)
> **需要的前置**:无;[解读 15](15-手部与模型对齐.md) 是数据的消费侧。

## 两代硬件,一个接口

VL53L5CX 与 VL53L8CX 同封装、同寄存器表、同 8×8 输出,差别只在固件与驱动前缀(sensor.rs:8-14)。哪一颗焊在板上不是编译期选择:`open` 先用 generation 无关的 `tof_probe_id`(sensor.rs:38)读 ID,revision `0x0C` → `Generation::L8cx`、`0x02` → `L5cx`(sensor.rs:86-95),之后才上传固件——上传是慢步骤,约 90 KB 走 I²C,400 kHz 要几秒(sensor.rs:226-228),所以放在进程启动时做、不占服务循环。未知 revision 得到 `Generation::Unknown`,拿不到驱动就拒绝:注释提醒,上传错误的固件块就是把探测头刷砖的方式(sensor.rs:388-391)。

Rust 侧的关键决定是**把 unsafe 关进一个文件、且只有一种形状**:"C 会往我按 64 格开好的缓冲区里写 64 格"(sensor.rs:4-6)。`extern "C"` 块(sensor.rs:36-62)声明两代各一套 `vl5_*`/`vl8_*`;`Driver` 枚举(sensor.rs:119)一个操作包一层,让每个 unsafe 块自己说明在做什么;`get_frame`(sensor.rs:201-211)的 SAFETY 注释把"为什么恰好是 64"钉死:分辨率由 `start` 配置成 8×8,两代 ULD 的结果块都宽 64。

单实例是强制的:每个 C shim 把配置放在文件作用域静态里,第二个 `Sensor` 会悄悄共享并弄脏第一个的状态。于是 `TAKEN: AtomicBool`(sensor.rs:66)在 `open` 里 `swap(true)` 抢占,失败路径必须归还(sensor.rs:235),否则一次失败的打开会让进程永远无传感器——测试 `a_failed_open_releases_the_claim`(sensor.rs:414)专钉"失败后还能重试"。

非 Linux 平台上 `Sensor` 的类型是 `std::convert::Infallible`(sensor.rs:354)——一个没有任何取值的类型,`match self.0 {}` 让编译器替你"写完"所有方法体。它不是假传感器(`tofd --fake` 才是,名字里说清楚了),存在的意义只是让 `cargo test --workspace` 在笔记本上也能跑。

## status.rs:三态,给刚连上的订阅者

`Status`(status.rs:11)就是一个 `Mutex<Inner>`:传感器型号 + 不可用原因,传感器线程写、每条连接读,一个小值配一把锁足矣。三种状态分开呈现:启动中("bringing the sensor up",status.rs:32——固件上传要几秒,这段窗口里的观看者该看到理由而非空白)、`up(型号)`、`down(原因)`——"没有传感器"与"还没出帧"不该让观众猜。`result`(status.rs:52)里 `accepted` 恒为 true:订阅本身有效,传感器出现后帧自然会来;拒绝会让早一秒订阅的客户端永远放弃(status.rs:55-58)。中毒的锁也不 panic(status.rs:69-71,Rust 里互斥锁的持有者 panic 后再取锁即"中毒")——一个状态字段不值得拖垮守护进程。

## 你带走的收获

- 多代硬件共存:运行时探测 ID → 选驱动,把"哪颗传感器"变成数据而非构建选项。
- FFI 的 unsafe 要收敛为单一形状,SAFETY 注释写清缓冲区契约。
- "失败必须归还全局标志/资源"要配一条重试能通过的测试。
- 用 `Infallible` 空类型让不支持平台的代码在编译期灭绝,而不是造一个会说谎的假实现。

## 延伸

- [解读 15](15-手部与模型对齐.md):status 字节在 theremin 里如何被解释。
- [解读 14](14-头部运动学.md):帧要变成机器人系方向,靠 `tof_in_trunk`。
- 源码:`tof/src/sensor.rs`、`tof/src/status.rs`、`tof/src/lib.rs`(`Frame`/`Zone`)。
