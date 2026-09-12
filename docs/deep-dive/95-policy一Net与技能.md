# 解读 95 · policy.rs(一):`Net` 与技能枚举

> **解读对象**:`duck-control/src/policy.rs`(811 行)
> **需要的前置**:[解读 03](03-策略加载.md)(同文件的导览篇);[解读 96](96-policy二加载门.md)是本篇的下半场

从这一篇起进入函数级精读。模块注释(policy.rs:1-14)先立两条规矩:走与站由速度指令的模长决定,技能网络(sit↔stand、ground pick、踢腿)由 `robotd` 的调度器**显式点名**,优先级规则住在那边;"一切都在加载时校验,而不是在推理时"(policy.rs:10-14)。本篇读前半:这个文件怎么给"该跑哪个网络"命名。

## 1. `Net`:一个五选一的枚举

Rust 的枚举(enum)是"几个变体里取一个"的类型,每个变体还可以携带数据。`Net`(policy.rs:204-219)正是这么用:

```rust
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Net {
    Walk,
    Stand,
    SitStand,
    GroundPick,
    Skill(usize),
}
```

`#[derive(...)]` 让编译器自动生成比较、拷贝等样板实现;`Copy` 使 `Net` 像整数一样按值复制,不涉及所有权转移(所有权是 Rust 的内存规则:每个值有唯一主人)。四个具名变体各带一行注释:`SitStand` 复用 twist 的 `vx` 槽传姿势旗标(1=坐下,0=站立,policy.rs:208-209);`GroundPick` 的 twist 槽传 `[cos φ, sin φ, 0]` 相位(policy.rs:210-211)——观测布局不扩,技能只是"指令编码"。

最值得读的是 `Skill(usize)`(`usize` 是平台位宽的无符号整数,policy.rs:212-218)。注释交代了重构史:踢左、踢右、roulade 曾经是三个枚举变体,后来发现它们是"同一件事重复三遍"——零指令网络、固定窗口、显式请求,只有时长与调参不同,那是**数据**不是类型。换成索引后,"给机器人加一个技能"从"改枚举发版"变成"加一条配置项"(policy.rs:214-218)。

## 2. `PolicyPaths`:配置即能力

`PolicyPaths`(policy.rs:223-233)回答"有哪些文件可载":`walk: PathBuf` 必填;`stand/sitstand/ground_pick` 是 `Option<PathBuf>`——`Option` 是 Rust 表达"可能没有"的类型(`Some(x)` 有、`None` 无),这里语义精确:**没配 = 机器人没这个能力**,不是"加载失败"。`skills: Vec<PathBuf>`(`Vec` 是可变长数组)按调用方希望的优先序排列,注释补了一句:空列表是"没有特技的机器人",不是"缺了东西的机器人"(policy.rs:229-232)。

## 3. 能力查询:先问有没有,再决定用不用

`Policy` 结构体(policy.rs:240-251)按同样形状存网络,查询方法全走 `Option`:`has_standing/has_sitstand/has_ground_pick`(policy.rs:316-326)、`skill_count()`(policy.rs:329-331)——调度器的纪律是先用 `has_*` 问,再发 `Net` 请求。`will_stand`(policy.rs:310-314)是三条件与:`stand.is_some() && !standing_disabled && twist_magnitude <= 0.05`(阈值常量 `DEFAULT_STANDING_THRESHOLD = 0.05`,policy.rs:28)。它单独存在,是因为调用方要拿同一答案去选增益和动作缩放,"问两次不能得到两个答案"(policy.rs:306-309);`set_standing_disabled`(policy.rs:302-304)给滚轮和摔倒恢复用——它们占用了站立网络,模长规则必须失效(字段注释 policy.rs:248-250)。

`infer`(policy.rs:336)入口还有一道保险:请求了没加载的网络,回退到 Walk 而不是 panic——注释原话"错误的步态好过死掉的控制线程"(policy.rs:333-335)。但设计意图是这条回退永远走不到:它给竞态兜底,不给调用方偷懒。

## 你带走的收获

- "能力"用 `Option` 建模而不是错误码:没配置是正常态,类型自己会说话。
- 三个雷同变体合并成带索引的一个:类型只编码"本质不同",参数差异交给数据。
- 查询与执行分离(`will_stand`/`infer`):同一问题问两次必须同答案。
- 纪律("先 `has_*` 再请求")防常态错误,回退防竞态——两层各管各的。
- 阈值 0.05 要有常量名和出处:它是原型的调参遗产,不是随手可改的字面量。

## 延伸

- 加载门与 `validate`(本文件下半场):[解读 96](96-policy二加载门.md)
- 导览版三道门总览:[解读 03](03-策略加载.md)
- 站立网络被摔倒恢复占用的另一端:[解读 05](05-摔倒检测.md)
- 本地:`/Volumes/dev/dev/microduck/duck-control/src/policy.rs`
