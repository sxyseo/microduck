# 解读 111 · robotd/main.rs(一):启动与参数

> **解读对象**:`robotd/src/main.rs`(8273 行)选段
> **需要的前置**:[解读 09](09-主循环.md)(主循环导览)、[解读 11](11-参数系统.md)(参数文件格式)

导览见解读 09,本篇逐函数下钻。源文件已长到 8273 行,09 的行号普遍前移(main 现在在 905 行),本篇与下一篇的行号均按当前文件核对。

## 1. 参数与开关:`Args` 与 `Params::load`

`Args`(main.rs:225-277)由 clap 派生(派生宏自动生成命令行解析代码),选项各有立场:`--socket` 默认 `/run/robotd.sock`(:229-230,"updaterd 必须指向同一个");`--params` 缺省 `/etc/robot/robotd.toml` 且**可以不存在**——"未配置的板子按默认值起",显式路径则必须存在(:232-235);`--port` 覆盖串口;`--fake` 无机器人;`--sim` 与 `--fake` 互斥;`--no-policy`(:262-264)与"策略加载失败"是两回事——后者不健康,前者是给"被测对象是更新器"的台架用的;`--unhealthy`/`--busy` 是验证回滚用的诚实开关(:267-273)。子命令 `Init`(:280-291)的 `--duration` 默认 `2s`,由 `parse_duration`(:293-305)解析。`main`(:905)把这些落进 `Params::load`(:924-930),再让 `--port` 与 `--no_policy` 覆盖字段(:931-936)。

## 2. `main` 的次序:锁先于电机

`main` 开头先恢复 SIGPIPE 默认行为(main.rs:906-907,否则 `robotd | head` 会 panic)。`Init` 子命令则先 `claim_lock` 拿实例锁再进 `run_init`(:938-950)。守护路径的顺序是刻意的:`claim_socket` **先于**发布身份、先于任何能碰电机的线程(:952-960);`RobotState`(IPC 侧只读的原子量集合)在 :963 构造;`poweroff` 闭包用 `setsid` 拉起 `systemctl poweroff`,避免被 systemd 连坐杀掉(:981-988);然后 `spawn_control_thread`(:990)与 `serve`(:1004)并行,`tokio::select!`(:1011-1019)等两者之一。收尾(:1021-1025):置 shutdown 标志、`control.join()`——"让循环做完手里那拍,而不是在事务中途夭折"——最后删 socket 文件。

## 3. 三种身体:fake、sim、真总线

`spawn_control_thread`(:1076-1154)按参数选身体,放进专属 OS 线程加 current-thread 运行时(为什么,解读 09 讲过)。`--fake` 直接 `control_loop(FakeIo::at(DEFAULT_POSITION), …)`(:1110-1122);`--sim` 用 `RemoteIo::at(addr)`,刻意没有"等总线"的对应物——它懒连接、每拍重试,"鸭子先于仿真器启动,只是报不健康"(:1124-1140);真总线走 `open_bus_waiting_with_backend`(:1148-1152)。总线本体 `BusIo`(:1157-1161)是 `Dynamixel`/`Hl2915` 两变体的枚举,方法全部 `match` 转发(:1164-1246)——枚举即开关。等待循环(:1262-1288)是"等,不是放弃":失败把尝试次数写进 `startup_bus_failures` **再**睡觉,"让 `robot.health` 立刻说出原因"(:1277-1278),每秒重试。

## 4. 打开总线、收养新舵机与 `init`

`open_bus_for`(:1297-1343)第一行定日志节奏:`loud = attempt == 0 || attempt.is_multiple_of(30)`(:1299,常量在 :1425)——守一夜的板子约 30 秒一行。后端分派(:1301-1311):Dynamixel 走 `DynamixelIo::open`;HL-2915 走 `Hl2915RobotIo::open(port, &DEFAULT_HL2915_IDS, IMU_DXL_ID, FeetechCalibration::default(), 30ms)`(见解读 109)。收养是 Dynamixel 独占的(:1323-1327),出厂探测要重开串口到 57 600 波特。`adopt_missing_servo`(:1356-1404)是决策树:ping 全员;不缺→继续;**15 只全缺**→"不是换舵机,只是没上电"(:1371-1375);恰好缺一只→`replacement_target` 定顶替者、`adopt_replacement` 收养;缺多只→分不清谁顶替谁,等人类。最后 `prepare()` 校验寄存器,`Ok(0)` 报"本来就对",`Ok(n)` 报"修正了 n 项"(:1328-1331)。`run_init`(:1031-1062)与守护进程同一条开总线路径,然后 `set_torque(true)`、`set_gain`、`interpolate_to` 到 home 位。增益必须在斜率**之前**写(:1043-1052):`position_p_gain` 是 RAM 寄存器,进程死了值还在,上次摔倒留下的 `gain_limp`(50)会让 init 用三分之一刚度拉起机器人。

## 你带走的收获

- 启动次序是安全设计:锁→状态→控制线程→IPC,端点先于一切能动机器人的东西。
- "打开失败"分两种:配置错误该快死,总线没电该等待并说出原因。
- 枚举后端加 `match` 转发,是最小的新硬件接入面。
- 一次性命令(`init`)与守护进程共用开总线代码,才不会"只有一条路认识新硬件"。

## 延伸

- 循环本身的逐行走读:[解读 112](112-robotd控制循环.md)
- 打开与收养的底层:[解读 99](99-busrs二慢速轮询.md)、[解读 109](109-hl2915rs二实现.md)
