# 解读 103 · safety.rs(二):`apply` 与受限动作

> **解读对象**:`duck-control/src/safety.rs`(612 行)
> **需要的前置**:[解读 04](04-安全层.md)(安全层导览)、[解读 102](102-safetyrs一gate.md)(`gate` 与回执类型)

导览见解读 04,本篇逐函数下钻 `apply` 的四个步骤,以及增益缓存与它的失效时机。

## 1. `apply`:通往电机的唯一路径,四步

签名(safety.rs:246-251):`(&mut self, targets: [f64; NUM_JOINTS], hold: [f64; NUM_JOINTS], running_gain: u16) -> Result<Applied, IoError>`。文档先划边界(safety.rs:239-245):`hold` 是"策略不许开车时改命令的位姿"(通常是机器人当前所在);`running_gain` 是调用方要的增益——站立策略跑软增益、limp-fall 更软,这些是**控制决策**,传进来而不是在这里二次猜测。注释还特意记下"这里没有的东西":摔倒闸(safety.rs:254-257,论证见解读 04)。

第一步先写增益(safety.rs:258 `self.set_gain(running_gain)?`),排在一切检查之前并非随手:即便这拍目标被判 NaN 拒绝,调用方要的增益也已生效——limp-fall 换软增益不依赖目标质量(测试 `a_caller_that_asks_for_the_limp_gain_gets_it`,safety.rs:486)。第二步非有限检查(safety.rs:263-267):`targets.iter().any(|v| !v.is_finite())` 命中即记 `Limit::NotFinite`、**写入 `hold`**、提前返回。注意是写 hold 而不是什么都不写:"拒绝移动"要落成一条真实的总线写,关节才停得住(为什么拒绝而非钳位,见解读 04)。第三步行程钳位(safety.rs:269-278):逐关节 `value.clamp(ACTUATOR_MIN, ACTUATOR_MAX)`,钳过才记 `Limit::Range`,并用 `limited_by` 去重——一拍最多记一次 Range,不按关节刷屏。第四步 `self.io.write(&JointTargets::new(safe))`(safety.rs:280)出总线。

## 2. `set_gain`:缓存与 reboot 失效

`set_gain`(safety.rs:284-291)两行短路:`if self.gain == Some(kp) { return Ok(()); }`——增益没变就不写,`Option<u16>` 的 `None` 表示"从没写过"。`gain()` 查询(safety.rs:184-186)返回"实际在跑的",与调用方要的在不写的那几拍里是同一个,在守卫与失效场景下可能不同。真正值得看的是失效路径 `reboot_motors`(safety.rs:173-180):逐 ID reboot 之后 `self.gain = None`。注释一句话(safety.rs:170-172):重启后的舵机回到 EEPROM 里存的增益,缓存若还咬定"200 已写入",舵机就停在 EEPROM 值上没人管;置 `None`,下一次 `apply` 无条件重写。测试 `rebooting_motors_rewrites_the_gain_on_the_next_apply`(safety.rs:306-321)完整走了这个循环:apply→reboot→gain 变 None→再 apply 恢复。

## 3. 门面:借出的读,收着的写

`Safety` 包着 IO,但只暴露方法(safety.rs:127-147):`read`、`slow_sensors`、`imu_stale`、`imu_ready` 逐个直通。为什么读要直通、写要包住?注释(safety.rs:131-136)给出判据:慢速传感与 IMU 诊断是读,不威胁"只有这里能写电机"的不变量;但**把句柄递出去**就是威胁——所以宁可逐个转接,也不开 `io()` 的口。唯一的例外是 `#[cfg(test)]` 的 `io()`(safety.rs:295-298):编译进测试二进制的借用器,注释明说"在生产里递出它会击穿安全层存在的意义"。`set_torque`(safety.rs:165-168)同样走这扇门,注释列明契约(safety.rs:153-164):人使能策略时调用一次、启动**不**调(更新重启的 robotd 必须让站着的鸭子继续站着)、且不绕过任何钳位——摔倒的鸭子扭矩开着,也照样被命令 hold 于 `gain_limp`。

## 你带走的收获

- 唯一写路径的步骤顺序有语义:增益先行,"拒绝"落成一次写 hold 的真实总线事务。
- 拒绝不是跳过:写 hold 才能让关节停在原地,"不动"也是一种被写入的状态。
- 缓存要有配对的失效动作:reboot 之于增益缓存,正如关文件之于文件句柄。
- 门面模式的关键不是包住危险方法,而是不递出原始句柄——读直通,写收权。

## 延伸

- `gate` 与三种克扣的回执:[解读 102](102-safetyrs一gate.md)
- 这条总线写下去之后发生什么:[解读 98](98-busrs一transact帧层.md)
- 课程对照:`/Volumes/dev/dev/microduck/docs/course/04-61到14-鸭子的神经回路.md`
