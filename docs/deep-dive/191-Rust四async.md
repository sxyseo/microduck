# 解读 191 · Rust 入门(四):async 与 tokio

> **解读对象**:概念课 · 以 `robotd/src/main.rs` 开头的 `#[tokio::main]` 与 `control_loop` 为教材
> **需要的前置**:[解读 188](188-Rust一所有权.md)、[解读 190](190-Rust三trait.md)

机器人程序要同时干两件拧巴的事:每 20 毫秒准时走一拍的控制循环,和"随时有人来问都得答"的遥控接口。Rust 的答案叫 async,tokio 是最常用的那套执行引擎。

## 为什么机器人程序要异步

`robotd` 一个进程里挤着:50 Hz 控制循环、`robot.*` 套接字服务、电量采样、声音播放。若用"一个循环轮询所有事"的老写法,任何一处等待(串口、网络、定时)都会拖累节拍。文件头注释把规矩立得很硬(main.rs:16-19):**"每个方法都必须在机器人状态很糟时仍可应答"**——所以 IPC 一侧只读控制循环发布的原子变量,从不调用循环本身;卡死的循环要自己报告不健康,而不是把打电话来的人一起挂死。async 的本事是**等待时让出**:像护士同时看几间病房,铃没响就去照看下一个,铃响了再回来——等待不占人手。

## `#[tokio::main]`:把 main 变成异步的地基

整个守护进程从这两行开始(robotd/src/main.rs:904-905):

```rust
#[tokio::main]
async fn main() -> ExitCode {
```

逐行看:上一行是属性宏,它把普通 `main` 改写成"搭好 tokio 运行时再调用你";下一行 `async fn` 声明这是个可等待的异步函数,里面因此允许用 `.await`。此后代码里到处是它的痕迹:启动重试用 `tokio::time::sleep(STARTUP_RETRY_INTERVAL).await`(main.rs:1540)——等 1 秒再试舵机,这一秒里运行时去跑别的任务,而不是干等。

## control_loop:用 ticker 守住 50 Hz

主循环的心脏是一个定时器(main.rs:1899、1914):

```rust
let mut ticker = tokio::time::interval(period);
```

```rust
ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
```

然后进入"醒来干一拍、睡到下一拍"的循环(main.rs:2073-2074):

```rust
while !state.shutdown.load(Ordering::Relaxed) {
    ticker.tick().await;
```

`tick().await` 就是"睡到下一拍,睡时让出线程"。真正值钱的是 `Skip` 这个选择:错过节拍时**跳过、不补课**。源码注释记录了一次实测:用另一种策略 `Delay`,每拍的调度延迟会累加进周期,循环"实测 43.1 Hz,却显示 missed = 0"——不是活多干不完,是每次都被推迟;换成 `Skip` 才守住原定时刻表。机器人宁可丢一拍,也不能让命令堆积成洪峰,这段注释就是"为什么"三个字的实测答案。

## 你带走的收获

- async 解决"多处等待互相不拖累":`.await` 等待时让出线程,护士看多间病房。
- `#[tokio::main]` 一行搭起运行时;`async fn` 里才能 `.await`;sleep 也是 await,等待不空转。
- 50 Hz 主循环 = `interval` + `tick().await`;错过节拍选 `Skip`(丢拍)而不是 `Delay`(漂移)。
- 43.1 Hz 的实测教训:定时器行为选错,症状像硬件问题,根因在调度策略。
- 架构铁律:IPC 只读原子变量、绝不调用循环——"糟状态下仍可应答"。

## 延伸

- 这条循环里每一步做什么:[解读 112](112-robotd控制循环.md)、[解读 09](09-主循环.md)
- 循环手里的"合同"从哪来:[解读 190](190-Rust三trait.md);错误怎么沿 `?` 上抛:[解读 189](189-Rust二Result.md)
- 本地路径:`robotd/src/main.rs`(16–19、904–905、1899–1914、2073–2074)
