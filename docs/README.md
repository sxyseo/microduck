# Docs

The [README](../README.md) is the front door — what a microduck is, and where to go. If you have
one in front of you and want to drive it, start at the [cheat sheet](robot/cheatsheet.md).

[`faq.md`](faq.md) is the other front door: task-shaped questions from somebody building
*against* a duck rather than changing it — running a model too heavy for the board, getting the
camera into their own program, why a Space cannot connect.

It is also where a **publisher** starts: [`policy-manifest.md`](policy-manifest.md) is the
contract for a `manifest.json` beside a microduck `.onnx`, and it owns every field. The design
docs give the reasoning and point at it.

## `robot/` — you have a robot

| | |
|---|---|
| [`新手学习文档.md`](新手学习文档.md) | 面向硬件、电路、机械零基础的学习顺序、设备分工、读图和上电安全。 |
| [`代码解释与使用教程.md`](代码解释与使用教程.md) | 从 `robotd` 控制链和 Rust workspace 地图入手，说明如何运行、阅读和改造代码。 |
| [`HL2915全链路落地手册.md`](HL2915全链路落地手册.md) | HL-2915-C001 从两只台架、Radxa、IMU/HAT、相机到重训的验收门槛。 |
| [`HL2915两只舵机现场验收表.md`](HL2915两只舵机现场验收表.md) | 打印后逐项勾选的接线、ID、读数、动作和证据记录表。 |
| [`Microduck Studio`](../microduck-studio/README.md) | 本地复刻工作台：硬件档案、只读探针、项目证据、训练服务适配和部署前检查。 |
| [`低成本舵机替换决策表.md`](低成本舵机替换决策表.md) | 完成 HL-2915 基线后，如何评估更便宜舵机的替换风险。 |
| [`BAM与URDF全流程小白教程.md`](BAM与URDF全流程小白教程.md) | 从关节命名、URDF、采集、BAM 处理到训练的入门路线。 |
| [`飞特官方BAM发布解读.md`](飞特官方BAM发布解读.md) | 飞特官方 Gitee 发布的 HD-1910 m1–m6 已辨识 BAM 模型（7.4 V）：与陆吾参照的逐参数对比、参照链插入位置、MuJoCo/mjlab 两条接线。 |
| [`ToF集成教程-I2C识别与tofd验收.md`](ToF集成教程-I2C识别与tofd验收.md) | 深度数据从哪来：总线 3 全家福判读（0x18/0x19/0x29/0x68）、0x52 与 0x29 的关系、VL53L5CX/L8CX 数据手册参数、tofd 出帧验收与故障速查。 |
| [`URT2-HD1910接线组装与测试指南.md`](URT2-HD1910接线组装与测试指南.md) | 装机主线 HD-1910-C001 的 7.4 V 台架：与 HL 线序相反的三根黑线、只读探针与摇晃法、官方关节 ID 表、寄存器速查和标定门控。 |
| [`IMU集成教程-I2C直读与imu_to_dxl.md`](IMU集成教程-I2C直读与imu_to_dxl.md) | 两条 IMU 运输路径：imu_to_dxl 桥板（ID 200，DXL/飞特双分支）与 I²C 直读（i2c_lsm6dsv16x，当前上板方案）；12 字节载荷契约、systemd 放行、方向核验五阶段。 |
| [`microduck-community-kit使用教程.md`](microduck-community-kit使用教程.md) | 社区套件与 hls_servo_debugger：核心板部署实测、浏览器逐颗标定工作流（cal/offset/mid）、EPROM 偏移与 robotd 标定模板的分工。 |
| [`HD1910全链路落地手册.md`](HD1910全链路落地手册.md) | HD-1910 整机的 H0–H9 门槛：IMU 双来源对齐、界面可见性、关节 capture、安装方向核对，以及舵机与 IMU 的双向联合标定和仲裁规则。 |
| [`HD1910整机现场验收表.md`](HD1910整机现场验收表.md) | 打印后逐项填写的 15 关节 capture、IMU 五阶段、联合核对偏差和运动解锁记录表。 |
| [`1910-HAT接线与标定清单.md`](1910-HAT接线与标定清单.md) | 带日期的现状清单：HAT 线材核对、整机接线与远程验证速查；反映某一时刻的板端状态，不是长期参考。 |
| [`HD1910仿真迁移与PPO训练教程.md`](HD1910仿真迁移与PPO训练教程.md) · [离线阅读版](HD1910仿真迁移与PPO训练教程.html) | XL330 → HD-1910 的参数迁移、PPO 训练、分项评测、ONNX 导出与后续真机验证。 |
| [`cheatsheet.md`](robot/cheatsheet.md) | Every `robotctl` command. |
| [`pair-a-gamepad.md`](robot/pair-a-gamepad.md) | Once per pad: pairing mode, `pad pair`, and what to do when it will not bond. |
| [`cheatsheet-dev.md`](robot/cheatsheet-dev.md) | The commands that need a dev board: branch builds, candidates, dev pushes. |
| [`dev-push.md`](robot/dev-push.md) | Build on your machine and install on the board over ssh, with no CI run. |
| [`simulation.md`](robot/simulation.md) | The simulated duck: `scripts/duck-sim`, the real daemons against a MuJoCo body, one duck or several in containers. |
| [`duckctl.md`](robot/duckctl.md) | Every `duckctl` command — the robot from a laptop, over Bluetooth. |
| [`install-dev.md`](robot/install-dev.md) | Setting up a board for development, from nothing. |
| [`install-by-hand.md`](robot/install-by-hand.md) | The same install as separate commands, for testing one step at a time. |

