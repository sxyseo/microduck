# 解读 115 · params.rs 与 robotd-params crate

> **解读对象**:`robotd/src/params.rs`(7 行)、`robotd-params/`(lib.rs 3346 行、edit.rs 1429 行、registry.rs 680 行)
> **需要的前置**:导览见[解读 11](11-参数系统.md)(schema 只留一份)、[解读 20](20-配置与IPC.md)

robotd/src/params.rs 全文是一句 `pub use robotd_params::*;`(params.rs:7)——Rust 的再导出,把另一个 crate 的名字搬进本模块命名空间。本篇读 crate 三个文件里导览没展开的函数。

## 1. `Params::load`:两遍解析,错误各归各位

`load`(lib.rs:1936-1985)第一道分岔是文件缺失:默认位置没有文件**不是错误**——未开通的板子按默认值起,起不来的守护进程更难诊断;显式指名的文件必须存在(lib.rs:1932-1935)。解析走两遍:先严格解析,serde 的错误带行列号(lib.rs:1951-1954);失败了才把本构建不认识的键剪掉重析并 warn 点名(lib.rs:1956-1970),剪完仍失败就报真错误。之后的 `validate`(lib.rs:1989-2009)只挡做不成循环的值:`control.hz` 为 0 或超 1000 拒绝(合法值含 1000);`media.bitrate` 限在 `BITRATE_MIN = 100_000` 到 `BITRATE_MAX = 20_000_000`(lib.rs:1928-1929),错误信息直接写明单位是 bits——`bitrate = 2000` 是想写千位的人,2 kb/s 是永远不出画面的流。码率不放在 mediad 查,是为了让编辑器当场拒绝写它(lib.rs:1996-1997)。

## 2. 名字即 API:`Slot` 与手柄绑定

`is_none_sentinel`(lib.rs:903-905)把字面量 `"none"`(忽略大小写)当"这个槽关掉",pub 是因为**三处要一致**:配置解析、`robotctl policy load <slot> none`、线上识别。`Slot` 枚举(lib.rs:1358-1417)把七个 `[policy]` 路径键变成值:线上加载、`toml_edit` 写盘、按槽报告三个消费方共用一份映射,免得谁写出 `policy.groundpick` 这种没人读回的键(lib.rs:1350-1354)。手柄侧 `PadParams`(lib.rs:140-166)默认五键:`a` 捡拾、`x` 侧滚、`lb/rb` 双踢、`dpad_down` 坐起,`skill()/bind()/names()`(lib.rs:173-200)供查询、改绑与报错拼名单;`PadImuHeadControlParams`(lib.rs:105-122)让带 IMU 的手柄倾斜摆头(lib.rs:100-102)。

## 3. 技能从哪来:清单、回退与合并

`builtin_skills`(lib.rs:1277-1307)读安装集合的清单:一条 `SetPolicy` 要**自认** episodic、零指令、给得出时长才成为技能。清单缺席是常态,回退是 `fallback_skills`(lib.rs:1311-1342)三件套:roulade 1.0 s、`chain: true`,踢腿各 0.5 s。`resolved_skills_with`(lib.rs:1499-1525)按名合并配置("文件是决策清单,不是默认值抄本"),三个槽键**最后**应用且获胜,保证 `policy load` 写的键与技能运行的文件一致(lib.rs:1487-1492);`"none"` 即关闭(lib.rs:1521-1523)。`SkillOverrides`(lib.rs:997-1007)刻意**小**:没有摔倒门覆盖(技能运行即 `busy()`,limp-fall 预测器不会被咨询)、没有 `cmd_alpha`(技能不读客户端指令),能改的只有 scale 与 gain 比。

## 4. edit.rs:四个写者一把锁

四个写者共用一个文件(edit.rs:523-526):`robotctl configure / policy / pad`,加 robotd 自己(替手机上的 `pad.bind` 写)。锁是配置旁的 `.lock` 文件而非配置本身——"持有要活得过替换它的那次 rename"(edit.rs:528-529)。`write_through`(edit.rs:491-515):写 `robotd.toml.new` → 用守护进程自己的 `Params::load` 校验,失败即删并拒绝写 → rename 就位 → fsync 目录。`edit()` 按注册表 `Kind` 分派(edit.rs:247-299):`Table`/`Record` 拒绝就地编辑,各指向命令与标定工具;`toggled`(edit.rs:317-321)把三态键循环成 auto→on→off。registry 的测试把编辑器钉在真相上:`the_feature_switches_are_the_expected_set`(registry.rs:646-679)钉死二十个功能开关名单——"拼错的开关会悄悄降级成调参项"。

## 你带走的收获

- 解析分两遍:常见路径拿最准的错误,宽容路径只为点名"哪个键不认识"。
- 名字映射集中成枚举加 `parse`,报错自带名单。
- 数据(清单)与决策(配置)分层解析,合并语义写明谁最后谁赢。
- 无损写配置闭环:旁锁、暂存、用消费者自己的解析器校验、原子改名、fsync 目录。
- 注册表完整性是测试不是希望:全覆盖、与类型互证、开关名单钉死。

## 延伸

- 七行再导出与路径常量:[解读 11](11-参数系统.md);解析出的技能进级联:[解读 113](113-robotd控制抽象.md)
- 本地:`/Volumes/dev/dev/microduck/robotd-params/src/{lib,edit,registry}.rs`
