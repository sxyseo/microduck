# 解读 08 · lib.rs 与 crate 组织:控制库的分层

> **解读对象**:`duck-control/src/lib.rs`(25 行)及两个 `Cargo.toml`
> **需要的前置**:Rust 的 crate(编译单元)与模块概念;各模块细节见[解读 01](01-总线调度.md)–[解读 07](07-模型与IO.md)

## 1. 25 行的 lib.rs,主要内容是一句"不"

整个文件只有模块声明和再导出,开头的模块注释是这个库的宪法(lib.rs:1-5):"Deliberately not a daemon. There is no tokio here, no socket, no systemd — `robotd` owns all of that. The boundary is enforced by the compiler rather than by discipline."——刻意不做守护进程:没有 tokio(异步运行时)、没有 socket、没有 systemd,进程层的事全归 `robotd`。关键在最后半句:边界靠编译器而不是靠纪律——crate 里根本没有那些依赖,想在这层开 socket 都写不出来。

接着列出控制路径:model、bus、`io::RobotIo`、observations、policy、safety(lib.rs:7-8),注明设计出处是 `docs/design/robotd-design.md` §2。其余是 `pub mod` 声明(bus、fall、imu、io、model、obs、policy、safety)和 `pub use` 再导出(lib.rs:19-25)——把 `battery_percent`、`Sensors` 等常用类型顶到 crate 根,下游写 `duck_control::Sensors` 而不必背模块路径。

## 2. 一条不寻常的依赖边

`duck-control` 依赖 `duck-ipc-proto`——一个 IPC 协议 crate,控制库为什么依赖通信协议?Cargo.toml 注释值得当范文读:为了 `JOINT_NAMES` 这一个常量。关节*顺序*就是协议——状态流里的 `joints`、`targets` 是裸数组,按下标索引,所以名字表应住在每个客户端都已链接的 crate 里,由本 crate 再导出,"而不是留两份副本手工同步"。注释同时堵住误读:"Not a door onto IPC: nothing here speaks to a socket"——依赖是单常量的,没有打开任何通信能力;`robotd` 本就同时链接两个 crate,没有二进制因此多出一条依赖边。

这是"一个常量的真相来源放哪"的答案:放在所有消费者共有的最低层。

## 3. Cargo.toml 里的三个工程决定

依赖列表本身也是文档(duck-control/Cargo.toml):

- `ort` 用 `load-dynamic` 特性:运行时 dlopen(动态加载)libonnxruntime 而非链接。两个好处——aarch64 交叉编译不需要目标架构的 ONNX Runtime;没装 so 的笔记本照样编译、照样跑所有不建会话的测试。版本钉在 `=2.0.0-rc.11`,"板子要保持它已经验证过的 ABI"。
- `rustypot = "1.6.0"` 是下限不是偏好:1.6.0 之前,状态包载荷里的 `FF FF FD` 会被错误解包,定长 `sync_read` 读回来就是垃圾——"这是总线的正确性约束,不是为了赶时髦的升级"。
- `serialport` 关掉默认特性:默认的 `libudev` 只用于枚举串口,这里按配置路径打开一个就够;libudev-sys 需要 pkg-config sysroot,交叉编译直接断。注释补了一刀:rustypot 也为同样理由关了它——"本 crate 必须跟着关,否则 cargo 的特性合并(feature unification:特性在构建图里取并集)会把它再打开"。

## 4. 守护进程那边的镜像

`robotd/Cargo.toml` 是同一枚硬币的反面:依赖 duck-control、robotd-params、duck-ipc-proto、kinematics、sounds 等;`arc-swap` 的注释一句——"无锁单值槽,控制循环每拍一次原子 load,永远不会被 IPC 任务卡住"。更讲究的是 dev-dependencies(仅测试链接):`updater` 出现在这里,因为有测试要驱动真实更新引擎对着真 robotd 二进制验证契约;注释解释了测试为何住在 robotd 包里——只有这里 cargo 定义 `CARGO_BIN_EXE_robotd` 并保证二进制是新的,放在 updater 那边就得猜路径。

## 你带走的收获

- 分层最有效的执行方式不是规范文档,是依赖图:下层没有那个依赖,越界代码写不出来。
- 共享常量的真相来源放在所有消费者共有的最低层,并写清楚"这不是后门"。
- Cargo.toml 的依赖注释是低成本高回报的文档:每个非常规选择写一句"为什么"。
- 特性合并会让 A crate 关掉的 feature 从 B crate 回来,两边都要关;测试专属依赖放 dev-dependencies,并写明"测试为什么住在这个包里"。

## 延伸

- 被分层挡在下面的总线与观测:[解读 01](01-总线调度.md)、[解读 02](02-观测拼装.md)
- 拿着这些模块跑起来的守护进程:[解读 09](09-主循环.md)
- 本地路径:`/Volumes/dev/dev/microduck/duck-control/Cargo.toml`、`/Volumes/dev/dev/microduck/robotd/Cargo.toml`