## `design/` — you are changing the daemon

How it works and why. These change rarely; when behaviour and a design doc disagree, the doc is
the bug.

**One page owns a mechanism, and the others link to it.** The table below is that assignment: if a
fact belongs to a page listed here, every other page says one sentence and points, rather than
explaining it again. A fact written down in six places drifts in six directions, each of them locally
reasonable — which is how six documents came to promise that `updaterd` and `btd` kept their old
binaries until the next reboot, two releases after they stopped doing so, including the two pages
someone reads while diagnosing exactly that. So when two documents disagree, the one that does not
own the mechanism is the bug.

| | |
|---|---|
| [`architecture.md`](design/architecture.md) | The service split, the IPC contract, state ownership, safety and authority. |
| [`robotd-design.md`](design/robotd-design.md) | The control loop: the Dynamixel bus and who owns the port, the model, sensing, observations, policy, safety — and what else hangs off the tick. |
| [`updater-design.md`](design/updater-design.md) | The update engine: verification, atomic swap, health gate, rollback, release format. |
| [`policy-channel-design.md`](design/policy-channel-design.md) | Where the ONNX policies come from: the `policies` component, trying someone else's, and what `reset` puts back. |
| [`restart-order.md`](design/restart-order.md) | Which unit restarts, at which step, on every path that moves `current` — and at boot. |
| [`app-path-design.md`](design/app-path-design.md) | `btd` and `configd` — how a phone configures a robot over BLE. |
| [`mobile-app.md`](design/mobile-app.md) | The phone app — what it is built from, and what the robot still owes it. The code is in [`microduck-app`](https://github.com/pollen-robotics/microduck-app). |
| [`remote-webrtc.md`](design/remote-webrtc.md) | WebRTC sessions, signalling, and the control channel — how a peer drives and observes the robot. |
| [`webrtc-console.md`](design/webrtc-console.md) | The WebRTC client: serving it from the robot, finding the robot, and what the page should be. |
| [`remote-access-design.md`](design/remote-access-design.md) | Reaching a duck from outside the LAN: the Hugging Face account, the device flow, and the bridge to a rendezvous service. |
| [`boot-recovery-net.md`](design/boot-recovery-net.md) | Falling back to golden when the release that booted cannot start its daemons. |
| [`simulation.md`](design/simulation.md) | The twin: where the seam between daemon and body is, the body protocol, the fake radio, the containers, and what it is and is not a twin of. |

## `project/` — you are running the project

Dated records rather than reference. They describe a moment, and go stale on purpose.

| | |
|---|---|
| [`roadmap.md`](project/roadmap.md) | Milestones, and what works today versus what is designed. |
| [`ci-setup.md`](project/ci-setup.md) | One-time setup for the release pipeline: keys, secrets, rotation. |
| [`install-path-gap.md`](project/install-path-gap.md) | Why four install-path bugs reached a board, and what closed it. Closed — the rule it taught is [`updater-design.md`](design/updater-design.md) §9.1. |
| [`slice-2-bringup.md`](project/slice-2-bringup.md) | What a real Radxa Zero 3W did with slice 2. |
| [`update-over-ble.md`](project/update-over-ble.md) | Driving the update path from a phone: what it turned up, and what rollback over a radio was decided on. |
| [`media-bringup.md`](project/media-bringup.md) | What a Radxa Zero 3W does about video: the VPU, what MPP needs, and the two plugins that have to be built. |
| [`pad-minimal-pairing.md`](project/pad-minimal-pairing.md) | The smallest board configuration a gamepad will bond under, found by taking one away at a time. |
| [`idle-cpu.md`](project/idle-cpu.md) | What the daemons do when nobody is asking them to: four things that stopped, two that were measured and left alone, and what still wants a board. |
| [`tof-on-demand.md`](project/tof-on-demand.md) | `tofd`'s idle 5% is nine parts head IMU to one part depth, and the IMU has no consumer. Why the laser and the unit were left alone and the IMU got a switch. |

## `ideas/` — not designed yet

Holding pens. Something that is going to need a design doc, written down before it has one, so the
thinking is not lost and does not get mistaken for a decision.

| | |
|---|---|
| [`autonomous_behavior.md`](ideas/autonomous_behavior.md) | The behavior stack: what the runtime's brain has to give up, and the ideas the chorale and theremin work left behind. |

## Elsewhere

| | |
|---|---|
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Building, testing, repo layout, conventions, releasing. |
| [`project/npu-bringup.md`](project/npu-bringup.md) | The duck detector on the RK3566's NPU: what runs, how to benchmark it, and the frame path that is still missing. |
| [`../deploy/README.md`](../deploy/README.md) | What a robot image is configured with, and what provisioning actually does. |
