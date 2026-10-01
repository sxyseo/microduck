# 解读 194 · 什么是 ONNX

> **解读对象**:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/export.py`(311 行,"从 checkpoint 到 `.onnx` 的唯一路径")
> **需要的前置**:[解读 32](32-导出与回放.md)(导出与回放);[解读 03](03-策略加载.md)(部署侧怎么加载)。

## ONNX 是"模型的 PDF"

训练完的网络是 PyTorch 格式的 `.pt` 文件:它离不开原来的框架、原来的 Python 环境,就像 `.keynote` 离不开 Keynote。**ONNX(Open Neural Network Exchange,开放神经网络交换格式)** 把网络"打印"成一个自包含的标准文件:结构、权重都固定下来,任何一方只要装一个"阅读器"就能运行——部署侧的阅读器叫 **onnxruntime**。

这只鸭子两端都用真实代码印证了"PDF"这个类比:

- **写PDF**:export.py 调 `runner.export_policy_to_onnx(path, filename)`,把训练好的策略导出;
- **读PDF**:仿真回放 `scripts/infer_policy.py` 用 `ort.InferenceSession(path)` 打开;真机上的 `duck-control/src/policy.rs` 用 Rust 的 `ort` 库打开同一个文件。

## 61→14:一张写死在文件里的合同

鸭子策略的"合同"是:**61 个数进,14 个数出**。61 维观测(角速度 3 + 投影重力 3 + 14 个关节位置 + 14 个关节速度 + 14 个上一步动作 + 13 维命令),14 维动作。这个形状在导出时就焊死进了 ONNX 图里,于是两侧代码都把它当**验收条款**逐字检查:

- infer_policy.py 打开文件就打印 `Walking policy input: … shape: […]`;
- policy.rs 检查不过就报错,注释里的原话是"`observation width is 51, expected 61`",推理结果还要过"expected 14 finite actions"这一关。

合同的好处:谁改了观测定义,加载当场就炸,而不是让鸭子走出莫名其妙的动作。

## 归一化层:烘焙进图,还是忘了就翻车

导出文件头有一句最能说明 ONNX 工程化的话:

> Export a trained checkpoint to ONNX, **with the observation normalizer baked in**.

什么是 normalizer?训练时观测先做统计归一化(减均值、除方差)再喂网络。这个步骤如果导出时漏掉,仿真里"自己动手补归一化"的回放脚本看不出来——**而真机会疯**。export.py 的防御是把归一化直接**烘焙进计算图**:注释写明 `EmpiricalNormalization` 是策略网络 MLPModel 的子模块,导出时 `export_policy_to_onnx` 自动输出 `actor(normalizer(obs))`,并留了一句教训:"In-sim `play` … hides a hand-converted checkpoint that forgot it — **never convert by hand**"(手转的 checkpoint 忘了归一化,别手工转换)。

还有个小彩蛋:导出时 `attach_metadata_to_onnx` 把元数据写进文件,infer_policy.py 会读出 `gait_period`(步态周期)打印——PDF 不光有正文,还能夹带"文档属性"。

## 你带走的收获

- ONNX = 模型的可携带存档:训练框架随便换,部署侧只需要 onnxruntime(Python)或 `ort`(Rust)。
- 输入/输出形状是部署合同:61→14 在加载时被两侧代码显式校验,错了立即报错。
- 预处理(归一化)要一起烘焙进图,而不是靠部署代码自觉——"never convert by hand"是真实事故教训。
- ONNX 支持自定义元数据,本项目用它随文件携带 `gait_period` 等训练参数。
- 导出必须走唯一通道(`run_export`),发布流程直接调用它,让"跳过导出规范"在机制上不可能。

## 延伸

- 导出全函数逐行走:[解读 128](128-export全函数.md);回放侧主流程:[解读 130](130-infer主流程.md)
- 部署侧加载、预热与校验:[解读 03](03-策略加载.md) · 61 维观测怎么拼:[解读 02](02-观测拼装.md)
- 本地:`microduck-replica/upstream/microduck_rl/src/mjlab_microduck/export.py`(文件头注释与 252–257 行)
