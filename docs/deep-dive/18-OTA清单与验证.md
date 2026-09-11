# 解读 18 · updater(上):manifest 与验证

> **解读对象**:`updater/src/manifest.rs`(275 行)+ `updater/src/verify.rs`(634 行)+ `updater/src/preflight.rs`(474 行)
> **需要的前置**:无。这一篇是通用的 OTA 工程教材。

## 为什么 OTA 必须这么谨慎

手机刷坏可以连电脑救;板子砖在够不到的地方,只能上门。所以这个更新器把每层防线都当唯一防线来写:**签名**(东西是谁发的)、**哈希**(东西完好吗)、**预检**(此刻能装吗)、**回滚**(装坏了怎么办,见[解读 19](19-OTA回滚.md))。三个文件各管一段。

## manifest.rs:字段即策略

`Manifest`(manifest.rs:11)的第一课是**首版就要带上暂时用不上的字段**——没学会读 `min_supported` 的机器人,日后无法被强制升级(manifest.rs:3-6)。清单格式是"无法回改"的契约:

- `channel` 与配置交叉核对,配错的 URL 不能把模型静默装成守护进程(manifest.rs:13-15)。
- `schema_version` **故意不是兼容门**(manifest.rs:37-44):评估清单的永远是上一个版本的引擎,拒绝 `schema_version > supported` 会让每次 schema 升级都无法交付——包括带来那个能理解它的引擎的版本。它只是交给 post-install 钩子做迁移的上下文。
- `compatibility`(manifest.rs:92)返回三态 `Ok / Refused / Unknown`(manifest.rs:142):robotd 不可达时 model_api 未知,是 `Unknown` 而非 `Refused`——守护进程通道照样装(那正是修活 robotd 的途径),模型通道则等。合并两态要么堵死恢复、要么装上加载不了的模型(manifest.rs:109-118)。

## verify.rs:一条顺序不变量

模块注释一行顶一万句(verify.rs:7-9):**未经签名的字节,永远不会落到活动路径或被执行**——清单签名 → 工件哈希 → 工件签名,全部通过才解压。要点:

- 信任锚是磁盘上的一**组** minisign 公钥而非单枚内置钥匙(丢钥、泄钥可存活);空钥匙环是错误而非空允许列表(verify.rs:128-133)——静默信任零个东西与配错路径无法区分,哪个方向都致命。依赖 `minisign-verify` 是仅验证实现:这个进程没有签名的业务,就不该链接能签名的代码(verify.rs:11-13)。
- `.dev.pub` 后缀的钥匙只在显式允许时可用(verify.rs:52):量产机器人装不进同事的本地构建。
- `extract_artifact`(verify.rs:287):路径穿越交给 `tar` 自带的 `unpack_in` 拒绝,其上再补总解压 2 GiB、5 万条目的上限(verify.rs:36-48),防 zip 炸弹填满 eMMC。穿越条目按**篡改**处理而非跳过(verify.rs:347-355):签名都验过了,敌意条目意味着我们自己的钥匙签了它,必须大声炸出来。

## preflight.rs:副作用之前,一遍报完

所有检查跑在下载之前,失败零副作用;每次 apply 跑两遍——拿到清单前查时钟/机器人停稳/无远程会话,拿到 `size` 后再查磁盘(preflight.rs:11-15)。顺序即诊断:时钟不对时,HTTPS 会以费解的 TLS 证书错误失败,而不是时钟检查想给的那句话。

- `CLOCK_FLOOR_UNIX = 1_735_689_600`(2025-01-01,preflight.rs:94):无电池 RTC 的板子开机即错钟,先抓"还没同步 NTP"。
- **故意不短路**(preflight.rs:99-101):一次报完"时钟错 AND 磁盘满",好过让用户修一个、重试、再撞下一个。
- `check_robot_stopped`(preflight.rs:185-209)藏着最精细的判断:robotd **不可达 = 安全**(控制循环没在跑就没东西在动,这正是需要更新的场合);**回答了但读不懂 = 拒绝**(循环在跑,只是协议错位),错误信息给出出路 `systemctl stop robotd`。测试注释(preflight.rs:382-387)记录了这个决定曾做反:读不懂曾被映射成"可达",于是一台正在走路的机器人被放行了。
- `SideloadDir`(preflight.rs:151)为 systemd 的 `PrivateTmp=yes` 生成一句人话:你的 `/var/tmp` 不是本进程的 `/var/tmp`,清单 `ls` 得见却"不存在"。

## 你带走的收获

- OTA 四层防线:签名(来源)、哈希(完整)、预检(时机)、回滚(后路);一层不能少,顺序不能换。
- 兼容性要三态:`Refused` 与 `Unknown` 混用会同时堵死恢复、放进坏安装。
- "schema_version 为什么不能当门"是向后兼容的最清晰教案。
- 错误信息必须带出路(具体命令),否则是在用户够不到的设备上砌墙。

## 延伸

- [解读 19](19-OTA回滚.md):装坏之后的另一半。
- [解读 20](20-配置与IPC.md):`update.*` 的线上契约。
- 源码:`updater/src/manifest.rs`、`updater/src/verify.rs`、`updater/src/preflight.rs`;设计文档 `docs/design/updater-design.md`。
