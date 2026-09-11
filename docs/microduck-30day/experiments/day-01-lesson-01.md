# Day 01 实验记录：5 次迭代 smoke test

## 目标

验证训练环境、PPO、TensorBoard、checkpoint 和 ONNX 导出链路都能工作。

这次实验不以“学会走路”为目标。

## 环境

- Task：`Mjlab-Velocity-Flat-MicroDuck`
- Device：CPU
- Number of environments：8
- Steps per environment：24
- Iterations：5
- Effective samples：`8 × 24 × 5 = 960`
- Per-environment simulated time：`5 × 24 × 0.02 = 2.4 s`

## 命令

```bash
cd /Volumes/dev/dev/microduck/microduck-replica/upstream/microduck_rl

uv run train Mjlab-Velocity-Flat-MicroDuck \
  --gpu-ids None \
  --env.scene.num-envs 8 \
  --agent.num-steps-per-env 24 \
  --agent.max-iterations 5 \
  --agent.logger tensorboard \
  --agent.upload-model False \
  --agent.run-name lesson-01
```

## 产物

- Run directory：`logs/rsl_rl/velocity/2026-09-05_00-14-47_lesson-01/`
- Checkpoint：`model_4.pt`
- TensorBoard event：`events.out.tfevents.1788538488.abeldeMac-mini.local.25488.0`
- ONNX：`lesson-01-explicit.onnx`
- Effective agent config：`params/agent.yaml`

## 结果

| 指标 | 迭代开始 | 迭代结束 | 解读 |
|---|---:|---:|---|
| `Train/mean_reward` | -0.0614 | 0.0950 | 有早期改善，但不能证明会走路 |
| `Train/mean_episode_length` | 32.5 | 35.7 | 存活时间略升 |
| `Loss/value` | 0.0222 | 0.0402 | 正常波动 |
| `Policy/mean_std` | 0.9997 | 0.9986 | 探索没有塌缩 |
| `Episode_Termination/fell_over` | 1.3750 | 1.0000 | 仍然频繁摔倒 |
| `Metrics/twist/error_vel_yaw` | 0.1374 | 0.1716 | 转向误差没有改善 |

## ONNX 校验

```text
input : obs     [1, 61] tensor(float)
output: actions [1, 14] tensor(float)
finite: True
```

## 结论

全链路已通过，但策略尚未学会稳定 walking。下一次实验应把环境数量提高到 64，迭代提高到 50 或 100，并用 `fell_over`、episode length 和速度误差共同判断进步。

