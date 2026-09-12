# 解读 113 · robotd/control.rs:`Controller` 抽象

> **解读对象**:`robotd/src/control.rs`(747 行)
> **需要的前置**:[解读 09](09-主循环.md)(循环怎么调它);[解读 95](95-policy一Net与技能.md)(`Net` 与 `Policy`)

[解读 09](09-主循环.md) 看过守护进程的一拍;本篇走进被它调用的 `Controller`。模块注释(control.rs:1-16)按序写死一拍:窗口推进 → 指令重编码 → 优先链选网络 → ONNX 推理 → 目标 → 低通。它不持任何 IO 句柄,"构造上就命令不了电机,只能提议目标"(control.rs:2-5)。

## 1. 两张调参表,一个一拍的结果

`Tuning`(control.rs:49-77):`action_scale 0.9`、`standing_gain_ratio 0.8`、`gain 200`,低通 `head_lowpass Some(0.5)`、`legs_lowpass Some(0.7)`(control.rs:66-77)。`Option` 是 Rust 表达"可能没有"的类型,`None` 即不过滤;注释点名低通是训练合约:"must match training or transfer degrades"(control.rs:59-61)。`SkillTuning`(control.rs:81-114)装脚本动作的数:pick 周期 4.0 s、交还相位 0.7,`skills` 直接装配置——技能是数据。每拍产出 `Step`(control.rs:116-131):targets、label(`Cow<'static, str>`,Rust 的"能借用就借用、需要时才拥有"字符串,因为配置技能的名字来自配置而非编译期)、gain、busy(control.rs:122-125)。

## 2. 状态机与搬状态

三个小类型撑起历史:`Sit` 三态 Up/Sitting/Rising{remaining}(control.rs:134-144);`ActiveSkill`(control.rs:147-160)记 index、phase、剩余秒、chain 倒计时;`SkillPhase` 分 Holding/Unwinding(control.rs:167-173)——后者只为"不会自己结束的策略"存在,直接交还 walk 会交出一个卡在姿势中间的机器人(control.rs:163-166)。`Driving`(control.rs:179-192)是 `last_net` 的对外版,`Seated` 单独成变体:坐稳是"停放不是行进",是唯一在网络被替换时无感切换的状态(control.rs:183-187)。字段里 `last_action` 存**原始**输出——策略观察的是自己的输出,不是执行器指令(control.rs:211-214);`previous: Option` 让低通从现实起滤(control.rs:215-217)。`carry_over`(control.rs:281-289)在热替换时搬走全部状态:"换上新控制器会从 `Sit::Up` 开始,对坐着的鸭子就是一次没人要求的起身"(control.rs:274-276)。

## 3. 请求怎么变成状态

`start_skill`(control.rs:357-382)返回 `Ok(true)` 启动 / `Ok(false)` 刷新链——"调用方保持安静,因为按住的按钮每秒落在这里五十次"(control.rs:350-351);链时效 `CHAIN_WINDOW = 0.15`(control.rs:47)即七拍。`sit_toggle`(control.rs:386-403)在 Rising 中拒绝;`busy`(control.rs:318-322)是 pick、one-shot、Rising 之或——坐着不算 busy,"parked, not travelling"(control.rs:317)。

## 4. `step`:一拍的完整旅程

签名在 control.rs:427-434。**先过期**(control.rs:435-478):有 unwind 的先进 Unwinding(control.rs:448-452),窗口尽头的分叉只有链上技能能走(control.rs:453-471);链上重放虽是同一个 `Net` 却是新 episode,要 `policy.reset()`(control.rs:462-464)。**再选网络**(control.rs:483-539):技能清零头身槽——`zero_command_padding` 训出的策略就盼着这个;pick 把相位编成 `[cos φ, sin φ, 0]`(control.rs:504-512);坐旗标乘 vx 槽:`[1,0,0]` 坐、全零起(control.rs:517-524)。**缩放跟随状态**:`standing_tuned`(control.rs:559-561)解释了模块注释里的怪癖——踢腿与 rise 的指令全零,模长落进站立阈值,自然落在站立增益。然后 `targets[j] = DEFAULT_POSITION[j] + scale × offsets[j]`(control.rs:608-610),头四关节(5..9,control.rs:40)与十腿各做一阶低通,腿跳过嘴(control.rs:620)。**窗口最后推进**(control.rs:629-643):"原型在电机写之后推进相位"。测试 `the_defaults_match_the_prototype`(control.rs:698)与 `standing_softens_the_gain`(control.rs:732)钉住这些数。

## 你带走的收获

- 纯计算对象靠"构造上不持 IO"获得可测试与安全,提议与执行分层。
- 调参数值是训练合约(0.5/0.7 低通、0.8 增益比),要有测试钉住。
- "看起来一样"的状态拆成两个变体(Seated vs SitStand):对网络替换的容忍度不同。
- 窗口"先过期、使用、再推进"的顺序与原型对齐,是 sim2real 的一部分。

## 延伸

- 调用它的循环:[解读 09](09-主循环.md);`Net`/`Policy`:[解读 95](95-policy一Net与技能.md);技能配置:[解读 11](11-参数系统.md)
- 本地:`/Volumes/dev/dev/microduck/robotd/src/control.rs`

