# 解读 114 · robotd/intents.rs:槽、快照与权力

> **解读对象**:`robotd/src/intents.rs`(703 行)
> **需要的前置**:导览见[解读 10](10-意图层.md)(三种槽语义);消费方见[解读 09](09-主循环.md)

[解读 10](10-意图层.md) 讲过地基:ArcSwap 槽、时间戳、边沿/电平/事件三分。本篇函数级走读没展开的部分——位掩码布局、快照组装、每对 `request_*`/`take_*` 的理由。**权力**取字面义:循环是唯一能碰总线的东西,intents 就是意愿递进循环的全部通道(intents.rs:155-157)。

## 1. 技能位掩码:一个 `u32` 的预算

一次一拍的技能请求不是单个槽,而是位图(intents.rs:74-87):"同一拍里两个不同的请求都该被看见——单个 last-writer 槽会弄丢一个"。布局三个数:底两位保留席 `SKILL_GROUND_PICK = 1 << 0`、`SKILL_SIT_TOGGLE = 1 << 1`(intents.rs:102-103)——这两个由守护进程自己驱动(关机坐下、开机起身也走它们),不进可配置清单(intents.rs:78-81);可配置技能从第三位起,`request_skill` 存 `1 << (index + SKILL_BITS)`(intents.rs:345-348),`take_skills` 用 `bits >> SKILL_BITS` 还原(intents.rs:352-359)。上限 `MAX_SKILLS = 30`(intents.rs:111)不是防滥用:每个技能的网络启动时都要加载加预热。`requested()`(intents.rs:96-99)按位号从低到高迭代——位号即优先序,因为技能清单本就按配置排序。

## 2. 声音请求的两个去向

`request_sound`(intents.rs:365-377)第一行就分岔:wheee 不是事件,是电平——按住的骑乘,写进带戳的槽;其余标签进 `sounds: AtomicU32` 位图。`take_sounds`(intents.rs:380-394)按写死的顺序过滤:`Alarm, Greet, Inquire, Peck, Chirp, Coo`——遍历顺序即优先级,和技能"位号即优先序"是同一个决定。注释补了一句:裸的 `tag: wheee` 不带 `hold` 当 `hold: true` 写——"一个立刻开始衰减的 hold:一小段骑乘"(intents.rs:361-364)。查询端 `wheee_hold`(intents.rs:398-408)把值加年龄判成三态;三态为何不能压成 bool,见[解读 10](10-意图层.md)。

## 3. 成对的 request/take,容器按载荷选

节奏:请求端 store,循环端 swap 取走。`power` 用 `AtomicU8` 编码两个互斥请求(intents.rs:149-153,"一次 set_torque 是每关节一笔总线事务,电平会让每拍十六次写");`reboot_motors` 带一个 id 列表,只能用 `Mutex<Option<Vec<u8>>>`,取时 `try_lock`——"锁被占着就读作'还没有',下一拍再来",循环永远不等(intents.rs:481-488)。`request_chorale`(intents.rs:503-512)是手工的两步:先写 piece 钉子再 swap 请求旗标——"先钉子后旗标,下一拍消费的循环才能看见";piece id 从 1 起,0 当"没钉"(intents.rs:506-507)。`stop` 与 `request_relax` 的区别:`stop` 只清 twist,不动 enabled——"机器人该站住,不是瘫软也不是停驶"(intents.rs:314-317,测试 intents.rs:685)。

## 4. snapshot,与一处看得见的手滑

循环每拍读的 `snapshot`(intents.rs:569-588)把各槽拼成 `Command`:body 块恒为 `BodyPose::default()`——"训练用的标称零,不是占位符",平滑由循环自己做,"平滑是每拍状态,意图槽不该拥有它"(intents.rs:578-581,246-248);`twist_age` 用 `saturating_sub` 防下溢(intents.rs:583)。`PoseIntent.active: false` 的语义是"立刻弹回标称",对应原型 B 键退出(intents.rs:54-57)。

如实记录一处瑕疵:intents.rs:469-491 一带,`request_relax` 与 `request_reboot_motors` 的文档注释互相串行——"Ask the loop to reboot these servos" 长在 relax 的文档里,relax 的后半句单独挂在 490 行。功能无损,读注释会拐弯;两个函数体(intents.rs:475-479、492-494)各自清楚:都清 `enabled`,一个存 POWER_RELAX、一个存 id 列表。

## 你带走的收获

- 位掩码合流"同拍多请求":保留席、位移还原、位号即优先序,全在常量里。
- 请求端/取走端成对,容器按载荷选:互斥小值用原子,带列表用 try_lock。
- 两步写没有原子性可蹭时,规定写入顺序并写明哪个读是同步点。
- 快照把"哪个字段的年龄要紧"(twist_age)显式带上。
- 注释会撒谎(串行的文档),函数体不会——读代码以函数体为准。

## 延伸

- 请求在循环顶部怎么被消费:[解读 09](09-主循环.md)
- wheee 三态与骑乘出口:[解读 10](10-意图层.md)、[解读 117](117-soundrs一播放管线.md)
- 本地:`/Volumes/dev/dev/microduck/robotd/src/intents.rs`
