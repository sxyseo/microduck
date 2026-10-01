# 解读 190 · Rust 入门(三):trait 与泛型

> **解读对象**:概念课 · 以 `duck-control/src/io.rs` 的 `RobotIo` trait 为教材
> **需要的前置**:[解读 189](189-Rust二Result.md)(Result 与 `?`)

这只鸭子有三套"身体":真机 XL330 总线、换装后的飞特 HL-2915 总线、电脑里的 MuJoCo 仿真。控制循环只有一套,凭什么都能跑?答案是 trait——**同一张合同,多个承包商**。

## 合同本身:RobotIo

trait 是一份"能力清单":谁签了字,谁就必须会做清单上的事。io.rs:113-116:

```rust
pub trait RobotIo {
    /// One transaction: joints and IMU together.
    fn read(&mut self) -> Result<Sensors>;
    fn write(&mut self, targets: &JointTargets) -> Result<()>;
```

白话:合同写明"必须会 `read`(一次事务把 15 个关节和 IMU 一起读回)"、"必须会 `write`",后面还有 `set_gain`、`set_torque`、`reboot`、`slow_sensors` 等条款(全六方法见[解读 106](106-iors六方法.md))。注意 `read` 的返回值正是上一篇的 `Result<Sensors>`——合同连"失败怎么交代"都规定了。

## 三个(半)承包商

合同是抽象的,干活的是具体类型,各自用 `impl RobotIo for X` 签字:

- `impl RobotIo for DynamixelIo`(bus.rs:425)——原装 Dynamixel 总线的承包商;
- `impl RobotIo for Hl2915RobotIo`(hl2915.rs:334)——飞特 HL-2915 总线,读的是另一套协议,但对外交出的仍是同一个 `Sensors`;
- `impl RobotIo for RemoteIo`(sim.rs:263)——把请求转发给 MuJoCo 仿真进程;
- `impl RobotIo for FakeIo`(io.rs:264)——"用代码做的假机器人",`cargo test` 靠它不需要任何硬件。

每个承包商内部天差地别(寄存器地址、帧格式全不同),但对上只交一张答卷:`fn read(&mut self) -> Result<Sensors>`。合同还允许"默认条款"——签了字就自动拥有,不想要才自己重写。io.rs:164:

```rust
fn imu_ready(&self) -> bool {
    true
}
```

## 泛型:同一套代码,编译时定承包商

合同签了,谁来用?看主循环的签名(robotd/src/main.rs:1826):`async fn control_loop<T: RobotIo>(io: T, ...)`。`<T: RobotIo>` 读作"任意类型 T,只要它签过 RobotIo 这张合同"。安全层同理(duck-control/src/safety.rs:105):

```rust
pub struct Safety<T: RobotIo> {
    io: T,
```

`Safety` 不关心手里是真舵机还是仿真,反正 T 都会那六个方法。编译器按实际传入的类型**各生成一份专用机器码**——抽象没有运行时开销。真正的点睛之笔是钥匙只发一把:[解读 188](188-Rust一所有权.md)讲过 `io` 被移交给 `Safety` 后别处再无副本,"任何电机命令必须过安全层"由编译器背书。

## 你带走的收获

- trait = 能力合同:规定方法签名(连返回的 `Result` 类型一起),实现者逐一兑现。
- 一个 trait,多个实现:DynamixelIo/Hl2915RobotIo/RemoteIo 三个后端 + FakeIo 测试替身,上层代码一行不改。
- 默认方法(`imu_ready`)是合同的可选条款,让新后端不必事事从头写。
- 泛型 `<T: RobotIo>` = "只跟签过合同的对象合作",编译期定型,零运行时代价。
- 换舵机为什么只改 IO 层?合同不变,换承包商即可(第 69 篇的软件适配就是这条路的实战)。

## 延伸

- 六方法逐个精读:[解读 106](106-iors六方法.md);两个真机实现:[解读 98](98-busrs一transact帧层.md)、[解读 109](109-hl2915rs二实现.md);仿真后端:[解读 110](110-simrs仿真后端.md)
- 异步版的控制循环:[解读 191](191-Rust四async.md)
- 本地路径:`duck-control/src/io.rs`(113–167、264 起)、`robotd/src/main.rs`(1826)
