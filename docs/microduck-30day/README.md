# 从零复刻 MicroDuck：30 天学习与公众号实验包

这是一套围绕本地 MicroDuck 仓库制作的学习资料。目标不是把代码“看过一遍”，而是每天完成一个小闭环：

```text
读一小段源码 → 提出一个假设 → 跑一个小实验 → 保存证据 → 写一段结论
```

## 当前项目边界

- `OpenMicroDuck/`：结构、外壳和硬件设计资料。
- `microduck-replica/`：复刻工程；训练代码位于 `upstream/microduck_rl/`。
- 外层仓库：MicroDuck 的 Rust 运行时、传感器、舵机、安全控制和 ONNX 加载。
- `xiaozhi-esp32/`：可作为第 30 天的语音/MCP 扩展，不属于 PPO 训练核心。

## 目录

- [30 天学习计划](30-day-plan.md)
- [源码地图](source-map.md)
- [公众号选题日历](articles/editorial-calendar.md)
- [第 1 天文章：5 次迭代 smoke test](articles/day-01-5-iteration-smoke-test.md)
- [公众号文章模板](articles/article-template.md)
- [第 1 天实验记录](experiments/day-01-lesson-01.md)
- [实验记录模板](experiments/experiment-template.md)
- [实验总表](experiments/experiment-log.csv)
- [辅助工具说明](../../tools/microduck_learning/README.md)

## 已生成素材

- [第 1 天指标图](assets/day-01-lesson-01/metrics.png)
- [第 1 天 TensorBoard 截图](../../output/playwright/tensorboard-day01.png)
- [scalar 摘要](assets/day-01-lesson-01/summary.md)
- [scalar 原始表](assets/day-01-lesson-01/scalars.csv)

## 运行环境

训练环境：

```bash
cd /Volumes/dev/dev/microduck/microduck-replica/upstream/microduck_rl
uv sync
```

本机 CPU smoke test：

```bash
bash /Volumes/dev/dev/microduck/tools/microduck_learning/run_5_iteration_smoke.sh
```

带 NVIDIA GPU 的正式训练应在 Linux/CUDA 主机上进行；树莓派只负责后续推理和机器人运行时，不负责 PPO 训练。

## 记录原则

每次实验都记录：代码 commit、训练命令、环境数量、迭代数量、日志目录、checkpoint、显存/时间、关键曲线、失败原因和下一步。没有实际证据的内容标为“待验证”。
