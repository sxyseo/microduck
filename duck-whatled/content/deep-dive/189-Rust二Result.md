# 解读 189 · Rust 入门(二):Result 与错误处理

> **解读对象**:概念课 · 以 `duck-control/src/io.rs` 的 `IoError`/`Result` 别名为教材
> **需要的前置**:[解读 188](188-Rust一所有权.md)(变量与所有权)

C 语言用返回码报错,忘了看就埋雷;很多语言用异常,炸在哪全凭运气。Rust 把"可能失败"直接写进类型:函数返回 `Result`,**要么成功 `Ok(值)`,要么失败 `Err(原因)`,编译器逼你二选一处理**。类比快递签收:Result 是一张签收单,要么签收拿到货(Ok),要么拿到一张写明理由的拒收单(Err)——不存在"没这张单子"这个选项。

## 一套本项目的错误清单:IoError

io.rs 给整条硬件通路定义了统一的错误类型(io.rs:51、63-68):

```rust
pub enum IoError {
    #[error("serial port {path}: {source}")]
    Port {
```

```rust
#[error("{what}: expected {expected}, got {got}")]
ShortRead {
    what: &'static str,
    expected: usize,
    got: usize,
},
```

`enum` 是"几种可能之一":打不开串口(Port)、总线事务失败(Bus)、设备少答了(ShortRead)、仿真注入的失败(Simulated)。每个变体还能带自己的字段——`ShortRead` 记着"期望几块、实到几块",等于拒收单上写明"订 16 件到货 15 件"。文件里还有一行别名(io.rs:73):

```rust
pub type Result<T> = std::result::Result<T, IoError>;
```

它只是起个短名字:本模块写 `Result<Sensors>`,意思是"成功给你 Sensors,失败给 IoError"。

## `?`:有问题就把拒收单递给上级

真正处理错误的第一件武器是 `?` 运算符。`DynamixelIo::read` 的开头(bus.rs:427-430):

```rust
let blocks = self
    .controller
    .sync_read_raw_data(&self.ids, READ_ADDR, READ_LEN)
    .map_err(|e| IoError::Bus(format!("combined imu+motor sync_read: {e}")))?;
```

白话拆解:先发总线问询;`map_err` 把底层库的错误"翻译"成本项目的 `IoError::Bus`,顺手写上下文;结尾的 `?` 是关键——**是 `Ok` 就拆包继续往下走,是 `Err` 就当场把这个错误返回给调用者**,本函数剩下的代码不执行。像仓库管理员:验货没问题继续上架,有问题直接把拒收单递给上级,自己不揽着。一个 `?` 顶掉四行 if-else,错误路径却一行不少。

## 为什么值得:静默失败才是最贵的

拒收单制度的价值,在 `ShortRead` 的文档注释里写得很透(io.rs:60-62):"一个静默变短的读,会让半边关节数组里留着**陈旧数据**"。如果不报错、拿缺的数据凑合,策略就会拿上一拍的旧姿态继续走——错误被推迟到摔倒那一刻才现形,而且查无可查。显式错误还能被测试:io.rs 的测试里有 `assert!(io.read().is_err());`(:348),先用 `FakeIo` 注入一次失败,再断言"确实报错了"。错误从"运行时惊喜"变成"编译期义务 + 测试期断言",这就是 Rust 错误处理的全部野心。

## 你带走的收获

- `Result<T, E>` 让"可能失败"写进函数签名;`Ok`/`Err` 必须处理,编译器当监工。
- `enum IoError` 给每类失败带上下文字段,像写明理由的拒收单。
- `?` = 拆包或上抛:`Ok` 继续、`Err` 立即返回,`map_err` 负责翻译并补充现场。
- 静默缺数据比报错更危险:陈旧观测会让策略"拿着旧地图开车"。
- 错误路径可以测试:`assert!(io.read().is_err())` 让"会报错"也成为被验证的行为。

## 延伸

- 这些错误怎么被六个方法逐个抛出:[解读 106](106-iors六方法.md);帧层与 ShortRead 的现场:[解读 98](98-busrs一transact帧层.md)
- 下一课:同一张合同多个实现:[解读 190](190-Rust三trait.md)
- 本地路径:`duck-control/src/io.rs`(50–73)、`duck-control/src/bus.rs`(427–438)
