# 解读 188 · Rust 入门(一):变量与所有权

> **解读对象**:概念课 · 以 `duck-control/src/`(bus.rs、safety.rs、io.rs)为教材
> **需要的前置**:零基础可读;下一篇:[解读 189](189-Rust二Result.md)

Rust 最出名的一条规矩是"所有权"。本篇不背定义,只用这只鸭子代码里的真实片段,讲三件事:`let`、`mut`、以及"钥匙移交"。

## let 与 mut:默认上锁的盒子

`let` 声明一个变量,但 Rust 的变量**默认不可变**——像个贴了封条的盒子,想改内容必须声明 `mut`(mutable)。`DynamixelIo::open` 里有一段标准示范(bus.rs:118-122):

```rust
let controller = open_controller(port, BAUD_RATE)?;

let mut ids = Vec::with_capacity(NUM_JOINTS + 1);
ids.push(IMU_DXL_ID);
ids.extend_from_slice(&JOINT_IDS);
```

逐行看:`controller` 没有 `mut`,因为它开好之后只被读;`ids` 是要往后添加设备的名单,所以声明成 `let mut`,下面才能 `push`。这不是啰嗦,是文档——读到 `let` 你就知道这名字不会再被赋值,读到 `let mut` 你会多看一眼谁在改它。

## 所有权:钥匙移交,原主人失效

Rust 规定:每块数据有一把"钥匙"(所有权),赋值或传参 = **把钥匙交给对方**,原变量就此失效,再用会编译报错。`FakeIo::at` 里能看到一次完整的"造出来→交出去"(io.rs:235-239):

```rust
pub fn at(positions: [f64; NUM_JOINTS]) -> Self {
    let mut io = Self::new();
    io.sensors.positions = positions;
    io
}
```

最后一行没有分号——把 `io` 这把钥匙**移交给调用者**。移交更严肃的用法在安全层:`Safety::new(io: T, config: SafetyConfig)` 把 `io` 整个收进 `Safety`(safety.rs:117),从此谁也别想绕开安全层直接摸电机。源码注释说得直白:"Safety 拥有唯一的 `RobotIo` 句柄……这是借入检查器**强制执行**的事实,而不是一条靠自觉的约定"。类比:把房子钥匙交给管家,你手里那把自动作废——想开锁只能走管家,这正是安全层要的效果。

## 借用:不交钥匙,借出去用一下

钥匙移交太狠?多数时候只需要"借用":加 `&` 表示临时借,用完归还,原主人还在。io.rs:116 的写信号签名:

```rust
fn write(&mut self, targets: &JointTargets) -> Result<()>;
```

`targets` 前面的 `&` 就是"借":调用者把目标位姿借给 `write` 抄一遍,自己照旧持有。`&mut`(可变借用)则规定**同一时刻只能有一个借用人**——房子要么一个人在里面装修,要么一群人隔着窗户看,不许边装修边围观。前一段代码里的 `&JOINT_IDS` 也是借用:只读那份关节编号表,不把表抢走。

## 你带走的收获

- `let` 默认不可变,可变要写 `let mut`;这不是限制,是给读代码的人的标注。
- 所有权 = 数据的钥匙:传参即移交,原变量失效;编译器替你查,错误在编译期而不是运行期。
- `&`/`&mut` 是借用:读多人可并发,写必须独占——数据竞争在编译期就写不出来。
- 真实案例: Safety 收走唯一的 IO 钥匙,"绕过安全层命令电机"在 Rust 里根本编译不过。

## 延伸

- 钥匙移交失败怎么表达:[解读 189](189-Rust二Result.md);合同与承包商:[解读 190](190-Rust三trait.md)
- 这套 IO 的六个方法逐个读:[解读 106](106-iors六方法.md);安全层怎么用这把钥匙:[解读 102](102-safetyrs一gate.md)
- 本地路径:`duck-control/src/bus.rs`(118–122)、`duck-control/src/safety.rs`(105–136)、`duck-control/src/io.rs`(235–239)
