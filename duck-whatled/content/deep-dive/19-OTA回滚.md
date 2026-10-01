# 解读 19 · updater(下):reconcile 与回滚

> **解读对象**:`updater/src/reconcile.rs`(373 行)+ `updater/src/orphan.rs`(352 行)+ `updater/src/faults.rs`(120 行)
> **需要的前置**:[解读 18](18-OTA清单与验证.md)。

## 回滚是最容易悄悄坏掉的功能

faults.rs 开头一句话足以立论(faults.rs:1-6):回滚只在"别的东西已经坏了"时运行,所以最容易悄悄坏——"回滚大概能用"必须变成 CI 断言。手段是**故障注入**:`Faults`(faults.rs:14)八个开关,从 `corrupt_artifact`(必须哈希不匹配、不安装)到 `fail_rollback`(更新失败且恢复失败,必须大声报告)。三条纪律值得抄走:

- 编译进正式二进制而非 `#[cfg(test)]`(Rust 的条件编译,只对测试构建生效),同一支二进制可在台架演练(faults.rs:8-10);
- 启用需配置 `allow_fault_injection`,量产配置永不设(faults.rs:59-65);
- 打错的故障名**报错而非忽略**(faults.rs:78-84)——静默忽略的注入会让测试在什么都没注入时"通过"。

回滚的机械动作很小:发布布局是 `releases/<版本>/` 加一个 `current` 符号链接(store.rs:6-8),换代 = `rename(2)` 原子改链接(store.rs:146),回滚 = 把链接指回去。难的是知道何时该回,以及回完之后世界是否一致。

## orphan.rs:把 203/EXEC 拦在换链接之前

一个真实事故(orphan.rs:10-14):板子从 dev 构建解析到 stable 0.2.0,而 0.2.0 早于 configd 诞生;`configd.service` 还在,`ExecStart` 指向旧版没有的二进制,systemd 报 `203/EXEC`,失败的重启又让更新失败、触发回滚。结局正确,诊断却只能靠读 systemd 错误码。

`would_orphan`(orphan.rs:66)把规则变成检查:扫 `/etc/systemd/system/*.service`,凡 `Exec*=` 指进 `current` 符号链接、而候选版本里没有对应文件的,就是孤儿。细节:

- 每个 `Exec*=` 都算,不只 `ExecStart`(orphan.rs:108-123)——`ExecStartPre` 缺文件一样失败;`logical_lines`(orphan.rs:130)合并 systemd 的反斜杠续行,`updaterd.service` 自己的 ExecStart 就跨三行。
- **故意 fail-open**(orphan.rs:26-31):读不懂的 unit 不产出结论。假阴性的代价是回到今天那个 203/EXEC 回滚;假阳性的代价是因解析器看不懂而拒绝更新——拒绝更新是更新系统唯一不可以做错的事。
- 位置讲究:不在 preflight(preflight 看不到候选文件列表),在"解压后、换链前"跑;也不在回滚路径上——能拒绝人的检查不得坐在恢复路上(orphan.rs:33-43)。
- `refusal`(orphan.rs:189)给的是可执行出路:`systemctl disable --now <unit> && rm <path>`;**故意不做 `--force` 旗标**——删除 unit 才是操作者真正的意思,让局面变真,而不是推翻一个说真话的检查。

## reconcile.rs:重启真的发生了吗

更新的延迟重启经 `systemd-run` 排程,而**排程成功 ≠ 重启发生**(reconcile.rs:3-8),这留下一个静默态:机器人跑着它没装过的版本。reconcile 在每次 `updaterd` 启动时对账:读每个守护进程启动时发布的 identity 文件(`running_release`,reconcile.rs:173),与组件 `current` 指向的版本比对,过期者 `systemctl restart`。

裁决函数 `verdict_for`(reconcile.rs:81)是纯函数、与一切 syscall 分离——"会判错的部分"必须可测,而真实板凑不出那个状态,它恰恰要靠坏更新才能制造。四条裁决里最重的一条:**`updaterd` 永不在这里重启自己**(`Verdict::ReportedOnly`,reconcile.rs:62-74)。若继任者对"哪个版本是活动"意见相左,它会重启、再相左、再重启——在独占恢复的进程里死循环,那是唯一没有出路的故障。检查放在启动时的理由也直白:updaterd 无法目睹自己的重启落地,只有继任者能查(reconcile.rs:21-27)。另外,停着的 unit 不是过期的 unit(reconcile.rs:87-89):每次启动都替人重启它停掉的服务,是没人要的决定。

## 你带走的收获

- 只在故障时运行的代码最容易烂:把故障做成可注入开关,恢复路径才进得了 CI。
- 检查宁可 fail-open,不可错误地拒绝——错误地拒绝更新本身就是最大事故。
- 错误信息给 remedy(具体命令),不开 escape-hatch 旗标。
- 对账交给继任者进程;拥有恢复能力的进程永不重启自己。

## 延伸

- [解读 18](18-OTA清单与验证.md):换链之前的防线。
- [解读 20](20-配置与IPC.md):`update.progress`/`update.show` 如何把这一切讲给客户端。
- 源码:`updater/src/reconcile.rs`、`updater/src/orphan.rs`、`updater/src/faults.rs`、`updater/src/store.rs`。
