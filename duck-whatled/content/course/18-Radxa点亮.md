# 第 18 课 · Radxa 点亮:把 Rust 运行时装上板子

> **这一课解决什么问题**:训练好的策略要有一颗"脑袋"才能在真机上跑。这一课把 Radxa Zero 3W 从一块空白板子变成一台能 SSH、能跑官方 Rust 运行时的开发板,并建立"改代码一分钟上板"的日常循环。
>
> **前置**:[第 05 课](05-第一次训练-冒烟测试.md)(完整跑通过 训练→回放→导出→验证)。手头要有一块 Radxa Zero 3W、电源和一个 WiFi 环境。

---

## 1. 先分清两台机器

从这一课起,你的桌子上同时出现两台电脑,分工完全不同:

- **开发机**(你的 Mac 或 Linux 电脑):写代码、编译、跑测试。整个工作区 **942 个测试**在这台机器上全过——无需硬件、网络和 Docker;
- **板子**(Radxa Zero 3W):一块 **aarch64** 架构的 ARM 小电脑(64 位 ARM 指令集,手机芯片同族,程序与电脑 CPU 不通用),只负责**运行**编译产物。

一条铁律来自 `docs/进阶学习文档-训练仿真与部署.md` 第 3 节:**不在板子上装 Rust**。编译是重活,板子那点算力干不来;它的本职是每 20 毫秒伺候 15 个舵机的 50Hz 闭环。

类比:开发机是中央厨房,板子是餐车——没人会在餐车上砌灶台。所以呢?开发体验全留在熟悉的电脑上,板子越简单越稳。

## 2. 刷卡三件事,一次填好

板子的系统装在 TF 卡上。用 Armbian 官方烧录工具选 **Radxa Zero 3 + Armbian 26.2.1 Minimal**,并且在**刷卡之前**把三件事一次填好:

1. **WiFi**——在烧录界面里填,板子开机自动联网,省掉接串口线救急;
2. **用户名密码**——同上,免得对着一块没有屏幕的板子猜"到底进系统没";
3. **ssh key**——`ssh-copy-id radxa@192.168.1.42`(IP 换成你板子的)。ssh key 是一对"锁和钥匙":公钥留在板子上,私钥在你电脑里,以后登录免密码,后面的全自动流程也靠这扇门。

这三件事一次填对,后面全是坦途;漏一件,就要给无屏板子接串口线排查。

## 3. 一键装机:provision-board.sh

一条命令把空白板子变成开发板:

```bash
./scripts/provision-board.sh --pause-btd-on-pair --name my-duck radxa@192.168.1.42
```

它依次完成:发 dev key → 装系统依赖 → 编译并部署 daemon → 重启 → 健康检查。(仓库未公开时需先 `export DUCK_TOKEN`,公开可省。)

注意 `--pause-btd-on-pair` 不是仪式感:板载 aic8800 无线芯片在手柄**首次配对**时需要它,漏了你会得到一只"怎么都查不出原因的配不上的手柄"(详见 `docs/robot/install-dev.md`)。

装完验证两件事:

```bash
robotctl health                                   # 健康检查通过
grep -c 'DEV BOARD' /var/lib/robot/provision.log  # 输出 1 = dev key 装好了
```

## 4. 日常循环:改代码一分钟上板

一次性准备(二选一):装交叉编译工具 `cargo-zigbuild + zig`(方案 A),或者什么都不装、命令加 `--docker`(方案 B,需要 Docker 在跑)。**交叉编译**就是在 Mac 上编译出 ARM 板子能跑的程序——中央厨房出餐,餐车直接端。

另外,团队 dev 私钥要放在 `~/.duck-keys/team.dev.key`:板子只认用它签过名的包,这是防陌生程序跑上真机的门卫。

之后每天的开发就是一条命令:

```bash
scripts/dev-push.sh radxa@192.168.1.42
```

它串起六步:交叉编译 → 打包 → 用 dev key 签名 → scp 到板子 → 过健康门安装 → 等守护进程报出新版本。你只管改代码,推上去等版本号。

还有个容易误解的设计:dev-push 装的是 **daemon**(常驻的控制程序),和"装模型"是**两条通道**——改步态不用重发 daemon,修 daemon 也不用重新下载 6MB 权重。脑子归脑子,小脑归小脑。

## 5. 动手练习(15 分钟)

1. 按第 2、3 节流程刷卡、ssh-copy-id、跑 provision;没板子就在纸上走查一遍,标出你会卡在哪;
2. 跑 `robotctl health` 和 `grep -c 'DEV BOARD' /var/lib/robot/provision.log`,把输出抄进笔记;
3. `robotctl policy list` 看一眼策略槽位——下一课你会知道里面装的是一份什么"合同"。

## 自查清单

- [ ] 我能说清开发机和板子各干什么、为什么不在板子上装 Rust
- [ ] 我知道刷卡前要填哪三件事,漏了分别会怎样
- [ ] 我能说出 dev-push 的六步,以及 daemon 和模型为什么分两条通道
- [ ] 我知道 `--pause-btd-on-pair` 防的是哪个坑

## 下一课预告

板子会跑程序了,但往它上面装的那个 `.onnx` 文件本身就是一份合同:61 维进、14 维出,还有一层最容易漏的归一化。第 19 课讲清这份合同的条款与验收方法。

## 延伸资源

- 进阶学习文档第 3 节(本课全部命令的出处):`docs/进阶学习文档-训练仿真与部署.md`
- 官方装机与推送文档:`docs/robot/install-dev.md`、`docs/robot/dev-push.md`
- Armbian 官方下载页:[armbian.com/radxa-zero-3](https://www.armbian.com/radxa-zero-3/)
- Radxa Zero 3 官方文档:[docs.radxa.com](https://docs.radxa.com/en/zero/zero3)
