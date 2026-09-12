# 解读 104 · fall.rs 全函数走读

> **解读对象**:`duck-control/src/fall.rs`(272 行)
> **需要的前置**:[解读 05](05-摔倒检测.md)(检测器导览与物理推导)、[解读 04](04-安全层.md)(安全层的"确认"版判据)

导览见解读 05,本篇把文件里的每个函数走完:配置、状态、两个纯函数、状态机 `observe` 与 `reset`。文件很小(272 行),但没有一行是填充。

## 1. 配置与状态:`FallPredictorConfig` 与 `FallPredictor`

`FallPredictorConfig`(fall.rs:56-68)四个字段,默认值集中在一个 `Default`(fall.rs:70-79):`tilt_z = -0.90`(约 26° 前倾,fall.rs:73)、`predicted_z = -0.5`(fall.rs:74,注释明说与 `SafetyConfig::fall_gravity_z` 同义且默认同值——"它将在 `lookahead` 后成为安全层眼中的摔倒",fall.rs:59-63)、`lookahead = 300 ms`(fall.rs:75)、`debounce = 60 ms`(fall.rs:76,50 Hz 下三个 tick)。`FallPredictor` 自身只带两个状态量(fall.rs:87-94):`falling_for`(三条件连续成立的时长)与 `fired`(这一跤的边沿发出去了没有)。`new`(fall.rs:97-103)把二者归零。整个检测器是纯内存状态机,不持传感器句柄——每个 tick 由调用方喂 `ImuData` 与 `dt`,所以它能对任意录像离线重放。

## 2. 两个可公开的数:`gravity_z_rate` 与 `predicted_z`

`gravity_z_rate`(fall.rs:110-112)是关联函数(不接 `self`,以 `FallPredictor::gravity_z_rate(&imu)` 调用):

```rust
-(imu.gyro[0] * imu.gravity[1] - imu.gyro[1] * imu.gravity[0])
```

一行就是 ġz = −(ωx·gy − ωy·gx)(恒等式从哪来、为什么不对四元数做数值微分,见解读 05)。它是 `pub` 的,理由写在注释里(fall.rs:107-109):这是对着录像调阈值时要盯的那个数,"不设为公开就从外面拿不到"。`predicted_z`(fall.rs:115-117)是线性外推:当前重力 z 加速率乘 `lookahead.as_secs_f64()`——`Duration::as_secs_f64` 把 300 ms 变成 0.3。两个函数都不碰 `self` 的状态,是纯粹的可复用数学,测试因此能断言解析值(`the_rate_is_the_analytic_derivative`,fall.rs:170,容差 1e-12)。

## 3. `observe`:边沿触发的状态机

签名(fall.rs:120):`(&mut self, imu: &ImuData, dt: Duration) -> bool`。第一段算判据(fall.rs:121-124):三个条件与运算——已越 `tilt_z`、`rate > 0`(还在倒下而不是从倾斜中恢复)、外推越 `predicted_z`,缺一即"不像在摔"。第二段(fall.rs:126-133)是这个函数真正的机密:不像在摔时,**同时**清 `falling_for` 与 `fired`。注释(fall.rs:128-131):重新武装必须等机器人"不再像在摔",否则正在软倒的第一跤还没落地,调用方就又收到一记触发;测试 `it_rearms_when_the_fall_stops`(fall.rs:244-257)验证了完整序列——触发后必须先恢复、再凑满新一轮去抖,才有第二枪。第三段(fall.rs:135-139):像在摔则 `saturating_add(dt)` 累计,`falling_for >= debounce && !fired` 同时成立才返回 `true` 并立起 `fired`——默认参数下第三 tick 触发(fall.rs:207-210),此后同一次摔倒永远 `false`(fall.rs:211-213)。`reset`(fall.rs:145-148)留给"调用方已接管"的场合:清掉进行中的去抖,下一跤从零检测;测试 `reset_drops_a_debounce_in_progress`(fall.rs:262-271)钉住"计数重启"而非"接着数"。

测试侧还值得一枚:`tipping`(fall.rs:158-164)用 `gravity = [sin θ, 0, −cos θ]` 造出解析可算的姿态,于是每个阈值测试断言的都是数学事实而非近似;`a_footfall_on_an_upright_robot_never_fires`(fall.rs:189-195)用 8° 倾角加 3 rad/s 冲量复现"每一步都会发生"的那类假阳性,把它拒之门外的是 `tilt_z` 这道位置闸。

## 你带走的收获

- 预测器的终点阈值复用安全层的阈值:两个检测器说的是同一种摔倒的两种时态。
- `pub` 不只是封装的让步:把"调参要看的中间量"设为公开 API,是可观测性的设计手段。
- 边沿触发器同时管理"计数"与"已发"两个状态,且复位必须双向同步,否则第一跤的尾巴会触发第二跤。
- 解析构造的测试数据(sin/cos 造重力)让断言停在数学事实层,不吃数值误差。

## 延伸

- 物理推导与"迟侧调参"的理由:[解读 05](05-摔倒检测.md)
- 摔倒"确认"版判据与 gain_limp:[解读 04](04-安全层.md)
- gyro 与 gravity 的来路:[解读 06](06-姿态解算.md)
