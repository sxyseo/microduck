# 解读 185 · TensorBoard 逐指标

> **解读对象**:概念课 · 以 `docs/microduck-30day/experiments/experiment-log.csv` 与 `docs/microduck-30day/assets/day-01-lesson-01/summary.md` 为教材
> **需要的前置**:零基础可读;训练命令怎么跑见[解读 186](186-uv入门.md)

训练时每隔几步,框架就把一批数字写进 event 文件;`tensorboard --logdir logs/rsl_rl` 把它们画成曲线。本篇不教开面板,只回答:几十条曲线里先看哪几条,以及它们怎么骗你。这只鸭子两次真实训练,正好是一正一反两个故事。

## mean_reward:涨了,不等于学会走

`Train/mean_reward` 是"平均每集拿多少分",最显眼,也最容易骗人。2026-09-05 的冒烟测试(lesson-01,8 环境 5 迭代,纯流程验证)生成了 `summary.md`,开头两行是机器从 event 文件算出的,不是手填的:

```text
| `Train/mean_reward` | -0.061442 | 0.094974 | 0.156416 | 4 |
| `Train/mean_episode_length` | 32.500000 | 35.708332 | 3.208332 | 4 |
```

reward 从 -0.0614 涨到 0.0950,看着像在进步;可同一张表里 `Episode_Termination/fell_over`(摔倒终止率)从 0 涨到 1.0,yaw 转向误差反而从 0.1374 升到 0.1716(`docs/course/06-看懂训练曲线.md`)。就像学生把卷子写满了不等于答对了——reward 上升只证明"网络在被更新",不证明"步态在形成"。当天日志的结论因此写成两句:流程通过;步态尚未开始。

## ep_len:回答"摔不摔",不回答"走不走"

ep_len(mean_episode_length)是平均每集活多少步,它涨说明摔得少了。本项目 expC 里 ep_len 51 → 315 步(约 6.3 秒),最终 checkpoint 回放 240 步零摔倒——站稳了。接着 expD 用 512 环境续训,实验总表 `experiment-log.csv` 里这一行是它的判决书:

```text
expD-m4-512,2026-09-07,Mjlab-Velocity-Flat-MicroDuck,cpu,512,24,12500->,microduck-replica/upstream/microduck_rl/logs/rsl_rl/velocity/2026-09-07_00-06-08_expD-m4-512,model_12500.pt,,superseded,512env续训自expC/2198；ep_len 315->744站稳但步态未成(air_time_mean卡0.04s,shuffle局部最优)
```

ep_len 315 → 744,鸭子活得很健康;但 `air_time_mean`(脚离地时间)卡死在 0.04 秒——脚几乎不离地,靠原地小幅挪脚蹭分。"不摔"和"会走"是两个优化目标。

## 用曲线改配方:expE 的门槛手术

看懂曲线的回报是能开出药方。训练参数指南的假设是:脚离地奖励的门槛设在 0.125 秒,策略从没迈出过够高的步,就永远收不到抬脚的正反馈。于是总表下一行 expE 把 `threshold_min 0.125->0.04 让步态奖励可见;air_time_mean>0.10后收紧回0.125`——先降低门槛让奖励"看得见",起来了再收紧。这就是逐指标读日志的完整闭环:发现卡住的指标 → 提出假设 → 改一个量 → 用下一条曲线验收。

## 你带走的收获

- 先看四类:ep_len(摔不摔)、速度跟踪误差(跟不跟)、air_time_mean(迈没迈步)、mean_std/entropy(还探不探索)。
- reward 涨 ≠ 学会走;要交叉验证 fell_over、误差类指标有没有同步变好。
- 真实案例:lesson-01 reward -0.0614→0.0950 但摔倒率 1.0;expD ep_len 315→744 却卡在"蹭步"。
- 曲线的终点是行动:expE 把 air_time 门槛 0.125→0.04 再收紧,是用日志诊断出的改进。
- 结论要写两句分开的:一句流程,一句步态——不许合并。

## 延伸

- 奖励表逐项:[解读 131](131-velocity奖励表.md);课程门槛怎么收紧:[解读 132](132-velocity课程.md)
- 云训练跑出这些日志:[解读 129](129-hfjobs云训练.md);TensorBoard 怎么启动:`uv run tensorboard --logdir logs/rsl_rl --port 6006`
- 本地路径:`docs/course/06-看懂训练曲线.md`(优先级表出处:训练参数指南 §7.3)
