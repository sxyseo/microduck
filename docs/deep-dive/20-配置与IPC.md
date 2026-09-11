# 解读 20 · configd + duckctl + duck-ipc-proto:配置、命令行与 IPC

> **解读对象**:`duck-ipc-proto/src/lib.rs`(5643 行)+ `configd/src/`(10 个文件共 4071 行)+ `duckctl/src/main.rs`(3069 行)
> **需要的前置**:[解读 18](18-OTA清单与验证.md)、[解读 19](19-OTA回滚.md) 里 `update.*` 的来历。

## duck-ipc-proto:一条线,一套契约

板子上多个守护进程(robotd/configd/updaterd/btd/tofd)与所有客户端说同一种话:**JSON-RPC 2.0、一行一个对象(NDJSON)、unix socket、换行分帧**(lib.rs:9-13);进度以无 `id` 的通知推送,断线重连的客户端重新订阅即可跟上。5643 行几乎全是类型,但三处值得专程来看:

- **版本哲学**(lib.rs:51-82)。`API_VERSION = 23`(lib.rs:276)的注释是一篇小论文:**bump 不承诺任何方向**(纯增量的 v5 也 bump);**守护进程不因版本号拒 call**——曾按 `!=` 拒绝,结果把包括 `update.apply` 在内的一切都拒了,而版本偏差恰恰是更新能修的;真正拒绝的只有更窄的两处:不认识的方法回 `METHOD_NOT_FOUND`,params 里不认识的成员回 `INVALID_PARAMS`——每个 params 类型都 `deny_unknown_fields`(serde 属性:遇到未声明字段即报错,而不是忽略)。v7 加 `from_dir` 的注释(lib.rs:83-97)是最好的例子:serde 会静默忽略未知字段,老守护进程收到 `--from` 会转身去装配置源——静默才是危险,分歧不是。
- **常量即契约**:`POLICY_OBS_LEN = 61`(lib.rs:285)、`POLICY_ACTION_LEN = 14`(lib.rs:289)是与任何策略发布者的契约;`UPDATE_MAX_SILENCE_SECONDS = 600`(lib.rs:307)定义"更新合法静默的上限",服务端与每个客户端读同一个常量,两边不可能各说各话。
- socket 路径集中在 `socket` 模块(lib.rs:317-333)。

## configd:配置必须是活的

为什么单开一个守护进程(configd/src/lib.rs:1-6):**配 wifi 恰恰是 robotd 死掉时最需要的能力**,配置不能住在控制守护进程里;它也**不存凭据**——NetworkManager 持有密码并自行重连(configd/src/lib.rs:16-18)。

`store.rs` 是"文件,不是服务"(store.rs:1-9)的范本:普通 JSON 文件 + `flock` 串行化写者 + 临时文件 `rename(2)` 原子替换,还补上最常被忘的一步——**目录 fsync**(store.rs:182),否则 rename 可能熬不过断电,而"拔墙上的电"是机器人的常态而非例外。处处是硬件约束:`MAX_NAME = 24` 来自 BLE 传统广播总共 31 字节载荷(store.rs:20-26);配对 PIN 恰好六位(store.rs:40-45)——蓝牙规范就是六位,"12345 还是 012345"的分歧是没人能诊断的客服电话。访问控制两层(main.rs:77-114):socket 组决定谁能**说话**,`--allow-user/--allow-group`(按用户名而非 uid,因 sysusers 动态分配 uid)决定谁能**改**;只读调用不设门,支持才能检查一台它无权重配的机器人。

## duckctl:超时即文档

`duckctl` 是手机 app 的替身,走 BLE(btleplug,为跨 macOS/Linux/Windows 选型,main.rs:15-18);板上没有任何东西依赖它,所以这个 BLE 库进不了发布件(main.rs:10-13)。最值得读的是超时常量组(main.rs:53-117):`REPLY_TIMEOUT = 15s` 是**空闲**预算而非总预算——每个进度通知都证明机器人活着并重置时钟,所以 apply 想跑多久跑多久,卡死的机器人几秒露馅;`UPDATE_IDLE_TIMEOUT` 直接由 `UPDATE_MAX_SILENCE_SECONDS + 60` 推导(main.rs:87-88),注释记着教训:它曾是 180 s,协议静默上限涨到 600 s 后,预算低于上限的客户端会把正常更新报成"机器人停止应答"。

## 你带走的收获

- 多进程协作先定一份线协议 crate:类型与常量共享,客户端预算从协议常量推导。
- 版本号只标记"不是一起构建的";拒绝要发生在具体方法与具体参数上,而非握手上。
- 配置 = 文件 + flock + rename + 目录 fsync;服务死活不应影响配置可达。
- 超时按"最长合法静默"设,不按"最长合法耗时"设。

## 延伸

- [解读 18](18-OTA清单与验证.md)、[解读 19](19-OTA回滚.md):`update.*` 背后的引擎。
- 第一辑《解读 01》《解读 09》:总线与主循环,这条协议的另一端。
- 源码:`duck-ipc-proto/src/lib.rs`、`configd/src/lib.rs`、`configd/src/store.rs`、`configd/src/main.rs`、`duckctl/src/main.rs`。
