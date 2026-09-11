# 源码地图：先读哪些文件

## 1. 训练主线

```text
任务 ID
  → tasks/__init__.py 注册
  → microduck_velocity_env_cfg.py 组装环境
  → mdp.py 提供 observation/reward/event 函数
  → mjlab + rsl_rl 执行 rollout/PPO
  → model_*.pt checkpoint
  → export.py 导出 ONNX
```

## 2. 推荐阅读顺序

| 顺序 | 文件 | 先回答的问题 |
|---|---|---|
| 1 | `src/mjlab_microduck/tasks/__init__.py` | 任务名称如何映射到配置？ |
| 2 | `src/mjlab_microduck/tasks/microduck_velocity_env_cfg.py` | 环境由哪些 manager 组成？ |
| 3 | `src/mjlab_microduck/tasks/mdp.py` | reward 和 observation 的数学公式是什么？ |
| 4 | `src/mjlab_microduck/robot/microduck_constants.py` | 默认姿态、关节和执行器如何定义？ |
| 5 | `src/mjlab_microduck/export.py` | 为什么 ONNX 必须走项目导出器？ |
| 6 | `scripts/infer_policy.py` | 仿真推理如何模拟 sim-to-real？ |
| 7 | `/Volumes/dev/dev/microduck/duck-control/src/obs.rs` | 真机如何构造 61 维 observation？ |
| 8 | `/Volumes/dev/dev/microduck/duck-control/src/policy.rs` | 真机如何加载、预热和校验 ONNX？ |
| 9 | `xiaozhi-esp32/docs/mcp-usage.md` | 语音工具如何发现和调用机器人能力？ |

## 3. velocity 配置的学习顺序

| 区域 | 重点 |
|---|---|
| `1–87` | 全局开关、随机化范围、命令范围 |
| `127–190` | 地形和足部接触传感器 |
| `193–390` | 环境工厂、动作、reward、终止条件 |
| `532–638` | actor 61 维、critic 76 维、噪声和延迟 |
| `639–748` | twist/head/body command |
| `749–917` | 平地/崎岖地形和 curriculum |
| `928–950` | PPO 网络和训练参数 |

每读一个配置，写出：改变了什么、对应现实中的什么、影响哪个指标、如何设计 A/B 实验。

