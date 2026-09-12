# 解读 112 · robotd/main.rs(二):`control_loop` 全走读

> **解读对象**:`robotd/src/main.rs` 的 `control_loop`(:1826–3275,约 1450 行)
> **需要的前置**:[解读 09](09-主循环.md)(主干导览)、[解读 111](111-robotd启动与参数.md)(谁把它跑起来)

导览见解读 09,本篇把 `control_loop` 从头走到尾。它由解读 111 的专属线程 `block_on` 驱动;安全层握着唯一的 IO 出口。

## 1. 搭台:第一拍之前(:1836–2072)

先消费参数:`policy_params` 克隆,`drop_unloadable_overrides` 把加载不了的策略槽降级回默认并记入 `slot_errors`(:1839-1843),`Safety::new(io, config)` 把 IO 包进安全层(:1856-1865)。`adopt_startup_pose` 阻塞到总线答出第一个样本,存为 `hold`——**启动绝不先动**(:1867-1869)。随后判定 `seated_boot`:腿关节偏离 home 位的均值超过 `SEATED_BOOT_RAD = 0.30`(:150)即坐着上电,起立要走 sitstand 而非线性斜率(:1875-1887)。`build_controller`(:1890)加载策略;`ticker.set_missed_tick_behavior(Skip)`(:1914,见解读 09)。之后是一串可缺席的协作者(`Coast`、`FallPredictor` :1968-1977、声音、宠物检测、特雷门、合唱),全坏了也不影响走路(:1979-2065)。

## 2. 一拍之始:读、滑行、门(:2074–2134)

`safety.read()` 成功则清 `consecutive_errors`;失败则计数打日志(:2093-2108):连续第 10 次的"一串"照旧报,孤立掉读受 `BUS_DROP_QUIET = 60`s 限流,压掉的次数记进 `bus_drops_quiet`。样本进 `Coast::sample`(:3310-3323):失败的头 3 拍(`COAST_TICKS`)沿用上个好样本,再往后返回 `None`。只有**新鲜**样本才喂 `safety.observe` 和里程计(须 `imu_ready`,滑行拍跳过,:2120-2129)。随后 `intents.snapshot()` 与 `safety.gate`(死手开关在这里读 twist 的年龄,:2132-2133)。

## 3. 一拍之中:请求与两个状态机(:2136–2615)

请求按优先级消费。`take_power_request`:`robot.init` 从 Limp 上扭矩后要么坐着起立、要么进 `Homing` 斜率,`robot.relax` 切扭矩回 Limp(:2141-2200);`robot.rebootMotors` 先切扭矩再重启舵机(:2211-2229)。模式切换(:2324-2357)先回家再换网络,并按目标模式 chirp 一声或两声。策略变更(:2368-2443)由 `change_disturbs`(:1641-1664)判断:换掉正在驱动的网络→回家等新网络;"坐着的机器人什么变更都不打扰",其余原地 `carry_over` 换入;加载在独立线程,`PendingSwap::poll` 非阻塞收结果(:1594-1614)。关机(:2445-2495):`robot.shutdown` 或电池 EMA 触到 `BATTERY_EMPTY_V` 时,能坐下就 `begin_shutdown_sit` + 非阻塞播 `peck`,坐完 `cut_torque_before_poweroff`(:1791,重试 3 次)再 `poweroff()`。limp-fall(:2510-2615)是三态机:`Idle` 里 `falling.observe` 判坠落→`Limp`(跟随实测、`gain_limp` 软着陆);`Landing::observe` 按陀螺幅值去抖判"已停"或超时→`Posing`(斜率回 home);到达后交还策略;中途被抢则弃权。

## 4. 一拍之末:目标、嘴与发布(:2618–3272)

命令平滑:`slew`(:1500-1504,丢弃非有限目标)对 twist/head/body 三个 EMA 各推一步,合成 `PolicyCommand`(:2638-2654)。使能路径(:2673-2709)在 `Limp`+使能+有控制器+有样本时上扭矩进 `Homing`,防的正是"坐下→站起→关机"的时序 bug;`Homing` 完成处(:2717-2755)顺势落地 `mode_change`,`pending_swap` 等 ramp 结束或原地生效(:2765-2846),失败保留旧控制器、错误记进 `slot_errors`。`driving` 七条件(:2869-2877)的边沿管理重置:`reset_on_resume`(:3337)只在真停顿(`RESET_AFTER_PAUSE = 200ms`)后才重置。电压自适应 `scale_mult = nominal_voltage / battery_v`(钳 6.0–9.5,:2923-2927)。目标四分支 `match`(:2929-2989):limp-fall 优先,然后策略步进(推理失败落 `hold`)、`homing` 斜率、`hold`。嘴有三个主人(:2992-3171):特雷门>合唱>意图,只有 driving 时意图才能动嘴。最后 `safety.apply` 写总线(:3173),有订阅者才组装状态帧(:3181-3224),每 1 秒窗口算 `achieved_hz` 并 `publish_slow_sensors`(:3237-3243),每 5 分钟汇总报真实掉读率(:3245-3271)。

## 你带走的收获

- 滑行(`Coast`)与新鲜样本分开管:去抖和里程计只吃新鲜读,策略可吃 3 拍内的旧读。
- 状态切换都"先回家":模式切换与扰动性变更共享 Homing 机制,网络永不在移动中换。
- 嘴的单一所有权链是并发写同一关节的干净解法:特雷门>合唱>意图。

## 延伸

- 启动与总线打开:[解读 111](111-robotd启动与参数.md)
- `gate`/`apply` 内部:[解读 04](04-安全层.md);limp-fall 预测器:[解读 05](05-摔倒检测.md)
