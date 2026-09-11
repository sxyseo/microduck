# 30 天公众号选题日历

栏目建议名称：**《从零复刻一只会走路的小鸭子》**。

每篇文章固定使用这个结构：问题、源码证据、实验命令、TensorBoard/视频证据、结论、未解决问题。

| 天数 | 文章标题 | 主要证据 |
|---:|---|---|
| 1 | 5 次迭代能不能证明训练环境可用？ | smoke 日志、TensorBoard、ONNX |
| 2 | 三个仓库到底分别负责什么？ | repo map |
| 3 | 用 `uv sync` 重建一个干净训练环境 | 依赖版本、测试结果 |
| 4 | 从任务 ID 追到真正的环境配置 | `tasks/__init__.py` |
| 5 | `microduck_velocity_env_cfg.py` 的前 87 行 | 开关和范围表 |
| 6 | MuJoCo 场景、地形和足部接触 | scene/sensor 配置 |
| 7 | 14 个动作是如何产生的？ | action manager、关节图 |
| 8 | 61 维 observation 是怎么拼出来的？ | actor/critic 对照 |
| 9 | 为什么 critic 有 76 维而 actor 只有 61 维？ | privileged observation |
| 10 | 速度、头部和身体指令如何进入策略？ | command 实验 |
| 11 | reward 不是越多越好吗？ | reward 权重和符号 |
| 12 | domain randomization 如何帮助 sim-to-real？ | DR A/B |
| 13 | 延迟、噪声和 encoder bias | 观测扰动实验 |
| 14 | curriculum 为什么会让训练突然变差？ | 阶段边界曲线 |
| 15 | PPO 的网络、batch 和学习率 | agent.yaml |
| 16 | 第一次 50 次迭代：曲线开始有意义了吗？ | TensorBoard |
| 17 | 第一次 200 次迭代：摔倒率是否下降？ | play 视频 |
| 18 | 显存到底消耗在哪里？ | 2080/3080/4090 benchmark |
| 19 | 训练速度应该按迭代还是 transition 衡量？ | throughput 表 |
| 20 | 如何判断策略真的学会了走路？ | 多指标验收 |
| 21 | checkpoint、resume 和失败恢复 | 训练命令 |
| 22 | 为什么不能手写 `torch.onnx.export`？ | 官方导出器 |
| 23 | ONNX 的 61→14 合同 | shape/数值校验 |
| 24 | 树莓派只做推理的最小闭环 | ORT benchmark |
| 25 | 真机部署最容易错的 5 个单位 | joint/order/scale |
| 26 | MicroDuck 的 walking 策略能不能跑步？ | 速度范围和假设 |
| 27 | 从 walking checkpoint 继续训练 running | fine-tune 设计 |
| 28 | 站立、坐下、翻滚为什么应该是独立任务？ | task registry |
| 29 | 给机器人加上小智语音控制 | MCP bridge 设计 |
| 30 | 30 天复刻复盘：哪些结论真的被验证了？ | 全部实验索引 |

