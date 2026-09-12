# 解读 102 · safety.rs(一):`gate` 死手开关

> **解读对象**:`duck-control/src/safety.rs`(612 行)
> **需要的前置**:[解读 04](04-安全层.md)(安全层导览)、[解读 10](10-意图层.md)(意图与时间戳)

导览见解读 04,本篇逐函数下钻:先读安全层的全部词汇(五个配置数),再逐行读 `gate`,最后看"被拒绝"如何被上报。

## 1. `SafetyConfig`:五个数字就是全部词汇

`SafetyConfig`(safety.rs:51-66)是 `Clone + Copy` 的小结构(导出 Copy 意味着赋值即按位拷贝,随处传值无负担),五个字段各是一道安全决策,默认值集中在 `Default`(safety.rs:68-79):`fall_gravity_z = -0.5`(投影重力 z 阈值,直立约 -1.0、侧躺近 0,safety.rs:72)、`fall_debounce = 200 ms`(safety.rs:73)、`deadman = 500 ms`(safety.rs:74)、`gain_running = 200`(safety.rs:75)、`gain_limp = 50`(safety.rs:76)。gain_limp 的定位注释值得抄(safety.rs:62-65):"机器人停止对抗地面的那个增益"——它住在这份配置里因为它是安全数字,但**本层不施加它**,limp-fall 由上层通过 `apply` 主动要(见解读 103)。行程常数 `ACTUATOR_MIN/MAX = ∓π`(safety.rs:47-48)也在文件头:注释明说是执行器行程而非解剖限位,挡得住 NaN 与垃圾张量,挡不住"机械上不明智"的姿势。

## 2. `gate`:拿走一个命令,还回一个命令

签名(safety.rs:230):

```rust
pub fn gate(&self, command: Command, intent_age: Duration) -> (Command, Option<Limit>)
```

三个细节都有讲究。`&self` 是只读借用——gate 不改任何状态,同一命令问多少次答案都一致;`command` 按值收、按值还,因为 `Command` 是 `Copy`(obs.rs:75),拷贝只是几个小数组,换来调用方不必自持两份;返回 `(命令, Option<Limit>)` 二元组,`Option` 表达"这拍有没有克扣你":`None` 原样放行,`Some(Limit::Deadman)` 告知动过手。逻辑四行(safety.rs:231-236):意图年龄不超过 `deadman` 就原样奉还;超龄则拷贝一份、`stopped.twist = [0.0; 3]` **只清 twist**,头部目标原样保留——过期姿态无害,过期速度会让机器人走进墙(safety.rs:226-229)。测试 `the_deadman_zeroes_the_twist_only`(safety.rs:564-580)把三件事钉死:新鲜放行相等、超龄只清 twist、返回值是 `Some(Deadman)`。这是纯函数加值语义的范式:审查时不需要追踪任何隐藏状态。

## 3. `Limit` 与 `Applied`:拒绝要能被看见

`Limit`(safety.rs:84-91)枚举三种克扣:`Deadman`(意图过期)、`Range`(超行程被钳)、`NotFinite`(NaN 被拒)。`Applied`(safety.rs:94-97)是一包 `Vec<Limit>`,作为 `apply` 的回执;`limited_by`(safety.rs:100-102)一行 `self.limits.contains(&limit)`,让调用方问"这拍被 X 拦过吗"。文档说破动机(safety.rs:81-82):克扣要能上报给客户端,"而不是让机器人眼看着不理你"——静默的修正与静默的拒绝同样是调试黑洞。同族还有 `fallen()`(safety.rs:149-151):`observe` 每 tick 更新、只发布不拦截,机制与那块板子上的真实事故见解读 04,本篇不重复。

## 你带走的收获

- 安全参数集中在一个 `Copy` 配置结构里:五个数就是这一层的全部自由度,没有藏着的第三个答案。
- 查询型函数用 `&self` 加值语义返回:可重入、可缓存、审查无需追踪状态。
- deadman 只清速度不清姿态:过期输入的危害要按通道分别评估。
- 每种拒绝都是一个枚举值:调用方拿回执,而不是猜机器人为什么没动。

## 延伸

- `apply` 怎么消费这些回执、增益怎么缓存:[解读 103](103-safetyrs二apply.md)
- observe 的双向去抖与 imu_ready 守卫:[解读 04](04-安全层.md)
- 课程对照:`/Volumes/dev/dev/microduck/docs/course/04-61到14-鸭子的神经回路.md`
