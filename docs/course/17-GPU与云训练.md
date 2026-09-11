# 第 17 课 · GPU 与云训练:什么时候该花钱算力

> **这一课解决什么问题**:训练到底要多贵的机器?这一课给你一张算力决策表:哪些实验本机 CPU 就够、哪些必须上 GPU、租云时怎么不花冤枉钱也不泄漏密钥——全部有本项目的真实开销作证。
>
> **前置**:[第 05 课](05-第一次训练-冒烟测试.md) 与 [第 14 课](14-单变量AB实验.md)。

---

## 1. 本机 CPU 能干什么:比你以为的多

`docs/microduck-30day/README.md` 把本机 CPU 定位成 smoke test 机器。实验总表证实走得通:

- **冒烟测试**:lesson-01(2026-09-05,8 环境 5 迭代),验证训练→回放→导出→验证整条流水线通不通——记录里明说"not a usable walking policy",它的任务是验证管道;
- **A/B 小实验**:exp001 单组 100 迭代 × 64 环境,**实测仅 4 分钟**(约 2.3 s/迭代),两组 8 分钟跑完——第 14 课整套方法论就是在这台无 GPU 的 Mac 上演的;
- 回放、导出 ONNX、写记录。

附带两个坑(构建日志 2026-09-06):无 CUDA 机器要设 `CUDA_VISIBLE_DEVICES=""`,logger 默认 wandb 没配 key 会报错,加 `--agent.logger tensorboard`。

所以呢?方法论的每一次迭代——假设、A/B、记录、复盘——CPU 全够用;别把"没 GPU"当成不开始实验的借口。

## 2. 本机 CPU 不能干什么:长训练

对比数量级:exp001 只有 100 迭代;而 expD 续训 12500 迭代、expE 目标 **50000 迭代**——实验总表里这两行的 device 列至今写着 cpu,本机不是跑不了,是跑得很奢侈。官方参考(`docs/进阶学习文档-训练仿真与部署.md` 2.2 节):**4096 并行环境的 walking 任务,在 NVIDIA GPU 上约 1–2 小时出可用步态**;构建日志另有一笔:exp001 的 15 万步只抵官方配方 49 亿步的 0.003%。

分工因此定死(30 天 README 原话):正式训练在带 NVIDIA GPU 的 Linux/CUDA 主机;树莓派只负责推理和运行时,**不负责 PPO 训练**。

## 3. GPU 的三种来源

| 来源 | 适用 | 注意 |
|---|---|---|
| 自有 NVIDIA GPU | 反复训练、改结构 | 官方 Quickstart 明确要求 CUDA |
| Hugging Face Jobs 云端 | 偶尔长训练 | 按所选硬件运行时间计费,**需要正的账户余额** |
| Apple Silicon 社区实验 | 原型尝试 | 非官方,不能代替正式 sim-to-real 训练 |

另一个冷知识(进阶文档 2.1 节):硬件和官方完全相同(含 XL330)就**根本不需要训练**——官方 9 个 ONNX 直接用,¥0。训练只为"改了什么"的人存在。

到了 GPU 主机,训练完整四步(`docs/进阶学习文档-训练仿真与部署.md` 2.2 节):

```bash
uv run train Mjlab-Velocity-Flat-MicroDuck --env.scene.num-envs 4096   # 训练
uv run play Mjlab-Velocity-Flat-MicroDuck --wandb-run-path <...>       # 回放
uv run scripts/export.py Mjlab-Velocity-Flat-MicroDuck --wandb-run-path <...>  # 导出 ONNX(必须官方脚本)
uv run scripts/infer_policy.py --walking output.onnx                   # 验证
```

## 4. 云训练安全五条

`open-microduck/docs/zh-CN/getting-started/choose-your-path.md` 的「使用云训练前先看」,照抄给你:

```text
1. 先查 Hugging Face Jobs 实时定价
2. `hf auth login`、`wandb login` 后,第一次必须加 --dry-run 看清规格和费用再真提交
3. 设明确的 --timeout
4. 知道怎么查看和取消 Job(hf jobs cancel <id>)
5. 不把 Token 写进 Git、截图或日志
```

前三条保钱包:云按运行时间计费,忘了取消的 Job 就是真金白银;第五条保账号:泄漏的 Token 比几小时算力贵得多。

## 5. 本项目的分工实例

把全课程的算力决策串一遍:本机 Mac CPU 负责冒烟(lesson-01,5 迭代)、A/B(exp001,每组 4 分钟)与记录;万级迭代的长训练(expD 已到 12500、expE 目标 50000)留给 Linux/CUDA 主机或云;将来的板子(Radxa/树莓派)只做推理。这是第 12 课预算意识的延续:**花钱前先问——这个实验,4 分钟的 CPU 小实验能不能先回答?**

## 动手练习(15 分钟)

为 expE(目标 50000 迭代)写一段 3 句话的算力决策:在哪跑、为什么、预算上限多少。要求引用本课至少两个真实数字。

## 自查清单

- [ ] 我能列出本机 CPU 适合的三类任务,并说出 exp001 的 4 分钟意味着什么
- [ ] 我能说出官方参考的 4096 环境 1–2 小时指的是什么条件
- [ ] 我能默写云训练安全五条
- [ ] 我知道什么情况下完全不需要训练

## 下一课预告

阶段 D 到此结课:地图、实验方法、鲁棒性意识、开发路线、算力账都齐了。第 18 课进入阶段 E——把 Rust 运行时装上 Radxa,鸭子的大脑要从电脑搬进身体了。

## 延伸资源

- `docs/进阶学习文档-训练仿真与部署.md` 第 2.1–2.2 节(路线选择与训练四步)
- `open-microduck/docs/zh-CN/getting-started/choose-your-path.md`(含 HF Jobs 定价与安全清单)
- [Hugging Face Jobs 实时定价](https://huggingface.co/docs/hub/jobs-pricing)
- RL 训练原理:[Hugging Face 深度强化学习课](https://huggingface.co/learn/deep-rl-course/unit0/introduction)
